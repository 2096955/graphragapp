import os

import pytest
from fastapi.testclient import TestClient

from app import main, retrieval
from app.claims import (ClaimsLab, LabelsBackend, candidate_pairs, check, claim_records, gold_claims,
                        most_common_baseline, quote_in_document, rule_answer, score, shift_pairs)
from app.claims_corpus import DOC, EXTRACTED
from app.claims_graph import ClaimsGraph
from app.claims_labels import QUESTIONS, SAME_YES, SHIFT, SUPPORTS
from app.decisions import CatalogueBackend, UniformBackend
from app.decisions.base import Backend, DecisionError


class BrokenBackend(Backend):
    name = "broken"

    def __init__(self):
        super().__init__("broken")

    def _decide(self, state, questions):
        raise DecisionError("backend down")


@pytest.fixture
def lab():
    lab = ClaimsLab(ClaimsGraph(engine="kuzu"))
    yield lab
    lab.store.close()


# ---------------------------------------------------------------------------- corpus and labels
def test_quotes_are_verbatim_except_the_planted_one():
    bad = [cid for cid, doc, *_rest, quote in EXTRACTED if not quote_in_document(quote, doc)]
    assert bad == ["X03"]


def test_pairs_match_the_labels():
    good = gold_claims()
    assert [c["id"] for c in good] == sorted(c["id"] for c in good) and len(good) == 20
    pairs = candidate_pairs(good)
    assert len(pairs) == 39
    assert {frozenset(p) for p in pairs} >= SAME_YES and len(SAME_YES) == 4
    assert set(shift_pairs(good)) == set(SHIFT)
    assert set(SUPPORTS) == {c["id"] for c in claim_records()} - {"X03"}


def test_corpus_is_invented():
    names = " ".join(d["text"] for d in DOC.values())
    for real in ("APRA", "ASIC", "OAIC", "Reserve Bank", "Australian Prudential"):
        assert real not in names


# ---------------------------------------------------------------------------- building
def test_rules_build_rejects_planted_errors_and_is_never_unsure(lab):
    out = lab.build(CatalogueBackend())
    rejected = {r["claim"]: r["why"] for r in out["rejected"]}
    assert "quote is not in the document" in rejected["X03"]
    assert {"X01", "X02"} <= set(rejected)
    assert out["review"] == []
    assert all(d["confidence"] == 1.0 for d in out["decisions"] if d["kind"] != "quote_check")


def test_labels_build_is_the_correct_graph(lab):
    out = lab.build(LabelsBackend())
    assert out["counts"]["Claim"] == 20 and out["counts"]["SAME_AS"] == 4 and out["counts"]["SHIFT"] == 9
    steps = lab.timeline("oyelaran", "human-review")["steps"]
    assert [s["id"] for s in steps] == ["C01", "C05", "C11", "C17"]
    assert [s["change"] for s in steps] == [None, "stronger", "stronger", "same"]
    assert all(s["quote"] and s["title"] and s["date"] for s in steps)
    as_of = lab.timeline("castellane", "use", not_after="2025-01-01")
    assert [s["id"] for s in as_of["steps"]] == ["C07"] and as_of["as_of"] == "2025-01-01"
    people = lab.who(aspect="human-review")
    assert [p["name"] for p in people] == ["Nadia Oyelaran", "Tomas Fairweather", "Rafael Quist"]
    assert [c["id"] for c in lab.store.claims(aspect="register", publisher_kind="regulator")] == ["C02", "C12", "C18"]


def test_uncertain_decisions_wait_for_a_person(lab):
    out = lab.build(UniformBackend())
    assert out["counts"]["Claim"] == 0 and len(out["review"]) == 22
    first = lab.review[0]["id"]
    assert lab.resolve(first, accept=True)["counts"]["Claim"] == 1
    second = lab.review[0]["id"]
    assert lab.resolve(second, accept=False)["counts"]["Claim"] == 1
    with pytest.raises(KeyError):
        lab.resolve(second, accept=True)


class CountingUniform(UniformBackend):
    def __init__(self):
        super().__init__()
        self.asked = 0

    def _decide(self, state, questions):
        self.asked += 1
        return super()._decide(state, questions)


