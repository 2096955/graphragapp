"""Synthetic knowledge graph, text-to-Cypher tasks and an execution-based reward.

Everything here runs on a laptop CPU. The GPU is only needed for training.

The reward is the point of the lab: a generated query is run against the graph
and scored on what it returns, so the model is rewarded for being right, not
for looking like the reference query.
"""
from __future__ import annotations

import random
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import kuzu

# --------------------------------------------------------------------------
# Schema
# --------------------------------------------------------------------------

SCHEMA_DDL = [
    "CREATE NODE TABLE Person(name STRING PRIMARY KEY, city STRING)",
    "CREATE NODE TABLE Company(name STRING PRIMARY KEY, sector STRING)",
    "CREATE NODE TABLE Project(name STRING PRIMARY KEY, status STRING, capacity_mw INT64)",
    "CREATE NODE TABLE Incident(id STRING PRIMARY KEY, severity STRING, hours INT64)",
    "CREATE REL TABLE WORKS_AT(FROM Person TO Company)",
    "CREATE REL TABLE LEADS(FROM Person TO Project)",
    "CREATE REL TABLE OWNS(FROM Company TO Project)",
    "CREATE REL TABLE DEPENDS_ON(FROM Project TO Project)",
    "CREATE REL TABLE AFFECTED(FROM Incident TO Project)",
]

# What the model sees. Kept short: every token here is paid for on every prompt.
SCHEMA_TEXT = """Nodes:
  (:Person {name, city})
  (:Company {name, sector})
  (:Project {name, status, capacity_mw})   status is 'planned', 'building' or 'operating'
  (:Incident {id, severity, hours})        severity is 'low', 'medium' or 'high'
Relationships:
  (:Person)-[:WORKS_AT]->(:Company)
  (:Person)-[:LEADS]->(:Project)
  (:Company)-[:OWNS]->(:Project)
  (:Project)-[:DEPENDS_ON]->(:Project)
  (:Incident)-[:AFFECTED]->(:Project)"""

SYSTEM_PROMPT = (
    "You translate questions into a single read-only Cypher query for the graph below. "
    "Reply with the query only, inside a ```cypher code block.\n\n" + SCHEMA_TEXT
)

# --------------------------------------------------------------------------
# Synthetic data (invented names, no real people or firms)
# --------------------------------------------------------------------------

_SYL = ["ka", "lo", "mi", "ra", "ven", "tor", "sa", "bel", "dun", "ori", "fen", "ma", "zu", "pel", "ar", "is"]
CITIES = ["Sydney", "Melbourne", "Brisbane", "Perth", "Adelaide", "Auckland"]
SECTORS = ["energy", "utilities", "construction", "finance"]
PROJECT_KINDS = ["Solar", "Wind", "Hydro", "Battery", "Grid", "Storage"]
STATUSES = ["planned", "building", "operating"]
SEVERITIES = ["low", "medium", "high"]


def _name(r: random.Random, parts: int) -> str:
    return "".join(r.choice(_SYL) for _ in range(parts)).capitalize()


@dataclass
class GraphData:
    people: list[dict]
    companies: list[dict]
    projects: list[dict]
    incidents: list[dict]
    rels: dict[str, list[tuple[str, str]]]


def make_graph_data(seed: int = 7, n_people: int = 80, n_companies: int = 16,
                    n_projects: int = 60, n_incidents: int = 40) -> GraphData:
    r = random.Random(seed)

    def unique(make, n):
        seen, out = set(), []
        while len(out) < n:
            v = make()
            if v not in seen:
                seen.add(v)
                out.append(v)
        return out

    people = [{"name": f"{a} {b}", "city": r.choice(CITIES)}
              for a, b in zip(unique(lambda: _name(r, 2), n_people), unique(lambda: _name(r, 3), n_people))]
    companies = [{"name": n + " " + r.choice(["Group", "Holdings", "Partners", "Energy"]), "sector": r.choice(SECTORS)}
                 for n in unique(lambda: _name(r, 2), n_companies)]
    projects = [{"name": f"{r.choice(PROJECT_KINDS)} {n}", "status": r.choice(STATUSES),
                 "capacity_mw": r.choice(range(20, 820, 20))}
                for n in unique(lambda: _name(r, 2), n_projects)]
    incidents = [{"id": f"INC-{1000 + i}", "severity": r.choice(SEVERITIES), "hours": r.randint(1, 72)}
                 for i in range(n_incidents)]

    P, C, J, I = ([x["name"] for x in people], [x["name"] for x in companies],
                  [x["name"] for x in projects], [x["id"] for x in incidents])
    rels = {
        "WORKS_AT": [(p, r.choice(C)) for p in P],
        "LEADS": [(r.choice(P), j) for j in J],
        "OWNS": [(r.choice(C), j) for j in J],
        "DEPENDS_ON": sorted({(a, b) for a, b in ((r.choice(J), r.choice(J)) for _ in range(n_projects)) if a != b}),
        "AFFECTED": [(i, r.choice(J)) for i in I],
    }
    return GraphData(people, companies, projects, incidents, rels)


