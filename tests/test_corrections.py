import json
import sys
import types

import pytest

from app import evaluation as ev
from app import tasks
from app.calibration import Calibration, question_key
from app.decisions import Backend, BackendUnavailable, CatalogueBackend, LayaBackend, UniformBackend
from app.graph import Graph
from app.pipeline import Pipeline
from app.request import preference_score, requested_groups, resolve
from app.testset import build
from scripts.fit_calibration import fit


@pytest.fixture(scope="module")
def graph():
    return Graph()


@pytest.mark.parametrize("text,groups", [
    ("Greenhouse gas emissions from road transport by country and month", ["ghg"]),
    ("Particulate matter by region", ["pm"]),
    ("Monthly NOx emissions by region", []),
    ("Monthly data by region", ["all"]),
    ("Ammonia from agriculture by country and year", []),
    ("fine particulate matter by country", []),
])
def test_explicit_group_semantics(text, groups):
    assert requested_groups(text) == groups


@pytest.mark.parametrize("text,expected", [
    ("Ammonia from agriculture by country and year", ["NH3"]),
    ("Particulate matter by region", ["PM2_5", "PM10"]),
    ("Monthly NOx emissions by region", ["NOx"]),
])
def test_catalogue_pipeline_without_weights(graph, text, expected):
    out = Pipeline(graph).run(CatalogueBackend(), text)
    assert out["outcome"] == "answer"
    assert out["query"]["pollutants"] == expected


def test_country_and_year_constraints(graph):
    out = Pipeline(graph).run(CatalogueBackend(), "Annual CO2 for Australia in 2024")
    assert out["outcome"] == "answer"
    assert out["solutions"]
    for sol in out["solutions"]:
        assert set(sol["profiles"]["GEO.country"]) == {"Australia"}
        assert set(sol["profiles"]["TIME.year"]) == {"2024"}
        assert sol["cells"] == 1


def test_region_constraint(graph):
    out = Pipeline(graph).run(CatalogueBackend(), "PM10 levels in Lombardy each month")
    assert out["outcome"] == "answer"
    assert all(set(s["profiles"]["GEO.region"]) == {"Lombardy"} for s in out["solutions"])


def test_all_named_members_required_after_rollup(graph):
    constraint = {"GEO": {"level": "country", "members": ["Italy", "China"]}}
    sols = graph.discover(["NOx"], {"GEO": "continent"}, filters=constraint)
    assert sols
    assert all({"Europe", "Asia"} <= set(s["profiles"]["GEO.continent"]) for s in sols)


@pytest.mark.parametrize("text", ["CO2 in 1850 by country", "CO2 forecast in 2040", "Daily PM2.5 for Milan"])
def test_unsupported_request_is_rejected(graph, text):
    assert Pipeline(graph).run(CatalogueBackend(), text)["outcome"] == "reject"


def test_relative_window_has_explicit_catalogue_anchor():
    parsed = resolve("Monthly NOx by region for the last five years")
    assert parsed["levels"]["TIME"] == "month"
    assert parsed["filters"]["TIME"]["members"] == ["2021", "2022", "2023", "2024", "2025"]
    assert parsed["time_anchor"] == 2025
    assert not parsed["issues"]


def test_low_confidence_is_never_reported_as_an_answer(graph):
    out = Pipeline(graph).run(UniformBackend(), "CO2 by country and year")
    assert out["outcome"] == "review"
    assert any(reason.startswith("Gate:") for reason in out["review"])
    assert out["query"]["pollutants"] == ["CO2"]      # named in the request, so not left to the model


class OverexpandedBackend(CatalogueBackend):
    def _decide(self, state, questions):
        answers, tokens, cost, detail = super()._decide(state, questions)
        for name in questions:
            if name.startswith("group:"):
                answers[name] = {"yes": 0.999, "no": 0.001}
        return answers, tokens, cost, detail


def test_wrong_group_model_cannot_broaden_request(graph):
    out = Pipeline(graph).run(OverexpandedBackend(), "Ammonia from agriculture by country and year")
    assert out["outcome"] == "review"
    assert out["query"]["pollutants"] == ["NH3"]
    assert any("added" in reason for reason in out["review"])


class MissingPollutantBackend(CatalogueBackend):
    def _decide(self, state, questions):
        answers, tokens, cost, detail = super()._decide(state, questions)
        if "pollutant:CH4" in answers:
            answers["pollutant:CH4"] = {"yes": 0.001, "no": 0.999}
        return answers, tokens, cost, detail


def test_confident_model_cannot_omit_named_pollutant(graph):
    out = Pipeline(graph).run(MissingPollutantBackend(), "CO2 and CH4 emissions by country and year")
    assert out["outcome"] == "review"
    assert out["query"]["pollutants"] == ["CO2", "CH4"]
    assert any("left out" in reason for reason in out["review"])


