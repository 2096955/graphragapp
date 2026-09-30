"""HTTP API. Run with:  uvicorn app.main:app --host 0.0.0.0 --port 8000

Serves the Decisions Lab at / and the graph-database field guide at /field-guide.
The page and API share an origin. /api/compare is decision backends, not databases.
"""
from __future__ import annotations

import collections
import json
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import domain as d
from . import evaluation as ev
from .arize_eval import ArizeEval
from .compliance import filter_payload, run_example
from .compliance_graph import ComplianceGraph
from .watts_strogatz import example as watts_example
from .config import Settings
from .decisions import BackendUnavailable, DecisionError, build_backends
from .explain import Explainer
from .graph import Graph
from .pipeline import Pipeline
from .testset import TASKS, build

VERSION = "1.1.0"
ROOT = Path(__file__).resolve().parents[1]

settings = Settings.from_env()
graph = Graph()
compliance_graph = ComplianceGraph()
arize = ArizeEval(settings.arize_space_id, settings.arize_api_key, settings.arize_project,
                  settings.arize_endpoint)
backends = build_backends(settings)
explainer = Explainer(settings.llm_base_url, settings.llm_api_key, settings.llm_model)
pipeline = Pipeline(graph, explainer, settings.min_confidence)
ITEMS = build()



@asynccontextmanager
async def lifespan(_app):
    if settings.preload:
        def warm():
            for b in backends.values():
                if b.available()[0] and b.residency == "local":
                    try:
                        b.warm_up()
                    except Exception:  # noqa: BLE001 - reported through /api/health instead
                        pass
        threading.Thread(target=warm, daemon=True).start()
    yield


app = FastAPI(title="GraphRAG decisions", version=VERSION, docs_url="/api/docs", openapi_url="/api/openapi.json",
              lifespan=lifespan)
if settings.allowed_origins:
    app.add_middleware(CORSMiddleware, allow_origins=settings.allowed_origins, allow_methods=["GET", "POST"],
                       allow_headers=["Authorization", "Content-Type"])


# ------------------------------------------------------------------------------ guards
_hits: dict[str, collections.deque] = collections.defaultdict(collections.deque)
_hits_lock = threading.Lock()


def guard(request: Request) -> None:
    """Bearer token (when API_TOKEN is set) and a per-client rate limit on every POST."""
    if settings.api_token:
        auth = request.headers.get("authorization", "")
        if auth != f"Bearer {settings.api_token}":
            raise HTTPException(401, "Missing or wrong token. Send Authorization: Bearer <API_TOKEN>.")
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _hits_lock:
        q = _hits[ip]
        while q and now - q[0] > 60:
            q.popleft()
        if len(q) >= settings.rate_limit_per_minute:
            raise HTTPException(429, "Too many requests. Wait a minute and try again.")
        q.append(now)


def backend_or_404(name: str):
    if name not in backends:
        raise HTTPException(404, f"Unknown backend {name!r}. Available: {', '.join(backends)}")
    return backends[name]


def check_state(state: Any) -> None:
    if len(json.dumps(state, default=str)) > settings.max_state_chars:
        raise HTTPException(413, f"State is longer than {settings.max_state_chars} characters.")


@app.exception_handler(BackendUnavailable)
def _unavailable(_, e):
    return JSONResponse({"detail": str(e)}, status_code=503)


@app.exception_handler(DecisionError)
def _decision(_, e):
    return JSONResponse({"detail": str(e)}, status_code=422)


# ------------------------------------------------------------------------------ models
class DecideIn(BaseModel):
    backend: str
    state: Any
    questions: dict[str, dict]


class CompareIn(BaseModel):
    backends: list[str] = Field(min_length=1, max_length=4)
    state: Any
    questions: dict[str, dict]


class PipelineIn(BaseModel):
    backend: str
    request: str = Field(min_length=1, max_length=500)
    preference: str | None = Field(default=None, max_length=300)
    use_llm: bool = False


class EvalIn(BaseModel):
    backend: str
    tasks: list[str] | None = None
    limit: int = Field(default=0, ge=0, le=500)


class ComplianceFilterIn(BaseModel):
    backend: str = "catalogue"
    payload: str = Field(min_length=1, max_length=2000)


class ComplianceExampleIn(BaseModel):
    backend: str = "catalogue"


# ------------------------------------------------------------------------------ routes
@app.get("/api/health")
def health():
    return {"ok": True, "version": VERSION, "graph": graph.counts(), "backends": [b.status() for b in backends.values()],
            "auth_required": settings.api_token is not None, "eval_enabled": settings.eval_enabled,
            "llm_explainer": explainer.llm_available, "items": len(ITEMS),
            "compliance": compliance_graph.counts(),
            "arize": {"configured": arize.configured, "source": "live" if arize.configured else "sample",
                      **arize.wiring()}}


@app.get("/api/catalogue")
def catalogue():
    return {
        "pollutants": [{"id": p.id, "label": p.label, "name": p.name, "unit": p.unit, "groups": list(p.groups)} for p in d.POLLUTANTS],
        "groups": d.GROUPS, "dimensions": d.DIMENSIONS, "defaults": d.DEFAULT_LEVEL, "summary": d.CATALOGUE_SUMMARY,
        "sources": [{"id": s.id, "name": s.name, "description": s.description, "publisher": s.publisher, "updated": s.updated,
                     "levels": s.levels, "pollutants": s.pollutants,
                     "coverage": {k: [v[0], v[-1], len(v)] for k, v in s.coverage.items()},
                     "columns": [{"name": c.name, "maps_to": c.maps_to, "samples": c.samples} for c in s.columns]}
                    for s in d.SOURCES],
    }


