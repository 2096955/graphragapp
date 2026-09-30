"""Score decision backends on the claims example's labelled decisions, and record the retrieval
comparison.

    python -m scripts.claims_check --backend catalogue --backend laya --backend anyjev
    python -m scripts.claims_check --rescore      # saved answers against the current labels
    python -m scripts.claims_check --retrieval
    python -m scripts.claims_check --build labels --build catalogue --build laya

Writes results/claims-check.json, results/claims-retrieval.json and results/claims-builds.json
(the graph each backend builds, with what it sent to review). Nothing here needs a key; the model
backends need `pip install -r requirements-local.txt`.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.claims import ClaimsLab, LabelsBackend, check, most_common_baseline, score  # noqa: E402
from app.config import Settings  # noqa: E402
from app.decisions import CatalogueBackend, build_backends  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", action="append", default=[])
    ap.add_argument("--rescore", action="store_true", help="rescore saved answers against the current labels")
    ap.add_argument("--retrieval", action="store_true", help="record the retrieval comparison")
    ap.add_argument("--build", action="append", default=[], help="record the graph this backend builds")
    ap.add_argument("--threshold", type=float, default=0.8)
    a = ap.parse_args()
    settings = Settings.from_env()
    out_dir = Path(settings.results_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    if a.backend or a.rescore:
        path = out_dir / "claims-check.json"
        saved = json.loads(path.read_text()) if path.exists() else {"backends": {}}
        chosen = build_backends(replace(settings, backends=a.backend)).items() if a.backend else []
        for name, backend in chosen:
            ok, why = backend.available()
            if not ok:
                print(f"skip {name}: {why}")
                continue
            backend.warm_up()
            res = check(backend.fork_for_benchmark(), a.threshold)
            res["label"] = backend.label
            res["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            res["hardware"] = f"{platform.machine()} {settings.device}"
            saved["backends"][name] = res
        for name, res in saved["backends"].items():
            if a.rescore:
                res.update(score(res["rows"], res.get("threshold", a.threshold)))
            print(f"{name}: {res['right']}/{res['n']} right; " + "; ".join(
                f"{k} {v['right']}/{v['n']}, decided {v['decided']}, wrong among those {v['wrong_decided']}"
                for k, v in res["summary"].items()) + f"; decided right {res['decided_right']}, "
                f"wrote something false {res['written_wrongly']}, left out something true {res['left_out_wrongly']}, "
                f"to review {res['to_review']}")
        saved["most_common"] = most_common_baseline()
        saved["note"] = ("Hand-labelled decisions for the claims example (app/claims_labels.py, LABELLING.md section 9). "
                         f"A check, not a benchmark. Decided means confidence at or above {a.threshold}. "
                         "most_common is the score of always giving each question's most common label.")
        path.write_text(json.dumps(saved, indent=1))
        print("saved", path)
    if a.build:
        path = out_dir / "claims-builds.json"
        saved = json.loads(path.read_text()) if path.exists() else {"builds": {}}
        chosen = {n: LabelsBackend() for n in a.build if n == "labels"}
        chosen.update(build_backends(replace(settings, backends=[n for n in a.build if n != "labels"])))
        for name in a.build:
            backend = chosen[name]
            ok, why = backend.available()
            if not ok:
                print(f"skip {name}: {why}")
                continue
            backend.warm_up()
            lab = ClaimsLab()
            try:
                out = lab.build(backend.fork_for_benchmark(), a.threshold)
                snap = lab.snapshot()
                timelines = {f"{p}|{asp}": lab.timeline(p, asp) for p, asp in (
                    ("oyelaran", "human-review"), ("oyelaran", "register"), ("fairweather", "human-review"),
                    ("castellane", "use"), ("castellane", "notice"), ("quist", "human-review"))}
                who = {asp: lab.who(aspect=asp) for asp in ("human-review", "register", "accountability", "use",
                                                            "notice", "explanation")}
            finally:
                lab.store.close()
            saved["builds"][name] = {
                "backend": name, "label": backend.label, "model": backend.model, "threshold": a.threshold,
                "engine": out["engine"], "counts": out["counts"], "rejected": out["rejected"],
                "review": [{k: r[k] for k in ("id", "kind", "claims", "answer", "confidence")} for r in out["review"]],
                "decisions": [{k: d.get(k) for k in ("kind", "claims", "answer", "confidence", "action")}
                              for d in out["decisions"]],
                "claims": snap["claims"], "same_as": snap["same_as"], "shifts": snap["shifts"],
                "timelines": timelines, "who": who,
                "finished": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            print(f"{name}: {out['counts']['Claim']} claims written, {len(out['review'])} sent to review, "
                  f"{len(out['rejected'])} rejected")
        path.write_text(json.dumps(saved, indent=1))
        print("saved", path)
    if a.retrieval:
        from app import retrieval
        gold, rules = ClaimsLab(), ClaimsLab()
        try:
            gold.build(LabelsBackend())
            rules.build(CatalogueBackend())
            res = retrieval.compare({"Graph, correct decisions": gold, "Graph, built by the rules": rules})
        finally:
            gold.store.close()
            rules.store.close()
        res["finished"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path = out_dir / "claims-retrieval.json"
        path.write_text(json.dumps(res, indent=1))
        print("recall at", res["k"], res["summary"])
        print("saved", path)


if __name__ == "__main__":
    main()
