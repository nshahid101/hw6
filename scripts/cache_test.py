"""Problem 4: measure what prompt-caching the handbook is actually worth.

Runs the vendor desk agent on all 12 practice docs twice:

- "with_cache": every call gets the exact same instructions string (handbook
  included), run back-to-back, so the provider's automatic prompt caching
  can reuse the handbook from cache across different docs' runs.
- "without_cache": every call's instructions get a fresh random nonce
  prepended, so the content has never been seen before and the FIRST
  internal model call of that run is guaranteed to miss the cache (nothing
  to reuse from any earlier run or doc).

Why "first internal call", not "zero cache_read_tokens overall": each
agent.run_sync() call here makes *two* model requests under the hood --
one where the model decides to call read_vendor_document, and a second,
moments later, where it's given the tool's result and produces the final
answer. Both requests in that pair share the exact same instructions, so
the second request *always* reads the first request's cache write, in
every run, no matter what setup we're testing. That's real, unavoidable,
same-run reuse -- not evidence of cross-run/cross-doc cache leakage. Two
earlier attempts at this script wrongly treated that unavoidable reuse as
a bug and kept "fixing" the wrong thing (first appending, then prepending
a nonce to the instructions string; then trying the openai_prompt_cache_key
setting and a Portkey cache-force-refresh header -- none of those were
the actual problem). The real check that matters is on the FIRST model
request specifically: did *it* find anything in the cache? `result.usage`
only gives the sum across both requests, so we pull the per-request
breakdown from `result.all_messages()` to verify the first request's
cache_read_tokens is 0 for every without_cache run, then use the summed
total (what's actually billed) for the cost math.
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse

from models import VendorDeskResult
from portkey_config import get_model
from tools import RunDeps, approve_payment, read_vendor_document, send_email

PROMPT_PATH = PROJECT_ROOT / "prompts" / "prompt.md"
DEFENSE_RULES_START = "<!-- DEFENSE RULES START -->"
HANDBOOK_PATH = PROJECT_ROOT / "data" / "shop_handbook.md"
PRICES_PATH = PROJECT_ROOT / "data" / "prices.json"
PRACTICE_DOCS_DIR = PROJECT_ROOT / "data" / "practice_docs"
OUTPUT_PATH = PROJECT_ROOT / "output" / "cache_test.json"
MODEL_KEY = "gpt-6-luna"


def base_instructions() -> str:
    """This experiment predates Problem 6's defenses, so it uses the prompt as it was then --
    everything in prompt.md before the DEFENSE RULES marker."""
    base, _, _ = PROMPT_PATH.read_text(encoding="utf-8").partition(DEFENSE_RULES_START)
    handbook = HANDBOOK_PATH.read_text(encoding="utf-8")
    return f"{base.strip()}\n\n## Campus Customs Shop Handbook (full text)\n\n{handbook}"


def build_bare_agent() -> Agent[RunDeps, VendorDeskResult]:
    """Same tools/model/output_type as agent.py's agent, but with no instructions baked in at
    construction time, so each run below can supply the full instructions itself."""
    agent = Agent(get_model(), deps_type=RunDeps, output_type=VendorDeskResult)
    agent.tool(read_vendor_document)
    agent.tool(send_email)
    agent.tool(approve_payment)
    return agent


def compute_cost(input_tokens: int, cache_read_tokens: int, cache_write_tokens: int, output_tokens: int) -> float:
    prices = json.loads(PRICES_PATH.read_text(encoding="utf-8"))[MODEL_KEY]
    uncached_input_tokens = max(input_tokens - cache_read_tokens, 0)
    return (
        uncached_input_tokens * prices["input_per_1m"]
        + cache_read_tokens * prices["cached_input_per_1m"]
        + cache_write_tokens * prices["cache_write_per_1m"]
        + output_tokens * prices["output_per_1m"]
    ) / 1_000_000


def first_request_cache_read(result) -> int:
    """cache_read_tokens on the first internal model request only (not the summed total) --
    this is the one request in the run that could possibly reuse a PRIOR run's cache."""
    for message in result.all_messages():
        if isinstance(message, ModelResponse):
            return message.usage.cache_read_tokens
    return 0


def run_one(agent: Agent, doc: Path, setup: str, instructions: str) -> dict:
    deps = RunDeps(doc_path=str(doc))
    prompt = f"Process the vendor document at this exact path, using the read_vendor_document tool: {doc}"
    result = agent.run_sync(prompt, instructions=instructions, deps=deps)
    usage = result.usage

    if setup == "without_cache":
        leaked = first_request_cache_read(result)
        if leaked:
            raise RuntimeError(
                f"without_cache run for {doc.name}: the FIRST model request still read {leaked} tokens "
                "from cache -- it reused a previous run's cached handbook, so this call doesn't count."
            )

    cost = compute_cost(usage.input_tokens, usage.cache_read_tokens, usage.cache_write_tokens, usage.output_tokens)
    return {
        "setup": setup,
        "doc": doc.name,
        "requests": usage.requests,
        "input_tokens": usage.input_tokens,
        "cache_read_tokens": usage.cache_read_tokens,
        "cache_write_tokens": usage.cache_write_tokens,
        "output_tokens": usage.output_tokens,
        "cost_usd": round(cost, 6),
        "decision": result.output.decision.value,
    }


def load_existing_records() -> list[dict]:
    if OUTPUT_PATH.exists():
        return json.loads(OUTPUT_PATH.read_text(encoding="utf-8"))
    return []


def save_records(records: list[dict]) -> None:
    OUTPUT_PATH.write_text(json.dumps(records, indent=2), encoding="utf-8")


def _phases_to_run(phase: str) -> set[str]:
    return {"with_cache", "without_cache"} if phase == "both" else {phase}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=["with_cache", "without_cache", "both"], default="both")
    args = parser.parse_args()
    phases = _phases_to_run(args.phase)

    docs = sorted(PRACTICE_DOCS_DIR.iterdir())
    agent = build_bare_agent()
    instructions = base_instructions()

    records = [r for r in load_existing_records() if r["setup"] not in phases]

    if "with_cache" in phases:
        print(f"--- with_cache: {len(docs)} calls, identical content every time ---")
        for doc in docs:
            record = run_one(agent, doc, "with_cache", instructions)
            records.append(record)
            save_records(records)
            print(f"  {doc.name}: input={record['input_tokens']} cache_read={record['cache_read_tokens']} "
                  f"cache_write={record['cache_write_tokens']} output={record['output_tokens']} "
                  f"cost=${record['cost_usd']}")

    if "without_cache" in phases:
        print(f"--- without_cache: {len(docs)} calls, fresh random content every time ---")
        for doc in docs:
            nonce_instructions = f"<!-- cache-buster: {uuid.uuid4()} -->\n\n{instructions}"
            record = run_one(agent, doc, "without_cache", nonce_instructions)
            records.append(record)
            save_records(records)
            print(f"  {doc.name}: input={record['input_tokens']} cache_read={record['cache_read_tokens']} "
                  f"cache_write={record['cache_write_tokens']} output={record['output_tokens']} "
                  f"cost=${record['cost_usd']}")

    print(f"\nWrote {len(records)} call records to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
