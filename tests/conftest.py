import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# Tests never load model weights or call a vendor: only the uniform baseline and an
# unconfigured Jev backend are built, plus the oracle backend defined below.
os.environ["BACKENDS"] = "catalogue,uniform,jev"
os.environ.pop("TYPESAFE_API_KEY", None)
os.environ.pop("API_TOKEN", None)
os.environ["RESULTS_DIR"] = str(Path(__file__).parent / "_results")

from app import domain as d  # noqa: E402
from app import tasks as t  # noqa: E402
from app.decisions import Backend  # noqa: E402
from app.testset import ALL, GHG, PM, REQUESTS  # noqa: E402

BY_TEXT = {r[1]: r for r in REQUESTS}
DESCRIBE = {p.describe: p.id for p in d.POLLUTANTS}
GROUP_DESCRIBE = {m["describe"]: g for g, m in d.GROUPS.items()}


class OracleBackend(Backend):
    """Answers every pipeline question from the labels. Used to test the plumbing, not a model."""

    name = "oracle"
    label = "Oracle"

    def __init__(self):
        super().__init__("labels")

    def _decide(self, state, questions):
        out = {}
        for name, q in questions.items():
            if q is t.GATE or q.get("instructions") == t.GATE["instructions"]:
                r = BY_TEXT[state["request"]]
                gold = "clarify" if r[0] == "P15" else r[2]
                out[name] = {k: float(k == gold) for k in q["criteria"]}
            elif q["type"] == "noul" and q["instructions"].startswith("Does the request ask for data on "):
                r = BY_TEXT[state["request"]]
                cand = q["instructions"][len("Does the request ask for data on "):-1]
                if cand in GROUP_DESCRIBE:
                    g = GROUP_DESCRIBE[cand]
                    yes = (g == "all" and r[3] == ALL) or (g == "ghg" and r[3] == GHG) or (g == "pm" and r[3] == PM)
                else:
                    pid = DESCRIBE[cand]
                    yes = r[3] != ALL and pid in r[3]
                out[name] = {"yes": float(yes), "no": float(not yes)}
            elif name in d.DIMENSIONS:
                r = BY_TEXT[state["request"]]
                gold = dict(zip(("GEO", "TIME", "SECTOR"), r[4:7]))[name]
                out[name] = {k: float(k == gold) for k in q["criteria"]}
            elif name.startswith("group:"):
                from app.testset import GROUP_GOLD
                r = BY_TEXT[state["request"]]
                yes = name.split(":")[1] in GROUP_GOLD.get(r[0], ())
                out[name] = {"yes": float(yes), "no": float(not yes)}
            elif q["type"] == "score":
                out[name] = {str(i): (1.0 if i == len(q["criteria"]) - 1 else 0.0) for i in range(len(q["criteria"]))}
            else:
                out[name] = {k: 1.0 / len(q["criteria"]) for k in (q.get("criteria") or {"yes": 0, "no": 0})}
        return out, None, 0.0, {}


import shutil  # noqa: E402

import pytest  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _clean_results():
    yield
    shutil.rmtree(os.environ["RESULTS_DIR"], ignore_errors=True)
