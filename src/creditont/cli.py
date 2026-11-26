"""creditont CLI.

    creditont ask "Northwind Logistics" max_leverage_ratio --as-of 2026-06-30
    creditont lenders                     # lenders with exposure to more than one borrower
    creditont review                      # fields waiting for a human
    creditont graph > graph.json          # nodes/edges for a front-end
    Add --extractor llm [--provider anthropic|openai] [--model ...] to any command.
"""
from __future__ import annotations

import argparse
import json
from datetime import date

from .normalize import canonical_name
from .pipeline import make_extractor, run


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="creditont")
    ap.add_argument("--extractor", choices=["baseline", "llm"], default="baseline")
    ap.add_argument("--provider", choices=["anthropic", "openai"], default="anthropic")
    ap.add_argument("--model")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("ask")
    a.add_argument("borrower")
    a.add_argument("field", choices=["max_leverage_ratio", "min_interest_coverage_ratio", "commitment_amount", "maturity_date", "margin_bps"])
    a.add_argument("--as-of", default=date.today().isoformat())
    sub.add_parser("lenders")
    sub.add_parser("review")
    sub.add_parser("graph")
    args = ap.parse_args(argv)

    _, ont = run(make_extractor(args.extractor, args.provider, args.model))
    if args.cmd == "ask":
        fact = ont.as_of(canonical_name(args.borrower), args.field, args.as_of)
        print(json.dumps(fact or {"value": None, "note": "No verified fact for this borrower and field."}, indent=2))
    elif args.cmd == "lenders":
        print(json.dumps({"lenders": ont.lenders_multi_borrower(), "warnings": ont.completeness_warnings(lenders=True)}, indent=2))
    elif args.cmd == "review":
        print(json.dumps([r.__dict__ for r in ont.review], indent=2, default=str))
    else:
        print(json.dumps(ont.graph(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
