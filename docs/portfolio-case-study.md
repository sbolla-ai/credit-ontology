# Portfolio text for sbolla.dev

**Card**

> **Credit Agreement Ontology** · Side project · Finance
> Turns credit agreements and amendments into a verified, Foundry-style ontology you can query "as of" any date, where every answer cites its source or warns why it can't be trusted.
> Stack: Python, Claude API, SQLite ontology, entity resolution, pytest eval gates, GitHub Actions
> Result: 0 wrong facts in the ontology and 0 silent wrong answers; found that a 0.94 field F1 still produced only 64% correct business answers.

**Full case study**

- **Problem:** Covenant questions take days, and a single missed amendment gives a confidently stale answer.
- **What I built:** Extraction with verbatim quotes, a check that every value is re-derivable from its quote, entity resolution across documents, amendments stored as dated facts, as-of queries with provenance, and warnings when an amendment mentions a term but no change was captured.
- **What I measured:** Field precision, recall and F1; as-of question accuracy; wrong facts allowed into the ontology; silent vs. flagged wrong answers; cost and latency per document by model.
- **Key finding:** Field metrics hide decision failures. The baseline scored 0.94 F1 but answered only 64% of questions correctly. So the release gate is "zero silent wrong answers", not a field-accuracy target alone.
- **Honest limits:** A real quote filed under the wrong covenant type passes the quote checks; only the labeled eval catches it. A covenant-type verifier is next.

**Interview story (30 seconds)**
"At SMBC I spent a year modeling Foundry ontologies, so I built one in public. The interesting result wasn't extraction accuracy. My baseline had 0.94 field F1 but only got 64% of the business questions right, because one missed amendment clause makes the covenant answer stale. So I changed what 'done' means: the system may be wrong, but never silently. Every answer carries its source, and if an amendment might have changed it, it says so."
