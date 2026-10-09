import datetime
import json
import os
import time
import uuid

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import func, text
from sqlalchemy.orm import Session
from starlette.middleware.sessions import SessionMiddleware

import admin
from agent_tools_bridge import AGENT_TOOLS_DEFS, call_agent_tool, is_agent_tool
from client_auth import resolve_client
from db import Base, SessionLocal, engine
from mcp_bridge import mcp_result_to_text, mcp_session, mcp_tools_to_anthropic, with_cache_breakpoint
from models import AgentAuditLog, AgentClient, AgentConversationMessage
from pricing import cost_usd

load_dotenv()

MODEL = "claude-sonnet-5"
MAX_TOOL_TURNS = 8
# 1024 era curto demais pra uma resposta com raciocínio + narrativa de
# várias chamadas de ferramenta em sequência -- risco real de cortar a
# resposta no meio sem aviso nenhum pro usuário.
MAX_TOKENS = 4096
# Quantos turnos (pergunta+resposta) de uma conversa carregar como contexto.
HISTORY_TURNS = 10
SYSTEM_PROMPT = [
    {
        "type": "text",
        "text": (
            "Você é o assistente de rede da Natverk. Seja econômico: use "
            "sempre a ferramenta e os filtros mais específicos e enxutos "
            "possíveis para responder exatamente o que foi perguntado — "
            "nunca busque mais dado do que o necessário pra essa resposta. "
            "Em particular: quando a pergunta for só uma contagem, use "
            "countOutput=true em vez de listar os registros; quando "
            "precisar de detalhes, passe output com só os campos que a "
            'resposta exige (nunca output="extend"); e responda de forma '
            "direta e curta, sem listar dado que não foi pedido."
        ),
        "cache_control": {"type": "ephemeral"},
    }
]

app = FastAPI()
app.add_middleware(
    SessionMiddleware,
    secret_key=os.environ["SESSION_SECRET"],
    # https_only: sem isso o cookie de sessão do admin ia sem a flag Secure
    # -- seria enviado mesmo numa conexão HTTP não criptografada caso o
    # HTTPS do Caddy seja contornado por algum motivo. same_site="lax" e
    # max_age mais curto (8h, não os 14 dias padrão do Starlette) reduzem
    # a janela de um cookie de sessão de administrador roubado/vazado.
    https_only=True,
    same_site="lax",
    max_age=8 * 60 * 60,
)
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(admin.router)

# max_retries/timeout: antes um 429 (rate limit) ou 529 (sobrecarregado) da
# Anthropic derrubava a chamada na hora -- com isso o SDK tenta de novo com
# backoff automático antes de desistir.
client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=3, timeout=60.0)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    # create_all só cria tabelas que não existem -- agent_clients já existia
    # em produção antes do campo de limite de gasto, então a coluna nova
    # precisa ser adicionada manualmente. IF NOT EXISTS torna isso idempotente
    # (seguro rodar em todo startup, inclusive num banco que já tem a coluna).
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE agent_clients ADD COLUMN IF NOT EXISTS monthly_budget_usd FLOAT"))


@app.get("/")
def root():
    return RedirectResponse(url="/admin/dashboard")


class ChatRequest(BaseModel):
    message: str
    # Opcional -- quando omitido, cada chamada é uma conversa nova e isolada
    # (comportamento antigo). Quando o chamador reenvia o mesmo
    # conversation_id (ex: o ID do chat do WhatsApp), o histórico da
    # conversa é carregado e o agente mantém contexto entre mensagens.
    conversation_id: str | None = None


@app.get("/health")
def health():
    return {"status": "ok"}


class Usage:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_creation_tokens = 0
        self.cache_read_tokens = 0

    def add(self, usage):
        self.input_tokens += usage.input_tokens
        self.output_tokens += usage.output_tokens
        self.cache_creation_tokens += getattr(usage, "cache_creation_input_tokens", 0) or 0
        self.cache_read_tokens += getattr(usage, "cache_read_input_tokens", 0) or 0


