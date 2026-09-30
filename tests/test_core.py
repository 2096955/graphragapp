import json
import math
from dataclasses import replace

import httpx
import pytest
from conftest import OracleBackend

from app import domain as d
from app import evaluation as ev
from app.config import Settings
from app.decisions import DecisionError, JevBackend, UniformBackend, build_backends, labels, validate_questions
from app.graph import Graph
from app.pipeline import Pipeline, lexical_candidates
from app.testset import REQUESTS, TASKS, build, gold_query


@pytest.fixture(scope="module")
def graph():
    return Graph()


# ------------------------------------------------------------------ test set
def test_items_are_well_formed():
    items = build()
    assert len({i["id"] for i in items}) == len(items)
    for it in items:
        q = it["questions"][it["question"]]
        validate_questions(it["questions"])
        assert it["gold"] in labels(q), it["id"]
        assert it["task"] in TASKS


def test_task_sizes_and_balance():
    items = build()
    count = lambda task, gold=None: sum(1 for i in items if i["task"] == task and (gold is None or i["gold"] == gold))  # noqa: E731
    assert count("gate") == 61 and count("gate", "answer") == 31 and count("gate", "clarify") == 16 and count("gate", "reject") == 14
    assert count("level") == 93 and count("relevance") == 132 and count("entity") == 82 and count("mapping") == 80
    assert count("relevance", "yes") == 53 and count("entity", "yes") == 49


def test_paper_requests_included_verbatim():
    paper = [r for r in REQUESTS if r[0].startswith("P")]
    assert len(paper) == 22
    assert paper[11][1] == "I want to aanlyse air pollution aggregated by region, month and sector"  # typo kept as published


# ------------------------------------------------------------------ graph
def test_graph_counts(graph):
    c = graph.counts()
    assert c["Pollutant"] == 24 and c["Source"] == 8 and c["Level"] == 7


def test_discovery_is_minimal_and_rolls_up(graph):
    sols = graph.discover(["PM2_5", "PM10"], {"GEO": "country", "TIME": "year"})
    ids = [[s["id"] for s in sol["sources"]] for sol in sols]
    assert ids == [["S3"], ["S4"], ["S6"]]          # S4 is regional and monthly: it rolls up
    s4 = sols[1]["profiles"]["GEO.country"]
    assert set(s4) <= {"Italy", "France", "Germany", "Spain"}
    for sol in graph.discover(["CH4", "PM2_5"], {"GEO": "country", "TIME": "year"}):
        assert len(sol["sources"]) == 2              # no single source holds both


def test_discovery_respects_levels(graph):
    # Country-level sources roll up to continent, so NOx by continent is answerable...
    assert graph.discover(["NOx"], {"GEO": "continent", "TIME": "year", "SECTOR": "macrosector"})
    # ...but nothing can drill down: only S4 is regional, and it holds no methane or ammonia by month.
    assert graph.discover(["CH4"], {"GEO": "region"}) == []
    assert graph.discover(["NH3"], {"TIME": "month"}) == []


def test_histogram_intersection_takes_the_minimum(graph):
    sol = graph.discover(["CH4", "PM2_5"], {"GEO": "country", "TIME": "year"})[0]
    a = graph.profile(sol["sources"][0]["id"], "GEO", "country")
    b = graph.profile(sol["sources"][1]["id"], "GEO", "country")
    for m, v in sol["profiles"]["GEO.country"].items():
        assert v == min(a[m], b[m])


def test_roll_up_helpers():
    assert d.roll_up("GEO", "region", "Lombardy", "continent") == "Europe"
    assert d.roll_up("TIME", "month", "2024-03", "year") == "2024"
    assert d.roll_up("SECTOR", "subsector", "Aviation", "macrosector") == "Transportation"
    assert d.roll_up("GEO", "country", "Italy", "region") is None


# ------------------------------------------------------------------ pipeline
def test_graph_first_cut_finds_named_pollutants():
    for r in REQUESTS:
        if r[2] == "answer" and isinstance(r[3], list) and len(r[3]) <= 3:
            found = {p for p, _ in lexical_candidates(r[1])}
            assert set(r[3]) <= found, r[0]


