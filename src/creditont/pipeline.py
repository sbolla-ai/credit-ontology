"""Documents -> extractions -> verified ontology + review queue."""
from __future__ import annotations

from pathlib import Path

from .extraction import BaselineExtractor, Extraction, LLMExtractor, run_extraction
from .ontology import Ontology

ROOT = Path(__file__).resolve().parents[2]
DOCS = ROOT / "data" / "docs"


def load_docs(folder: Path = DOCS) -> dict[str, str]:
    """doc_id is the file-name prefix before the first underscore (e.g. CA-001)."""
    return {p.name.split("_", 1)[0]: p.read_text() for p in sorted(folder.glob("*.txt"))}


def make_extractor(kind: str = "baseline", provider: str = "anthropic", model: str | None = None):
    if kind == "baseline":
        return BaselineExtractor()
    from .providers import get_provider

    return LLMExtractor(get_provider(provider, model))


def run(extractor, docs: dict[str, str] | None = None) -> tuple[list[Extraction], Ontology]:
    docs = docs if docs is not None else load_docs()
    extractions = [run_extraction(extractor, doc_id, text) for doc_id, text in docs.items()]
    return extractions, Ontology().load(extractions, docs)