def load_history(db: Session, client_name: str, conversation_id: str) -> list[dict]:
    rows = (
        db.query(AgentConversationMessage)
        .filter(AgentConversationMessage.client_name == client_name)
        .filter(AgentConversationMessage.conversation_id == conversation_id)
        .order_by(AgentConversationMessage.created_at.desc())
        .limit(HISTORY_TURNS * 2)
        .all()
    )
    rows.reverse()
    return [{"role": r.role, "content": r.content} for r in rows]


def save_turn(
    db: Session, client_name: str, conversation_id: str, user_message: str, assistant_text: str
) -> None:
    db.add(
        AgentConversationMessage(
            client_name=client_name,
            conversation_id=conversation_id,
            role="user",
            content=user_message,
        )
    )
    db.add(
        AgentConversationMessage(
            client_name=client_name,
            conversation_id=conversation_id,
            role="assistant",
            content=assistant_text,
        )
    )


def monthly_spend_usd(db: Session, client_name: str) -> float:
    month_start = datetime.datetime.utcnow().replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    row = (
        db.query(
            func.coalesce(func.sum(AgentAuditLog.input_tokens), 0),
            func.coalesce(func.sum(AgentAuditLog.output_tokens), 0),
            func.coalesce(func.sum(AgentAuditLog.cache_creation_tokens), 0),
            func.coalesce(func.sum(AgentAuditLog.cache_read_tokens), 0),
        )
        .filter(AgentAuditLog.client_name == client_name)
        .filter(AgentAuditLog.created_at >= month_start)
        .first()
    )
    return cost_usd(*row)


def check_budget(db: Session, agent_client: AgentClient) -> tuple[bool, float]:
    """Retorna (bloqueado, gasto_no_mes). Sem monthly_budget_usd configurado
    (None ou 0), nunca bloqueia."""
    if not agent_client.monthly_budget_usd:
        return False, 0.0
    spent = monthly_spend_usd(db, agent_client.name)
    return spent >= agent_client.monthly_budget_usd, spent


async def run_with_tools(
    message: str,
    mcp_url: str,
    mcp_token: str | None,
    base_url: str | None,
    agent_tools_token: str | None,
    history: list[dict],
):
    """Roda o loop Claude <-> (Zabbix MCP + agent_tools), transmitindo o
    texto da resposta em tempo real conforme o modelo gera (em vez de
    montar a resposta inteira em memória e só então mandar tudo de uma
    vez). Terminado o loop, produz um evento final com usage/tool_calls
    pro chamador logar na auditoria."""
    usage = Usage()
    tool_calls: list[dict] = []
    has_agent_tools = bool(base_url and agent_tools_token)

    async with mcp_session(mcp_url, mcp_token) as session:
        mcp_tools = (await session.list_tools()).tools
        tools = mcp_tools_to_anthropic(mcp_tools)
        if has_agent_tools:
            tools = tools + AGENT_TOOLS_DEFS
        tools = with_cache_breakpoint(tools)

        messages = history + [{"role": "user", "content": message}]
        for _ in range(MAX_TOOL_TURNS):
            async with client.messages.stream(
                model=MODEL,
                max_tokens=MAX_TOKENS,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            ) as stream:
                async for chunk in stream.text_stream:
                    yield {"type": "text", "text": chunk}
                response = await stream.get_final_message()
            usage.add(response.usage)

            if response.stop_reason != "tool_use":
                yield {"type": "final", "usage": usage, "tool_calls": tool_calls}
                return

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                if has_agent_tools and is_agent_tool(block.name):
                    result_text = await call_agent_tool(
                        base_url, agent_tools_token, block.name, block.input
                    )
                    is_error = result_text.startswith("Erro")
                else:
                    result = await session.call_tool(block.name, block.input)
                    result_text = mcp_result_to_text(result)
                    is_error = bool(result.is_error)
                tool_calls.append(
                    {
                        "name": block.name,
                        "input": block.input,
                        "result_chars": len(result_text),
                        "result_preview": result_text[:300],
                    }
                )
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_text,
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        yield {
            "type": "text",
            "text": "Não consegui concluir a consulta (muitas chamadas de ferramenta em sequência).",
        }
        yield {"type": "final", "usage": usage, "tool_calls": tool_calls}


