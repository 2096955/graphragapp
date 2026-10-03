"""Writable Kuzu graph for compliance filter decisions.

The catalogue graph in graph.py stays read-only. This store is the memory of the
compliance agent: patterns, attempts, and decisions. A repeated injection updates
the pattern node instead of disappearing as a one-off score.

Two hops from a pattern reach its attempts and decisions. The Watts–Strogatz
figures are a synthetic N=500 visual, not a measurement of this catalogue graph.
Token-bounded retrieval is the design claim, not a measured p95.
"""
from __future__ import annotations

import shutil
import tempfile
import threading
from pathlib import Path

import kuzu

SCHEMA = [
    "CREATE NODE TABLE Agent(id STRING PRIMARY KEY, role STRING, label STRING)",
    "CREATE NODE TABLE Pattern(id STRING PRIMARY KEY, kind STRING, label STRING, attempts INT64, last_action STRING)",
    "CREATE NODE TABLE Attempt(id STRING PRIMARY KEY, at STRING, action STRING, backend STRING)",
    "CREATE NODE TABLE Decision(id STRING PRIMARY KEY, action STRING, confidence DOUBLE, cost_usd DOUBLE, model STRING)",
    "CREATE REL TABLE SITS_IN_FRONT_OF(FROM Agent TO Agent)",
    "CREATE REL TABLE WATCHES(FROM Agent TO Pattern)",
    "CREATE REL TABLE MATCHES(FROM Attempt TO Pattern)",
    "CREATE REL TABLE DECIDED(FROM Attempt TO Decision)",
    "CREATE REL TABLE RECORDED_BY(FROM Decision TO Agent)",
]


