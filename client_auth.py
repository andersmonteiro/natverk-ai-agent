import hashlib

from sqlalchemy.orm import Session

from models import AgentClient


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def resolve_client(token: str, db: Session) -> AgentClient | None:
    return (
        db.query(AgentClient).filter(AgentClient.token_hash == hash_token(token)).first()
    )
