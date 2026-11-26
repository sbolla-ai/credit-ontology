"""Score an extractor on the labeled documents, the ontology on the as-of questions, and enforce gates.

    python evals/run_evals.py                                   # offline baseline
    python evals/run_evals.py --extractor llm --provider anthropic [--model claude-haiku-5-5]
    python evals/run_evals.py --compare reports/a.json reports/b.json   # side-by-side table

Field scoring (per document field):
  correct          predicted value == gold (names compared after entity resolution, lender lists as sets)
  wrong            predicted a value that differs from gold          -> counts against precision
  missed           gold has a value, prediction is null              -> counts against recall
  hallucinated     gold is null, prediction is a value               -> counts against precision
  correct_absent   both null (e.g. Orion has no interest-coverage covenant)
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from creditont.extraction import AGREEMENT_FIELDS, AMENDMENT_FIELDS  # noqa: E402
from creditont.normalize import canonical_name  # noqa: E402
from creditont.pipeline import make_extractor, run  # noqa: E402


def gold_value(gold: dict, field: str):
    return gold.get("changes", {}).get(field.split(".", 1)[1]) if field.startswith("changes.") else gold.get(field)


def same(kind: str, pred, gold) -> bool:
    if pred is None or gold is None:
        return pred is None and gold is None
    if kind == "name":
        return canonical_name(str(pred)) == canonical_name(str(gold))
    if kind == "name_list":
        return isinstance(pred, list) and {canonical_name(p) for p in pred} == {canonical_name(g) for g in gold}
    if kind in ("ratio", "money", "margin"):
        try:
            return abs(float(pred) - float(gold)) < 1e-6
        except (TypeError, ValueError):
            return False
    return str(pred) == str(gold)


def score_fields(extractions, labels) -> dict:
    counts = {"correct": 0, "wrong": 0, "missed": 0, "hallucinated": 0, "correct_absent": 0}
    per_field: dict[str, dict] = {}
    rows = []
    for ex in extractions:
        gold = labels[ex.doc_id]
        kinds = AGREEMENT_FIELDS if ex.doc_type == "credit_agreement" else AMENDMENT_FIELDS
        for name, kind in kinds.items():
            pred, g = ex.fields[name].value, gold_value(gold, name)
            if pred is None and g is None:
                outcome = "correct_absent"
            elif pred is None:
                outcome = "missed"
            elif g is None:
                outcome = "hallucinated"
            else:
                outcome = "correct" if same(kind, pred, g) else "wrong"
            counts[outcome] += 1
            bucket = per_field.setdefault(name.replace("changes.", "Δ "), {"correct": 0, "total_gold": 0})
            bucket["correct"] += outcome == "correct"
            bucket["total_gold"] += g is not None
            if outcome not in ("correct", "correct_absent"):
                rows.append({"doc": ex.doc_id, "field": name, "outcome": outcome, "pred": pred, "gold": g,
                             "confidence": ex.fields[name].confidence, "accepted": ex.fields[name].confidence >= 0.9})
    tp = counts["correct"]
    precision = tp / max(1, tp + counts["wrong"] + counts["hallucinated"])
    recall = tp / max(1, tp + counts["wrong"] + counts["missed"])
    f1 = 2 * precision * recall / max(1e-9, precision + recall)
    return {"counts": counts, "precision": round(precision, 3), "recall": round(recall, 3), "f1": round(f1, 3), "per_field": per_field, "errors": rows}


def score_questions(ont, questions) -> dict:
    results = []
    for q in questions:
        if q.get("type") == "lenders_multi_borrower":
            got = ont.lenders_multi_borrower()
            ok = sorted(got) == sorted(q["answer"])
            warned = bool(ont.completeness_warnings(lenders=True))
        elif q.get("type") == "borrowers_where":
            got = ont.borrowers_where(q["field"], q["op"], q["value"], q["as_of"])
            ok = sorted(got) == sorted(q["answer"])
            warned = bool(ont.completeness_warnings(fname=q["field"]))
        else:
            fact = ont.as_of(q["borrower"], q["field"], q["as_of"])
            got = fact["value"] if fact else None
            warned = bool(fact and fact.get("warnings")) or (fact is None and bool(ont.completeness_warnings()))
            ok = got == q["answer"] or (got is not None and q["answer"] is not None and not isinstance(got, str) and abs(float(got) - float(q["answer"])) < 1e-6)
        results.append({"id": q["id"], "question": q["question"], "expected": q["answer"], "got": got, "correct": bool(ok), "warned": warned})
    wrong = [r for r in results if not r["correct"]]
    return {"accuracy": round(sum(r["correct"] for r in results) / len(results), 3),
            "wrong_answers_flagged": sum(r["warned"] for r in wrong), "wrong_answers_silent": sum(not r["warned"] for r in wrong), "results": results}


def integrity(extractions, labels) -> dict:
    """Facts that entered the ontology must be verified+grounded AND correct. Wrong-but-accepted facts are the
    failure that matters most: they'd flow silently into credit decisions."""
    unsupported = wrong = 0
    for ex in extractions:
        kinds = AGREEMENT_FIELDS if ex.doc_type == "credit_agreement" else AMENDMENT_FIELDS
        for name, value in ex.accepted().items():
            f = ex.fields[name]
            unsupported += not (f.verified and f.grounded)
            wrong += not same(kinds[name], value, gold_value(labels[ex.doc_id], name))
    queued = sum(1 for ex in extractions for f in ex.fields.values() if f.value is not None and f.confidence < 0.9)
    return {"unsupported_facts_in_ontology": unsupported, "wrong_facts_in_ontology": wrong, "fields_sent_to_review": queued}


