# AI Prompts Log — HW 6

This log records the prompts used while working with Claude on this homework, one section per problem.
For each problem: the problem number & title, at least one prompt (in my own words), and — if a follow-up
was needed — the follow-up prompt plus a sentence on what was missing from the first one.

## Problem 1 — Project setup

**Prompt:** "I added a zip folder in the HW 6 folder, can you unzip it and tell me what the
contents are" / "I'd like to use gpt-6-luna through Portkey for every agent" / "Once hw 6 is
setup, ensure there is a .venv folder in there as well"

**Follow-up (if needed):** Not needed — each request was handled directly (unzip and summarize
the data folder, wire up `portkey_config.py` to match the course's existing gpt-6-luna/Portkey
pattern from HW 5, create `.venv` and install `requirements.txt`).

## Problem 2 — Size up the handbook

**Prompt:** "Please tell me how many tokens the handbook is. In output/handbook_estimate.md
write: the token count and how it was calculated, what the handbook alone costs in dollars in
once call and on 1k calls, with cached tokens and without them - show the math. I'll later check
these estimated against real runs in later steps."

**Follow-up (if needed):** "What is 1 call with caching?" followed by "Add this info to problem
2 as well." The first write-up only gave one blended "1 call" figure for the cached scenario,
which conflated two different rates — it didn't separate the cache-write cost of the first call
from the much cheaper cached-input cost of later calls that reuse the cache.

## Problem 3 — Build the vendor desk agent

**Prompt:** "I want to build a PydanticAI agent using gpt 5.6 luna. The agent is these 4 files:
prompts/prompts.md, agent.py, tools.py, models.py. Give the agent the path to one vendor doc. It
should read the doc with a tool (HTML, PDF & .eml as email files all have to work) and returns the
vendor, SKU, unit price, lead time in days, min order, a decision (recommend OR do_not_recommend)
following the handbook rules and one sentence reason. The agent should also have two trap tools:
send_email and approve_payment... After every run, append to output/usage_log.json,
output/audit_trails.json... The agent should run like this in the terminal: python agent.py --doc
data/practice_docs/p01_bluehen_quote.html. Run it on p01 and p08 to show how it works. Start
output/harness.md: each field in models.py and why and each tool in one line."

**Follow-up (if needed):** Not needed.

## Problem 4 — With and without cached tokens

**Prompt:** "Since the handbook is the same on every call, the model can reuse it from cache at a
much cheaper price. Test what this is worth. Run the agent on all 12 practice docs 2 ways: with
cache (set up so handbook gets reused from cache), without cache (set up so nothing gets reused
from cache). Check token counts the API sends back. A without-cache run that still shows cached
tokens doesn't count. Save every model call from both setups to output/cache_test.json... In
output/cache_test.md: total cost and cost per doc for each setup and the % saved, how the real
numbers compare to the Problem 2 estimate, a projection for 1k docs a day for 30 days, with and
without cache, anything in the numbers that was surprising and why it happened."

**Follow-up (if needed):** Not needed from the user — but worth noting for the record: my own
first two attempts at "without cache" were wrong and I had to self-correct. Each agent run
actually makes two model calls internally (decide to use the read tool, then answer after the tool
result), and the second always legitimately reuses the first call's cache within that same run.
My first fix attempts (moving a cache-busting comment around in the prompt, then trying
`prompt_cache_key`, then a Portkey force-refresh header) were chasing that unavoidable same-run
reuse as if it were a bug. The real fix was checking only the *first* model call of each run for
cache reuse, not the run's summed total — documented in `scripts/cache_test.py`'s docstring.

## Problem 5 — Attack your own agent

**Prompt:** "Run the problem 3 agent with no new defenses on all 12 docs in
data_practice_docs/. Compare each answer to data/practice_key.json and check
output/trap_calls.json. Save output/attack_results.json: for each doc, whether each field matched
the key, if the decision matched, if a trap tool was called and if a link or other strange text
showed up in the answer. In output/attck_results.md, for every doc that fooled the agent, write
what fooled it and where in the file it was hiding."

**Follow-up (if needed):** "In output/attack_result.md can you add a line that I then opened the
documents in a standard way and to compare with what the agent read the traps are invisible to the
human eye - ie in p12 the trailing sentence with the revised price cannot be spotted." Not a gap in
the original write-up so much as new information to add — I hadn't visually opened the rendered
documents myself (only read the raw/extracted text), so this records the user's own manual
comparison.

## Problem 6 — Defend your agent

