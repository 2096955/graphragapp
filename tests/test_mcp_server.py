"""The MCP server exposes the lab's API as tools, against any lab address."""
import asyncio
import json

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("mcp")

from app import main  # noqa: E402
from app.mcp_server import build_server  # noqa: E402


def _call(server, name, args):
    result = asyncio.run(server.call_tool(name, args))
    if isinstance(result, tuple):          # SDK 1.x with structured output: (content, structured)
        result = result[0]
    content = getattr(result, "content", result)   # SDK 2.x returns a CallToolResult
    return json.loads(content[0].text)


@pytest.fixture(scope="module")
def server():
    with TestClient(main.app) as client:
        yield build_server(client)


def test_tools_are_listed_with_descriptions(server):
    tools = {t.name: t.description for t in asyncio.run(server.list_tools())}
    assert set(tools) == {"health", "decide", "compare", "discover", "claims_who", "claims_timeline", "search"}
    assert all(d and len(d) > 30 for d in tools.values())


def test_tools_call_the_lab(server):
    health = _call(server, "health", {})
    assert any(b["name"] == "catalogue" and b["available"] for b in health["backends"])
    decided = _call(server, "decide", {"backend": "catalogue", "state": {"request": "Annual CO2 for Australia in 2024"},
                                       "questions": {"gate": {"type": "choice", "instructions": "Can the catalogue answer it?",
                                                              "criteria": {"answer": None, "clarify": None, "reject": None}}}})
    assert decided["answers"]["gate"]["top"] == "answer"
    found = _call(server, "discover", {"request": "Annual CO2 for Australia in 2024"})
    assert found["outcome"] == "answer" and found["solutions"]
    tl = _call(server, "claims_timeline", {"person": "oyelaran", "aspect": "human-review"})
    assert tl["steps"]
    hits = _call(server, "search", {"question": "climate scenarios", "method": "bm25", "k": 3})
    assert hits["results"][0]["id"] == "D08.1"


def test_lab_errors_come_back_as_tool_errors(server):
    with pytest.raises(Exception, match="HTTP 404: Unknown person"):
        asyncio.run(server.call_tool("claims_timeline", {"person": "nobody", "aspect": "use"}))
