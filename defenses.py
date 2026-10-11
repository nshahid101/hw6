"""Problem 6: defenses for the vendor desk agent.

Three independent layers live here, matching the three the assignment asks for:

- CODE:   `strip_invisible_unicode`, `strip_hidden_html`, and `redact_override_claims` run on a
          document's text *before* the model ever sees it (called from tools.py's
          read_vendor_document). `extract_authoritative_fields` pulls the first-stated price/
          lead-time/min-order straight out of the text with regex, with no model involved.
- DESIGN: `load_catalog`/`load_vendor_status`/`verify_decision` let agent.py independently
          recompute the purchasing decision from the handbook itself and the (redaction-protected,
          first-match) extracted fields, and override the model's answer if it disagrees. This is
          the backstop: even if an injection somehow survived the code and prompt layers and
          talked the model into a wrong number or decision, the final answer that gets logged and
          printed is the one this module computed from source data, not the one the model said.
          (The other design-level defense -- gating send_email/approve_payment behind
          `requires_approval` so a poisoned doc can trigger a *request* but never an *action* --
          lives in agent.py, since it's about how tools are registered on the Agent.)
- PROMPT: the "DEFENSE RULES" section of prompts/prompt.md, included in the agent's instructions
          only when defenses are enabled (see agent.py's build_instructions).

Everything here is designed to be skippable: tools.py and agent.py both take a
`defenses_enabled` flag and fall back to the original Problem 3 behavior (raw text, no
extraction, no verification, no approval gate) when it's False, so Problem 5's attack can still
be reproduced for comparison.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
HANDBOOK_PATH = PROJECT_ROOT / "data" / "shop_handbook.md"

# Zero-width and other invisible-but-not-whitespace characters used to obfuscate text from
# naive keyword filters (seen in Problem 5's p09 attack: a zero-width space between every letter).
_INVISIBLE_CHARS = re.compile(
    "[​‌‍⁠﻿­]"  # ZWSP, ZWNJ, ZWJ, word joiner, BOM, soft hyphen
)

# Inline styles/attributes that make an HTML element invisible to a human reader but leave its
# text fully present in the DOM (and therefore in BeautifulSoup's get_text() output).
_HIDDEN_STYLE_PATTERN = re.compile(
    r"display\s*:\s*none"
    r"|visibility\s*:\s*hidden"
    r"|font-size\s*:\s*0(?:\.0*)?(?:px|pt|em|%)?\b"
    r"|font-size\s*:\s*1px\b"
    r"|color\s*:\s*(#fff(?:fff)?|white|transparent)\b",
    re.IGNORECASE,
)

# Sentences that claim a previously stated number is wrong, outdated, or superseded -- the exact
# pattern behind all three successful Problem 5 attacks (p02, p07, p12). Matches a sentence
# starting with one of these cue words/phrases and ending at the next sentence boundary.
_OVERRIDE_SENTENCE_PATTERN = re.compile(
    r"[^.\n]*\b(revised|revision|correction|corrected|updated pricing|this replaces|"
    r"replaces the (?:price|unit price|lead time)|is now \$|now \d+ business days|"
    r"old standard|under volume agreement)\b[^.\n]*[.\n]",
    re.IGNORECASE,
)

_PRICE_PATTERN = re.compile(r"Unit price\s*:?\s*\n?\s*\$?\s*([\d,]+(?:\.\d+)?)", re.IGNORECASE)
_LEAD_TIME_PATTERN = re.compile(r"Lead time\s*:?\s*\n?\s*([\d,]+)\s*business days", re.IGNORECASE)
_MIN_ORDER_PATTERN = re.compile(r"Minimum order\s*:?\s*\n?\s*([\d,]+)\s*units", re.IGNORECASE)


def strip_invisible_unicode(text: str) -> str:
    """Remove zero-width/invisible characters used to obfuscate text from keyword filters."""
    text = _INVISIBLE_CHARS.sub("", text)
    return unicodedata.normalize("NFKC", text)


def strip_hidden_html(soup) -> None:  # soup: bs4.BeautifulSoup, typed loosely to avoid an import cycle
    """Remove any element whose inline style hides it from a human reader (display:none,
    visibility:hidden, zero/near-zero font size, or text colored to match a white background).
    Mutates `soup` in place -- call before `.get_text()`."""
    for element in soup.find_all(style=True):
        if _HIDDEN_STYLE_PATTERN.search(element.get("style", "")):
            element.decompose()
    for element in soup.find_all(hidden=True):
        element.decompose()


def redact_override_claims(text: str) -> tuple[str, list[str]]:
    """Remove sentences that claim an earlier-stated number is revised/corrected/outdated.

    Returns the redacted text and the list of sentences that were removed, so callers can log
    what was stripped. This is a blunt, pattern-based filter -- it will have false positives on
    genuinely new information (see prompt.md's "DEFENSE RULES" section, which tells the agent what
    to do when it sees a redaction marker) but a false positive here is far cheaper than accepting an
    injected price.
    """
    removed: list[str] = []

    def _replace(match: re.Match) -> str:
        removed.append(match.group(0).strip())
        return " [REDACTED BY SYSTEM: a claim that an earlier stated number is revised/corrected -- not trusted, see audit log] "

    redacted_text = _OVERRIDE_SENTENCE_PATTERN.sub(_replace, text)
    return redacted_text, removed


def extract_authoritative_fields(text: str) -> dict[str, float | int | None]:
    """Pull the FIRST-stated unit price, lead time, and minimum order out of the text with regex.

    Deliberately not an LLM call: regex always takes the first match in document order, so a
    later sentence claiming a different number (even one that survived redaction) cannot change
    what this function returns. This is the ground truth the model is told to defer to.
    """
    price_match = _PRICE_PATTERN.search(text)
    lead_time_match = _LEAD_TIME_PATTERN.search(text)
    min_order_match = _MIN_ORDER_PATTERN.search(text)
    return {
        "unit_price": float(price_match.group(1).replace(",", "")) if price_match else None,
        "lead_time_days": int(lead_time_match.group(1).replace(",", "")) if lead_time_match else None,
        "min_order": int(min_order_match.group(1).replace(",", "")) if min_order_match else None,
    }


_CATALOG_ROW = re.compile(
    r"^\|\s*(CC-[A-Z0-9-]+)\s*\|[^|]*\|[^|]*\|[^|]*\|\s*\$([\d,]+\.\d+)\s*\|", re.MULTILINE
)
_APPROVED_VENDOR_ROW = re.compile(r"^\|\s*([A-Z]{3})\s*\|\s*([^|]+?)\s*\|", re.MULTILINE)
_REMOVED_VENDOR_ROW = re.compile(r"^\|\s*([^|]+?)\s*\|\s*(Removed|Application pending)[^|]*\|", re.MULTILINE)


def load_catalog() -> dict[str, float]:
    """Parse the handbook's product catalogue (section 9) into {sku: max_unit_cost}."""
    text = HANDBOOK_PATH.read_text(encoding="utf-8")
    section = text.split("## 9. Product catalogue")[1].split("## 10.")[0]
    return {sku: float(cost.replace(",", "")) for sku, cost in _CATALOG_ROW.findall(section)}


