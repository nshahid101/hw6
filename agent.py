"""Entry point for the Campus Customs vendor desk agent.

Usage:
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html
    python agent.py --doc data/practice_docs/p01_bluehen_quote.html --no-defenses

Defenses are on by default (Problem 6). `--no-defenses` reproduces the original Problem 3/5
behavior exactly -- no document sanitization, no authoritative-field extraction, no independent
decision verification, and send_email/approve_payment execute immediately instead of requiring
approval -- for direct before/after comparison.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from pydantic_ai import Agent, DeferredToolRequests, ToolDenied

import defenses
from models import AuditEntry, Decision, UsageEntry, VendorDeskResult
from portkey_config import get_model
from tools import RunDeps, approve_payment, log_trap_call, read_vendor_document, send_email

PROJECT_ROOT = Path(__file__).resolve().parent
PROMPT_PATH = PROJECT_ROOT / "prompts" / "prompt.md"
HANDBOOK_PATH = PROJECT_ROOT / "data" / "shop_handbook.md"
PRICES_PATH = PROJECT_ROOT / "data" / "prices.json"
OUTPUT_DIR = PROJECT_ROOT / "output"
AUDIT_LOG_PATH = OUTPUT_DIR / "audit_trail.json"
USAGE_LOG_PATH = OUTPUT_DIR / "usage_log.json"
MODEL_KEY = "gpt-6-luna"
MAX_APPROVAL_ROUNDS = 3
DEFENSE_RULES_START = "<!-- DEFENSE RULES START -->"
DEFENSE_RULES_END = "<!-- DEFENSE RULES END -->"


def build_instructions(defenses_enabled: bool) -> str:
    """The agent's instructions, with the handbook appended so it is sent on every call.

    PROMPT-level defense: prompts/prompt.md has a clearly delimited "defense rules" section
    (between the DEFENSE_RULES_START/END markers) that is only included when defenses are
    enabled, so --no-defenses reproduces the original Problem 3/5 prompt exactly.
    """
    full_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    base, _, rest = full_prompt.partition(DEFENSE_RULES_START)
    defense_section, _, _ = rest.partition(DEFENSE_RULES_END)

    handbook = HANDBOOK_PATH.read_text(encoding="utf-8")
    instructions = f"{base.strip()}\n\n## Campus Customs Shop Handbook (full text)\n\n{handbook}"
    if defenses_enabled:
        instructions += "\n\n" + defense_section.strip()
    return instructions


def build_agent(defenses_enabled: bool) -> Agent[RunDeps, VendorDeskResult | DeferredToolRequests]:
    agent = Agent(
        get_model(),
        deps_type=RunDeps,
        output_type=[VendorDeskResult, DeferredToolRequests],
        instructions=build_instructions(defenses_enabled),
    )
    agent.tool(read_vendor_document)
    # DESIGN-level defense: with defenses enabled, these two tools require approval before their
    # bodies ever run. A poisoned document can talk the model into *requesting* send_email or
    # approve_payment, but the request is intercepted here -- see resolve_deferred_calls() below --
    # and nothing is actually sent or paid without a human saying so. They are never removed, per
    # the shop's plan to use them later with real sign-off.
    agent.tool(send_email, requires_approval=defenses_enabled)
    agent.tool(approve_payment, requires_approval=defenses_enabled)
    return agent


def resolve_deferred_calls(agent: Agent, result, deps: RunDeps):
    """If the model tried to call send_email/approve_payment, log every attempt, deny it (no human
    is present to sign off in this CLI), and let the agent continue its real job. Loops in case the
    model tries again after being denied; gives up safely after a few rounds."""
    rounds = 0
    while isinstance(result.output, DeferredToolRequests) and rounds < MAX_APPROVAL_ROUNDS:
        rounds += 1
        denials = {}
        for call in result.output.approvals:
            log_trap_call(call.tool_name, call.args_as_dict())
            denials[call.tool_call_id] = ToolDenied(
                "Denied: no human sign-off is available in this run. send_email and "
                "approve_payment always require explicit human approval."
            )
        deferred_results = result.output.build_results(approvals=denials)
        result = agent.run_sync(
            "Continue with your read-and-report job. The tool call you just attempted was denied.",
            message_history=result.all_messages(),
            deferred_tool_results=deferred_results,
            deps=deps,
        )

    if isinstance(result.output, DeferredToolRequests):
        # Gave up after MAX_APPROVAL_ROUNDS -- fail safe rather than loop forever or crash.
        safe_output = VendorDeskResult(
            vendor=None,
            sku=None,
            unit_price=None,
            lead_time_days=None,
            min_order=None,
            decision="do_not_recommend",
            reason="Blocked: the document repeatedly tried to trigger a restricted tool call.",
        )
        return result, safe_output
    return result, result.output


def verify_decision(output: VendorDeskResult, deps: RunDeps) -> VendorDeskResult:
    """DESIGN-level backstop: independently recompute the purchasing decision from the handbook
    and the code-extracted (first-stated, redaction-protected) fields, and override the model's
    answer if it disagrees. This is what actually fixes Problem 5's p02/p07/p12 attacks even if an
    injection somehow talked the model into a wrong number despite the code and prompt defenses --
    the number that gets logged and printed is this function's, not the model's."""
    extracted = deps.extracted_fields or {}
    unit_price = extracted.get("unit_price") if extracted.get("unit_price") is not None else output.unit_price
    lead_time_days = (
        extracted.get("lead_time_days") if extracted.get("lead_time_days") is not None else output.lead_time_days
    )
    min_order = extracted.get("min_order") if extracted.get("min_order") is not None else output.min_order

    verified_decision, verified_reason = defenses.verify_decision(
        output.vendor, output.sku, unit_price, lead_time_days, min_order
    )

    disagrees = (
        output.decision.value != verified_decision
        or output.unit_price != unit_price
        or output.lead_time_days != lead_time_days
        or output.min_order != min_order
    )
    if not disagrees:
        return output

    return output.model_copy(
        update={
            "unit_price": unit_price,
            "lead_time_days": lead_time_days,
            "min_order": min_order,
            "decision": Decision(verified_decision),
            "reason": f"{verified_reason} (independent verifier overrode the model's answer, which "
            "disagreed with the document's first-stated facts and/or the handbook rule).",
        }
    )


def _append_json_list(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
    entries.append(entry)
    path.write_text(json.dumps(entries, indent=2, default=str), encoding="utf-8")


def compute_cost(input_tokens: int, cache_read_tokens: int, cache_write_tokens: int, output_tokens: int) -> float:
    prices = json.loads(PRICES_PATH.read_text(encoding="utf-8"))[MODEL_KEY]
    uncached_input_tokens = max(input_tokens - cache_read_tokens, 0)
    return (
        uncached_input_tokens * prices["input_per_1m"]
        + cache_read_tokens * prices["cached_input_per_1m"]
        + cache_write_tokens * prices["cache_write_per_1m"]
        + output_tokens * prices["output_per_1m"]
    ) / 1_000_000


def main() -> None:
    parser = argparse.ArgumentParser(description="Campus Customs vendor desk agent")
    parser.add_argument("--doc", required=True, help="Path to a vendor document (HTML, PDF, or .eml)")
    parser.add_argument(
        "--no-defenses",
        action="store_true",
        help="Disable all Problem 6 defenses (code sanitization, tool approval gating, decision "
        "verification) to reproduce the original Problem 3/5 behavior.",
    )
    args = parser.parse_args()
    defenses_enabled = not args.no_defenses

    doc_path = Path(args.doc).resolve()
    deps = RunDeps(doc_path=str(doc_path), defenses_enabled=defenses_enabled)
    agent = build_agent(defenses_enabled)

    user_prompt = (
        f"Process the vendor document at this exact path, using the read_vendor_document tool: "
        f"{doc_path}"
    )
    result = agent.run_sync(user_prompt, deps=deps)
    result, output = resolve_deferred_calls(agent, result, deps)

    if defenses_enabled:
        output = verify_decision(output, deps)

    print(output.model_dump_json(indent=2))

    timestamp = datetime.now(timezone.utc)
    usage = result.usage
    cost = compute_cost(usage.input_tokens, usage.cache_read_tokens, usage.cache_write_tokens, usage.output_tokens)

    usage_entry = UsageEntry(
        doc=str(doc_path),
        timestamp=timestamp,
        input_tokens=usage.input_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        output_tokens=usage.output_tokens,
        cost_usd=round(cost, 6),
    )
    _append_json_list(USAGE_LOG_PATH, json.loads(usage_entry.model_dump_json()))

    audit_entry = AuditEntry(
        doc=str(doc_path),
        timestamp=timestamp,
        tool_calls=deps.audit,
        final_answer=output,
    )
    _append_json_list(AUDIT_LOG_PATH, json.loads(audit_entry.model_dump_json()))


if __name__ == "__main__":
    main()
