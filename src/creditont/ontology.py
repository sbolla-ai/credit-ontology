"""A small Foundry-style ontology in SQLite.

Object types: Company, Agreement.  Link type: Participation (company -[borrower|agent|lender]-> agreement).
Properties that change over time are stored as Facts with an effective date, so every question can be asked
"as of" a date and answered with the source document and quote that set the value.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field

from .extraction import AMENDABLE, Extraction
from .normalize import canonical_name

SCHEMA = """
CREATE TABLE company (key TEXT PRIMARY KEY, display_name TEXT, aliases TEXT);
CREATE TABLE agreement (id TEXT PRIMARY KEY, borrower_key TEXT, agreement_date TEXT, facility_type TEXT, currency TEXT,
                        benchmark TEXT, governing_law TEXT);
CREATE TABLE participation (agreement_id TEXT, company_key TEXT, role TEXT, UNIQUE(agreement_id, company_key, role));
CREATE TABLE fact (agreement_id TEXT, field TEXT, value TEXT, effective_date TEXT, source_doc TEXT, quote TEXT);
CREATE TABLE amendment (id TEXT PRIMARY KEY, agreement_id TEXT, effective_date TEXT, text TEXT);
"""

# Words that signal an amendment touches a field. Used only to WARN, never to set values.
FIELD_SIGNALS = {
    "max_leverage_ratio": ["leverage"],
    "min_interest_coverage_ratio": ["interest coverage", "interest cover"],
    "commitment_amount": ["commitment"],
    "maturity_date": ["maturity", "termination date"],
    "margin_bps": ["margin", "applicable rate", "pricing", " plus "],
}


@dataclass
class ReviewItem:
    doc_id: str
    field: str
    value: object
    quotes: list
    reason: str


@dataclass
class Ontology:
    db: sqlite3.Connection = field(default_factory=lambda: sqlite3.connect(":memory:"))
    review: list[ReviewItem] = field(default_factory=list)

    def __post_init__(self):
        self.db.executescript(SCHEMA)

    # ---------------------------------------------------------------- load
    def _company(self, name: str) -> str:
        key = canonical_name(name)
        row = self.db.execute("SELECT aliases FROM company WHERE key=?", (key,)).fetchone()
        if row is None:
            self.db.execute("INSERT INTO company VALUES (?,?,?)", (key, name, json.dumps([name])))
        elif name not in (aliases := json.loads(row[0])):
            self.db.execute("UPDATE company SET aliases=? WHERE key=?", (json.dumps(aliases + [name]), key))
        return key

    def _queue_rejected(self, ex: Extraction) -> None:
        for f in ex.fields.values():
            if f.value is not None and f.confidence < 0.9:
                self.review.append(ReviewItem(ex.doc_id, f.field, f.value, f.quotes, f.reason))

    def load(self, extractions: list[Extraction], texts: dict[str, str] | None = None) -> "Ontology":
        self.texts = texts or {}
        # Agreements first, so amendments can be attached to them in any input order.
        for ex in sorted(extractions, key=lambda e: e.doc_type != "credit_agreement"):
            self._queue_rejected(ex)
            (self._load_agreement if ex.doc_type == "credit_agreement" else self._load_amendment)(ex)
        self.db.commit()
        return self

    def _load_agreement(self, ex: Extraction) -> None:
        a = ex.accepted()
        if "borrower" not in a or "agreement_date" not in a:
            self.review.append(ReviewItem(ex.doc_id, "*", None, [], "agreement missing a verified borrower or date"))
            return
        bkey = self._company(a["borrower"])
        self.db.execute("INSERT INTO agreement VALUES (?,?,?,?,?,?,?)", (ex.doc_id, bkey, a["agreement_date"], a.get("facility_type"),
                                                                       a.get("currency"), a.get("benchmark"), a.get("governing_law")))
        self.db.execute("INSERT OR IGNORE INTO participation VALUES (?,?,?)", (ex.doc_id, bkey, "borrower"))
        if a.get("administrative_agent"):
            self.db.execute("INSERT OR IGNORE INTO participation VALUES (?,?,?)", (ex.doc_id, self._company(a["administrative_agent"]), "agent"))
        for lender in a.get("lenders") or []:
            self.db.execute("INSERT OR IGNORE INTO participation VALUES (?,?,?)", (ex.doc_id, self._company(lender), "lender"))
        for fname in AMENDABLE:
            if fname in a:
                fv = ex.fields[fname]
                self.db.execute("INSERT INTO fact VALUES (?,?,?,?,?,?)", (ex.doc_id, fname, json.dumps(a[fname]), a["agreement_date"], ex.doc_id, fv.quotes[0]))

    def _load_amendment(self, ex: Extraction) -> None:
        a = ex.accepted()
        bkey = canonical_name(a.get("borrower"))
        row = self.db.execute("SELECT id FROM agreement WHERE borrower_key=? AND agreement_date=?", (bkey, a.get("amends_agreement_date"))).fetchone()
        if row is None or "effective_date" not in a:
            self.review.append(ReviewItem(ex.doc_id, "*", None, [], "could not match amendment to a loaded agreement"))
            return
        self._company(a["borrower"])  # records the alias
        self.db.execute("INSERT INTO amendment VALUES (?,?,?,?)", (ex.doc_id, row[0], a["effective_date"], self.texts.get(ex.doc_id, "")))
        for fname in AMENDABLE:
            key = f"changes.{fname}"
            if key in a:
                self.db.execute("INSERT INTO fact VALUES (?,?,?,?,?,?)", (row[0], fname, json.dumps(a[key]), a["effective_date"], ex.doc_id, ex.fields[key].quotes[0]))

    # ---------------------------------------------------------------- query
    def agreement_for(self, borrower_key: str, as_of: str) -> str | None:
        row = self.db.execute("SELECT id FROM agreement WHERE borrower_key=? AND agreement_date<=? ORDER BY agreement_date DESC LIMIT 1",
                              (borrower_key, as_of)).fetchone()
        return row[0] if row else None

    def as_of(self, borrower_key: str, fname: str, as_of: str) -> dict | None:
        """Value in force on `as_of`, with provenance. None if no verified fact exists."""
        agr = self.agreement_for(borrower_key, as_of)
        if agr is None:
            return None
        row = self.db.execute("SELECT value, effective_date, source_doc, quote FROM fact WHERE agreement_id=? AND field=? AND effective_date<=? "
                              "ORDER BY effective_date DESC LIMIT 1", (agr, fname, as_of)).fetchone()
        warnings = self._unapplied_amendment_warnings(agr, fname, as_of, row[1] if row else None)
        if row is None:
            return {"value": None, "warnings": warnings} if warnings else None
        return {"value": json.loads(row[0]), "effective_date": row[1], "source_doc": row[2], "quote": row[3], "warnings": warnings}

    def _unapplied_amendment_warnings(self, agr: str, fname: str, as_of: str, fact_date: str | None) -> list[str]:
        """An amendment in force by `as_of`, later than the fact we're returning, whose text mentions this field
        but produced no verified change for it: the answer may be stale. Say so instead of answering silently."""
        out = []
        for doc_id, eff, text in self.db.execute("SELECT id, effective_date, text FROM amendment WHERE agreement_id=? AND effective_date<=?", (agr, as_of)):
            if fact_date and eff <= fact_date:
                continue
            applied = self.db.execute("SELECT 1 FROM fact WHERE source_doc=? AND field=?", (doc_id, fname)).fetchone()
            if not applied and any(sig in text.lower() for sig in FIELD_SIGNALS.get(fname, [])):
                out.append(f"{doc_id} (effective {eff}) mentions this term but no change was extracted; verify before relying on this value")
        return out

    def lenders_multi_borrower(self) -> list[str]:
        rows = self.db.execute("SELECT p.company_key FROM participation p JOIN agreement a ON a.id=p.agreement_id "
                               "WHERE p.role='lender' GROUP BY p.company_key HAVING COUNT(DISTINCT a.borrower_key) > 1 ORDER BY 1")
        return [r[0] for r in rows]

    def borrowers_where(self, fname: str, op: str, value: float, as_of: str) -> list[str]:
        ops = {">": float.__gt__, "<": float.__lt__, ">=": float.__ge__, "<=": float.__le__}
        out = []
        for (bkey,) in self.db.execute("SELECT DISTINCT borrower_key FROM agreement ORDER BY 1"):
            fact = self.as_of(bkey, fname, as_of)
            if fact and ops[op](float(fact["value"]), value):
                out.append(bkey)
        return out

    def completeness_warnings(self, fname: str | None = None, lenders: bool = False) -> list[str]:
        """Aggregate answers are only as complete as the data behind them. Say what's missing."""
        out = [f"{r.doc_id} not loaded ({r.reason})" for r in self.review if r.field == "*"]
        if lenders:
            out += [f"{a} has no verified lenders" for (a,) in self.db.execute(
                "SELECT id FROM agreement WHERE id NOT IN (SELECT agreement_id FROM participation WHERE role='lender')")]
        if fname:
            out += [f"{a} has no verified {fname}" for (a,) in self.db.execute(
                "SELECT id FROM agreement WHERE id NOT IN (SELECT agreement_id FROM fact WHERE field=?)", (fname,))]
        return out

    def graph(self) -> dict:
        """Nodes and edges, for a front-end graph view."""
        nodes = [{"id": k, "type": "Company", "label": n} for k, n in self.db.execute("SELECT key, display_name FROM company")]
        nodes += [{"id": i, "type": "Agreement", "label": f"{i} ({d})"} for i, d in self.db.execute("SELECT id, agreement_date FROM agreement")]
        edges = [{"source": c, "target": a, "type": r} for a, c, r in self.db.execute("SELECT agreement_id, company_key, role FROM participation")]
        return {"nodes": nodes, "edges": edges}
