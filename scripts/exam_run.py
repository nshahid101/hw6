"""Problem 8: run the final defended agent on the 10 real exam documents and save
output/exam_results.json in the exact shape requested -- one entry per file, with the answer
fields, trap_tool_called, and token/cost data.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
EXAM_DOCS_DIR = PROJECT_ROOT / "data" / "exam_docs"
TRAP_CALLS_PATH = PROJECT_ROOT / "output" / "trap_calls.json"
USAGE_LOG_PATH = PROJECT_ROOT / "output" / "usage_log.json"
RESULTS_PATH = PROJECT_ROOT / "output" / "exam_results.json"
PYTHON = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"


def load_trap_calls() -> list[dict]:
    if TRAP_CALLS_PATH.exists():
        return json.loads(TRAP_CALLS_PATH.read_text(encoding="utf-8"))
    return []


def run_agent(doc: Path) -> tuple[dict, dict]:
    proc = subprocess.run(
        [str(PYTHON), str(PROJECT_ROOT / "agent.py"), "--doc", str(doc)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
    )
    if proc.returncode != 0:
        raise RuntimeError(f"agent.py failed on {doc.name}:\n{proc.stderr}")
    answer = json.loads(proc.stdout)
    usage_entry = json.loads(USAGE_LOG_PATH.read_text(encoding="utf-8"))[-1]
    return answer, usage_entry


def main() -> None:
    docs = sorted(EXAM_DOCS_DIR.iterdir())
    results = []

    for doc in docs:
        traps_before = len(load_trap_calls())
        answer, usage = run_agent(doc)
        trap_tool_called = len(load_trap_calls()) > traps_before

        results.append(
            {
                "file": doc.name,
                "vendor": answer.get("vendor"),
                "sku": answer.get("sku"),
                "unit_price": answer.get("unit_price"),
                "lead_time_days": answer.get("lead_time_days"),
                "min_order": answer.get("min_order"),
                "decision": answer.get("decision"),
                "reason": answer.get("reason"),
                "trap_tool_called": trap_tool_called,
                "input_tokens": usage["input_tokens"],
                "cached_tokens": usage["cache_read_tokens"],
                "output_tokens": usage["output_tokens"],
                "cost_usd": usage["cost_usd"],
            }
        )
        print(f"{doc.name}: {answer.get('decision')} (trap_tool_called={trap_tool_called}, cost=${usage['cost_usd']})")

    RESULTS_PATH.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\nWrote {len(results)} entries to {RESULTS_PATH}")


if __name__ == "__main__":
    main()
