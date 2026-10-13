import datetime

from sqlalchemy import Column, DateTime, Float, Integer, String, Text

from db import Base


class AgentClient(Base):
    __tablename__ = "agent_clients"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    base_url = Column(String, nullable=False)
    token_hash = Column(String, nullable=False)
    zabbix_mcp_url = Column(String, nullable=True)
    zabbix_mcp_token = Column(String, nullable=True)
    # Token do /api/agent-tools/* do map/ desse cliente (base_url + essas
    # rotas = as ferramentas de SSH: interfaces, rotas, BGP, log).
    agent_tools_token = Column(String, nullable=True)
    # Teto de gasto mensal em USD -- None/0 = sem limite. Checado no /chat
    # antes de cada chamada à Anthropic (ver chat.py:check_budget).
    monthly_budget_usd = Column(Float, nullable=True)
    # URL do endpoint /health do bot WhatsApp desse cliente (ex:
    # http://IP-do-cliente:8765/health) -- usado só pro widget de status
    # no painel (admin.py:check_whatsapp_status), não pro agente em si.
    whatsapp_health_url = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class AgentConversationMessage(Base):
    """Histórico de turnos por conversa -- sem isso cada chamada a /chat
    começava do zero, o agente "esquecia" a pergunta anterior na mesma
    conversa. Guarda só a pergunta do usuário e a resposta final em texto
    (não o rascunho intermediário de chamadas de ferramenta: cada turno
    novo refaz as consultas que precisar, mais simples e sem inflar o
    histórico com tool_use/tool_result de turnos antigos)."""

    __tablename__ = "agent_conversation_messages"

    id = Column(Integer, primary_key=True)
    client_name = Column(String, nullable=False)
    conversation_id = Column(String, nullable=False)
    role = Column(String, nullable=False)  # "user" | "assistant"
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class CommandKnowledge(Base):
    """Catálogo de comandos reais de equipamento, por fabricante --
    cadastrado pelo operador no painel (/admin/knowledge), nunca pelo
    agente de IA. Serve como referência pra implementar/corrigir as
    ferramentas de SSH (ssh_tools.py no lado de cada cliente): o
    operador cadastra o comando exato + uma saída de exemplo + o que
    ele faz, evitando adivinhar/buscar comandos de equipamento de rede
    de produção na internet. Não é consultado em runtime pelo agente --
    é puramente documentação estruturada."""

    __tablename__ = "command_knowledge"

    id = Column(Integer, primary_key=True)
    vendor = Column(String, nullable=False)  # "huawei" | "mikrotik" | "datacom" | "outro"
    category = Column(String, nullable=False)  # ex: "Sinal óptico", "PPPoE conectados"
    command = Column(Text, nullable=False)
    sample_output = Column(Text, nullable=True)
    description = Column(Text, nullable=True)
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
    cache_creation_tokens = Column(Integer, nullable=False, default=0)
    cache_read_tokens = Column(Integer, nullable=False, default=0)
    duration_ms = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="ok")
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
