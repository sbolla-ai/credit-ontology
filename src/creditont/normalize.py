"""Normalizers: turn the many ways legal documents write a number, ratio, date or name into one canonical value.

Each `values_in(text, kind)` returns every value of that kind found in a span. That powers the grounding
check: an extracted value only counts if it can be re-derived from its own quote.
"""
from __future__ import annotations

import re
from datetime import date, datetime

WORD_NUM = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
FRACTIONS = {"one-quarter": 0.25, "one quarter": 0.25, "one-half": 0.5, "one half": 0.5, "three-quarters": 0.75, "three quarters": 0.75}

# ---------------------------------------------------------------- money
_MONEY = re.compile(r"(?:(?P<sym>\$|€|£)|(?P<code>USD|EUR|GBP)\s?)(?P<num>\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)(?:\s?(?P<scale>million|billion))?", re.I)
_SYM = {"$": "USD", "€": "EUR", "£": "GBP"}


def money_in(text: str) -> list[tuple[int, str]]:
    out = []
    for m in _MONEY.finditer(text):
        amount = float(m.group("num").replace(",", ""))
        scale = (m.group("scale") or "").lower()
        amount *= 1e9 if scale == "billion" else 1e6 if scale == "million" else 1
        currency = _SYM.get(m.group("sym") or "", (m.group("code") or "USD").upper())
        out.append((int(round(amount)), currency))
    return out


# ---------------------------------------------------------------- ratios
_RATIO_NUM = re.compile(r"(\d+(?:\.\d+)?)\s*(?::|to)\s*1(?:\.0+)?\b", re.I)
_RATIO_WORDS = re.compile(r"\b(" + "|".join(WORD_NUM) + r")(?:\s+and\s+(" + "|".join(map(re.escape, FRACTIONS)) + r"))?\s+to\s+one\b", re.I)
_TIMES = re.compile(r"(\d+(?:\.\d+)?)\s*x\b", re.I)


def ratios_in(text: str) -> list[float]:
    vals = [float(m.group(1)) for m in _RATIO_NUM.finditer(text)]
    for m in _RATIO_WORDS.finditer(text):
        vals.append(WORD_NUM[m.group(1).lower()] + FRACTIONS.get((m.group(2) or "").lower(), 0))
    vals += [float(m.group(1)) for m in _TIMES.finditer(text)]
    return [round(v, 4) for v in vals]


# ---------------------------------------------------------------- margins
_PCT = re.compile(r"(\d+(?:\.\d+)?)\s*(?:%|per\s*cent\.?|percent)", re.I)
_BPS = re.compile(r"(\d+)\s*(?:basis points|bps)\b", re.I)


def margins_bps_in(text: str) -> list[int]:
    return [int(round(float(m.group(1)) * 100)) for m in _PCT.finditer(text)] + [int(m.group(1)) for m in _BPS.finditer(text)]


# ---------------------------------------------------------------- dates
MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_DATE_US = re.compile(rf"\b({MONTHS})\s+(\d{{1,2}}),\s*(\d{{4}})\b")
_DATE_UK = re.compile(rf"\b(\d{{1,2}})\s+({MONTHS})\s+(\d{{4}})\b")
_DATE_ISO = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")


def dates_in(text: str) -> list[str]:
    out = []
    for m in _DATE_US.finditer(text):
        out.append(datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date().isoformat())
    for m in _DATE_UK.finditer(text):
        out.append(datetime.strptime(f"{m.group(2)} {m.group(1)} {m.group(3)}", "%B %d %Y").date().isoformat())
    for m in _DATE_ISO.finditer(text):
        out.append(date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat())
    return out


# ---------------------------------------------------------------- names
_SUFFIXES = r"\b(?:inc|incorporated|llc|l\s?l\s?c|lp|l\s?p|corp|corporation|co|n\s?a|plc|ag|ltd|limited|company)\b"


def canonical_name(name: str | None) -> str | None:
    """'Granite Point Bank, N.A.' and 'Granite Point Bank' -> 'granite point bank'."""
    if not name:
        return None
    s = name.lower().replace("&", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(_SUFFIXES, " ", s)
    return re.sub(r"\s+", " ", s).strip()


LAW = {"new york": "New York", "delaware": "Delaware", "texas": "Texas", "english": "England", "england": "England", "california": "California"}


def governing_law(text: str | None) -> str | None:
    if not text:
        return None
    low = text.lower()
    for key, val in LAW.items():
        if key in low:
            return val
    return None


def benchmark(text: str | None) -> str | None:
    if not text:
        return None
    low = text.lower()
    return "SOFR" if "sofr" in low else "EURIBOR" if "euribor" in low else "SONIA" if "sonia" in low else None
