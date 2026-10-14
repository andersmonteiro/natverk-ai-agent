"""Ponte pras ferramentas de SSH do cliente (interfaces, rotas, BGP, log) --
expostas pelo map/ em /api/agent-tools/*. Mesma lógica do mcp_bridge.py,
mas sem MCP: são rotas HTTP simples que nós mesmos definimos, protegidas
pelo agent_tools_token de cada cliente."""
import httpx

AGENT_TOOLS_DEFS = [
    {
        "name": "consultar_funcoes_equipamento",
        "description": (
            "Consulta (sem abrir SSH -- só lê um cadastro no Zabbix) quais "
            "funções um equipamento exerce, ex: ['BGP','PPPOE'] ou "
            "['SWITCH']. Um mesmo equipamento (NE8000, Mikrotik, ...) pode "
            "exercer mais de uma função ao mesmo tempo. Use isso quando a "
            "busca por nome de host trouxer MAIS DE UM candidato (ex: "
            "'Castelo' bate com um roteador BGP/PPPoE e um switch de "
            "acesso) pra escolher o certo antes de prosseguir, em vez de "
            "adivinhar só pelo nome. Lista vazia = função não cadastrada "
            "pra esse host ainda, não é erro -- nesse caso, use o nome do "
            "host como contexto (ex: prefixo 'BGP-') em vez de desistir."
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
        "name": "buscar_interface_por_descricao",
        "description": (
            "Busca (sem abrir SSH) por um TRECHO de descrição/apelido de "
            "circuito em TODOS os hosts de uma vez, sem precisar saber de "
            "antemão em qual host/local está -- primeiro checa os apelidos "
            "cadastrados manualmente pelo operador (resolução exata), e só "
            "se nenhum bater cai pra busca por trecho na descrição real da "
            "porta (cache de listar_interfaces_equipamento). Use isso "
            "PRIMEIRO quando o pedido descrever um circuito/porta pelo "
            "apelido dele sem dizer o host (ex: 'a fibra da travessia "
            "parece ter rompido' -- sem dizer qual equipamento). Pode "
            "retornar MAIS DE UM resultado (ex: os dois lados de uma "
            "travessia de fibra, cada um num switch diferente) -- nesse "
            "caso considere todos, não só o primeiro. Lista vazia = "
            "nenhuma interface cacheada bate com esse trecho; tente um "
            "trecho mais curto/genérico antes de desistir (ex: 'travessia' "
            "em vez de 'fibra da travessia')."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Trecho da descrição da porta (ex: 'travessia', 'proxmox')",
                },
            },
            "required": ["query"],
        },
    },
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
        "name": "consultar_resumo_pppoe",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) o TOTAL consolidado de "
            "assinantes PPPoE conectados agora (total geral, IPv4, IPv6, "
            "Dual-Stack, por domínio, etc). Use esta -- não "
            "listar_sessoes_pppoe -- quando a pergunta for 'quantos "
            "clientes PPPoE estão conectados', já que traz o total pronto "
            "em vez de uma lista longa pra contar manualmente. Só Huawei "
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
        "name": "listar_sessoes_pppoe",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) a lista completa de "
            "sessões PPPoE conectadas, uma por assinante: login, VLAN, "
            "interface do PPPoE Server, IP e MAC. Pode ser uma lista longa "
            "(centenas de linhas) -- pra só saber o total, use "
            "consultar_resumo_pppoe. Só Huawei por enquanto."
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
        "name": "consultar_pppoe_por_vlan",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) a(s) sessão(ões) PPPoE de "
            "uma VLAN de assinante específica. Só Huawei por enquanto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
                "pevlan": {"type": "string", "description": "Número da VLAN do assinante"},
            },
            "required": ["hostid", "pevlan"],
        },
    },
    {
        "name": "consultar_pppoe_por_login",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) a sessão PPPoE de um "
            "assinante pelo login (ou parte dele). Só Huawei por enquanto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
                "username_fragment": {"type": "string", "description": "Login do assinante, ou parte dele"},
            },
            "required": ["hostid", "username_fragment"],
        },
    },
    {
        "name": "consultar_uso_pool_pppoe",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) a capacidade das pools de "
            "IP usadas pelos domínios PPPoE: total, usado e porcentagem de "
            "ocupação por domínio. Use pra saber se uma pool está perto de "
            "esgotar. Só Huawei por enquanto."
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
        "name": "consultar_falha_autenticacao_pppoe",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) o registro de falha de "
            "autenticação AAA de assinantes PPPoE de uma VLAN -- pra achar "
            "clientes bloqueados/rejeitados pelo RADIUS, senha/login "
            "errados, etc. Só Huawei por enquanto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
                "pevlan": {"type": "string", "description": "Número da VLAN do assinante"},
            },
            "required": ["hostid", "pevlan"],
        },
    },
    {
        "name": "consultar_status_interface",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) o status operacional "
            "detalhado de UMA interface: se está UP/DOWN física e por "
            "protocolo, há quanto tempo, modo trunk/access, velocidade, "
            "tráfego dos últimos 300s (bits/sec, pacotes/sec) e erros. "
            "Diferente de consultar_configuracao_interface (configuração "
            "estática) e consultar_sinal_optico (sinal óptico). Só Huawei "
            "por enquanto."
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
        "name": "consultar_mac_por_vlan",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) a tabela de endereços MAC "
            "aprendidos numa VLAN específica: MAC, tipo (dynamic/static) e "
            "de qual interface foi aprendido. Só Huawei por enquanto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
                "vlan_id": {"type": "string", "description": "Número da VLAN"},
            },
            "required": ["hostid", "vlan_id"],
        },
    },
    {
        "name": "listar_vlans",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) todas as VLANs criadas no "
            "equipamento (estáticas, dinâmicas e reservadas). Só Huawei por "
            "enquanto."
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
        "name": "consultar_configuracao_completa",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) a configuração COMPLETA do "
            "equipamento: VLANs, interfaces e descrições, IPs, roteamento, "
            "filtros, BGP, etc. Saída pode ser bem longa -- prefira "
            "consultar_configuracao_bgp ou consultar_configuracao_interface "
            "quando só precisar de uma parte específica. Só Huawei por "
            "enquanto."
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
        "name": "consultar_rota_destino",
        "description": (
            "Consulta AO VIVO (abre SSH na hora) a rota de melhor match pra "
            "um IP específico -- de QUALQUER protocolo (BGP, OSPF, "
            "estática, etc), não só estática. Use destination='0.0.0.0' "
            "pra achar a ROTA DEFAULT do equipamento (0.0.0.0 é sempre o "
            "pior/mais genérico match, então a rota retornada é sempre a "
            "default). Diferente de listar_rotas_estaticas (cache, só "
            "mostra rotas ESTÁTICAS) -- a rota default de um roteador de "
            "borda é normalmente aprendida via BGP do provedor de trânsito, "
            "não estática, e por isso nunca aparece em "
            "listar_rotas_estaticas. Depois de achar o NextHop aqui, pra "
            "identificar QUEM é esse vizinho (ex: qual provedor de "
            "trânsito/\"upload\"), chame consultar_configuracao_bgp e "
            "procure 'peer <NextHop> description ...'. Só aceita IP puro "
            "(sem /máscara). Só Huawei por enquanto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "hostid": {"type": "string", "description": "hostid do Zabbix"},
                "destination": {
                    "type": "string",
                    "description": "IP de destino, ou '0.0.0.0' pra achar a rota default",
                },
            },
            "required": ["hostid", "destination"],
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
    # 15s não bastava pros comandos de saída grande (sessões PPPoE, config
    # completa) que agora pedem read_timeout=60 pro netmiko do lado do
    # map/ -- o HTTP desistia antes do SSH terminar de paginar a saída.
    async with httpx.AsyncClient(timeout=75) as client:
        if name == "consultar_funcoes_equipamento":
            resp = await client.get(f"{base_url}/api/agent-tools/host-functions/{args['hostid']}", headers=headers)
        elif name == "buscar_interface_por_descricao":
            resp = await client.post(f"{base_url}/api/agent-tools/search-interfaces", headers=headers, json=args)
        elif name == "listar_interfaces_equipamento":
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
        elif name == "consultar_resumo_pppoe":
            resp = await client.post(f"{base_url}/api/agent-tools/pppoe-summary", headers=headers, json=args)
        elif name == "listar_sessoes_pppoe":
            resp = await client.post(f"{base_url}/api/agent-tools/pppoe-sessions", headers=headers, json=args)
        elif name == "consultar_pppoe_por_vlan":
            resp = await client.post(f"{base_url}/api/agent-tools/pppoe-session-by-vlan", headers=headers, json=args)
        elif name == "consultar_pppoe_por_login":
            resp = await client.post(f"{base_url}/api/agent-tools/pppoe-session-by-username", headers=headers, json=args)
        elif name == "consultar_uso_pool_pppoe":
            resp = await client.post(f"{base_url}/api/agent-tools/pppoe-pool-usage", headers=headers, json=args)
        elif name == "consultar_falha_autenticacao_pppoe":
            resp = await client.post(f"{base_url}/api/agent-tools/pppoe-aaa-fail-record", headers=headers, json=args)
        elif name == "consultar_status_interface":
            resp = await client.post(f"{base_url}/api/agent-tools/interface-status", headers=headers, json=args)
        elif name == "consultar_mac_por_vlan":
            resp = await client.post(f"{base_url}/api/agent-tools/mac-address-by-vlan", headers=headers, json=args)
        elif name == "listar_vlans":
            resp = await client.post(f"{base_url}/api/agent-tools/vlan-summary", headers=headers, json=args)
        elif name == "consultar_configuracao_completa":
            resp = await client.post(f"{base_url}/api/agent-tools/full-config", headers=headers, json=args)
        elif name == "consultar_rota_destino":
            resp = await client.post(f"{base_url}/api/agent-tools/route-lookup", headers=headers, json=args)
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
    # As rotas que encapsulam saída crua de equipamento devolvem
    # {"output": "..."} -- sem desembrulhar aqui, o modelo recebia o JSON
    # inteiro como texto (chaves + aspas + \n escapado em vez de quebra de
    # linha real), o que tanto desperdiça tokens quanto atrapalha a
    # instrução do system prompt de reproduzir a saída verbatim num bloco
    # de código. listar_interfaces_equipamento/listar_rotas_estaticas (e
    # user-by-phone) têm um schema de resposta diferente (sem "output") e
    # continuam passando como JSON de propósito -- o modelo precisa da
    # estrutura deles, não é texto de CLI.
    try:
        parsed = resp.json()
    except Exception:
        return resp.text
    if isinstance(parsed, dict) and "output" in parsed:
        return parsed["output"]
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
