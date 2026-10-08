import os

from anthropic import Anthropic
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

load_dotenv()

MODEL = "claude-sonnet-5"

app = FastAPI()
client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])


class ChatRequest(BaseModel):
    message: str


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/chat")
def chat(req: ChatRequest):
    def event_stream():
        with client.messages.stream(
            model=MODEL,
            max_tokens=1024,
            messages=[{"role": "user", "content": req.message}],
        ) as stream:
            for text in stream.text_stream:
                yield f"data: {text}\n\n"
        yield "event: done\ndata: {}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")