def test_pipeline_recovers_every_labelled_query(graph):
    pipe, oracle = Pipeline(graph), OracleBackend()
    for r in REQUESTS:
        out = pipe.run(oracle, r[1], "European countries, recent years")
        if r[2] != "answer":
            assert out["outcome"] == r[2], r[0]
            continue
        gq = gold_query(r[0])
        assert out["query"]["pollutants"] == gq["pollutants"], r[0]
        assert out["query"]["levels"] == gq["levels"], r[0]
        # A perfect model is only sent to review for words the checks cannot place (typos here).
        assert out["outcome"] in ("answer", "no_data", "review"), r[0]
        if out["outcome"] == "review":
            assert all(x.startswith("Words the catalogue checks could not place") for x in out["review"]), r[0]


def test_pipeline_explains_ranked_solutions(graph):
    out = Pipeline(graph).run(OracleBackend(), "Find particulate matter emissions in datasets with continents and years",
                              "European countries")
    assert out["outcome"] == "answer" and out["solutions"]
    assert out["explanation"]["by"] == "template" and out["solutions"][0]["id"] in out["explanation"]["text"]
    assert out["totals"]["calls"] == 3 + len(out["solutions"])


# ------------------------------------------------------------------ backends
def test_uniform_backend():
    res = UniformBackend().decide({"x": 1}, {"q": {"type": "choice", "criteria": {"a": None, "b": None, "c": None}}})
    assert res.answers["q"].probabilities == pytest.approx({"a": 1 / 3, "b": 1 / 3, "c": 1 / 3})


def test_validation_rejects_bad_questions():
    with pytest.raises(DecisionError):
        validate_questions({"q": {"type": "choice", "criteria": {"only": None}}})
    with pytest.raises(DecisionError):
        validate_questions({"q": {"type": "score", "criteria": ["one"]}})
    with pytest.raises(DecisionError):
        validate_questions({"q": {"type": "maybe"}})
    with pytest.raises(DecisionError):
        validate_questions({"q": {"type": "choice", "criteria": {chr(65 + i): None for i in range(27)}}})


def test_jev_wire_format_round_trip():
    seen = {}

    def handler(request: httpx.Request):
        seen["auth"] = request.headers["authorization"]
        seen["path"] = request.url.path
        body = json.loads(request.content)
        seen["body"] = body
        return httpx.Response(200, json={
            "model": "jev-1.13.0",
            "answers": {"rel": {"type": "noul", "noul": 0.9},
                        "gate": {"type": "choice", "choice": "answer", "confidence": 0.8,
                                 "probabilities": {"answer": 0.8, "clarify": 0.15, "reject": 0.05}},
                        "fit": {"type": "score", "score": 1.7, "confidence": 0.7, "legend": {"0": "a", "1": "b", "2": "c"},
                                "probabilities": {"0": 0.1, "1": 0.1, "2": 0.8}}},
            "usage": {"input_tokens": 1000, "output_tokens": 3}})

    jev = JevBackend("key-123", transport=httpx.MockTransport(handler))
    qs = {"rel": {"type": "noul", "instructions": "Is it?"},
          "gate": {"type": "choice", "instructions": "Which?", "criteria": {"answer": "x", "clarify": None, "reject": None}},
          "fit": {"type": "score", "instructions": "How well?", "criteria": ["a", "b", "c"]}}
    res = jev.decide({"request": "hi"}, qs)
    assert seen["auth"] == "Bearer key-123" and seen["path"] == "/v1/systemone"
    assert seen["body"]["model"] == "jev-latest" and seen["body"]["questions"]["rel"] == {"type": "noul", "instructions": "Is it?"}
    assert res.answers["rel"].probabilities == pytest.approx({"yes": 0.9, "no": 0.1})
    assert res.answers["gate"].top == "answer" and res.answers["fit"].top == "2"
    assert res.cost_usd == pytest.approx(1000 * 0.042 / 1e6) and res.residency == "hosted"


def test_jev_without_key_is_unavailable():
    ok, why = JevBackend(None).available()
    assert not ok and "TYPESAFE_API_KEY" in why
    ok, why = JevBackend(None, provider="openrouter").available()
    assert not ok and "OPENROUTER_API_KEY" in why


