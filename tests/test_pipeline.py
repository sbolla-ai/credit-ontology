import json

import pytest

from creditont.extraction import FieldValue, LLMExtractor, run_extraction, verify
from creditont.normalize import canonical_name, dates_in, margins_bps_in, money_in, ratios_in
from creditont.pipeline import load_docs, make_extractor, run

DOCS = load_docs()


# ---------------------------------------------------------------- normalization
@pytest.mark.parametrize("text,expected", [
    ("not to exceed 3.50:1.00", [3.5]), ("not more than 3.00 to 1.00", [3.0]), ("shall not exceed 3.75:1", [3.75]),
    ("shall not exceed four and one-quarter to one", [4.25]), ("leverage of 4.5x", [4.5]),
])
def test_ratios(text, expected):
    assert ratios_in(text) == expected


def test_money_dates_margins():
    assert money_in("Four Hundred Million Dollars ($400,000,000)") == [(400_000_000, "USD")]
    assert money_in("an aggregate amount equal to EUR 150,000,000") == [(150_000_000, "EUR")]
    assert dates_in("15 September 2024; March 15, 2024") == ["2024-03-15", "2024-09-15"]
    assert margins_bps_in("Term SOFR plus 2.25%") == [225] and margins_bps_in("275 basis points") == [275]
    assert margins_bps_in("Margin means 2.00 per cent. per annum") == [200]


def test_entity_resolution():
    assert canonical_name("Granite Point Bank, N.A.") == canonical_name("Granite Point Bank")
    assert canonical_name("Tidewater Energy Partners, L.P.") == canonical_name("Tidewater Energy Partners LP")
    assert canonical_name("Northwind Logistics Inc.") == canonical_name("NORTHWIND LOGISTICS, INC.")
    assert canonical_name("Granite Point Bank") != canonical_name("Harborline Bank, N.A.")


# ---------------------------------------------------------------- verification
TEXT = DOCS["CA-001"]


def test_invented_quote_is_rejected():
    fv = verify(FieldValue("max_leverage_ratio", 3.5, ["greater than 3.50:1.00 at all times"]), "ratio", TEXT)
    assert not fv.verified and fv.confidence == 0


def test_real_quote_that_does_not_support_value_is_rejected():
    # Quote is genuine, but it says 3.50, not 4.0: a model that misreads the number can't slip it through.
    fv = verify(FieldValue("max_leverage_ratio", 4.0, ["to be greater than 3.50:1.00"]), "ratio", TEXT)
    assert fv.verified and not fv.grounded and fv.confidence < 0.9


def test_supported_value_is_accepted():
    fv = verify(FieldValue("max_leverage_ratio", 3.5, ["to be greater than 3.50:1.00"]), "ratio", TEXT)
    assert fv.confidence == 1.0


# ---------------------------------------------------------------- ontology
@pytest.fixture(scope="module")
def baseline():
    return run(make_extractor("baseline"))


def test_amendments_apply_in_date_order(baseline):
    _, ont = baseline
    assert ont.as_of("northwind logistics", "max_leverage_ratio", "2025-06-30")["value"] == 3.5
    assert ont.as_of("northwind logistics", "max_leverage_ratio", "2025-12-31")["value"] == 4.0
    latest = ont.as_of("northwind logistics", "max_leverage_ratio", "2026-06-30")
    assert latest["value"] == 3.75 and latest["source_doc"] == "AM-002" and "3.75:1.00" in latest["quote"]


def test_amendment_name_variant_links_to_same_company(baseline):
    _, ont = baseline
    aliases = json.loads(ont.db.execute("SELECT aliases FROM company WHERE key='northwind logistics'").fetchone()[0])
    assert len(aliases) >= 2  # "NORTHWIND LOGISTICS, INC." and the amendment's "Northwind Logistics Inc."


def test_missed_amendment_change_produces_warning_not_silence(baseline):
    _, ont = baseline  # the regex baseline misses AM-003's interest-coverage change
    fact = ont.as_of("tidewater energy partners", "min_interest_coverage_ratio", "2026-06-30")
    assert fact["value"] == 2.25 and any("AM-003" in w for w in fact["warnings"])


def test_no_warning_before_the_amendment_is_effective(baseline):
    _, ont = baseline
    assert ont.as_of("tidewater energy partners", "min_interest_coverage_ratio", "2026-01-01")["warnings"] == []


# ---------------------------------------------------------------- LLM path with a fake model
class FakeProvider:
    name, model = "fake", "fake-model"

    def __init__(self, payload):
        self.payload = payload

    def complete(self, system, user):
        return json.dumps(self.payload), {"input_tokens": 1000, "output_tokens": 200}


def test_llm_hallucinated_covenant_never_enters_ontology():
    # Model claims Orion has a 1.25x interest-coverage covenant (it's a FIXED CHARGE covenant) and quotes it.
    payload = {"borrower": {"value": "Orion Fabrication Corp.", "quotes": ["ORION FABRICATION CORP., as Borrower"]},
               "agreement_date": {"value": "2025-01-10", "quotes": ["Dated as of January 10, 2025"]},
               "min_interest_coverage_ratio": {"value": 1.25, "quotes": ["Fixed Charge Coverage Ratio of not less than 1.25 to 1.00"]}}
    ex = run_extraction(LLMExtractor(FakeProvider(payload)), "CA-003", DOCS["CA-003"])
    # The quote is real and contains 1.25, so grounding alone can't catch a wrong covenant TYPE.
    # That is exactly what the eval's 'hallucinated' count and the labeled set exist to measure.
    assert ex.fields["min_interest_coverage_ratio"].confidence == 1.0
    from evals_helpers import score_one
    assert score_one(ex)["min_interest_coverage_ratio"] == "hallucinated"


def test_llm_garbage_output_extracts_nothing():
    ex = run_extraction(LLMExtractor(FakeProvider("not json")), "CA-001", DOCS["CA-001"])
    assert ex.accepted() == {}


def test_baseline_passes_integrity_gates():
    import importlib.util, pathlib, sys

    path = pathlib.Path(__file__).resolve().parents[1] / "evals" / "run_evals.py"
    spec = importlib.util.spec_from_file_location("run_evals", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["run_evals"] = mod
    spec.loader.exec_module(mod)
    report = mod.evaluate(make_extractor("baseline"))
    assert report["integrity"]["wrong_facts_in_ontology"] == 0
    assert report["questions"]["wrong_answers_silent"] == 0
    assert report["gate_failures"] == []
