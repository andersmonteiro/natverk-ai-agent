# Claude Sonnet 5 pricing, USD per million tokens.
INPUT_PRICE_PER_M = 2.0
OUTPUT_PRICE_PER_M = 10.0

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
