"""Field schema, extractors (offline baseline + LLM) and the two-step verification every field goes through.

  1. Verified: every quote appears verbatim in the document.
  2. Grounded: the normalized value can be re-derived from its own quote
     (e.g. the quote for max_leverage_ratio=4.25 must contain a ratio that normalizes to 4.25).

Only verified AND grounded fields enter the ontology. Everything else goes to a human review queue.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from . import normalize as N

AGREEMENT_FIELDS: dict[str, str] = {
    "agreement_date": "date", "borrower": "name", "administrative_agent": "name", "lenders": "name_list",
    "facility_type": "facility", "commitment_amount": "money", "currency": "currency", "maturity_date": "date",
    "benchmark": "benchmark", "margin_bps": "margin", "max_leverage_ratio": "ratio",
    "min_interest_coverage_ratio": "ratio", "governing_law": "law",
}
AMENDABLE = ["commitment_amount", "maturity_date", "margin_bps", "max_leverage_ratio", "min_interest_coverage_ratio"]
AMENDMENT_FIELDS: dict[str, str] = {"effective_date": "date", "borrower": "name", "amends_agreement_date": "date",
                                    **{f"changes.{f}": AGREEMENT_FIELDS[f] for f in AMENDABLE}}

ACCEPT_THRESHOLD = 0.9


@dataclass
class FieldValue:
    field: str
    value: Any
    quotes: list[str] = field(default_factory=list)
    verified: bool = False
    grounded: bool = False
    confidence: float = 0.0
    reason: str = ""


@dataclass
class Extraction:
    doc_id: str
    doc_type: str
    fields: dict[str, FieldValue]
    extractor: str
    usage: dict = field(default_factory=dict)
    latency_ms: float = 0.0

    def accepted(self) -> dict[str, Any]:
        return {k: f.value for k, f in self.fields.items() if f.value is not None and f.confidence >= ACCEPT_THRESHOLD}

    def to_dict(self) -> dict:
        return {**asdict(self), "fields": {k: asdict(v) for k, v in self.fields.items()}}


def doc_type_of(text: str) -> str:
    head = text[:400].upper()
    return "amendment" if "AMENDMENT" in head else "credit_agreement"


# ---------------------------------------------------------------- verification
def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.strip().strip("\"'“”")).lower()


def grounded(kind: str, value: Any, quote: str) -> bool:
    if value is None:
        return True
    q = quote
    if kind == "date":
        return value in N.dates_in(q)
    if kind == "money":
        return value in [a for a, _ in N.money_in(q)]
    if kind == "currency":
        return value in [c for _, c in N.money_in(q)]
    if kind == "ratio":
        return any(abs(v - float(value)) < 1e-6 for v in N.ratios_in(q))
    if kind == "margin":
        return int(value) in N.margins_bps_in(q)
    if kind == "name":
        cv, cq = N.canonical_name(str(value)), N.canonical_name(q)
        return bool(cv) and cv in cq
    if kind == "facility":
        return {"revolving": "revolv", "term": "term loan"}.get(value, "\0") in q.lower()
    if kind == "benchmark":
        return N.benchmark(q) == value
    if kind == "law":
        return N.governing_law(q) == value
    return False


def verify(fv: FieldValue, kind: str, text: str) -> FieldValue:
    if fv.value is None:
        fv.verified = fv.grounded = True
        fv.confidence = 1.0
        return fv
    doc = _norm(text)
    fv.verified = bool(fv.quotes) and all(_norm(q) in doc for q in fv.quotes if q)
    if kind == "name_list":
        values = fv.value if isinstance(fv.value, list) else [fv.value]
        fv.grounded = all(any(grounded("name", v, q) for q in fv.quotes) for v in values)
    else:
        fv.grounded = any(grounded(kind, fv.value, q) for q in fv.quotes)
    fv.confidence = 1.0 if (fv.verified and fv.grounded) else 0.4 if fv.verified else 0.0
    if fv.confidence < ACCEPT_THRESHOLD:
        fv.reason = "quote not found in document" if not fv.verified else "value not supported by its quote"
    return fv


# ---------------------------------------------------------------- baseline extractor
def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.;:])\s+(?=[A-Z(\d])|\n{1,}", text)
    return [p.strip() for p in parts if p.strip()]


class BaselineExtractor:
    """Keyword-and-regex rules. Offline, transparent, and deliberately simple: the bar an LLM has to beat."""

    name, model = "baseline", None

    def extract(self, doc_id: str, text: str) -> tuple[dict[str, FieldValue], dict]:
        sents = _sentences(text)
        dt = doc_type_of(text)
        out: dict[str, FieldValue] = {}

        def find(pattern: str, picker, start=0):
            for s in sents[start:]:
                if re.search(pattern, s, re.I):
                    vals = picker(s)
                    if vals:
                        return vals, s
            return None, None

        def put(name, val, quote):
            out[name] = FieldValue(name, val, [quote] if quote else [])

        if dt == "credit_agreement":
            v, q = find(r"dated|as of|entered into", N.dates_in)
            put("agreement_date", v[0] if v else None, q)
            v, q = find(r"maturity|termination date|mature|repay", N.dates_in)
            put("maturity_date", v[-1] if v else None, q)
            v, q = find(r"commitment|facility|aggregate|principal amount", N.money_in)
            put("commitment_amount", v[0][0] if v else None, q)
            put("currency", v[0][1] if v else None, q)
            v, q = find(r"\binterest\b|margin", lambda s: [N.benchmark(s)] if N.benchmark(s) else None)
            put("benchmark", v[0] if v else None, q)
            v, q = find(r"(?:SOFR|EURIBOR).*?(?:plus|margin)|margin|applicable rate", N.margins_bps_in)
            put("margin_bps", v[0] if v else None, q)
            v, q = find(r"leverage", N.ratios_in)
            put("max_leverage_ratio", v[0] if v else None, q)
            v, q = find(r"interest cover", N.ratios_in)
            put("min_interest_coverage_ratio", v[0] if v else None, q)
            v, q = find(r"govern", lambda s: [N.governing_law(s)] if N.governing_law(s) else None)
            put("governing_law", v[0] if v else None, q)
            v, q = find(r"revolving|term loan|term a", lambda s: ["revolving"] if "revolv" in s.lower() else ["term"] if "term loan" in s.lower() else None)
            put("facility_type", v[0] if v else None, q)
            m = re.search(r"([A-Z][A-Z&.,' ]{3,}?),?\s*\n?\s*as (?:the )?(?:Borrower|Company)", text) or \
                re.search(r"(?:among|by and among)\s+([A-Z][\w&.,' ]+?),\s*(?:a [^,]+,\s*)?(?:\(the \"Borrower\"\)|as Borrower)", text)
            put("borrower", m.group(1).strip().rstrip(",") if m else None, m.group(0) if m else None)
            m = re.search(r"([A-Z][A-Za-z&.,' ]{3,}?),?\s*\n?\s*(?:as|acting as) (?:the )?(?:administrative )?agent", text, re.I)
            agent = re.sub(r"^(?:and|by)\s+", "", m.group(1).strip().rstrip(","), flags=re.I) if m else None
            put("administrative_agent", agent, m.group(0) if m else None)
            out["lenders"] = FieldValue("lenders", None)  # the baseline doesn't attempt lender lists
        else:
            v, q = find(r"dated|as of", N.dates_in)
            put("effective_date", v[0] if v else None, q)
            v, q = find(r"credit agreement|loan agreement", N.dates_in)
            put("amends_agreement_date", v[-1] if v else None, q)
            m = re.search(r"(?:among|by and among)\s+([A-Z][\w&.,' ]+?)(?:\s*\(the \"Borrower\"\)|,\s+the Lenders|,\s+HARBORLINE)", text) or \
                re.search(r"\n([A-Z][A-Z&.,' ]{3,}?),\s+[A-Z]", text)
            put("borrower", m.group(1).strip().rstrip(",") if m else None, m.group(0) if m else None)
            for fname, pat, picker in [
                ("max_leverage_ratio", r"leverage|7\.11\(a\)", N.ratios_in), ("min_interest_coverage_ratio", r"interest coverage", N.ratios_in),
                ("commitment_amount", r"commitments", lambda s: [a for a, _ in N.money_in(s)]),
                ("maturity_date", r"maturity date", N.dates_in), ("margin_bps", r"pricing|plus", N.margins_bps_in)]:
                v, q = find(pat, picker, start=3)
                put(f"changes.{fname}", v[-1] if v else None, q)
        return out, {}


# ---------------------------------------------------------------- LLM extractor
SYSTEM_PROMPT = """You extract structured data from credit agreements and amendments for a credit-risk team.

