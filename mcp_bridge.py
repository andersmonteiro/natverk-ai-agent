from contextlib import asynccontextmanager

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


@asynccontextmanager
async def mcp_session(url: str, token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with streamable_http_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            yield session


def mcp_tools_to_anthropic(mcp_tools) -> list[dict]:
    return [
        {
            "name": t.name,
            "description": t.description or "",
            "input_schema": t.inputSchema,
        }
        for t in mcp_tools
    ]


def mcp_result_to_text(result) -> str:
    parts = []
    for block in result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts) if parts else "(sem conteúdo)"
