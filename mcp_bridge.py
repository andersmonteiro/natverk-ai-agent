from contextlib import asynccontextmanager

import httpx2
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@asynccontextmanager
async def mcp_session(url: str, token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    # Sem timeout aqui, um Zabbix MCP travado ou fora do ar deixava o /chat
    # inteiro pendurado pra sempre (sem resposta, sem erro) -- 30s é generoso
    # o bastante pra uma consulta Zabbix normal e curto o bastante pra não
    # segurar a requisição indefinidamente.
    async with httpx2.AsyncClient(headers=headers, timeout=30.0) as http_client:
        async with streamable_http_client(url, http_client=http_client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def mcp_tools_to_anthropic(mcp_tools) -> list[dict]:
    """Converts MCP tool definitions to Anthropic's tool format."""
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.input_schema,
        }
        for t in mcp_tools
    ]


def with_cache_breakpoint(tools: list[dict]) -> list[dict]:
    """Marks the last tool in the combined catalog as a cache breakpoint --
    the whole catalog (plus the system prompt, which precedes it in the
    request) is byte-identical on every call for a given client, so
    Anthropic can cache it and charge ~10% of the normal input price on a
    hit instead of resending it fresh every turn."""
    if tools:
        tools[-1] = {**tools[-1], "cache_control": {"type": "ephemeral"}}
    return tools


def mcp_result_to_text(result) -> str:
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else "(sem conteúdo)"
