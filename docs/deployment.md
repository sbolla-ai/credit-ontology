# Deploying in a lender's environment

```
Document store (PDF/HTML) ──► text extraction / OCR ──► creditont extraction (private model endpoint)
                                                            │
                                    verified facts ◄────────┤────► review queue (analyst UI)
                                          │                               │ corrections
                                          ▼                               ▼
                               ontology DB (Postgres / Foundry)   labeled set ──► CI eval gates
```

## Checklist
- **Model hosting:** a model endpoint the firm has approved for confidential documents, with zero data retention confirmed in writing.
- **OCR quality first:** scanned agreements need OCR before extraction. Measure OCR errors separately, since a misread digit looks like a model error.
- **Release gate:** CI runs `evals/run_evals.py` on the firm's labeled set. Any wrong fact in the ontology or silent wrong answer blocks the release.
- **Corrections loop:** analyst fixes from the review queue are added to the labeled set weekly.
- **Model changes:** re-run the comparison (`--compare`) before switching models or prompt versions; record the report with the release.
- **Access:** documents and the ontology inherit the firm's entitlements; the extraction service itself holds no standing access to the document store.
