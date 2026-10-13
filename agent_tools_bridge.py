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
            "sinal óptico de uma porta), nunca para estado em tempo real. "
            "Resposta: {interfaces: [...], note?: string}. Se vier 'note', "
            "a lista está vazia porque o cache ainda não tem dado pra esse "
            "host (não porque o host não tem interfaces de verdade) -- "
            "nunca conclua que o equipamento não tem interfaces com base "
            "numa lista vazia, diga que não conseguiu obter o dado ainda."
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
        "description": (
            "Lista as rotas estáticas configuradas num equipamento (cache, "
            "não ao vivo). Resposta: {routes: [...], note?: string}. Se "
            "vier 'note', a lista está vazia porque o cache ainda não tem "
            "dado pra esse host -- nunca conclua que o equipamento não tem "
            "rotas com base numa lista vazia, diga que não conseguiu obter "
            "o dado ainda."
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
        "name": "consultar_bgp_vizinho",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) os prefixos anunciados por "
            "um vizinho BGP específico. Estado em tempo real, nunca cacheado. "
            "Só Huawei por enquanto. Precisa do IP do vizinho -- se não "
            "souber, use listar_sessoes_bgp primeiro."
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
        "name": "listar_sessoes_bgp",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) TODAS as sessões BGP "
            "configuradas no equipamento: IP do vizinho, AS, estado "
            "(Established/Idle/Active), tempo de atividade e prefixos "
            "recebidos. Use isso primeiro quando não souber o IP de um "
            "vizinho BGP específico -- por exemplo, pra achar qual sessão "
            "corresponde a uma interface ou descrição conhecida. Só Huawei "
            "por enquanto."
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
        "name": "consultar_sessao_bgp_especifica",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) o estado resumido de UM "
            "vizinho BGP (estado, AS, prefixos recebidos), já sabendo o IP "
            "dele -- mais direto que listar_sessoes_bgp quando o IP já é "
            "conhecido. Só Huawei por enquanto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
                "peer_ip": {"type": "string", "description": "IP do vizinho BGP"},
            },
            "required": ["hostid", "peer_ip"],
        },
    },
    {
        "name": "consultar_configuracao_bgp",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) a configuração completa de "
            "BGP do equipamento: AS local, vizinhos configurados (inclusive "
            "a DESCRIÇÃO de cada peer, ex: 'peer 10.163.151.2 description "
            "MECHS-GTA-BGP'), e qual route-policy de entrada/saída está "
            "aplicada a cada um. Use esta -- não listar_sessoes_bgp, que não "
            "traz descrição -- quando precisar achar/identificar/ordenar um "
            "vizinho pela descrição dele. Só Huawei por enquanto."
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
        "name": "consultar_configuracao_route_policy",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) a configuração de todos os "
            "filtros de rota (route-policy) usados nas sessões BGP -- o que "
            "cada filtro de entrada/saída faz (permite, nega, ajusta "
            "local-preference/as-path/community). Só Huawei por enquanto."
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
        "name": "consultar_prefixos_ipv4",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) todos os prefixos IPv4 "
            "cadastrados (ip-prefix) usados pelos filtros de BGP. Só "
            "Huawei por enquanto."
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
        "name": "consultar_prefixos_ipv6",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) todos os prefixos IPv6 "
            "cadastrados (ipv6-prefix) usados pelos filtros de BGP. Só "
            "Huawei por enquanto."
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
    {
        "name": "consultar_configuracao_interface",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) a configuração completa de "
            "UMA interface -- todos os IPs/sub-IPs configurados nela, modo da "
            "porta, vlans, etc. Diferente de listar_interfaces_equipamento "
            "(cache): aquela só traz o IP principal, esta traz TODOS os IPs "
            "configurados na porta (inclusive endereços secundários/'sub'). "
            "Use listar_interfaces_equipamento primeiro pra achar o nome "
            "exato da interface certa (ex: pela descrição), e só então chame "
            "esta com o nome exato retornado de lá."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
                "interface": {
                    "type": "string",
                    "description": "Nome exato da interface, como retornado por listar_interfaces_equipamento",
                },
            },
            "required": ["hostid", "interface"],
        },
    },
    {
        "name": "consultar_arp_interface",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) a tabela ARP filtrada por "
            "uma interface -- mostra quais dos IPs configurados nessa porta "
            "(ver consultar_configuracao_interface) estão de fato em uso por "
            "algum equipamento agora, e o MAC de quem está usando."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
                "interface": {
                    "type": "string",
                    "description": "Nome exato da interface, como retornado por listar_interfaces_equipamento",
                },
            },
            "required": ["hostid", "interface"],
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
        elif name == "listar_sessoes_bgp":
            resp = await client.post(f"{base_url}/api/agent-tools/bgp-peers", headers=headers, json=args)
        elif name == "consultar_sessao_bgp_especifica":
            resp = await client.post(f"{base_url}/api/agent-tools/bgp-peer-detail", headers=headers, json=args)
        elif name == "consultar_configuracao_bgp":
            resp = await client.post(f"{base_url}/api/agent-tools/bgp-config", headers=headers, json=args)
        elif name == "consultar_configuracao_route_policy":
            resp = await client.post(f"{base_url}/api/agent-tools/route-policy-config", headers=headers, json=args)
        elif name == "consultar_prefixos_ipv4":
            resp = await client.post(f"{base_url}/api/agent-tools/ip-prefix-list", headers=headers, json=args)
        elif name == "consultar_prefixos_ipv6":
            resp = await client.post(f"{base_url}/api/agent-tools/ipv6-prefix-list", headers=headers, json=args)
        elif name == "consultar_log_equipamento":
            resp = await client.post(f"{base_url}/api/agent-tools/device-logs", headers=headers, json=args)
        elif name == "consultar_configuracao_interface":
            resp = await client.post(f"{base_url}/api/agent-tools/interface-config", headers=headers, json=args)
        elif name == "consultar_arp_interface":
            resp = await client.post(f"{base_url}/api/agent-tools/interface-arp", headers=headers, json=args)
        else:
            return f"Ferramenta desconhecida: {name}"

    if resp.status_code >= 400:
        try:
            return f"Erro: {resp.json().get('error', resp.text)}"
        except Exception:
            return f"Erro HTTP {resp.status_code}: {resp.text[:300]}"
    return resp.text


async def resolve_sender_name(base_url: str, token: str, sender_phone: str) -> str | None:
    """Consulta o cadastro de usuários do map/ (não é uma ferramenta que o
    modelo chama, é resolvido aqui antes de montar o system prompt) --
    None quando o telefone não está vinculado a nenhum usuário, o que é
    esperado e não um erro: o número ainda é logado no audit log mesmo
    sem nome resolvido."""
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{base_url}/api/agent-tools/user-by-phone/{sender_phone}",
                headers={"Authorization": f"Bearer {token}"},
            )
        if resp.status_code != 200:
            return None
        return resp.json().get("display_name")
    except Exception:
        return None
