# Cache test: what caching the handbook is worth

Method: `scripts/cache_test.py` ran the vendor desk agent on all 12 practice docs twice.

- **with_cache** — every call sends the exact same instructions (prompt.md + handbook),
  back-to-back, so the provider's automatic prompt caching can reuse the handbook across docs.
- **without_cache** — every call's instructions get a fresh random comment prepended, so the
  content has never been sent before and cannot be served from any earlier run's cache.

**A finding that shaped the method:** each agent run makes *two* model calls under the hood — one
where the model decides to call `read_vendor_document`, and a second, moments later, where it's
given the tool's result and produces the final answer. Both calls in that pair share the same
instructions, so the second call *always* reads the first call's cache write, in every run,
regardless of setup — that's real, unavoidable reuse within a single run, not cross-run cache
leakage. Checking the run's *summed* `cache_read_tokens` can't tell those two apart. So
`cache_test.py` instead checks the **first** model call of each run specifically (the only one
that could possibly inherit a *different* run's cache) and requires that one to show zero
cache-read tokens for every without_cache call — confirmed for all 12. The summed totals (what's
actually billed) are still what's recorded in `output/cache_test.json` and used for the cost math
below.

All 24 calls, every token count the API reported, and the computed cost are in
`output/cache_test.json`.

## Cost per doc and total, each setup

| Doc | with_cache cost | without_cache cost | % saved |
|---|---|---|---|
| p01_bluehen_quote.html | $0.002752 | $0.002756 | 0.1% |
| p02_elmcity_quote.html | $0.000369 | $0.002758 | 86.6% |
| p03_ivyprint_catalog.html | $0.000368 | $0.002759 | 86.7% |
| p04_harborstitch_quote.html | $0.000368 | $0.002756 | 86.6% |
| p05_maplemills_quote.pdf | $0.000365 | $0.002754 | 86.7% |
| p06_qtextile_quote.pdf | $0.000374 | $0.002763 | 86.5% |
| p07_longwharf_quote.pdf | $0.000377 | $0.002759 | 86.3% |
| p08_chapelst_email.eml | $0.000364 | $0.002754 | 86.8% |
| p09_westville_email.eml | $0.000367 | $0.002757 | 86.7% |
| p10_eastrock_email.eml | $0.000369 | $0.002758 | 86.6% |
| p11_yorkst_quote.html | $0.000361 | $0.002750 | 86.9% |
| p12_bluehen_quote.pdf | $0.000364 | $0.002753 | 86.8% |
| **Total (12 docs)** | **$0.006798** | **$0.033077** | **79.5%** |

The first with_cache row (p01) isn't a discount at all — $0.002752, almost identical to every
without_cache row — because it's the call that has to pay to *write* the cache in the first place.
From p02 onward, with_cache drops to a steady ~$0.00037/doc (reading the cache instead of writing
it), while without_cache stays flat at ~$0.00276/doc on every single call, since there's never
anything to reuse. Comparing just the steady-state calls (docs 2-12, after the cache is warm):
**$0.000368/doc with caching vs. $0.002756/doc without — an 86.7% saving per doc once the cache is
warm.** The 79.5% figure above is lower only because it still includes p01's one-time cache-write
cost in the with_cache total.

## How the real numbers compare to the Problem 2 estimate

Problem 2 estimated the handbook *alone* (10,058 tokens, via `tiktoken`'s `o200k_base` proxy) at:

| | Problem 2 estimate (handbook only) | Real run (handbook + prompt.md + tool schemas + both model calls) |
|---|---|---|
| Uncached cost | $0.0010058 | $0.002756 (without_cache, full run) |
| First-call / cache-write cost | $0.00125725 | $0.002752-0.002756 (p01 and all without_cache) |
| Cached-hit cost | $0.00010058 | $0.000364-0.000377 (with_cache, docs 2-12) |

The real per-call costs are **roughly 2.2-3.7x the Problem 2 estimate** across the board — expected,
because Problem 2 only ever counted the handbook's own ~10,058 tokens, while a real call also sends
`prompt.md`'s instructions, the three tool schemas plus the structured-output schema, the user
prompt, and (because of the two-call tool-use loop explained above) effectively pays for the shared
system content *twice* per run. The *shape* of the estimate held up well, though: Problem 2 predicted
a cached-hit should cost about 1/10th of a full-price call, and the real run shows a cached-hit
costing $0.000368 against a $0.002756 full-price call — almost exactly that same ~1/10th ratio.

## Projection: 1,000 docs/day for 30 days (30,000 docs)

Using the real per-doc costs measured above, and assuming the cache stays warm across the whole
month once written (one cache-write cost on day 1, steady-state cached cost for every call after):

```
without_cache: 30,000 docs x $0.002756/doc                         = $82.69

with_cache:    1 cache-write call x $0.002752
             + 29,999 cache-hit calls x $0.000368/doc               = $11.04
```

**Caching the handbook saves about $71.65 over the month (86.7%)** — essentially the same
steady-state percentage seen per-doc above, because at 30,000 calls the one-time $0.0028 cache-write
cost is negligible next to the total.

## What was surprising, and why

- **Caching barely moved the first call's price, but it isn't "wasted" — it's the cache purchase.**
  p01's with_cache cost ($0.002752) and every without_cache cost (~$0.00276) are essentially
  identical. That's expected once you see the mechanism: a "cold" call pays the `cache_write_per_1m`
  rate rather than the plain `input_per_1m` rate for the shared content, and those two rates are
  close enough (0.125 vs 0.10 per 1M, from `data/prices.json`) that a single cache-write call costs
  about the same as a call with no caching involved at all. The savings only show up once that
  write gets *reused*.
- **Every run secretly makes two model calls, not one, and that nearly derailed the experiment.**
  The agent's own tool-use loop (decide to call `read_vendor_document`, then answer using its
  result) means the *second* internal call of any single run always reads the *first* internal
  call's freshly written cache — a real, unavoidable saving that happens regardless of the
  with/without-cache setup being tested. Two earlier attempts at this script mistook that
  always-present reuse for a broken cache-buster and kept "fixing" the wrong knob (moving a
  cache-busting comment around in the prompt, then trying OpenAI's `prompt_cache_key` setting,
  then a Portkey cache-force-refresh header) before realizing the real fix was to check only the
  *first* call's cache status per run, not the run's summed total.
- **The documented cache-partitioning knob (`openai_prompt_cache_key`) had no effect here.** Giving
  every without_cache call a unique random `prompt_cache_key` did not stop it from reading a
  previous run's cache — this course's `gpt-6-luna` deployment appears to key its cache purely off
  prompt content, not off that parameter. The only thing that reliably forced a cold start was
  changing the actual content sent (prepending a random comment).
- **Cache reuse was essentially all-or-nothing across docs, not partial.** Every with_cache doc
  from p02 on reused ~22,209 of its ~22,730 input tokens (over 97%) — HTML, PDF, and `.eml` docs
  alike — because the only thing that changes between docs is the small, document-specific tail of
  the prompt (the tool's extracted text and the model's own reply), while the shared
  prompt.md+handbook block is large enough to dominate the token count either way.
