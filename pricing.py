# Preço por milhão de tokens -- precisa acompanhar o MODEL em chat.py pro
# painel de custo/orçamento mensal não mentir. Testando Haiku 5.5 por
# custo; valores de Sonnet 5 ficam comentados do lado pra reverter junto
# se o MODEL voltar.
INPUT_PRICE_PER_M = 0.10   # Sonnet 5: 2.0
OUTPUT_PRICE_PER_M = 0.50  # Sonnet 5: 10.0

# Prompt caching multipliers (standard across Claude models): writing to
# cache costs more than a normal input token, reading from cache costs
# much less -- that's the whole point of caching the tool catalog/system
# prompt, which is identical across calls.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.1


def cost_usd(
    input_tokens: int,
    output_tokens: int,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> float:
    return (
        (input_tokens / 1_000_000) * INPUT_PRICE_PER_M
        + (output_tokens / 1_000_000) * OUTPUT_PRICE_PER_M
        + (cache_creation_tokens / 1_000_000) * INPUT_PRICE_PER_M * CACHE_WRITE_MULTIPLIER
        + (cache_read_tokens / 1_000_000) * INPUT_PRICE_PER_M * CACHE_READ_MULTIPLIER
    )
