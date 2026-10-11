"""Count tokens in the shop handbook and estimate its per-call cost.

gpt-6-luna is a course-only model name, not one tiktoken recognizes, so
there is no exact encoding for it. This uses tiktoken's o200k_base
encoding (the encoding behind GPT-4o-family models) as a best-effort
proxy -- the actual token count gpt-6-luna reports at run time may differ.
"""

from __future__ import annotations

import json
from pathlib import Path

import tiktoken

PROJECT_ROOT = Path(__file__).resolve().parent.parent
HANDBOOK_PATH = PROJECT_ROOT / "data" / "shop_handbook.md"
PRICES_PATH = PROJECT_ROOT / "data" / "prices.json"

ENCODING_NAME = "o200k_base"
MODEL_KEY = "gpt-6-luna"
N_CALLS = 1000


def main() -> None:
    text = HANDBOOK_PATH.read_text(encoding="utf-8")
    encoding = tiktoken.get_encoding(ENCODING_NAME)
    tokens = encoding.encode(text)
    token_count = len(tokens)

    char_count = len(text)
    word_count = len(text.split())

    prices = json.loads(PRICES_PATH.read_text(encoding="utf-8"))[MODEL_KEY]
    input_rate = prices["input_per_1m"]
    cached_rate = prices["cached_input_per_1m"]
    write_rate = prices["cache_write_per_1m"]

    cost_per_call_uncached = token_count * input_rate / 1_000_000
    cost_1000_uncached = cost_per_call_uncached * N_CALLS

    cost_first_call_cached = token_count * write_rate / 1_000_000
    cost_per_call_cached_hit = token_count * cached_rate / 1_000_000
    cost_1000_cached = cost_first_call_cached + cost_per_call_cached_hit * (N_CALLS - 1)

    result = {
        "char_count": char_count,
        "word_count": word_count,
        "token_count": token_count,
        "chars_per_token": round(char_count / token_count, 3),
        "input_rate_per_1m": input_rate,
        "cached_rate_per_1m": cached_rate,
        "cache_write_rate_per_1m": write_rate,
        "cost_per_call_uncached": cost_per_call_uncached,
        "cost_1000_calls_uncached": cost_1000_uncached,
        "cost_first_call_cached": cost_first_call_cached,
        "cost_per_call_cached_hit": cost_per_call_cached_hit,
        "cost_1000_calls_cached": cost_1000_cached,
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