def test_an_accepted_claim_gets_its_own_questions(lab):
    backend = CountingUniform()
    lab.build(backend)
    assert backend.asked == 22 and len(lab.review) == 22
    lab.resolve("supports:C01", accept=True)
    assert backend.asked == 22, "a rebuild reuses the backend's earlier answers"
    lab.resolve("supports:C05", accept=True)
    # C05 now has an earlier claim on the same point by the same person, so both questions are asked.
    ids = {r["id"] for r in lab.review}
    assert {"same_claim:C01:C05", "shift:C01:C05"} <= ids and backend.asked == 24
    with pytest.raises(ValueError):
        lab.resolve("shift:C01:C05", accept=True, label="sideways")
    assert "shift:C01:C05" in {r["id"] for r in lab.review}, "a bad label leaves the item waiting"
    lab.resolve("shift:C01:C05", accept=True, label="stronger")
    assert [(s["label"], s["decided_by"]) for s in lab.store.shifts()] == [("stronger", "person")]
    lab.resolve("same_claim:C01:C05", accept=False)
    assert lab.store.same_pairs() == [] and lab.store.counts()["Claim"] == 2
    lab.build(backend)
    assert lab.person == {} and lab.store.counts()["Claim"] == 0, "a fresh build forgets a person's answers"


def test_failed_decisions_are_never_written(lab):
    out = lab.build(BrokenBackend())
    assert out["counts"]["Claim"] == 0
    assert all(d["action"] in ("review", "rejected") for d in out["decisions"])


# ---------------------------------------------------------------------------- labelled check
def test_check_scores_every_labelled_decision():
    rules = check(CatalogueBackend())
    assert rules["n"] == 70 and set(rules["summary"]) == {"supports", "same_claim", "shift"}
    assert rules["right"] < rules["n"], "the rules should not look perfect"
    uniform = check(UniformBackend())
    assert all(v["decided"] == 0 for v in uniform["summary"].values())
    # Every decision ends one of four ways, and they add up.
    for res in (rules, uniform):
        assert sum(res[k] for k in ("decided_right", "written_wrongly", "left_out_wrongly", "to_review")) == 70
    assert uniform["to_review"] == 70
    perfect = check(LabelsBackend())
    assert perfect["right"] == perfect["decided_right"] == 70 and perfect["written_wrongly"] == 0
    # A wrong change label is written, so it counts as false, not as left out.
    wrong_shift = [{"kind": "shift", "claims": ["C01", "C05"], "answer": "same", "confidence": 0.9}]
    assert score(wrong_shift)["written_wrongly"] == 1
    assert score([{**wrong_shift[0], "confidence": 0.5}])["to_review"] == 1
    assert most_common_baseline()["right"] == 59


def test_rules_are_generic():
    # Stronger wording is a different claim, and a claim that overstates its quote is not supported.
    assert rule_answer("same_claim", {"statement A": "Firms should keep a register of models.",
                                      "statement B": "Firms must keep a register of models."}) == "no"
    assert rule_answer("supports", {"claim": "Firms must keep a register of models.",
                                    "quote": "firms should keep a register of models"}) == "no"


# ---------------------------------------------------------------------------- retrieval
def test_plans_parse_people_publishers_aspects_and_dates():
    q = {x["id"]: x["question"] for x in QUESTIONS}
    assert retrieval.plan(q["R02"]) == {"kind": "timeline", "person": "oyelaran", "topic": "automated-declines",
                                        "aspect": "human-review"}
    assert retrieval.plan(q["R04"])["not_after"] == "2025-01-01"
    assert retrieval.plan(q["R06"])["publisher_kind"] == "regulator"
    assert not retrieval.plan(q["R10"]).get("aspect")


def test_graph_against_text_retrieval(lab):
    lab.build(LabelsBackend())
    res = retrieval.compare({"Graph": lab}, with_dense=False)
    assert res["methods"] == ["BM25", "Graph"]
    rows = {r["id"]: r["methods"] for r in res["questions"]}
    assert rows["R10"]["BM25"]["recall"] == 1.0 and rows["R10"]["Graph"]["recall"] == 0.0
    assert rows["R01"]["Graph"]["recall"] == 1.0 and rows["R02"]["Graph"]["recall"] == 1.0
    assert rows["R04"]["Graph"]["later_than_as_of"] == 0 and rows["R04"]["BM25"]["later_than_as_of"] > 0


def test_every_claim_maps_to_a_passage():
    for c in claim_records():
        if c["id"] != "X03":
            assert retrieval.claim_passages(c["quote"], c["document"]), c["id"]


