# Eval report: baseline
_2026-11-26 04:13 UTC · 8 documents · 11 questions_

**Gate: PASS**

| Metric | Value |
|---|---|
| Field precision / recall / F1 | 1.0 / 0.886 / 0.94 |
| Correct · wrong · missed · hallucinated · correct-absent | 70 · 0 · 9 · 0 · 10 |
| As-of question accuracy | 0.636 |
| Wrong answers flagged with a warning / silent | 4 / 0 |
| Facts in ontology that are unsupported / wrong | 0 / 0 |
| Fields sent to human review | 0 |
| Tokens in / out | 0 / 0 |
| Cost total / per doc (USD) | n/a (set prices in config/models.json) / n/a |
| Median latency per doc (ms) | 2.0 |

## Questions

| ID | Question | Expected | Got | |
|---|---|---|---|---|
| Q01 | Northwind's maximum leverage ratio as of 2025-06-30 | `3.5` | `3.5` | ✅ |
| Q02 | Northwind's maximum leverage ratio as of 2025-12-31 (after the First Amendment) | `4.0` | `4.0` | ✅ |
| Q03 | Northwind's maximum leverage ratio as of 2026-06-30 (after the Second Amendment) | `3.75` | `3.75` | ✅ |
| Q04 | Northwind's total commitments as of 2026-01-01 | `300000000` | `300000000` | ✅ |
| Q05 | Northwind's maturity date as of 2026-06-30 | `2030-06-30` | `2030-06-30` | ✅ |
| Q06 | Tidewater's minimum interest coverage as of 2026-06-30 | `2.0` | `2.25` | ⚠️ wrong, flagged |
| Q07 | Tidewater's margin (bps) as of 2026-01-15, before its amendment | `300` | `300` | ✅ |
| Q08 | Orion's minimum interest coverage ratio (it has a fixed-charge covenant, not an interest-coverage one) | `None` | `None` | ✅ |
| Q09 | Cedar & Pine's maximum leverage ratio | `4.25` | `None` | ⚠️ wrong, flagged |
| Q10 | Lenders with exposure to more than one borrower | `['bayview trust', 'granite point bank', 'meridian credit partners', 'summit ridge capital']` | `[]` | ⚠️ wrong, flagged |
| Q11 | Borrowers whose maximum leverage ratio is above 4.0x as of 2026-06-30 | `['cedar pine health systems', 'tidewater energy partners']` | `['tidewater energy partners']` | ⚠️ wrong, flagged |

## Field errors

| Doc | Field | Outcome | Predicted | Gold | Entered ontology? |
|---|---|---|---|---|---|
| AM-003 | changes.min_interest_coverage_ratio | missed | `None` | `2.0` | n/a (nothing extracted) |
| CA-001 | lenders | missed | `None` | `['Harborline Bank, N.A.', 'Summit Ridge Capital LLC', 'Bayview Trust Company']` | n/a (nothing extracted) |
| CA-002 | borrower | missed | `None` | `Cedar & Pine Health Systems, LLC` | n/a (nothing extracted) |
| CA-002 | lenders | missed | `None` | `['Granite Point Bank', 'Bayview Trust Company', 'Meridian Credit Partners LP']` | n/a (nothing extracted) |
| CA-002 | max_leverage_ratio | missed | `None` | `4.25` | n/a (nothing extracted) |
| CA-002 | min_interest_coverage_ratio | missed | `None` | `2.5` | n/a (nothing extracted) |
| CA-003 | lenders | missed | `None` | `['Summit Ridge Capital LLC']` | n/a (nothing extracted) |
| CA-004 | lenders | missed | `None` | `['Nordhaven Bank AG', 'Bayview Trust Company']` | n/a (nothing extracted) |
| CA-005 | lenders | missed | `None` | `['Granite Point Bank, N.A.', 'Meridian Credit Partners LP']` | n/a (nothing extracted) |