Rules:
1. Return ONLY JSON. For every field return {"value": <normalized value or null>, "quotes": ["exact text copied from the document"]}.
2. Quotes must be copied VERBATIM from the document and must contain the evidence for the value. Unverifiable fields are discarded.
3. Use null when the document does not state the field. Do not infer or compute.
4. Normalize: dates as YYYY-MM-DD; amounts as integers in the stated currency; currency as ISO code; ratios as decimal multiples
   (e.g. "3.50:1.00" -> 3.5); margins in basis points for the benchmark-rate loans (2.25% -> 225); facility_type "revolving" or "term";
   benchmark "SOFR", "EURIBOR" or "SONIA"; governing_law as the state or country name (e.g. "New York", "England").
5. max_leverage_ratio is a leverage/debt-to-EBITDA ceiling. min_interest_coverage_ratio is ONLY an interest coverage floor;
   a fixed charge coverage covenant is a different covenant -> null.
6. lenders are the lending institutions, not the agent unless it is also a lender."""


def build_prompt(doc_type: str, text: str) -> str:
    fields = AGREEMENT_FIELDS if doc_type == "credit_agreement" else AMENDMENT_FIELDS
    keys = ", ".join(fields)
    extra = ("For an amendment, changes.<field> is the NEW value set by this amendment, or null if unchanged. "
             "amends_agreement_date is the date of the original agreement being amended.") if doc_type == "amendment" else ""
    return f"Document type: {doc_type}\nFields: {keys}\n{extra}\n\n<document>\n{text}\n</document>"


class LLMExtractor:
    def __init__(self, provider):
        self.provider, self.name, self.model = provider, f"llm:{provider.name}", provider.model

    def extract(self, doc_id: str, text: str) -> tuple[dict[str, FieldValue], dict]:
        dt = doc_type_of(text)
        raw, usage = self.provider.complete(SYSTEM_PROMPT, build_prompt(dt, text))
        try:
            data = json.loads(re.search(r"\{.*\}", raw, re.S).group(0))
        except (AttributeError, json.JSONDecodeError):
            data = {}
        fields = AGREEMENT_FIELDS if dt == "credit_agreement" else AMENDMENT_FIELDS
        out = {}
        for name in fields:
            item = data.get(name)
            if item is None and name.startswith("changes."):
                item = (data.get("changes") or {}).get(name.split(".", 1)[1])
            if not isinstance(item, dict):
                item = {"value": item, "quotes": []}
            out[name] = FieldValue(name, item.get("value"), [str(q) for q in item.get("quotes") or []])
        return out, usage


def run_extraction(extractor, doc_id: str, text: str) -> Extraction:
    import time

    t0 = time.perf_counter()
    raw_fields, usage = extractor.extract(doc_id, text)
    dt = doc_type_of(text)
    kinds = AGREEMENT_FIELDS if dt == "credit_agreement" else AMENDMENT_FIELDS
    fields = {name: verify(raw_fields.get(name, FieldValue(name, None)), kind, text) for name, kind in kinds.items()}
    return Extraction(doc_id, dt, fields, extractor.name, usage, round((time.perf_counter() - t0) * 1000, 1))
