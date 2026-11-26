"""Small helper so tests can score a single extraction against the gold labels."""
import json
from pathlib import Path

from creditont.extraction import AGREEMENT_FIELDS, AMENDMENT_FIELDS
from creditont.normalize import canonical_name

LABELS = json.loads((Path(__file__).resolve().parents[1] / "data" / "labels.json").read_text())


def score_one(ex) -> dict[str, str]:
    gold = LABELS[ex.doc_id]
    kinds = AGREEMENT_FIELDS if ex.doc_type == "credit_agreement" else AMENDMENT_FIELDS
    out = {}
    for name, kind in kinds.items():
        pred = ex.fields[name].value
        g = gold.get("changes", {}).get(name.split(".", 1)[1]) if name.startswith("changes.") else gold.get(name)
        if pred is None and g is None:
            out[name] = "correct_absent"
        elif pred is None:
            out[name] = "missed"
        elif g is None:
            out[name] = "hallucinated"
        elif kind == "name":
            out[name] = "correct" if canonical_name(pred) == canonical_name(g) else "wrong"
        else:
            out[name] = "correct" if pred == g else "wrong"
    return out
