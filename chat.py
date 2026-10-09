import os
import time

from anthropic import AsyncAnthropic
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

import admin
from agent_tools_bridge import AGENT_TOOLS_DEFS, call_agent_tool, is_agent_tool
from client_auth import resolve_client
from db import Base, SessionLocal, engine
from mcp_bridge import mcp_result_to_text, mcp_session, mcp_tools_to_anthropic, with_cache_breakpoint
from models import AgentAuditLog

load_dotenv()

MODEL = "claude-sonnet-5"
MAX_TOOL_TURNS = 8
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

client = AsyncAnthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


@app.get("/")
def root():
    return RedirectResponse(url="/admin/dashboard")


class ChatRequest(BaseModel):
    message: str


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


async def run_with_tools(
    message: str,
    mcp_url: str,
    mcp_token: str | None,
    base_url: str | None,
    agent_tools_token: str | None,
):
    """Runs the Claude <-> (Zabbix MCP + agent_tools) loop and returns
    (final_text, usage, tool_calls)."""
    usage = Usage()
    tool_calls: list[dict] = []
    has_agent_tools = bool(base_url and agent_tools_token)

    async with mcp_session(mcp_url, mcp_token) as session:
        mcp_tools = (await session.list_tools()).tools
        tools = mcp_tools_to_anthropic(mcp_tools)
        if has_agent_tools:
            tools = tools + AGENT_TOOLS_DEFS
        tools = with_cache_breakpoint(tools)

        messages = [{"role": "user", "content": message}]
        for _ in range(MAX_TOOL_TURNS):
            response = await client.messages.create(
                model=MODEL,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=tools,
                messages=messages,
            )
            usage.add(response.usage)

            if response.stop_reason != "tool_use":
                final_text = "".join(
                    b.text for b in response.content if b.type == "text"
                )
                return final_text, usage, tool_calls

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

        return (
            "Não consegui concluir a consulta (muitas chamadas de ferramenta em sequência).",
            usage,
            tool_calls,
        )


async def run_plain_chat(message: str):
    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": message}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    usage = Usage()
    usage.add(response.usage)
    return text, usage


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

    async def event_stream():
        start = time.monotonic()
        usage = Usage()
        status = "ok"
        tool_calls: list[dict] = []
        try:
            if mcp_url:
                text, usage, tool_calls = await run_with_tools(
                    req.message, mcp_url, mcp_token, base_url, agent_tools_token
                )
            else:
                text, usage = await run_plain_chat(req.message)
            yield f"data: {text}\n\n"
        except Exception:
            status = "error"
            raise
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
            db.commit()
            db.close()
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