def build_db(path: str | Path, data: GraphData) -> None:
    """Create the database on disk. Training opens it read-only afterwards."""
    path = Path(path)
    if path.exists():
        shutil.rmtree(path) if path.is_dir() else path.unlink()
    db = kuzu.Database(str(path))
    conn = kuzu.Connection(db)
    for ddl in SCHEMA_DDL:
        conn.execute(ddl)
    for table, rows in [("Person", data.people), ("Company", data.companies),
                        ("Project", data.projects), ("Incident", data.incidents)]:
        for row in rows:
            props = ", ".join(f"{k}: ${k}" for k in row)
            conn.execute(f"CREATE (:{table} {{{props}}})", row)
    keys = {"Person": "name", "Company": "name", "Project": "name", "Incident": "id"}
    ends = {"WORKS_AT": ("Person", "Company"), "LEADS": ("Person", "Project"), "OWNS": ("Company", "Project"),
            "DEPENDS_ON": ("Project", "Project"), "AFFECTED": ("Incident", "Project")}
    for rel, pairs in data.rels.items():
        a, b = ends[rel]
        q = (f"MATCH (x:{a} {{{keys[a]}: $x}}), (y:{b} {{{keys[b]}: $y}}) "
             f"CREATE (x)-[:{rel}]->(y)")
        for x, y in pairs:
            conn.execute(q, {"x": x, "y": y})
    conn.close()
    db.close()


# --------------------------------------------------------------------------
# Question templates with reference Cypher
# --------------------------------------------------------------------------
# Each template: question pattern, Cypher pattern, which entity list fills {x}.
# Values are inlined as literals so the model has to write them into the query.

TEMPLATES = {
    "leads":            ("Which projects does {x} lead?", "Person",
                         "MATCH (p:Person {{name: '{x}'}})-[:LEADS]->(j:Project) RETURN j.name"),
    "employer":         ("Which company does {x} work for?", "Person",
                         "MATCH (p:Person {{name: '{x}'}})-[:WORKS_AT]->(c:Company) RETURN c.name"),
    "owned":            ("List the projects owned by {x}.", "Company",
                         "MATCH (c:Company {{name: '{x}'}})-[:OWNS]->(j:Project) RETURN j.name"),
    "staff_count":      ("How many people work at {x}?", "Company",
                         "MATCH (p:Person)-[:WORKS_AT]->(c:Company {{name: '{x}'}}) RETURN count(p)"),
    "project_owner":    ("Who owns {x}?", "Project",
                         "MATCH (c:Company)-[:OWNS]->(j:Project {{name: '{x}'}}) RETURN c.name"),
    "incidents_on":     ("Which incidents affected {x}?", "Project",
                         "MATCH (i:Incident)-[:AFFECTED]->(j:Project {{name: '{x}'}}) RETURN i.id"),
    "city_people":      ("Who is based in {x}?", "City",
                         "MATCH (p:Person {{city: '{x}'}}) RETURN p.name"),
    "status_projects":  ("Which projects have status {x}?", "Status",
                         "MATCH (j:Project {{status: '{x}'}}) RETURN j.name"),
    # Two-hop templates. Held out of training to test whether multi-hop reasoning generalises.
    "colleague_projects": ("Which projects are led by people who work at {x}?", "Company",
                           "MATCH (c:Company {{name: '{x}'}})<-[:WORKS_AT]-(p:Person)-[:LEADS]->(j:Project) RETURN j.name"),
    "upstream_incidents": ("Which incidents affected projects that {x} depends on?", "Project",
                           "MATCH (j:Project {{name: '{x}'}})-[:DEPENDS_ON]->(d:Project)<-[:AFFECTED]-(i:Incident) RETURN i.id"),
}
HELD_OUT_TEMPLATES = {"colleague_projects", "upstream_incidents"}


@dataclass
class Task:
    template: str
    question: str
    gold_cypher: str
    gold_rows: list[tuple]
    split: str  # train, test_seen (new entities) or test_unseen (new template)


def _entities(data: GraphData) -> dict[str, list[str]]:
    return {"Person": [p["name"] for p in data.people], "Company": [c["name"] for c in data.companies],
            "Project": [j["name"] for j in data.projects], "City": CITIES, "Status": STATUSES}