def cost(extractions, model: str | None) -> dict:
    tin = sum(e.usage.get("input_tokens", 0) for e in extractions)
    tout = sum(e.usage.get("output_tokens", 0) for e in extractions)
    prices = json.loads((ROOT / "config" / "models.json").read_text())["prices_per_mtok"].get(model or "", {})
    usd = None
    if prices.get("input") is not None and prices.get("output") is not None:
        usd = round((tin * prices["input"] + tout * prices["output"]) / 1e6, 4)
    lat = sorted(e.latency_ms for e in extractions)
    return {"input_tokens": tin, "output_tokens": tout, "usd_total": usd,
            "usd_per_doc": round(usd / len(extractions), 5) if usd is not None else None,
            "latency_ms_p50": lat[len(lat) // 2]}


def gates(report: dict, thresholds: dict) -> list[str]:
    fails = []
    i, t = report["integrity"], thresholds["integrity"]
    if i["unsupported_facts_in_ontology"] > t["unsupported_facts_in_ontology_max"]:
        fails.append(f"unsupported facts in ontology: {i['unsupported_facts_in_ontology']}")
    if i["wrong_facts_in_ontology"] > t["wrong_facts_in_ontology_max"]:
        fails.append(f"wrong facts in ontology: {i['wrong_facts_in_ontology']}")
    if report["questions"]["wrong_answers_silent"] > t["silent_wrong_answers_max"]:
        fails.append(f"silent wrong answers: {report['questions']['wrong_answers_silent']}")
    if report["extractor"] != "baseline":
        q = thresholds["quality_llm"]
        if report["fields"]["f1"] < q["field_f1_min"]:
            fails.append(f"field F1 {report['fields']['f1']} < {q['field_f1_min']}")
        if report["questions"]["accuracy"] < q["question_accuracy_min"]:
            fails.append(f"question accuracy {report['questions']['accuracy']} < {q['question_accuracy_min']}")
    return fails


def markdown(r: dict) -> str:
    f, q, i, c = r["fields"], r["questions"], r["integrity"], r["cost"]
    out = [f"# Eval report: {r['name']}", f"_{r['generated']} · {r['docs']} documents · {len(q['results'])} questions_", "",
           f"**Gate: {'PASS' if not r['gate_failures'] else 'FAIL: ' + '; '.join(r['gate_failures'])}**", "",
           "| Metric | Value |", "|---|---|",
           f"| Field precision / recall / F1 | {f['precision']} / {f['recall']} / {f['f1']} |",
           f"| Correct · wrong · missed · hallucinated · correct-absent | {' · '.join(str(v) for v in f['counts'].values())} |",
           f"| As-of question accuracy | {q['accuracy']} |",
           f"| Wrong answers flagged with a warning / silent | {q['wrong_answers_flagged']} / {q['wrong_answers_silent']} |",
           f"| Facts in ontology that are unsupported / wrong | {i['unsupported_facts_in_ontology']} / {i['wrong_facts_in_ontology']} |",
           f"| Fields sent to human review | {i['fields_sent_to_review']} |",
           f"| Tokens in / out | {c['input_tokens']} / {c['output_tokens']} |",
           f"| Cost total / per doc (USD) | {c['usd_total'] if c['usd_total'] is not None else 'n/a (set prices in config/models.json)'} / {c['usd_per_doc'] if c['usd_per_doc'] is not None else 'n/a'} |",
           f"| Median latency per doc (ms) | {c['latency_ms_p50']} |", "",
           "## Questions", "", "| ID | Question | Expected | Got | |", "|---|---|---|---|---|"]
    out += [f"| {x['id']} | {x['question']} | `{x['expected']}` | `{x['got']}` | {'✅' if x['correct'] else ('⚠️ wrong, flagged' if x['warned'] else '❌')} |" for x in q["results"]]
    out += ["", "## Field errors", "", "| Doc | Field | Outcome | Predicted | Gold | Entered ontology? |", "|---|---|---|---|---|---|"]
    out += [f"| {e['doc']} | {e['field']} | {e['outcome']} | `{e['pred']}` | `{e['gold']}` | {('yes' if e['accepted'] else 'no (review queue)') if e['pred'] is not None else 'n/a (nothing extracted)'} |" for e in f["errors"]]
    return "\n".join(out) + "\n"


def evaluate(extractor) -> dict:
    labels = json.loads((ROOT / "data" / "labels.json").read_text())
    questions = json.loads((ROOT / "data" / "questions.json").read_text())
    extractions, ont = run(extractor)
    report = {"name": extractor.name + (f" ({extractor.model})" if extractor.model else ""), "extractor": extractor.name,
              "model": extractor.model, "generated": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"), "docs": len(extractions),
              "fields": score_fields(extractions, labels), "questions": score_questions(ont, questions),
              "integrity": integrity(extractions, labels), "cost": cost(extractions, extractor.model)}
    report["gate_failures"] = gates(report, json.loads((HERE / "thresholds.json").read_text()))
    return report


def compare(paths: list[str]) -> str:
    rows = ["| Extractor | Field F1 | Question acc. | Wrong facts in ontology | Sent to review | USD / doc | p50 latency (ms) |", "|---|---|---|---|---|---|---|"]
    for p in paths:
        r = json.loads(Path(p).read_text())
        rows.append(f"| {r['name']} | {r['fields']['f1']} | {r['questions']['accuracy']} | {r['integrity']['wrong_facts_in_ontology']} | "
                    f"{r['integrity']['fields_sent_to_review']} | {r['cost']['usd_per_doc'] if r['cost']['usd_per_doc'] is not None else 'n/a'} | {r['cost']['latency_ms_p50']} |")
    return "\n".join(rows) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--extractor", choices=["baseline", "llm"], default="baseline")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    ap.add_argument("--model")
    ap.add_argument("--compare", nargs="+")
    args = ap.parse_args()
    if args.compare:
        print(compare(args.compare))
        return 0
    report = evaluate(make_extractor(args.extractor, args.provider, args.model))
    slug = report["name"].replace(" ", "_").replace(":", "_").replace("(", "").replace(")", "")
    (HERE / "reports").mkdir(exist_ok=True)
    (HERE / "reports" / f"{slug}.json").write_text(json.dumps(report, indent=2, default=str))
    md = markdown(report)
    (HERE / "reports" / f"{slug}.md").write_text(md)
    print(md)
    return 1 if report["gate_failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
