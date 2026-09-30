"""MCP server for the lab: typed decisions, dataset discovery and the claims graph, from your editor.

A thin layer over the lab's HTTP API, so it works against a lab running anywhere and loads no
models itself. It needs only `httpx` and the MCP SDK (`pip install -r requirements-mcp.txt`).

    LAB_URL=http://localhost:8000 python app/mcp_server.py        # stdio, for Claude Code or Cursor

    claude mcp add graphs-lab -e LAB_URL=http://localhost:8000 -- python /path/to/repo/app/mcp_server.py

Set API_TOKEN as well if the lab requires one. The token stays in the environment of this
process; it is never passed to the model.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

try:  # MCP SDK 2.x
    from mcp.server import MCPServer
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:  # MCP SDK 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer
    from mcp.server.fastmcp.exceptions import ToolError

INSTRUCTIONS = (
    "Tools for a lab that pairs a knowledge graph with typed decision models. Use `decide` or `compare` to "
    "ask a typed question (yes/no, choice or score) and get a probability per answer. Use `discover` to find "
    "datasets in the lab's synthetic emissions catalogue. Use `claims_who`, `claims_timeline` and `search` for "
    "the claims graph: who said what, where and when, in a corpus of invented regulator publications. Treat "
    "any answer below 0.8 confidence as needing a person."
)


def _client_from_env() -> httpx.Client:
    headers = {}
    token = (os.environ.get("API_TOKEN") or "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return httpx.Client(base_url=os.environ.get("LAB_URL", "http://localhost:8000").rstrip("/"),
                        headers=headers, timeout=180.0)


def build_server(client: httpx.Client | None = None) -> Any:
    """The MCP server. Pass an httpx client to point it at a particular lab (tests pass the app's)."""
    http = client or _client_from_env()
    server = MCPServer("graphs-lab", instructions=INSTRUCTIONS)

    def get(path: str, **params) -> Any:
        r = http.get(path, params={k: v for k, v in params.items() if v is not None})
        return _json(r)

    def post(path: str, body: dict) -> Any:
        return _json(http.post(path, json=body))

    @server.tool()
    def health() -> dict:
        """Which decision backends the lab has, whether each is available and why not, and graph sizes."""
        h = get("/api/health")
        return {"version": h.get("version"), "backends": [{k: b.get(k) for k in ("name", "label", "available", "reason")}
                                                         for b in h.get("backends", [])],
                "graph": h.get("graph"), "claims": h.get("claims")}

    @server.tool()
    def decide(backend: str, state: dict, questions: dict) -> dict:
        """Ask one decision backend typed questions about a state.

        questions maps a name to a question in Jev's format, for example
        {"same": {"type": "noul", "instructions": "Do the two names refer to the same country?"}} or
        {"kind": {"type": "choice", "instructions": "...", "criteria": {"a": "...", "b": "..."}}}.
        Backends: catalogue (rules, no keys), laya, laya-typed, anyjev, jev, uniform.
        Returns a probability for every permitted answer, the top answer and its confidence."""
        return post("/api/decide", {"backend": backend, "state": state, "questions": questions})

    @server.tool()
    def compare(backends: list[str], state: dict, questions: dict) -> dict:
        """Ask the same typed questions of up to four decision backends and return every answer."""
        return post("/api/compare", {"backends": backends, "state": state, "questions": questions})

    @server.tool()
    def discover(request: str, preference: str | None = None, backend: str = "catalogue") -> dict:
        """Find datasets for a data request in the lab's synthetic emissions catalogue, for example
        "Annual CO2 for Australia in 2024". Returns the outcome (answer, review, clarify, reject or
        no_data), the query the model settled on, the top-ranked source sets and any review reasons."""
        r = post("/api/pipeline", {"backend": backend, "request": request, "preference": preference})
        return {k: r.get(k) for k in ("outcome", "message", "query", "review", "explanation")} | {
            "solutions": [{k: s.get(k) for k in ("id", "sources", "summary", "cells")}
                          for s in (r.get("solutions") or [])[:3]]}

    @server.tool()
    def claims_who(topic: str | None = None, aspect: str | None = None, publisher_kind: str | None = None) -> dict:
        """Everyone in the claims graph who has said something about a topic or aspect, with each claim's
        quote, document and date. Topics: automated-declines, model-register, vendor-models,
        genai-customer-data. Aspects: human-review, explanation, register, accountability, use, notice.
        publisher_kind: regulator, industry body or consumer group."""
        return get("/api/claims/who", topic=topic, aspect=aspect, publisher_kind=publisher_kind)

    @server.tool()
    def claims_timeline(person: str, aspect: str, as_of: str | None = None) -> dict:
        """One person's claims on one aspect, oldest first, with how each changed their position (same,
        stronger, weaker or opposite). People: oyelaran, fairweather, castellane, quist, okafor-lane.
        as_of (YYYY-MM-DD) leaves out anything said later."""
        return get("/api/claims/timeline", person=person, aspect=aspect, as_of=as_of)

    @server.tool()
    def search(question: str, method: str = "graph", k: int = 10) -> dict:
        """Answer a question from the claims corpus. method: graph (claims with who said them and when),
        hybrid (BM25 plus dense), bm25 or dense. Returns passages with their publisher, speaker and date."""
        return get("/api/claims/search", q=question, method=method, k=k)

    return server


def _json(r: httpx.Response) -> Any:
    if r.status_code >= 400:
        try:
            detail = r.json().get("detail")
        except ValueError:
            detail = r.text[:300]
        raise ToolError(f"The lab returned HTTP {r.status_code}: {detail}")
    return r.json()


if __name__ == "__main__":
    build_server().run()
