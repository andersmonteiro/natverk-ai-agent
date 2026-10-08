# Claude Sonnet 5 pricing, USD per million tokens.
INPUT_PRICE_PER_M = 2.0
OUTPUT_PRICE_PER_M = 10.0


def cost_usd(input_tokens: int, output_tokens: int) -> float:
    return (input_tokens / 1_000_000) * INPUT_PRICE_PER_M + (
        output_tokens / 1_000_000
    ) * OUTPUT_PRICE_PER_M