def make_tasks(conn: kuzu.Connection, data: GraphData, seed: int = 11, test_share: float = 0.2,
               max_train_per_template: int = 25) -> list[Task]:
    """Every template x entity pair, with entities split so test entities never appear in training.

    Training examples are capped per template so one question type cannot dominate the reward.
    """
    r = random.Random(seed)
    ents = _entities(data)
    held = {k: set(r.sample(v, max(1, int(len(v) * test_share)))) for k, v in ents.items()}
    tasks = []
    for tid, (q, kind, cy) in TEMPLATES.items():
        for x in ents[kind]:
            cypher = cy.format(x=x)
            rows = run(conn, cypher)
            if rows is None or (not rows and "count(" not in cypher):
                continue  # skip questions whose answer is empty: they reward "return nothing"
            if tid in HELD_OUT_TEMPLATES:
                split = "test_unseen"
            else:
                split = "test_seen" if x in held[kind] else "train"
            tasks.append(Task(tid, q.format(x=x), cypher, rows, split))
    r.shuffle(tasks)
    kept, per = [], {}
    for t in tasks:
        if t.split == "train":
            per[t.template] = per.get(t.template, 0) + 1
            if per[t.template] > max_train_per_template:
                continue
        kept.append(t)
    return kept


# --------------------------------------------------------------------------
# Execution and reward
# --------------------------------------------------------------------------

WRITE_WORDS = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|ALTER|COPY|LOAD|INSTALL|CALL|ATTACH)\b", re.I)
BLOCK = re.compile(r"```(?:cypher)?\s*(.*?)```", re.S | re.I)


def extract_query(text: str) -> str | None:
    """Pull the query out of a ```cypher block. Returns None if there is no block."""
    m = BLOCK.search(text)
    if not m:
        return None
    q = m.group(1).strip().rstrip(";").strip()
    return q or None


def run(conn: kuzu.Connection, query: str) -> list[tuple] | None:
    """Run a query; return rows, or None if it fails. Rows are sorted so order does not matter."""
    try:
        res = conn.execute(query)
        rows = []
        while res.has_next():
            rows.append(tuple(res.get_next()))
        return sorted(rows, key=repr)
    except Exception:
        return None


def score(completion: str, gold_rows: list[tuple], conn: kuzu.Connection) -> tuple[float, str]:
    """Reward for one completion, with the reason.

    1.0   returns exactly the reference rows (order and column names ignored)
    0.3 + 0.4 * overlap   runs but returns different rows (partial credit)
    0.1   query found but fails to run
    0.0   no query found
    -1.0  attempts to write or call procedures (never executed)
    """
    q = extract_query(completion)
    if q is None:
        return 0.0, "no query"
    if WRITE_WORDS.search(q):
        return -1.0, "write blocked"
    rows = run(conn, q)
    if rows is None:
        return 0.1, "error"
    if rows == gold_rows:
        return 1.0, "correct"
    a, b = set(rows), set(gold_rows)
    overlap = len(a & b) / len(a | b) if a | b else 0.0
    return 0.3 + 0.4 * overlap, "wrong rows"


def open_readonly(path: str | Path, timeout_ms: int = 2000) -> kuzu.Connection:
    """Read-only connection with a timeout, so a runaway query cannot stall training."""
    db = kuzu.Database(str(path), read_only=True)
    conn = kuzu.Connection(db)
    conn.set_query_timeout(timeout_ms)
    conn._db_ref = db  # keep the database object alive with the connection
    return conn


def prompt_messages(question: str) -> list[dict]:
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------

def evaluate(generate, tasks: list[Task], conn: kuzu.Connection, splits=("test_seen", "test_unseen")) -> dict:
    """Score a generator on the test splits.

    generate(list_of_message_lists) -> list_of_completion_strings, so any model
    (local, fine-tuned or a hosted API) can be compared on the same footing.
    """
    report = {}
    for split in splits:
        subset = [t for t in tasks if t.split == split]
        outs = generate([prompt_messages(t.question) for t in subset])
        results = [score(o, t.gold_rows, conn) for o, t in zip(outs, subset)]
        by_reason, by_template = {}, {}
        for (s, why), t in zip(results, subset):
            by_reason[why] = by_reason.get(why, 0) + 1
            ok, n = by_template.get(t.template, (0, 0))
            by_template[t.template] = (ok + (s == 1.0), n + 1)
        report[split] = {
            "n": len(subset),
            "accuracy": sum(s == 1.0 for s, _ in results) / max(1, len(subset)),
            "mean_reward": sum(s for s, _ in results) / max(1, len(subset)),
            "outcomes": by_reason,
            "by_template": {k: f"{ok}/{n}" for k, (ok, n) in sorted(by_template.items())},
            "examples": [(t.question, o, why) for (s, why), t, o in zip(results, subset, outs) if s < 1.0][:5],
        }
    return report


def print_report(name: str, report: dict) -> None:
    print(f"== {name}")
    for split, r in report.items():
        print(f"  {split:12s} accuracy {r['accuracy']:.0%}  mean reward {r['mean_reward']:.2f}  (n={r['n']})  {r['outcomes']}")
