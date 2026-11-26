# Engagement scoping: covenant intelligence for a credit portfolio

_How I'd scope this with a lender's credit-risk and portfolio-management teams in week one. The customer and bracketed numbers are placeholders for discovery data._

## Problem
Analysts track covenants for [N] borrowers across agreements and amendments stored as PDFs. Answering "which borrowers are close to their leverage limit this quarter?" takes days, and missed amendments cause stale answers.

## Pilot scope
| In | Out (for now) |
|---|---|
| Leverage and interest-coverage covenants, commitments, maturity, pricing | Full credit memos, collateral packages |
| Amendments applied with effective dates | Waivers and consent letters |
| [N] borrowers in one portfolio | Firm-wide rollout |

## Success criteria
- **Integrity (gates):** 0 wrong facts in the ontology and 0 silent wrong answers on a held-out labeled set of [N] real agreements.
- **Quality:** field F1 ≥ [0.95] and as-of question accuracy ≥ [0.95] on that set.
- **Efficiency:** time to answer a portfolio covenant question from [days] to [minutes]; review queue under [X]% of fields.
- **Cost:** under $[Y] per document at the chosen model, measured, not estimated.

## Discovery questions
1. Where do agreements live (document management, loan system, shared drives), and are amendments linked to their originals?
2. Which questions do analysts and the credit committee ask most?
3. How are covenant definitions customized (EBITDA add-backs, step-downs), and which matter most?
4. Data handling: can documents go to a hosted model under the firm's agreement, or must the model run in a private cloud?
5. Who owns corrections, and how should they flow back into the system?

## Plan
| Week | Milestone |
|---|---|
| 1–2 | Label 50–100 real agreements with analysts; agree the ontology |
| 3 | Run 2–3 models on the labeled set; pick on quality, cost and latency |
| 4–5 | Analyst review queue; shadow mode against the current covenant tracker |
| 6 | Pilot for one portfolio; weekly readout to the head of credit risk |
