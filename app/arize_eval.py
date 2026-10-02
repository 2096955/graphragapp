"""Arize eval and cost view for the compliance filter.

Send traces with register(space_id, api_key, project_name=...) or OTLP:
gRPC https://otlp.arize.com/v1 and HTTP https://otlp.arize.com/v1/traces.

Environment variables: ARIZE_SPACE_ID, ARIZE_API_KEY, ARIZE_PROJECT_NAME.
The signed-in space is named AzureDev. A key named graph-demo exists there
and must not be committed. This module never invents a key.

When those env vars are unset, the compliance example still runs and this
module returns the sample eval fixture plus locally recorded traces.
When they are set, traces go to Arize.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
SAMPLE_PATH = ROOT / "results" / "compliance-arize-sample.json"
OTLP_HTTP = "https://otlp.arize.com/v1/traces"
OTLP_GRPC = "https://otlp.arize.com/v1"
SPACE_NAME = "AzureDev"
REGISTER = "register(space_id, api_key, project_name=...)"


def load_sample() -> dict[str, Any]:
    if SAMPLE_PATH.exists():
        return json.loads(SAMPLE_PATH.read_text())
    return {
        "source": "sample",
        "project": "graphrag-compliance",
        "summary": {
            "decisions": 2,
            "filter_correct": 1.0,
            "cost_usd": 0.0,
            "note": (
                "Sample fixture. Catalogue mode costs $0. Set ARIZE_SPACE_ID, "
                "ARIZE_API_KEY and ARIZE_PROJECT_NAME to export live traces to space AzureDev."
            ),
        },
        "traces": [],
    }


class ArizeEval:
    """Collects filter traces. Exports to Arize only when both credentials are present."""

    def __init__(self, space_id: str | None, api_key: str | None, project: str = "graphrag-compliance",
                 endpoint: str = OTLP_HTTP, transport: httpx.BaseTransport | None = None):
        self.space_id = (space_id or "").strip() or None
        self.api_key = (api_key or "").strip() or None
        self.project = project
        self.endpoint = endpoint.rstrip("/")
        self._client = httpx.Client(timeout=8.0, transport=transport)
        self.traces: list[dict[str, Any]] = []
        self.last_export: dict[str, Any] | None = None

    @property
    def configured(self) -> bool:
        return bool(self.space_id and self.api_key)

    def reset(self) -> None:
        """Forget local traces. Used when the worked example rebuilds the graph."""
        self.traces.clear()
        self.last_export = None

    def record(self, trace: dict[str, Any]) -> dict[str, Any]:
        self.traces.append(trace)
        if self.configured:
            self.last_export = self._export(trace)
        return self.view()

    def wiring(self) -> dict[str, Any]:
        return {
            "space_name": SPACE_NAME,
            "project": self.project,
            "register": REGISTER,
            "otlp_http": OTLP_HTTP,
            "otlp_grpc": OTLP_GRPC,
            "env": ["ARIZE_SPACE_ID", "ARIZE_API_KEY", "ARIZE_PROJECT_NAME"],
            "key_name": "graph-demo",
            "key_committed": False,
        }

    def view(self) -> dict[str, Any]:
        local = self._summarise(self.traces)
        meta = self.wiring()
        if self.configured:
            return {
                "source": "live",
                "project": self.project,
                "configured": True,
                "exported": bool(self.last_export and self.last_export.get("ok")),
                "export": self.last_export,
                "summary": local,
                "traces": list(self.traces),
                **meta,
            }
        sample = load_sample()
        return {
            "source": "sample",
            "project": self.project,
            "configured": False,
            "exported": False,
            "summary": {**sample.get("summary", {}), **local,
                        "note": sample.get("summary", {}).get("note") or local.get("note")},
            "traces": list(self.traces) or sample.get("traces", []),
            "sample": sample,
            **meta,
        }

    def _summarise(self, traces: list[dict[str, Any]]) -> dict[str, Any]:
        if not traces:
            return {"decisions": 0, "filter_correct": None, "cost_usd": 0.0,
                    "note": "No filter traces yet. Run the compliance example."}
        n = len(traces)
        labelled = [t for t in traces if t.get("correct") is not None]
        right = sum(1 for t in labelled if t["correct"])
        cost = round(sum(float(t.get("cost_usd") or 0) for t in traces), 6)
        return {
            "decisions": n,
            "filter_correct": round(right / len(labelled), 4) if labelled else None,
            "cost_usd": cost,
            "note": (
                "Live Arize export is on." if self.configured
                else "Arize credentials are unset. Showing local traces plus the sample eval fixture. Catalogue mode costs $0."
            ),
        }

    @staticmethod
    def _attributes(trace: dict[str, Any]) -> list[dict[str, Any]]:
        attrs = [
            {"key": "filter.action", "value": {"stringValue": str(trace.get("action"))}},
            {"key": "filter.cost_usd", "value": {"doubleValue": float(trace.get("cost_usd") or 0)}},
            {"key": "filter.pattern_id", "value": {"stringValue": str(trace.get("pattern_id"))}},
            {"key": "filter.backend", "value": {"stringValue": str(trace.get("backend"))}},
        ]
        if trace.get("correct") is not None:
            attrs.append({"key": "filter.correct", "value": {"boolValue": bool(trace["correct"])}})
        return attrs

    def _export(self, trace: dict[str, Any]) -> dict[str, Any]:
        """OTLP-ish JSON body. Never called unless both credentials are set."""
        body = {
            "resourceSpans": [{
                "resource": {"attributes": [
                    {"key": "project.name", "value": {"stringValue": self.project}},
                    {"key": "arize.space_id", "value": {"stringValue": self.space_id}},
                ]},
                "scopeSpans": [{
                    "spans": [{
                        "name": trace.get("name") or "compliance.filter",
                        "attributes": self._attributes(trace),
                    }],
                }],
            }],
        }
        headers = {
            "Content-Type": "application/json",
            "space_id": self.space_id or "",
            "api_key": self.api_key or "",
            "Authorization": f"Bearer {self.api_key}",
        }
        try:
            resp = self._client.post(self.endpoint, json=body, headers=headers)
            return {"ok": resp.status_code < 300, "status": resp.status_code}
        except httpx.HTTPError as e:
            return {"ok": False, "status": 0, "error": type(e).__name__}
