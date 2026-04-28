def tokens_from_usage(usage):
    if not usage:
        return {
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        }

    input_tokens = (
        usage.get("input_tokens")
        or usage.get("prompt_tokens")
        or 0
    )

    output_tokens = (
        usage.get("output_tokens")
        or usage.get("completion_tokens")
        or 0
    )

    total_tokens = (
        usage.get("total_tokens")
        or input_tokens + output_tokens
    )

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def estimate_openai_cost(
    usage_items,
    input_cost_per_1m,
    output_cost_per_1m,
    web_search_calls=0,
    web_search_cost_per_1k=10.0,
):
    total_input = 0
    total_output = 0

    for usage in usage_items:
        tokens = tokens_from_usage(usage)
        total_input += tokens["input_tokens"]
        total_output += tokens["output_tokens"]

    token_cost = (
        total_input / 1_000_000 * input_cost_per_1m
        + total_output / 1_000_000 * output_cost_per_1m
    )

    web_cost = web_search_calls / 1000 * web_search_cost_per_1k

    return {
        "input_tokens": total_input,
        "output_tokens": total_output,
        "total_tokens": total_input + total_output,
        "token_cost_usd": round(token_cost, 6),
        "web_search_calls": web_search_calls,
        "web_search_cost_usd": round(web_cost, 6),
        "total_openai_cost_usd": round(token_cost + web_cost, 6),
    }