import os
import time

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.sessions import SessionMiddleware

import admin
from client_auth import resolve_client
from db import Base, SessionLocal, engine
from models import AgentAuditLog

load_dotenv()

MODEL = "claude-sonnet-5"

app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.environ["SESSION_SECRET"])
app.mount("/static", StaticFiles(directory="static"), name="static")
app.include_router(admin.router)

client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


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


@app.post("/chat")
def chat(req: ChatRequest, x_agent_token: str = Header(...)):
    db = SessionLocal()
    agent_client = resolve_client(x_agent_token, db)
    if agent_client is None:
        db.close()
        raise HTTPException(status_code=401, detail="Token de cliente inválido")
    client_name = agent_client.name

    def event_stream():
        start = time.monotonic()
        input_tokens = output_tokens = 0
        status = "ok"
        try:
            with client.messages.stream(
                model=MODEL,
                max_tokens=1024,
                messages=[{"role": "user", "content": req.message}],
            ) as stream:
                for text in stream.text_stream:
                    yield f"data: {text}\n\n"
                final = stream.get_final_message()
                input_tokens = final.usage.input_tokens
                output_tokens = final.usage.output_tokens
        except Exception:
            status = "error"
            raise
        finally:
            duration_ms = int((time.monotonic() - start) * 1000)
            db.add(
                AgentAuditLog(
                    client_name=client_name,
                    tool_name="chat",
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
