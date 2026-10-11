# Campus Customs Vendor Desk Agent — HW6

A PydanticAI agent (model `gpt-6-luna`, via Portkey) that reads a vendor quote document (HTML,
PDF, or `.eml` email), matches it to the Campus Customs product catalogue, and recommends or
rejects it against the shop handbook's purchasing rules — defended against prompt-injection
attacks hidden inside the documents it reads.

## Setup

```bash
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt   # Windows
# .venv/bin/python -m pip install -r requirements.txt         # macOS/Linux

cp .env.example .env
# then edit .env and set PORTKEY_API_KEY=<your real key>
```

## Running the agent

```bash
python agent.py --doc data/practice_docs/p01_bluehen_quote.html
```

Prints the structured answer (vendor, SKU, unit price, lead time, minimum order, decision, reason)
to stdout, and appends a record of the run to `output/usage_log.json` (token counts and cost),
`output/audit_trail.json` (every tool call made), and — only if a document tries to hijack
`send_email` or `approve_payment` — `output/trap_calls.json`.

Defenses (document sanitization, authoritative-field extraction, tool-approval gating, and an
independent decision verifier — see `output/defense_results.md`) are **on by default**. Add
`--no-defenses` to reproduce the original, undefended behavior:

```bash
python agent.py --doc data/practice_docs/p02_elmcity_quote.html --no-defenses
```

## Project layout

- `agent.py`, `tools.py`, `models.py`, `prompts/prompt.md` — the agent itself.
- `defenses.py` — the code-level sanitization/extraction and the handbook-based decision verifier
  used by `agent.py` when defenses are enabled.
- `portkey_config.py` — wires every agent call through Portkey to `gpt-6-luna`.
- `data/` — the shop handbook, pricing, the 12 practice docs + answer key, the 10 exam docs, and
  the two booby-trapped documents built for the red-team exercise (`data/my_attacks/`).
- `scripts/` — one-off analysis scripts used to produce the files in `output/` (token/cost
  estimates, the cache A/B test, the attack and defense comparisons, the exam run).
- `output/` — every deliverable: cost estimates, the harness writeup, attack/defense results, the
  red-team writeup, the exam results, and the single-file results page (`hw6_report.html` — open
  it directly in a browser, no server needed).
- `AI_prompts.md` — the per-problem prompt log for this assignment.

## Security note

`send_email` and `approve_payment` stay in the agent's toolset (for the shop's planned future use
with a human reviewer) but, with defenses on, always require approval before they can execute — no
document can ever make either one actually send or pay anything on its own. See
`output/defense_results.md` and `output/red_team.md` for what was tested and what it caught.