def test_jev_through_openrouter(monkeypatch):
    """OpenRouter's Decisions API: same request and answers, its own URL, model alias and reported cost."""
    seen, calls = {}, []
    monkeypatch.setattr("app.decisions.backends.time.sleep", lambda s: calls.append(s))

    def handler(request: httpx.Request):
        calls.append(str(request.url))
        if len(calls) == 1:
            return httpx.Response(529, headers={"retry-after": "1"})   # overloaded: retried
        seen["auth"], seen["body"] = request.headers["authorization"], json.loads(request.content)
        return httpx.Response(200, json={"model": "typesafe/jev-1.13", "answers": {"rel": {"type": "noul", "noul": 0.25}},
                                         "usage": {"input_tokens": 400, "output_tokens": 1, "cost": 0.0000168}})

    jev = JevBackend("or-key", transport=httpx.MockTransport(handler), provider="openrouter")
    res = jev.decide({"request": "hi"}, {"rel": {"type": "noul", "instructions": "Is it?"}})
    assert calls[0] == "https://openrouter.ai/api/alpha/decisions" and calls[1] == 1.0
    assert seen["auth"] == "Bearer or-key" and seen["body"]["model"] == "~typesafe/jev-latest"
    assert res.answers["rel"].probabilities == pytest.approx({"yes": 0.25, "no": 0.75})
    assert res.cost_usd == pytest.approx(0.0000168) and res.detail["cost_source"] == "reported"
    assert res.detail["via"] == "openrouter" and res.detail["served_by"] == "typesafe/jev-1.13"
    with pytest.raises(ValueError):
        JevBackend("k", provider="elsewhere")


def test_jev_provider_follows_the_keys(monkeypatch):
    for k in ("TYPESAFE_API_KEY", "OPENROUTER_API_KEY", "JEV_PROVIDER", "JEV_MODEL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "or")
    s = Settings.from_env()
    assert (s.jev_provider, s.jev_model) == ("openrouter", "~typesafe/jev-latest")
    for typesafe_name, openrouter_name in (("jev-latest", "~typesafe/jev-latest"), ("jev-1.13", "typesafe/jev-1.13"),
                                           ("typesafe/jev-1.13", "typesafe/jev-1.13")):
        monkeypatch.setenv("JEV_MODEL", typesafe_name)
        assert Settings.from_env().jev_model == openrouter_name
    monkeypatch.delenv("JEV_MODEL")
    monkeypatch.setenv("TYPESAFE_API_KEY", "ts")        # both keys: TypeSafe's own API first
    s = Settings.from_env()
    assert (s.jev_provider, s.jev_model) == ("typesafe", "jev-latest")
    monkeypatch.setenv("JEV_PROVIDER", "openrouter")
    assert Settings.from_env().jev_provider == "openrouter"
    jev = build_backends(replace(Settings.from_env(), backends=["jev"]))["jev"]
    assert jev.available()[0] and jev.provider == "openrouter"


def test_jev_errors_are_reported():
    jev = JevBackend("k", transport=httpx.MockTransport(lambda r: httpx.Response(401, json={"detail": "bad key"})))
    with pytest.raises(DecisionError, match="401"):
        jev.decide({"s": 1}, {"q": {"type": "noul"}})


# ------------------------------------------------------------------ metrics
def _rec(conf, correct, gold="a"):
    wrong = "b" if gold == "a" else "a"
    top = gold if correct else wrong
    rest = wrong if correct else gold
    return {"task": "gate", "gold": gold, "top": top, "confidence": conf, "correct": correct,
            "probs": {top: conf, rest: 1 - conf}, "latency_ms": 1.0}


def test_ece_perfect_and_overconfident():
    calibrated = [_rec(0.8, i < 8) for i in range(10)]
    assert ev.ece(calibrated) == pytest.approx(0.0)
    over = [_rec(0.95, i < 5) for i in range(10)]
    assert ev.ece(over) == pytest.approx(0.45)


def test_coverage_at_risk():
    recs = [_rec(0.99, True) for _ in range(19)] + [_rec(0.98, False)] + [_rec(0.6, False) for _ in range(5)]
    cov = ev.coverage_at_risk(recs, 0.05)
    assert cov["coverage"] == pytest.approx(20 / 25) and cov["threshold"] == pytest.approx(0.98)


def test_temperature_scaling_fixes_overconfidence():
    recs = [_rec(0.99, i % 2 == 0) for i in range(40)]
    fixed, temps = ev.recalibrated(recs)
    assert ev.ece(fixed) < ev.ece(recs) and all(t > 1 for t in temps)


def test_clean_removes_nan():
    assert ev.clean({"a": float("nan"), "b": [1.0, math.inf]}) == {"a": None, "b": [1.0, None]}
