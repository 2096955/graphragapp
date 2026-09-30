import pytest
from conftest import OracleBackend
from fastapi.testclient import TestClient

from app import main
from app.testset import build, TASKS


@pytest.fixture(scope="module")
def client():
    main.backends["oracle"] = OracleBackend()
    with TestClient(main.app) as c:
        yield c
    main.backends.pop("oracle", None)


def test_health(client):
    h = client.get("/api/health").json()
    assert h["ok"] and h["items"] == len(build()) and not h["auth_required"]
    by = {b["name"]: b for b in h["backends"]}
    assert by["catalogue"]["available"] and by["uniform"]["available"] and not by["jev"]["available"]


def test_decide_and_errors(client):
    q = {"q": {"type": "choice", "instructions": "Pick", "criteria": {"a": None, "b": None}}}
    r = client.post("/api/decide", json={"backend": "uniform", "state": {"x": 1}, "questions": q})
    assert r.status_code == 200 and r.json()["answers"]["q"]["probabilities"] == {"a": 0.5, "b": 0.5}
    assert client.post("/api/decide", json={"backend": "nope", "state": 1, "questions": q}).status_code == 404
    assert client.post("/api/decide", json={"backend": "jev", "state": 1, "questions": q}).status_code == 503
    bad = {"q": {"type": "choice", "criteria": {"a": None}}}
    assert client.post("/api/decide", json={"backend": "uniform", "state": 1, "questions": bad}).status_code == 422
    assert client.post("/api/decide", json={"backend": "uniform", "state": "x" * 5000, "questions": q}).status_code == 413


def test_compare_reports_each_backend(client):
    q = {"q": {"type": "noul", "instructions": "Yes?"}}
    res = client.post("/api/compare", json={"backends": ["uniform", "jev"], "state": "s", "questions": q}).json()["results"]
    assert res[0]["answers"]["q"]["noul"] == 0.5 and "error" in res[1]


def test_pipeline_endpoint(client):
    r = client.post("/api/pipeline", json={"backend": "oracle", "request": "Particulate matter by region",
                                           "preference": "Italian regions"})
    body = r.json()
    assert r.status_code == 200 and body["outcome"] == "answer"
    assert body["query"] == {"pollutants": ["PM2_5", "PM10"], "levels": {"GEO": "region"}, "filters": {}}
    assert body["subgraph"]["nodes"]


def test_catalogue_and_testset(client):
    cat = client.get("/api/catalogue").json()
    assert len(cat["pollutants"]) == 24 and len(cat["sources"]) == 8
    ts = client.get("/api/testset").json()
    assert len(ts["items"]) == len(build()) and set(ts["tasks"]) == set(TASKS)


def test_catalogue_pipeline_endpoint_needs_no_key(client):
    r = client.post("/api/pipeline", json={"backend": "catalogue", "request": "Annual CO2 for Australia in 2024"})
    body = r.json()
    assert r.status_code == 200 and body["outcome"] == "answer"
    assert "CO2" in body["query"]["pollutants"]


def test_pages_link_to_each_other(client):
    lab = client.get("/")
    assert lab.status_code == 200 and "GraphRAG Decisions Lab" in lab.text
    assert "not measured here" in lab.text
    assert 'href="field-guide.html"' in lab.text and 'href="small-world.html"' in lab.text
    for path in ("/field-guide", "/field-guide.html"):
        guide = client.get(path)
        assert guide.status_code == 200 and "Graphs for agent context" in guide.text
        assert "Jev is the typed decision layer" in guide.text and "/api/compare" in guide.text
        assert "Neo4j" in guide.text and "Kuzu" in guide.text
        assert "field-guide_files" not in guide.text
        assert 'href="index.html"' in guide.text and 'href="small-world.html"' in guide.text
    for path in ("/small-world", "/small-world.html"):
        world = client.get(path)
        assert world.status_code == 200 and "Watts" in world.text
        assert 'href="field-guide.html' in world.text
    assert client.get("/index.html").status_code == 200


def test_eval_off_without_token(client):
    r = client.post("/api/eval", json={"backend": "uniform"})
    assert r.status_code == 403


def test_token_and_rate_limit(client, monkeypatch):
    monkeypatch.setattr(main, "settings", main.settings.__class__(**{**main.settings.__dict__, "api_token": "t0k",
                                                                      "rate_limit_per_minute": 3}))
    main._hits.clear()
    q = {"q": {"type": "noul"}}
    assert client.post("/api/decide", json={"backend": "uniform", "state": 1, "questions": q}).status_code == 401
    h = {"Authorization": "Bearer t0k"}
    codes = [client.post("/api/decide", headers=h, json={"backend": "uniform", "state": 1, "questions": q}).status_code
             for _ in range(4)]
    assert codes[:2] == [200, 200] and codes[-1] == 429
    main._hits.clear()


def test_eval_job_runs(client, monkeypatch):
    monkeypatch.setattr(main, "settings", main.settings.__class__(**{**main.settings.__dict__, "eval_enabled": True}))
    r = client.post("/api/eval", json={"backend": "uniform", "tasks": ["gate"], "limit": 5})
    assert r.status_code == 200
    jid = r.json()["id"]
    import time
    for _ in range(50):
        st = client.get(f"/api/eval/{jid}").json()
        if st["state"] != "running":
            break
        time.sleep(0.1)
    assert st["state"] == "finished" and st["done"] == 5 and st["result"] == "uniform-partial.json"