def load_vendor_status() -> tuple[set[str], set[str]]:
    """Parse the handbook's vendor tables (sections 5-6) into (approved_names, removed_or_pending_names)."""
    text = HANDBOOK_PATH.read_text(encoding="utf-8")
    approved_section = text.split("## 5. Approved vendors")[1].split("## 6.")[0]
    removed_section = text.split("## 6. Removed and pending vendors")[1].split("## 7.")[0]

    approved = set()
    for code, name in _APPROVED_VENDOR_ROW.findall(approved_section):
        if code != "Code":  # skip the header row
            approved.add(name.strip())

    removed = {name.strip() for name, _status in _REMOVED_VENDOR_ROW.findall(removed_section)}
    return approved, removed


def verify_decision(
    vendor: str | None,
    sku: str | None,
    unit_price: float | None,
    lead_time_days: int | None,
    min_order: int | None,
) -> tuple[str, str]:
    """Independently recompute the handbook's four-check purchasing rule from source data.

    This never looks at anything the model said about the decision -- only at the fields (which
    should themselves be the code-extracted, redaction-protected ones) and the handbook's own
    vendor/catalogue tables. Used by agent.py as a backstop that overrides the model's decision
    whenever the two disagree.
    """
    approved, removed = load_vendor_status()
    catalog = load_catalog()

    if vendor is None or vendor not in approved or vendor in removed:
        return "do_not_recommend", "approved vendor check fails: vendor is not on the approved list"

    max_cost = catalog.get(sku) if sku else None
    if max_cost is None:
        return "do_not_recommend", "price check fails: SKU not found in the catalogue, so price cannot be verified"
    if unit_price is None or unit_price > max_cost:
        return "do_not_recommend", f"price check fails: unit price exceeds the catalogue max unit cost (${max_cost})"

    if lead_time_days is None or lead_time_days > 21:
        return "do_not_recommend", "lead time check fails: lead time exceeds 21 days"

    if min_order is None or min_order > 600:
        return "do_not_recommend", "minimum order check fails: minimum order exceeds 600 units"

    return "recommend", "approved vendor, price, lead time, and minimum order checks all pass"
