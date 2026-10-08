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
from client_auth import resolve_client
from db import Base, SessionLocal, engine
from mcp_bridge import mcp_result_to_text, mcp_session, mcp_tools_to_anthropic
from models import AgentAuditLog

load_dotenv()

MODEL = "claude-sonnet-5"
MAX_TOOL_TURNS = 8

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET"])
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


async def run_with_tools(message: str, mcp_url: str, mcp_token: str | None):
    """Runs the Claude <-> Zabbix MCP tool loop and returns
    (final_text, input_tokens, output_tokens, tool_names_used)."""
    input_tokens = output_tokens = 0
    tool_names_used: list[str] = []

    async with mcp_session(mcp_url, mcp_token) as session:
        mcp_tools = (await session.list_tools()).tools
        tools = mcp_tools_to_anthropic(mcp_tools)

        messages = [{"role": "user", "content": message}]
        for _ in range(MAX_TOOL_TURNS):
            response = await client.messages.create(
                model=MODEL,
                max_tokens=1024,
                tools=tools,
                messages=messages,
            )
            input_tokens += response.usage.input_tokens
            output_tokens += response.usage.output_tokens

            if response.stop_reason != "tool_use":
                final_text = "".join(
                    b.text for b in response.content if b.type == "text"
                )
                return final_text, input_tokens, output_tokens, tool_names_used

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                tool_names_used.append(block.name)
                result = await session.call_tool(block.name, block.input)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": mcp_result_to_text(result),
                        "is_error": bool(result.is_error),
                    }
                )
            messages.append({"role": "user", "content": tool_results})

        return (
            "Não consegui concluir a consulta (muitas chamadas de ferramenta em sequência).",
            input_tokens,
            output_tokens,
            tool_names_used,
        )


async def run_plain_chat(message: str):
    response = await client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": message}],
    )
    text = "".join(b.text for b in response.content if b.type == "text")
    return text, response.usage.input_tokens, response.usage.output_tokens


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

    async def event_stream():
        start = time.monotonic()
        input_tokens = output_tokens = 0
        status = "ok"
        tool_names_used: list[str] = []
        try:
            if mcp_url:
                text, input_tokens, output_tokens, tool_names_used = await run_with_tools(
                    req.message, mcp_url, mcp_token
                )
            else:
                text, input_tokens, output_tokens = await run_plain_chat(req.message)
            yield f"data: {text}\n\n"
        except Exception:
            status = "error"
            raise
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            db.add(
                AgentAuditLog(
                    client_name=client_name,
                    tool_name=", ".join(dict.fromkeys(tool_names_used)) or "chat",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    duration_ms=duration_ms,
                    status=status,
                )
            )
            db.commit()
            db.close()
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
