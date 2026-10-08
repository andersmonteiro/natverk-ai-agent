"""Ponte pras ferramentas de SSH do cliente (interfaces, rotas, BGP, log) --
expostas pelo map/ em /api/agent-tools/*. Mesma lógica do mcp_bridge.py,
mas sem MCP: são rotas HTTP simples que nós mesmos definimos, protegidas
pelo agent_tools_token de cada cliente."""
import httpx

AGENT_TOOLS_DEFS = [
    {
        "name": "listar_interfaces_equipamento",
        "description": (
            "Lista as interfaces de um equipamento com IP, descrição (ex: "
            "para onde aquela porta vai) e sinal óptico, quando aplicável. "
            "Vem de um cache atualizado a cada poucos minutos, não de uma "
            "consulta ao vivo -- use para perguntas sobre configuração "
            "(IP de uma interface, qual porta vai para tal localidade, "
            "sinal óptico de uma porta), nunca para estado em tempo real."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
            },
            "required": ["hostid"],
        },
    },
    {
        "name": "listar_rotas_estaticas",
        "description": "Lista as rotas estáticas configuradas num equipamento (cache, não ao vivo).",
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
            },
            "required": ["hostid"],
        },
    },
    {
        "name": "consultar_bgp_vizinho",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) os prefixos anunciados por "
            "um vizinho BGP específico. Estado em tempo real, nunca cacheado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
                "neighbor_ip": {"type": "string", "description": "IP do vizinho BGP"},
            },
            "required": ["hostid", "neighbor_ip"],
        },
    },
    {
        "name": "consultar_log_equipamento",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) o log do próprio equipamento, "
            "opcionalmente a partir de uma data. Estado em tempo real, nunca cacheado."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
                "since": {"type": "string", "description": "Data/hora a partir de quando (opcional)"},
            },
            "required": ["hostid"],
        },
    },
]

_TOOL_NAMES = {t["name"] for t in AGENT_TOOLS_DEFS}


def is_agent_tool(name: str) -> bool:
    return name in _TOOL_NAMES


async def call_agent_tool(base_url: str, token: str, name: str, args: dict) -> str:
    headers = {"Authorization": f"Bearer {token}"}
    async with httpx.AsyncClient(timeout=15) as client:
        if name == "listar_interfaces_equipamento":
            resp = await client.get(f"{base_url}/api/agent-tools/interfaces/{args['hostid']}", headers=headers)
        elif name == "listar_rotas_estaticas":
            resp = await client.get(f"{base_url}/api/agent-tools/routes/{args['hostid']}", headers=headers)
        elif name == "consultar_bgp_vizinho":
            resp = await client.post(f"{base_url}/api/agent-tools/bgp-prefixes", headers=headers, json=args)
        elif name == "consultar_log_equipamento":
            resp = await client.post(f"{base_url}/api/agent-tools/device-logs", headers=headers, json=args)
        else:
            return f"Ferramenta desconhecida: {name}"

    if resp.status_code >= 400:
        try:
            return f"Erro: {resp.json().get('error', resp.text)}"
        except Exception:
            return f"Erro HTTP {resp.status_code}: {resp.text[:300]}"
    return resp.text
