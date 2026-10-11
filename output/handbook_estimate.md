# Handbook token & cost estimate

File: `data/shop_handbook.md`

## Token count

**10,058 tokens** (estimated).

How it was calculated:

- The handbook is 28,903 characters / 6,127 words.
- Tokenized with `tiktoken`'s `o200k_base` encoding (the encoding behind the GPT-4o model
  family) using `scripts/handbook_token_count.py`.
- **Caveat:** `gpt-6-luna` is a course-only model name, not one `tiktoken` recognizes, so there
  is no exact encoding for it. `o200k_base` is a best-effort proxy; the real token count
  gpt-6-luna reports at run time (from the API response's `usage` object) may differ from this
  estimate. That's what later steps will check this against.
- Result: 10,058 tokens over 28,903 characters = ~2.87 characters per token, which is in the
  normal range for English prose/markdown tables.

## Pricing used

From `data/prices.json`, model `gpt-6-luna` (OpenAI Standard pricing, per 1M tokens):

| Rate | $ per 1M tokens |
|---|---|
| Input (uncached) | $0.10 |
| Cached input | $0.01 |
| Cache write | $0.125 |
| Output | $0.50 |

The handbook is sent as input context, so only the input/cached-input/cache-write rates apply
here — this estimate does not include any output tokens, since those depend on what the model
is asked to produce, not on the handbook itself.

## Cost math

Let `T` = 10,058 tokens (the handbook).

### Without caching

Every call pays the full input rate:

```
cost_per_call = T x (input_rate / 1,000,000)
              = 10,058 x (0.10 / 1,000,000)
              = $0.0010058   (~0.101 cents)

cost_1000_calls = cost_per_call x 1,000
                = $0.0010058 x 1,000
                = $1.0058
```

### With caching

Portkey/OpenAI-style prompt caching charges the **cache write rate** the first time a prefix is
cached, then the much cheaper **cached input rate** on every subsequent call that reuses it. For
1,000 calls that all send the same handbook text as a stable prefix:

```
cost_first_call  = T x (cache_write_rate / 1,000,000)
                 = 10,058 x (0.125 / 1,000,000)
                 = $0.00125725

cost_per_cache_hit = T x (cached_rate / 1,000,000)
                    = 10,058 x (0.01 / 1,000,000)
                    = $0.00010058

cost_1000_calls_cached = cost_first_call + cost_per_cache_hit x (1,000 - 1)
                        = $0.00125725 + $0.00010058 x 999
                        = $0.00125725 + $0.10047942
                        = $0.10173667
```

**"1 call with caching" is two different numbers, not one**, because the first call and every
call after it are billed at different rates:

- **The 1st call (writes the cache):** $0.00125725 — this is actually *more* than an uncached
  call, because it pays the cache-write premium ($0.125/1M) on top of being a normal input send.
- **Any later call that hits the existing cache:** $0.00010058 — this is the cheap steady-state
  cost, 1/10th of the uncached input rate.

Caching only pays off once you reuse the cached handbook across many subsequent calls. A single
one-off call is cheaper *without* caching; the win shows up at scale (see the 1,000-call row
below).

## Summary table

| Scenario | 1st call | Later cached-hit call | 1,000 calls total |
|---|---|---|---|
| No caching (full input rate every time) | $0.0010058 | $0.0010058 | $1.0058 |
| With caching (cache write once, cached-input rate after) | $0.00125725 | $0.00010058 | $0.1017 |

Caching the handbook cuts the 1,000-call cost by roughly **90%** (from ~$1.01 to ~$0.10), because
after the first call every subsequent call pays the cached-input rate (1/10th of the normal input
rate) instead of the full input rate for the same ~10k-token handbook.

## Open question to check against real runs

This is a pre-send estimate from a local tokenizer, not a real API count. Later steps should
compare this 10,058-token estimate (and the derived costs) against the actual `input_tokens` /
`cached_tokens` values gpt-6-luna reports in its response `usage` object for real calls that
include the handbook, to see how close the `o200k_base` proxy is.