@pytest.mark.parametrize("text", ["CO2 for Paris by year", "CO2 for norway by year", "CO2 for Italy and Norway by year"])
def test_unknown_member_is_not_silently_dropped(graph, text):
    out = Pipeline(graph).run(CatalogueBackend(), text)
    assert out["outcome"] == "clarify"
    assert not any(s["stage"] == "discover" for s in out["stages"])


@pytest.mark.parametrize("text", ["Benzene emissions by country and year",
                                  "CO2 and benzene by country and year", "CO2 for Canada in 2024"])
def test_unknown_pollutants_and_qualifiers_are_not_broadened(graph, text):
    out = Pipeline(graph).run(CatalogueBackend(), text)
    assert out["outcome"] == "clarify"
    assert not any(s["stage"] == "discover" for s in out["stages"])


def test_known_unheld_pollutant_is_rejected(graph):
    out = Pipeline(graph).run(CatalogueBackend(), "NO2 emissions by country and year")
    assert out["outcome"] == "reject"
    assert not any(s["stage"] == "discover" for s in out["stages"])


def test_catalogue_checks_agree_with_labels_and_never_block_an_answerable_request():
    # The checks stop requests outright, so they must never stop one the labels answer.
    for item in build():
        if item["task"] != "gate":
            continue
        parsed = resolve(item["state"]["request"])
        if parsed["hard_reject"]:
            assert item["gold"] == "reject", item["id"]            # a hard reject must be right
        if parsed["issues"]:
            # Clarify is safe for anything the labels do not answer; a confident model reject
            # takes precedence over it in the pipeline.
            assert item["gold"] in ("clarify", "reject"), item["id"]


@pytest.mark.parametrize("text", [
    "Could you pull together CO2 figures by country and year for me?",
    "I need nitrogen oxides by region and month",
    "Give me a breakdown of CO2 by country and year",
    "I'd like CH4 and N2O by continent and year",
    "Compare sulphur dioxide across countries over time",
])
def test_ordinary_wording_is_not_stopped_by_the_checks(text):
    parsed = resolve(text)
    assert not parsed["hard_reject"] and not parsed["issues"], parsed


def test_unknown_words_do_not_widen_a_general_request():
    assert resolve("Benzene emissions by country and year")["pollutants"] == []
    assert resolve("Air emissions by country and year")["groups"] == ["all"]


def test_held_and_unheld_pollutants_are_answered_with_a_note(graph):
    text = "I would like to obtain data about CO2, NOx and NO2 for each region, month and subsector"
    out = Pipeline(graph).run(CatalogueBackend(), text)
    assert out["outcome"] in ("answer", "no_data")     # the synthetic catalogue has no source for this breakdown
    assert out["query"]["pollutants"] == ["CO2", "NOx"]
    assert any("NO2" in note for note in out["notes"])


def test_distinct_years_are_not_expanded_by_sector_preposition():
    parsed = resolve("CO2 from agriculture in 2020 and 2024 by country")
    assert parsed["filters"]["TIME"]["members"] == ["2020", "2024"]


@pytest.mark.parametrize("text,members", [
    ("CO2 from 2021 to 2025 by country", ["2021", "2022", "2023", "2024", "2025"]),
    ("CO2 by country for 2024 through 2025", ["2024", "2025"]),
    ("CO2 by country between 2023 and 2025", ["2023", "2024", "2025"]),
    ("CO2 for 2024-01 to 2024-03 by country", ["2024-01", "2024-02", "2024-03"]),
])
def test_date_range_constraints(text, members):
    parsed = resolve(text)
    assert not parsed["issues"]
    assert parsed["gate"] == "answer"
    assert parsed["filters"]["TIME"]["members"] == members


def test_preference_does_not_ignore_missing_dimension():
    sol = {"sources": [{"publisher": "official"}], "profiles": {"TIME.year": {"2024": 1}}}
    assert preference_score("Official sources for Italy", sol) == 0
    assert preference_score("Official sources for Norway", sol) is None


def test_dimension_specific_coverage_preference_requires_review(graph):
    out = Pipeline(graph).run(CatalogueBackend(), "CO2 by country and year", "As many countries as possible")
    assert out["outcome"] == "review"
    assert out["solutions"]


def test_join_recency_uses_oldest_constituent():
    sol = {"sources": [{"updated": 2025}, {"updated": 2018}], "profiles": {}}
    assert preference_score("Most recent data available", sol) == 0


def test_unknown_preference_clause_is_not_ignored():
    sol = {"sources": [{"publisher": "official", "updated": 2025}], "profiles": {}}
    assert preference_score("Official sources with open licenses", sol) is None


def test_loaded_calibration_missing_question_requires_review(graph, tmp_path):
    backend = CatalogueBackend()
    path = tmp_path / "partial.json"
    path.write_text(json.dumps({"version": 1, "model": backend.model, "tasks": {}}))
    backend.calibration = Calibration(path, backend.model)
    out = Pipeline(graph).run(backend, "CO2 by country and year")
    assert out["outcome"] == "review"
    assert any(reason.startswith("Gate:") for reason in out["review"])