@app.post("/api/decide", dependencies=[Depends(guard)])
def decide(body: DecideIn):
    check_state(body.state)
    return backend_or_404(body.backend).decide(body.state, body.questions).to_dict()


@app.post("/api/compare", dependencies=[Depends(guard)])
def compare(body: CompareIn):
    check_state(body.state)
    out = []
    for name in body.backends:
        b = backend_or_404(name)
        try:
            out.append(b.decide(body.state, body.questions).to_dict())
        except DecisionError as e:
            out.append({"backend": name, "error": str(e)})
    return {"results": out}


@app.post("/api/pipeline", dependencies=[Depends(guard)])
def run_pipeline(body: PipelineIn):
    return pipeline.run(backend_or_404(body.backend), body.request.strip(), (body.preference or "").strip() or None, body.use_llm)


@app.post("/api/compliance/filter", dependencies=[Depends(guard)])
def compliance_filter(body: ComplianceFilterIn):
    b = backend_or_404(body.backend)
    ok, why = b.available()
    if not ok:
        raise HTTPException(503, why)
    try:
        return filter_payload(b, body.payload.strip(), compliance_graph, arize)
    except ValueError as e:
        raise HTTPException(422, str(e)) from None


@app.post("/api/compliance/example", dependencies=[Depends(guard)])
def compliance_example(body: ComplianceExampleIn):
    b = backend_or_404(body.backend)
    ok, why = b.available()
    if not ok:
        raise HTTPException(503, why)
    return run_example(b, compliance_graph, arize)


@app.get("/api/compliance/graph")
def compliance_graph_view():
    return compliance_graph.snapshot()


@app.get("/api/compliance/eval")
def compliance_eval():
    return arize.view()


@app.get("/api/watts-strogatz")
def watts_strogatz_example():
    """Cited small-world visual. No keys. Same numbers as the on-screen example."""
    return watts_example()


@app.get("/api/testset")
def testset():
    return {"tasks": TASKS, "items": ITEMS}


@app.get("/api/results")
def results():
    out = {}
    for f in sorted(Path(settings.results_dir).glob("*.json")):
        try:
            data = json.loads(f.read_text())
            if "records" not in data or f.name.endswith("-partial.json"):
                continue
            data["legacy"] = data.get("pipeline_version") != VERSION
            data["metrics"] = ev.clean(ev.metrics(data["records"]))
            out[data["backend"]] = data
        except (OSError, ValueError, KeyError):
            continue
    return out


# ------------------------------------------------------------------------------ benchmark jobs
_jobs: dict[str, dict] = {}
_run_lock = threading.Lock()


@app.post("/api/eval", dependencies=[Depends(guard)])
def start_eval(body: EvalIn):
    if not settings.eval_enabled:
        raise HTTPException(403, "Benchmark runs are switched off. Set API_TOKEN (or EVAL_ENABLED=true) on the server.")
    b = backend_or_404(body.backend)
    ok, why = b.available()
    if not ok:
        raise HTTPException(503, why)
    items = [i for i in ITEMS if not body.tasks or i["task"] in body.tasks]
    if body.limit:
        per: dict[str, int] = collections.Counter()
        kept = []
        for i in items:
            if per[i["task"]] < body.limit:
                per[i["task"]] += 1
                kept.append(i)
        items = kept
    if any(j["state"] == "running" for j in _jobs.values()):
        raise HTTPException(409, "A benchmark is already running. Wait for it to finish.")
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "backend": b.name, "state": "running", "done": 0, "total": len(items), "error": None, "stop": False}
    _jobs[jid] = job

    def work():
        with _run_lock:
            try:
                runner = b.fork_for_benchmark()
                runner.warm_up()
                recs, secs = ev.timed_run(runner, items, progress=lambda i, n: job.update(done=i),
                                          should_stop=lambda: job["stop"])
                path = Path(settings.results_dir) / f"{b.name}.json"
                if job["stop"] or len(recs) < len(ITEMS):
                    path = Path(settings.results_dir) / f"{b.name}-partial.json"
                ev.save(path, runner, recs, "this server", secs)
                job.update(state="cancelled" if job["stop"] else "finished", result=str(path.name))
            except Exception as e:  # noqa: BLE001
                job.update(state="failed", error=f"{type(e).__name__}: {str(e)[:300]}")

    threading.Thread(target=work, daemon=True).start()
    return {k: v for k, v in job.items() if k != "stop"}


@app.get("/api/eval/{jid}")
def eval_status(jid: str):
    if jid not in _jobs:
        raise HTTPException(404, "No such run.")
    return {k: v for k, v in _jobs[jid].items() if k != "stop"}


@app.post("/api/eval/{jid}/cancel", dependencies=[Depends(guard)])
def eval_cancel(jid: str):
    if jid not in _jobs:
        raise HTTPException(404, "No such run.")
    _jobs[jid]["stop"] = True
    return {"ok": True}


# ------------------------------------------------------------------------------ pages
def _page(rel: str, missing: str):
    f = ROOT / "web" / rel
    if not f.exists():
        return JSONResponse({"detail": missing}, status_code=404)
    return FileResponse(f, media_type="text/html")


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
def page():
    return _page("index.html", "No page built. Run python -m scripts.build_page.")


@app.get("/field-guide", include_in_schema=False)
@app.get("/field-guide.html", include_in_schema=False)
def field_guide():
    return _page("field-guide.html", "Field guide is missing.")


_files = ROOT / "web" / "field-guide_files"
if _files.is_dir():
    app.mount("/field-guide_files", StaticFiles(directory=_files), name="field-guide-files")
