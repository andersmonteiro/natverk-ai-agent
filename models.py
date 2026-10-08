import datetime

from sqlalchemy import Column, DateTime, Integer, String, Text

from db import Base


class AgentClient(Base):
    __tablename__ = "agent_clients"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    base_url = Column(String, nullable=False)
    token_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AgentAuditLog(Base):
    __tablename__ = "agent_audit_log"

    id = Column(Integer, primary_key=True)
    client_name = Column(String, nullable=False)
    user = Column(String, nullable=True)
    tool_name = Column(String, nullable=False)
    target_host = Column(String, nullable=True)
    request_summary = Column(Text, nullable=True)
    response_summary = Column(Text, nullable=True)
    input_tokens = Column(Integer, nullable=False, default=0)
    output_tokens = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="ok")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