def test_serving_calibration_and_model_guard(tmp_path):
    q = {"q": {"type": "noul"}}
    class RawBackend(Backend):
        def _decide(self, state, questions):
            return {"q": {"yes": 0.99, "no": 0.01}}, None, 0, {}
    backend = RawBackend("test-model")
    path = tmp_path / "cal.json"
    path.write_text(json.dumps({"version": 1, "model": "test-model", "tasks": {
        "relevance": {"temperature": 5, "threshold": 0.8, "questions": [question_key(q["q"])]}}}))
    backend.calibration = Calibration(path, backend.model)
    assert backend.decide({}, q).answers["q"].confidence < 0.8
    assert backend.decide({}, q, calibrate=False).answers["q"].confidence == 0.99
    with pytest.raises(ValueError, match="model"):
        Calibration(path, "different-model")


def test_grouped_folds_and_holdout_are_disjoint():
    recs = [{"id": f"rel-P{i // 3:02d}-{i}", "task": "relevance", "gold": "yes", "top": "yes",
             "correct": True, "confidence": 0.9, "probs": {"yes": 0.9, "no": 0.1}, "latency_ms": 1}
            for i in range(30)]
    folds = ev.group_folds(recs)
    for group in {ev.group_id(r) for r in recs}:
        assert len({folds[i] for i, r in enumerate(recs) if ev.group_id(r) == group}) == 1
    metric = ev.heldout_coverage(recs)
    assert not set(metric["selection_groups"]) & set(metric["evaluation_groups"])
    assert metric["validated_risk_guarantee"] is False


def test_failures_count_in_coverage_denominator():
    good = {"correct": True, "confidence": 0.9}
    result = ev.coverage_at_risk([good, {"error": "unavailable"}])
    assert result["coverage"] == 0.5
    assert result["method"] == "empirical_in_sample"


def test_extended_tasks_are_labelled_independently():
    items = build()
    assert sum(i["task"] == "group" for i in items) == 128
    assert sum(i["task"] == "fit" for i in items) == 8
    assert {i["gold"] for i in items if i["task"] == "group" and i["question"] == "group:metal"} == {"yes", "no"}


def test_calibration_has_three_disjoint_partitions():
    q = tasks.GATE
    recs = [{"id": f"gate-P{i:02d}", "task": "gate", "question_key": question_key(q), "gold": "answer",
             "top": "answer", "correct": True, "confidence": 0.9,
             "probs": {"answer": 0.9, "clarify": 0.05, "reject": 0.05}, "latency_ms": 1} for i in range(30)]
    artifact = fit({"model": "test", "records": recs})
    spec = artifact["tasks"]["gate"]
    a, b, c = map(set, spec["partition_groups"])
    assert not a & b and not a & c and not b & c
    assert spec["holdout"]["total"] == 10


def test_legacy_records_cannot_produce_serving_artifact():
    with pytest.raises(ValueError, match="signatures"):
        fit({"model": "legacy", "records": [{"id": f"gate-P{i}", "task": "gate", "correct": True,
             "gold": "a", "confidence": 0.9, "probs": {"a": 0.9, "b": 0.1}} for i in range(12)]})


def test_laya_source_only_install_is_unavailable(monkeypatch):
    package = types.ModuleType("laya")
    package.__path__ = []
    monkeypatch.setitem(sys.modules, "laya", package)
    monkeypatch.setitem(sys.modules, "laya.agent", None)
    backend = LayaBackend()
    assert backend.available()[0] is False
    with pytest.raises(BackendUnavailable):
        backend.decide({}, {"q": {"type": "noul"}})


class ConfidentGate(CatalogueBackend):
    """Catalogue rules, except the gate always answers with full confidence, as a model might."""
    def _decide(self, state, questions):
        if "gate" in questions:
            return {"gate": {"answer": 1.0, "clarify": 0.0, "reject": 0.0}}, None, 0.0, {}
        return super()._decide(state, questions)


def test_words_the_checks_cannot_place_go_to_review(graph):
    out = Pipeline(graph).run(ConfidentGate(), "Benzene and CO2 by country and year")
    assert out["outcome"] == "review"
    assert out["query"]["pollutants"] == ["CO2"]
    assert any("benzene" in reason for reason in out["review"])


def test_no_data_is_only_reported_when_the_query_was_confident(graph):
    text = "I would like to obtain data about CO2, NOx and NO2 for each region, month and subsector"
    assert Pipeline(graph).run(CatalogueBackend(), text)["outcome"] == "no_data"
    out = Pipeline(graph).run(UniformBackend(), text)
    assert out["outcome"] == "review" and not out.get("solutions")
    assert "no combination" in out["message"].lower()


@pytest.mark.parametrize("text", ["N2O emissions from soil management by country and year",
                                  "CO2 by country and year to check our forecasts"])
def test_judgements_are_left_to_the_model(text):
    # Neither is a fact about the catalogue, so the checks must not reject it outright.
    assert resolve(text)["hard_reject"] is None


def test_rules_backend_still_rejects_forecasts_for_itself():
    assert resolve("CO2 forecast by country and year")["gate"] == "reject"