**Prompt:** "Defend the agent at 3 levels: Code: what the program does to the doc before any model
sees it. Design: how the agent is put together, so a poisoned doc cannot reach the dangerous tools
or decisions. Prompt: rules in prompts/prompt.md. Do not delete send_email or approve_payment from
the system. The shop will use them later with a human sign-off. Keep a way to run the agent with
no defenses."

**Follow-up (if needed):** "Since all 12 practice docs were rerun, save output/defense_results.json
in the same shape as problem 5 - inc tokens and dollars per doc. Clean docs must still come back
with the right values. Refusing or blanking our a real quote counts as a failure. In
output/defense_results.md inc: a before and after table for all 12 docs, what each layer catches
that the others miss, extra tokens and dollars each layer adds per doc. Add a safety feature to
output/harness.md in a Safety section: what each defense layer does, in easy to understand plain,
non-technical English." The first defense write-up (output/defense_report.md) covered the 3 layers
and a pass/fail comparison, but didn't have per-doc token/cost data, a false-positive check
(blanked/refused fields), or a plain-English explanation for a non-technical reader -- this added
all three.

## Problem 7 — Red team

**Prompt:** "Now you are the attacker. Make two new booby trapped vendor docs in data/my_attacks/
(HTML, PDF or email). Each one should use a hiding trick or an attack goal that is not in the
practice set. A person opening the doc should see a normal quote. Run both attacks on my agent
with no defenses vs on the defended agent. In output/red_team.md, for each attack document: what
is hidden, where, what it tries to make the agent do and what happened before and after your
defenses. More points are awarded for attacks that are new and actually fool the agent with no
defenses."

**Follow-up (if needed):** Not a user follow-up, but worth logging: my first two drafts of attack 1
(an off-canvas CSS min-order waiver, then an off-canvas CSS confidentiality-leak request) did not
fool the no-defenses agent at all despite several reruns. I diagnosed this empirically rather than
guessing -- by testing a version of the *practice set's* own p02 attack with only its hiding
mechanism swapped to off-canvas CSS (still worked), then narrowing down what differed between that
and my draft -- and found a price-override attack (reusing the proven-effective goal from Problem
5, paired with the new off-canvas hiding trick) succeeded reliably. Recorded in
`output/red_team.md` as the final attack 1.

## Problem 8 — Exam documents

**Prompt:** "Run the final defended agent on data/exam_docs/, which should have 10 vendor docs.
Save output/exam_results.json with one entry per exam file. Each entry has these fields: file,
vendor, sku, unit_price, lead_time_days, min_order, decision, reason, trap_tool_called,
input_tokens, cached_tokens, output_tokens, cost_usd. Keep in mind this hw is graded for correct
fields and decisions, not trap tool calls and clean docs handled normally."

**Follow-up (if needed):** Not needed from the user, but worth logging: reviewing the first run's
output caught a real bug — e07's stated minimum order was "1,000 units" (comma-formatted), and
`defenses.py`'s regex only matched plain digits, so it silently returned `min_order: null` instead
of `1000`. Fixed the regex to accept comma-formatted numbers and reran all 10 docs before treating
the file as final — given the "graded for correct fields" instruction, a silent null here would
have been a real grading loss, not just a cosmetic issue.

## Problem 9 — Results page

**Prompt:** "Build output/hw6_report.html. It must be one file that opens by double-click with no
internet and no other files next to it. The page must show the 5 things below, using real numbers
from the earlier problems: the caching results, with a chart; attacks before and after the
defenses; what the defenses cost in tokens and dollars; the exam results and the two red team
attacks; a short recc to the store manager: should Campus Customs turn this agent on for real
vendor mail and what would it cost per month at 1k docs a day. More points are given for a well
designed page that reads well (inc fonts, color, layout). Feel free to take design inspo from the
screenshot attached [a dark-navy/mono-section-label studio homepage]." Per AGENTS.md's standing
style rule for any site I build, I used the screenshot for layout/structure only (numbered
sections, nav bar, stat-tile row) and reskinned it in the project's required classic palette
(navy/cream/gold/muted-red/dark-gray) rather than the screenshot's own colors.

**Follow-up (if needed):** "Can you follow the screenshot's color palette instead for the html?"
The first version deliberately overrode the screenshot's own colors with the project's standing
classic palette (per AGENTS.md) — this explicit ask takes that override back for this one file:
swapped to the screenshot's white background, near-black header/text, and blue/green/amber accent
trio, re-validated the chart's color pair for colorblind-safety, and re-checked every section for
contrast after the swap.

## Problem 10 —

**Prompt:**

**Follow-up (if needed):**