# ---------------------------------------------------------------------------- API
def test_claims_api_without_keys():
    with TestClient(main.app) as client:
        body = client.get("/api/claims").json()
        assert body["built_with"] == "catalogue" and body["counts"]["Claim"] > 0
        who = client.get("/api/claims/who", params={"topic": "automated-declines"}).json()
        assert who["people"]
        assert client.get("/api/claims/who", params={"topic": "nope"}).status_code == 404
        assert client.get("/api/claims/timeline", params={"person": "nobody", "aspect": "use"}).status_code == 404
        s = client.get("/api/claims/search", params={"q": "climate scenarios", "method": "bm25", "k": 3}).json()
        assert s["results"][0]["id"] == "D08.1"
        g = client.get("/api/claims/search", params={"q": "What have regulators said about keeping a register of "
                                                          "models?", "method": "graph"}).json()
        assert g["plan"]["publisher_kind"] == "regulator"
        assert client.get("/api/claims/search", params={"q": "x", "method": "psychic"}).status_code == 422
        built = client.post("/api/claims/build", json={"backend": "uniform"}).json()
        assert built["counts"]["Claim"] == 0 and len(built["review"]) == 22
        item = built["review"][0]["id"]
        assert client.post("/api/claims/review", json={"id": item, "accept": True}).json()["counts"]["Claim"] == 1
        assert client.post("/api/claims/review", json={"id": "nope", "accept": True}).status_code == 404
        chk = client.post("/api/claims/check", json={"backend": "catalogue"}).json()
        assert chk["n"] == 70 and chk["decided_right"] + chk["written_wrongly"] + chk["left_out_wrongly"] == 70
        client.post("/api/claims/build", json={"backend": "catalogue"})
        assert client.get("/api/health").json()["claims"]["Claim"] > 0


PAGE_TIMELINES = [("oyelaran", "human-review"), ("oyelaran", "register"), ("castellane", "use"),
                  ("quist", "human-review"), ("fairweather", "human-review")]
PAGE_POINTS = ["human-review", "register", "accountability", "use", "notice", "explanation"]


def _fingerprint(lab: ClaimsLab) -> dict:
    """Everything the page and the API show from one build."""
    return {"counts": lab.store.counts(), "rejected": lab.last["rejected"], "review": [r["id"] for r in lab.review],
            "claims": lab.store.claims(),
            "who": {a: lab.who(aspect=a) for a in PAGE_POINTS},
            "timelines": {f"{p}|{a}": lab.timeline(p, a) for p, a in PAGE_TIMELINES},
            "as_of": lab.timeline("castellane", "use", "2025-01-01"),
            "same": sorted((x["a"], x["b"], x["confidence"], x["decided_by"]) for x in lab.store.same_pairs()),
            "shifts": sorted((x["earlier"], x["later"], x["label"], x["confidence"], x["decided_by"])
                             for x in lab.store.shifts()),
            "regulators": [c["id"] for c in lab.store.claims(aspect="register", publisher_kind="regulator")]}


# A FalkorDB server for this test only: the lab's own FALKORDB_URL is never touched by the tests.
TEST_URL = os.environ.get("TEST_FALKORDB_URL") or None


@pytest.mark.skipif(not (TEST_URL or __import__("importlib").util.find_spec("redislite")),
                    reason="needs TEST_FALKORDB_URL or falkordblite (Python 3.12+)")
def test_falkordb_gives_the_same_graph():
    for backend in (LabelsBackend(), CatalogueBackend(), UniformBackend()):
        results = []
        for engine in ("falkordb", "kuzu"):
            lab = ClaimsLab(ClaimsGraph(engine=engine, url=TEST_URL if engine == "falkordb" else None,
                                        name="graphs_lab_claims_test"))
            try:
                lab.build(backend)
                if backend.name == "uniform":            # a person's answers, and the rebuilds they cause
                    for item in ("supports:C01", "supports:C05", "shift:C01:C05"):
                        lab.resolve(item, accept=True, label="stronger" if item.startswith("shift") else None)
                results.append(_fingerprint(lab))
            finally:
                lab.store.close()
        assert results[0] == results[1], backend.name


def test_unreachable_falkordb_falls_back_to_kuzu_only_on_auto():
    g = ClaimsGraph(engine="auto", url="redis://127.0.0.1:1")
    try:
        assert g.engine == "kuzu" and "not usable" in g.detail
        assert "127.0.0.1" not in g.detail   # a URL can hold a password, so it is never shown
    finally:
        g.close()
    with pytest.raises(RuntimeError, match="not usable"):
        ClaimsGraph(engine="falkordb", url="redis://127.0.0.1:1")
