from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app import main
from app.compliance import FIRST_PAYLOAD, REPEAT_PAYLOAD, classify, filter_payload
from app.compliance_graph import ComplianceGraph
from app.config import Settings
from app.decisions import CatalogueBackend


PROD_HASH_KEY = "k" * 48


def _clear(monkeypatch):
    for name in (
        "APP_ENV",
        "API_TOKEN",
        "COMPLIANCE_HASH_KEY",
        "COMPLIANCE_DB_PATH",
        "ENABLE_COMPLIANCE",
        "ENABLE_DOCS",
        "ENABLE_DEMO_ENDPOINTS",
        "EVAL_ENABLED",
        "ALLOW_HOSTED_COMPLIANCE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_production_requires_api_token(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("COMPLIANCE_HASH_KEY", PROD_HASH_KEY)
    with pytest.raises(RuntimeError, match="API_TOKEN"):
        Settings.from_env()


def test_production_requires_strong_compliance_hash_key(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_TOKEN", "service-token")
    monkeypatch.setenv("COMPLIANCE_HASH_KEY", "too-short")

    # ENABLE_COMPLIANCE defaults off in production, so a short key is allowed.
    settings = Settings.from_env()
    assert not settings.compliance_enabled

    monkeypatch.setenv("ENABLE_COMPLIANCE", "true")
    with pytest.raises(RuntimeError, match="COMPLIANCE_HASH_KEY"):
        Settings.from_env()


def test_production_defaults_are_safe(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("API_TOKEN", "service-token")
    monkeypatch.setenv("COMPLIANCE_HASH_KEY", PROD_HASH_KEY)
    settings = Settings.from_env()
    assert settings.production
    assert not settings.eval_enabled
    assert not settings.enable_docs
    assert not settings.enable_demo_endpoints
    assert not settings.allow_hosted_compliance
    assert settings.compliance_db_path == "data/compliance.kuzu"
    assert not settings.compliance_hash_key_ephemeral


def test_compliance_identity_is_keyed():
    a = classify(FIRST_PAYLOAD, "a" * 32)
    b = classify(FIRST_PAYLOAD, "b" * 32)
    repeat = classify(REPEAT_PAYLOAD, "a" * 32)
    assert a["pattern_id"] != b["pattern_id"]
    assert a["pattern_id"] == repeat["pattern_id"]
    assert "alex.rivera@example.test" not in a["pattern_id"]


def test_persistent_compliance_graph_reopens_without_reset(tmp_path):
    path = tmp_path / "compliance.kuzu"
    first = ComplianceGraph(path)
    try:
        out = filter_payload(CatalogueBackend(), FIRST_PAYLOAD, first, hash_key=PROD_HASH_KEY)
        assert out["pattern"]["attempts"] == 1
        assert first.counts()["Attempt"] == 1
    finally:
        first.close()

    reopened = ComplianceGraph(path)
    try:
        assert reopened.counts()["Attempt"] == 1
        out = filter_payload(CatalogueBackend(), REPEAT_PAYLOAD, reopened, hash_key=PROD_HASH_KEY)
        assert out["pattern"]["attempts"] == 2
    finally:
        reopened.close()


def test_production_internal_reads_require_auth_and_demo_is_disabled(monkeypatch):
    prod = replace(
        main.settings,
        environment="production",
        api_token="service-token",
        compliance_hash_key=PROD_HASH_KEY,
        compliance_hash_key_ephemeral=False,
        enable_demo_endpoints=False,
        eval_enabled=False,
        allow_hosted_compliance=False,
    )
    monkeypatch.setattr(main, "settings", prod)
    main._request_guard.clear()

    with TestClient(main.app) as client:
        assert client.get("/api/health").status_code == 200
        assert "backends" not in client.get("/api/health").json()
        assert client.get("/api/compliance/graph").status_code == 401

        headers = {"Authorization": "Bearer service-token"}
        assert client.get("/api/compliance/graph", headers=headers).status_code == 200
        demo = client.post(
            "/api/compliance/example",
            headers=headers,
            json={"backend": "catalogue"},
        )
        assert demo.status_code == 403