class ComplianceGraph:
    """Thread-safe Kuzu store.

    With no path the store is ephemeral and starts empty. With a path, an
    existing database is reopened without being deleted; a new path is
    initialised once. reset() is deliberately destructive and is used only by
    the synthetic demo/test flow.
    """

    def __init__(self, path: str | Path | None = None):
        self._tmp = None
        if path is None:
            self._tmp = tempfile.mkdtemp(prefix="compliance-")
            path = Path(self._tmp) / "compliance.kuzu"
        self.path = Path(path)
        self._lock = threading.Lock()
        self._db = None
        self._conn = None

        is_new = not self.path.exists()
        self._open(create_schema=is_new)

    def _open(self, *, create_schema: bool) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db = kuzu.Database(str(self.path))
        self._conn = kuzu.Connection(self._db)
        if create_schema:
            for ddl in SCHEMA:
                self._conn.execute(ddl)
            self._conn.execute(
                "CREATE (:Agent {id: 'compliance', role: 'compliance', label: 'Legal and compliance agent'})"
            )
            self._conn.execute(
                "CREATE (:Agent {id: 'downstream', role: 'downstream', label: 'Downstream research agent'})"
            )
            self._conn.execute(
                "MATCH (a:Agent {id: 'compliance'}), (b:Agent {id: 'downstream'}) "
                "CREATE (a)-[:SITS_IN_FRONT_OF]->(b)"
            )
        else:
            # Fail startup rather than silently wiping or recreating an
            # incompatible production store.
            try:
                for table in ("Agent", "Pattern", "Attempt", "Decision"):
                    self._q(f"MATCH (n:{table}) RETURN count(n)")
            except Exception as exc:
                self._close_handles()
                raise RuntimeError(
                    f"Compliance database at {self.path} is incompatible or unreadable."
                ) from exc

    def _close_handles(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
        if self._db is not None:
            self._db.close()
            self._db = None

    def close(self) -> None:
        with self._lock:
            self._close_handles()
            if self._tmp and Path(self._tmp).exists():
                shutil.rmtree(self._tmp, ignore_errors=True)

    def reset(self) -> None:
        """Destructively rebuild the store. Intended for the synthetic demo/tests."""
        with self._lock:
            self._close_handles()
            if self.path.exists():
                shutil.rmtree(self.path) if self.path.is_dir() else self.path.unlink()
            self._open(create_schema=True)

    def _q(self, cypher: str, params: dict | None = None) -> list[tuple]:
        if self._conn is None:
            raise RuntimeError("Compliance graph is closed.")
        res = self._conn.execute(cypher, params or {})
        rows = []
        while res.has_next():
            rows.append(tuple(res.get_next()))
        return rows

    def record(
        self,
        *,
        attempt_id: str,
        at: str,
        action: str,
        backend: str,
        pattern_id: str,
        pattern_kind: str,
        pattern_label: str,
        decision_id: str,
        confidence: float,
        cost_usd: float,
        model: str,
    ) -> dict:
        """Attach an attempt to a pattern. Same attempt_id is idempotent.

        Stores only pseudonymous identifiers, decisions, and attempt metadata;
        it does not store the raw payload.
        """
        with self._lock:
            existing = self._q("MATCH (t:Attempt {id: $id}) RETURN t.id", {"id": attempt_id})
            found = self._q("MATCH (p:Pattern {id: $id}) RETURN p.attempts", {"id": pattern_id})
            if existing:
                attempts = int(found[0][0]) if found else 0
                return {"pattern_id": pattern_id, "attempts": attempts, "repeated": attempts > 1}
            if found:
                attempts = int(found[0][0]) + 1
                self._conn.execute(
                    "MATCH (p:Pattern {id: $id}) SET p.attempts = $n, p.last_action = $a",
                    {"id": pattern_id, "n": attempts, "a": action},
                )
            else:
                attempts = 1
                self._conn.execute(
                    "CREATE (:Pattern {id: $id, kind: $k, label: $l, attempts: 1, last_action: $a})",
                    {"id": pattern_id, "k": pattern_kind, "l": pattern_label, "a": action},
                )
                self._conn.execute(
                    "MATCH (a:Agent {id: 'compliance'}), (p:Pattern {id: $p}) CREATE (a)-[:WATCHES]->(p)",
                    {"p": pattern_id},
                )
            self._conn.execute(
                "CREATE (:Attempt {id: $id, at: $at, action: $a, backend: $b})",
                {"id": attempt_id, "at": at, "a": action, "b": backend},
            )
            self._conn.execute(
                "CREATE (:Decision {id: $id, action: $a, confidence: $c, cost_usd: $usd, model: $m})",
                {"id": decision_id, "a": action, "c": confidence, "usd": cost_usd, "m": model},
            )
            self._conn.execute(
                "MATCH (t:Attempt {id: $t}), (p:Pattern {id: $p}) CREATE (t)-[:MATCHES]->(p)",
                {"t": attempt_id, "p": pattern_id},
            )
            self._conn.execute(
                "MATCH (t:Attempt {id: $t}), (d:Decision {id: $d}) CREATE (t)-[:DECIDED]->(d)",
                {"t": attempt_id, "d": decision_id},
            )
            self._conn.execute(
                "MATCH (d:Decision {id: $d}), (a:Agent {id: 'compliance'}) CREATE (d)-[:RECORDED_BY]->(a)",
                {"d": decision_id},
            )
        return {"pattern_id": pattern_id, "attempts": attempts, "repeated": attempts > 1}

    def counts(self) -> dict:
        with self._lock:
            return {
                "Agent": int(self._q("MATCH (n:Agent) RETURN count(n)")[0][0]),
                "Pattern": int(self._q("MATCH (n:Pattern) RETURN count(n)")[0][0]),
                "Attempt": int(self._q("MATCH (n:Attempt) RETURN count(n)")[0][0]),
                "Decision": int(self._q("MATCH (n:Decision) RETURN count(n)")[0][0]),
            }

    def snapshot(self, focus: str | None = None) -> dict:
        """Nodes and edges, plus an optional two-hop neighbourhood."""
        with self._lock:
            nodes = []
            for kind, q in (
                ("Agent", "MATCH (n:Agent) RETURN n.id, n.role, n.label"),
                ("Pattern", "MATCH (n:Pattern) RETURN n.id, n.kind, n.label, n.attempts, n.last_action"),
                ("Attempt", "MATCH (n:Attempt) RETURN n.id, n.at, n.action, n.backend"),
                ("Decision", "MATCH (n:Decision) RETURN n.id, n.action, n.confidence, n.cost_usd, n.model"),
            ):
                for row in self._q(q):
                    node = {"id": row[0], "kind": kind}
                    if kind == "Agent":
                        node.update(role=row[1], label=row[2])
                    elif kind == "Pattern":
                        node.update(
                            pattern_kind=row[1],
                            label=row[2],
                            attempts=int(row[3]),
                            last_action=row[4],
                        )
                    elif kind == "Attempt":
                        node.update(at=row[1], action=row[2], backend=row[3], label=row[2])
                    else:
                        node.update(
                            action=row[1],
                            confidence=float(row[2]),
                            cost_usd=float(row[3]),
                            model=row[4],
                            label=row[1],
                        )
                    nodes.append(node)
            edges = []
            for typ, q in (
                ("SITS_IN_FRONT_OF", "MATCH (a)-[r:SITS_IN_FRONT_OF]->(b) RETURN a.id, b.id"),
                ("WATCHES", "MATCH (a)-[r:WATCHES]->(b) RETURN a.id, b.id"),
                ("MATCHES", "MATCH (a)-[r:MATCHES]->(b) RETURN a.id, b.id"),
                ("DECIDED", "MATCH (a)-[r:DECIDED]->(b) RETURN a.id, b.id"),
                ("RECORDED_BY", "MATCH (a)-[r:RECORDED_BY]->(b) RETURN a.id, b.id"),
            ):
                for src, dst in self._q(q):
                    edges.append({"source": src, "target": dst, "type": typ})
        hops = two_hop(nodes, edges, focus) if focus else []
        return {
            "nodes": nodes,
            "edges": edges,
            "hops": hops,
            "focus": focus,
            "note": (
                "Two hops from the matched pattern reach nearby attempts and decisions in "
                "this worked graph. The Watts–Strogatz figures are a synthetic N=500 visual, "
                "not a measurement of this catalogue graph. Token-bounded retrieval is the "
                "design claim, not a measured p95."
            ),
        }


def two_hop(nodes: list[dict], edges: list[dict], start: str, hops: int = 2) -> list[dict]:
    """Expand an undirected neighbourhood up to the requested hop count."""
    by_id = {n["id"]: n for n in nodes}
    adj: dict[str, list[tuple[str, str]]] = {}
    for e in edges:
        adj.setdefault(e["source"], []).append((e["target"], e["type"]))
        adj.setdefault(e["target"], []).append((e["source"], e["type"]))
    seen = {start: 0}
    out = [{"id": start, "kind": by_id.get(start, {}).get("kind"), "via": "self", "hop": 0}]
    frontier = [start]
    for dist in range(1, hops + 1):
        nxt = []
        for nid in frontier:
            for other, typ in adj.get(nid, []):
                if other in seen:
                    continue
                seen[other] = dist
                nxt.append(other)
                out.append(
                    {
                        "id": other,
                        "kind": by_id.get(other, {}).get("kind"),
                        "via": typ,
                        "hop": dist,
                    }
                )
        frontier = nxt
    return out
