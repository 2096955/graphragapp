"""Bake the recorded results into the page, so it works with no backend at all.

    python -m scripts.build_page            # web/template.html + results/*.json -> web/index.html

Metrics are recomputed from the saved records, so a change to the metric code shows up
without rerunning any model.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import domain as d  # noqa: E402
from app import evaluation as ev  # noqa: E402
from app.arize_eval import ArizeEval  # noqa: E402
from app.compliance import run_example  # noqa: E402
from app.compliance_graph import ComplianceGraph  # noqa: E402
from app.decisions import CatalogueBackend  # noqa: E402
from app.pipeline import PIPELINE_VERSION  # noqa: E402
from app.testset import REQUESTS, TASKS, build, gold_query  # noqa: E402
from app.watts_strogatz import example as watts_example  # noqa: E402

ORDER = ["catalogue", "laya", "laya-typed", "anyjev", "jev", "uniform"]


def compact_items(items: list[dict]) -> tuple[list, dict]:
    """Share identical question objects between items."""
    qtable, keys, out = {}, {}, []
    for it in items:
        q = it["questions"][it["question"]]
        sig = json.dumps(q, sort_keys=True)
        if sig not in keys:
            keys[sig] = f"q{len(keys)}"
            qtable[keys[sig]] = q
        out.append({"id": it["id"], "task": it["task"], "state": it["state"], "q": keys[sig], "gold": it["gold"],
                    "meta": it["meta"]})
    return out, qtable


def main() -> None:
    current_items = build()
    items, qtable = compact_items(current_items)
    results, examples = {}, {}
    for f in sorted((ROOT / "results").glob("*.json")):
        data = json.loads(f.read_text())
        if f.name.startswith("compliance") or f.name.startswith("watts"):
            continue
        if f.name.startswith("examples-"):
            if data.get("pipeline_version") != PIPELINE_VERSION:
                print(f"skipped {f.name}: recorded with pipeline {data.get('pipeline_version')}, not {PIPELINE_VERSION}")
                continue
            examples[data["backend"]] = data
            continue
        if f.name.endswith("-partial.json") or "records" not in data:
            continue
        data = ev.refresh(data, current_items)
        if not data["current"]:
            print(f"skipped {f.name}: {data['stale']} decisions asked a different question, {data['missing']} missing")
            continue
        data["records"] = [{k: r.get(k) for k in ("id", "top", "confidence", "probs", "latency_ms", "error") if k in r}
                           for r in data["records"]]
        results[data["backend"]] = data
    catalogue = {
        "pollutants": [{"id": p.id, "label": p.label, "name": p.name} for p in d.POLLUTANTS],
        "groups": {g: m["label"] for g, m in d.GROUPS.items()},
        "dimensions": d.DIMENSIONS,
        "sources": [{"id": s.id, "name": s.name, "publisher": s.publisher, "updated": s.updated, "levels": s.levels,
                     "pollutants": s.pollutants} for s in d.SOURCES],
        "summary": d.CATALOGUE_SUMMARY,
    }
    gates = {it["meta"]["request"]: it["gold"] for it in current_items if it["task"] == "gate"}
    gold = {r[1]: {"id": r[0], "gate": gates[r[0]], **(gold_query(r[0]) or {})} for r in REQUESTS}
    store = ComplianceGraph()
    try:
        compliance = run_example(CatalogueBackend(), store, ArizeEval(None, None))
    finally:
        store.close()
    check_path = ROOT / "results" / "compliance-check.json"
    compliance_check = None
    if check_path.exists():
        saved = json.loads(check_path.read_text())
        compliance_check = [
            {"backend": k, "label": v.get("label") or k, "right": v["right"], "n": v["n"],
             "leaked": v["released_when_it_should_not"], "finished": v.get("finished"),
             "caught": {a: v["per_action"][a]["caught"] for a in ("release", "redact", "block")},
             "labelled": {a: v["per_action"][a]["labelled"] for a in ("release", "redact", "block")}}
            for k, v in saved.get("backends", {}).items()]
    payload = {"tasks": TASKS, "items": items, "questions": qtable, "results": results, "examples": examples,
               "catalogue": catalogue, "order": [b for b in ORDER], "gold": gold, "compliance": compliance,
               "compliance_check": compliance_check, "watts_strogatz": watts_example()}
    blob = json.dumps(ev.clean(payload), separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    tpl = (ROOT / "web" / "template.html").read_text()
    marker = "/*__DATA__*/"
    if marker not in tpl:
        sys.exit("template.html has no /*__DATA__*/ marker")
    page = tpl.replace(marker, blob)
    (ROOT / "web" / "index.html").write_text(page)
    # The same page without its document shell, for hosts that supply their own (claude.ai artifacts).
    head = page[page.index("<title>"):page.index("</head>")]
    body = page[page.index("<body>") + len("<body>"):page.rindex("</body>")]
    (ROOT / "web" / "fragment.html").write_text(head.strip() + "\n" + body.strip() + "\n")
    print(f"web/index.html and web/fragment.html: {len(items)} items, results for {', '.join(results) or 'none'}, "
          f"examples for {', '.join(examples) or 'none'}, {len(blob) / 1024:.0f} KB of data")


if __name__ == "__main__":
    main()