async def run_plain_chat(message: str, history: list[dict]):
    usage = Usage()
    messages = history + [{"role": "user", "content": message}]
    async with client.messages.stream(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=SYSTEM_PROMPT,
        messages=messages,
    ) as stream:
        async for chunk in stream.text_stream:
            yield {"type": "text", "text": chunk}
        response = await stream.get_final_message()
    usage.add(response.usage)
    yield {"type": "final", "usage": usage, "tool_calls": []}


@app.post("/chat")
async def chat(req: ChatRequest, x_agent_token: str = Header(...)):
    db = SessionLocal()
    agent_client = resolve_client(x_agent_token, db)
    if agent_client is None:
        db.close()
        raise HTTPException(status_code=401, detail="Token de cliente inválido")
    client_name = agent_client.name
    mcp_url = agent_client.zabbix_mcp_url
    mcp_token = agent_client.zabbix_mcp_token
    base_url = agent_client.base_url
    agent_tools_token = agent_client.agent_tools_token
    conversation_id = req.conversation_id or uuid.uuid4().hex

    async def event_stream():
        start = time.monotonic()
        usage = Usage()
        status = "ok"
        tool_calls: list[dict] = []
        full_text = ""
        error_message: str | None = None

        over_budget, spent = check_budget(db, agent_client)
        if over_budget:
            msg = (
                f"Limite de uso mensal (${agent_client.monthly_budget_usd:.2f}) atingido "
                f"para este cliente (gasto no mês: ${spent:.2f}). Fale com o administrador "
                "do agente para revisar o limite."
            )
            yield f"data: {msg}\n\n"
            db.add(
                AgentAuditLog(
                    client_name=client_name,
                    tool_name="budget_blocked",
                    request_summary=req.message,
                    response_summary=msg,
                    input_tokens=0,
                    output_tokens=0,
                    cache_creation_tokens=0,
                    cache_read_tokens=0,
                    duration_ms=0,
                    status="blocked",
                )
            )
            db.commit()
            db.close()
            yield f"event: done\ndata: {json.dumps({'conversation_id': conversation_id})}\n\n"
            return

        history = load_history(db, client_name, conversation_id)

        try:
            if mcp_url:
                gen = run_with_tools(
                    req.message, mcp_url, mcp_token, base_url, agent_tools_token, history
                )
            else:
                gen = run_plain_chat(req.message, history)

            async for event in gen:
                if event["type"] == "text":
                    full_text += event["text"]
                    # Mesmo framing de sempre (uma linha "data: " por envio),
                    # só que agora em vários pedaços conforme o modelo gera
                    # em vez de um único envio no final -- streaming de
                    # verdade em vez de só a aparência de stream.
                    yield f"data: {event['text']}\n\n"
                elif event["type"] == "final":
                    usage = event["usage"]
                    tool_calls = event["tool_calls"]
        except Exception as exc:
            status = "error"
            error_message = str(exc)[:500]
            yield (
                "data: Desculpe, ocorreu um erro ao processar sua pergunta. "
                "Tente novamente em instantes.\n\n"
            )
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            tool_names = [t["name"] for t in tool_calls]
            request_summary = "\n".join(
                f"{t['name']}({t['input']})" for t in tool_calls
            )
            response_summary = "\n".join(
                f"{t['name']}: {t['result_chars']} chars -> {t['result_preview']}"
                for t in tool_calls
            )
            if error_message:
                # Sem coluna própria pra erro na auditoria -- prefixar aqui
                # é o jeito mais simples de guardar o que quebrou sem exigir
                # migração de schema. "status" já marca a linha como erro;
                # isso só preserva o detalhe pra quem for investigar depois.
                prefix = f"ERRO: {error_message}"
                response_summary = f"{prefix}\n{response_summary}" if response_summary else prefix
            db.add(
                AgentAuditLog(
                    client_name=client_name,
                    tool_name=", ".join(dict.fromkeys(tool_names)) or "chat",
                    request_summary=request_summary or None,
                    response_summary=response_summary or None,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_creation_tokens=usage.cache_creation_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    duration_ms=duration_ms,
                    status=status,
                )
            )
            if status == "ok" and full_text:
                save_turn(db, client_name, conversation_id, req.message, full_text)
            db.commit()
            db.close()
        yield f"event: done\ndata: {json.dumps({'conversation_id': conversation_id})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
