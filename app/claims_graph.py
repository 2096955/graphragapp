"""Claims graph store: FalkorDB when one is available, embedded Kuzu otherwise.

Engine choice (CLAIMS_GRAPH=auto, the default):
1. FALKORDB_URL is set: a FalkorDB server, for example `docker run -p 6379:6379 falkordb/falkordb`.
2. The `falkordblite` package is installed (Python 3.12 or later): FalkorDB embedded in this process.
3. Otherwise Kuzu, embedded, which the lab already uses, so the example runs with nothing installed.
   With CLAIMS_GRAPH=auto, a FALKORDB_URL that cannot be reached also falls back to Kuzu, with the
   reason in `detail`; with CLAIMS_GRAPH=falkordb it is an error. On a server the lab uses one
   graph, GRAPH_NAME, which it deletes and rebuilds.

The queries are the same Cypher on both engines. Kuzu needs the schema declared first; FalkorDB
does not. Dates are ISO strings, so they sort and compare the same way on both.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
import threading
from pathlib import Path
from typing import Any

KUZU_SCHEMA = [
    "CREATE NODE TABLE Publisher(id STRING, name STRING, kind STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE Person(id STRING, name STRING, role STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE Document(id STRING, title STRING, date STRING, kind STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE Topic(id STRING, label STRING, PRIMARY KEY(id))",
    "CREATE NODE TABLE Claim(id STRING, statement STRING, quote STRING, date STRING, aspect STRING, PRIMARY KEY(id))",
    "CREATE REL TABLE MADE(FROM Person TO Claim)",
    "CREATE REL TABLE IN_DOC(FROM Claim TO Document)",
    "CREATE REL TABLE PUBLISHED_BY(FROM Document TO Publisher)",
    "CREATE REL TABLE SPEAKS_FOR(FROM Person TO Publisher)",
    "CREATE REL TABLE ABOUT(FROM Claim TO Topic)",
    "CREATE REL TABLE SAME_AS(FROM Claim TO Claim, confidence DOUBLE, decided_by STRING)",
    "CREATE REL TABLE SHIFT(FROM Claim TO Claim, label STRING, confidence DOUBLE, decided_by STRING)",
]
FALKOR_INDEXES = [
    "CREATE INDEX FOR (n:Claim) ON (n.id)",
    "CREATE INDEX FOR (n:Person) ON (n.id)",
    "CREATE INDEX FOR (n:Document) ON (n.id)",
    "CREATE INDEX FOR (n:Publisher) ON (n.id)",
    "CREATE INDEX FOR (n:Topic) ON (n.id)",
]
# The graph this lab owns on a FalkorDB server. It is deleted and rebuilt at start-up and on every
# rebuild, so the name is specific enough not to meet a graph of anyone else's.
GRAPH_NAME = "graphs_lab_claims"
CLAIM_COLUMNS = ["id", "statement", "quote", "date", "aspect", "topic", "person", "person_name", "publisher",
                 "publisher_name", "publisher_kind", "document", "title"]


def _embedded_falkordb():
    try:
        from redislite.falkordb_client import FalkorDB  # falkordblite, Python 3.12+
    except ImportError:
        return None
    return FalkorDB


class ClaimsGraph:
    """Thread-safe store for claims, who made them, where, and how they relate."""

    def __init__(self, engine: str | None = None, url: str | None = None, name: str = GRAPH_NAME):
        engine = (engine or os.environ.get("CLAIMS_GRAPH") or "auto").strip().lower()
        url = url if url is not None else (os.environ.get("FALKORDB_URL") or "").strip() or None
        self.name = name
        self._lock = threading.Lock()
        self._tmp = tempfile.mkdtemp(prefix="claims-")
        self._graph = self._db = self._conn = None
        self.engine, self.detail = "kuzu", "Kuzu, embedded (set FALKORDB_URL to use FalkorDB)"
        if engine in ("auto", "falkordb") and url:
            try:
                from falkordb import FalkorDB
                self._db = FalkorDB.from_url(url, socket_connect_timeout=5, socket_timeout=30)
                self._db.connection.ping()
                self.engine, self.detail = "falkordb", "FalkorDB server"
                self.reset()                  # also fails on a Redis server without the graph module
                return
            except Exception as exc:  # noqa: BLE001 - the URL may hold a password, so only the error type is shown
                if engine == "falkordb":
                    raise RuntimeError(f"CLAIMS_GRAPH=falkordb, but the FalkorDB server at FALKORDB_URL is not "
                                       f"usable ({type(exc).__name__}). Is it running with the graph module, "
                                       "and is the falkordb package installed?") from None
                # auto: the example keeps working on Kuzu, and the page and /api/health say why.
                self._graph = self._db = None
                self.engine = "kuzu"
                self.detail = f"Kuzu, embedded (FalkorDB at FALKORDB_URL not usable: {type(exc).__name__})"
                logging.getLogger(__name__).warning("Claims graph on Kuzu: FalkorDB at FALKORDB_URL not usable (%s)",
                                                    type(exc).__name__)
        elif engine in ("auto", "falkordb") and _embedded_falkordb() is not None:
            self._db = _embedded_falkordb()(str(Path(self._tmp) / "claims.db"))
            self.engine, self.detail = "falkordb", "FalkorDB, embedded (falkordblite)"
        elif engine == "falkordb":
            raise RuntimeError("CLAIMS_GRAPH=falkordb needs FALKORDB_URL or the falkordblite package")
        self.reset()

    # ------------------------------------------------------------------ plumbing
    def reset(self) -> None:
        with self._lock:
            if self.engine == "falkordb":
                self._graph = self._db.select_graph(self.name)
                try:
                    self._graph.delete()
                except Exception:  # noqa: BLE001 - the graph did not exist yet
                    pass
                self._graph = self._db.select_graph(self.name)
                for q in FALKOR_INDEXES:
                    self._graph.query(q)
            else:
                import kuzu
                if self._conn is not None:
                    self._conn.close()
                    self._db.close()
                self._resets = getattr(self, "_resets", 0) + 1
                path = Path(self._tmp) / f"claims-{self._resets}.kuzu"   # a fresh file each time
                self._db = kuzu.Database(str(path))
                self._conn = kuzu.Connection(self._db)
                for q in KUZU_SCHEMA:
                    self._conn.execute(q)

    def close(self) -> None:
        with self._lock:
            try:
                if self.engine == "kuzu" and self._conn is not None:
                    self._conn.close()
                    self._db.close()
                elif self.engine == "falkordb" and hasattr(self._db, "close"):
                    self._db.close()
            finally:
                self._conn = None
                shutil.rmtree(self._tmp, ignore_errors=True)

    def run(self, cypher: str, params: dict[str, Any] | None = None) -> list[list[Any]]:
        with self._lock:
            if self.engine == "falkordb":
                return [list(r) for r in self._graph.query(cypher, params or {}).result_set]
            res = self._conn.execute(cypher, params or {})
            rows = []
            while res.has_next():
                rows.append(list(res.get_next()))
            return rows

    # ------------------------------------------------------------------ writes
    def add_publisher(self, pid: str, name: str, kind: str) -> None:
        self.run("CREATE (:Publisher {id: $id, name: $name, kind: $kind})", {"id": pid, "name": name, "kind": kind})

    def add_person(self, pid: str, name: str, role: str, publisher: str) -> None:
        self.run("CREATE (:Person {id: $id, name: $name, role: $role})", {"id": pid, "name": name, "role": role})
        self.run("MATCH (p:Person {id: $p}), (o:Publisher {id: $o}) CREATE (p)-[:SPEAKS_FOR]->(o)",
                 {"p": pid, "o": publisher})

    def add_document(self, did: str, title: str, date: str, kind: str, publisher: str) -> None:
        self.run("CREATE (:Document {id: $id, title: $title, date: $date, kind: $kind})",
                 {"id": did, "title": title, "date": date, "kind": kind})
        self.run("MATCH (d:Document {id: $d}), (o:Publisher {id: $o}) CREATE (d)-[:PUBLISHED_BY]->(o)",
                 {"d": did, "o": publisher})

    def add_topic(self, tid: str, label: str) -> None:
        self.run("CREATE (:Topic {id: $id, label: $label})", {"id": tid, "label": label})

    def add_claim(self, cid: str, statement: str, quote: str, date: str, aspect: str, topic: str,
                  person: str, document: str) -> None:
        self.run("CREATE (:Claim {id: $id, statement: $statement, quote: $quote, date: $date, aspect: $aspect})",
                 {"id": cid, "statement": statement, "quote": quote, "date": date, "aspect": aspect})
        self.run("MATCH (p:Person {id: $p}), (c:Claim {id: $c}) CREATE (p)-[:MADE]->(c)", {"p": person, "c": cid})
        self.run("MATCH (c:Claim {id: $c}), (d:Document {id: $d}) CREATE (c)-[:IN_DOC]->(d)", {"c": cid, "d": document})
        self.run("MATCH (c:Claim {id: $c}), (t:Topic {id: $t}) CREATE (c)-[:ABOUT]->(t)", {"c": cid, "t": topic})

    def add_same(self, a: str, b: str, confidence: float, decided_by: str) -> None:
        self.run("MATCH (a:Claim {id: $a}), (b:Claim {id: $b}) "
                 "CREATE (a)-[:SAME_AS {confidence: $c, decided_by: $by}]->(b)",
                 {"a": a, "b": b, "c": float(confidence), "by": decided_by})

    def add_shift(self, later: str, earlier: str, label: str, confidence: float, decided_by: str) -> None:
        self.run("MATCH (a:Claim {id: $a}), (b:Claim {id: $b}) "
                 "CREATE (a)-[:SHIFT {label: $l, confidence: $c, decided_by: $by}]->(b)",
                 {"a": later, "b": earlier, "l": label, "c": float(confidence), "by": decided_by})

    # ------------------------------------------------------------------ reads
    def claims(self, *, topic: str | None = None, aspect: str | None = None, person: str | None = None,
               publisher: str | None = None, publisher_kind: str | None = None,
               not_after: str | None = None) -> list[dict[str, Any]]:
        """Claims with who made them, where and when, oldest first. Every filter is optional."""
        where, params = [], {}
        for key, value, expr in (("topic", topic, "t.id = $topic"), ("aspect", aspect, "c.aspect = $aspect"),
                                 ("person", person, "p.id = $person"), ("publisher", publisher, "o.id = $publisher"),
                                 ("kind", publisher_kind, "o.kind = $kind"), ("not_after", not_after, "c.date <= $not_after")):
            if value:
                where.append(expr)
                params[key] = value
        q = ("MATCH (p:Person)-[:MADE]->(c:Claim)-[:IN_DOC]->(d:Document)-[:PUBLISHED_BY]->(o:Publisher), "
             "(c)-[:ABOUT]->(t:Topic) " + ("WHERE " + " AND ".join(where) + " " if where else "") +
             "RETURN c.id, c.statement, c.quote, c.date, c.aspect, t.id, p.id, p.name, o.id, o.name, o.kind, "
             "d.id, d.title ORDER BY c.date, c.id")
        return [dict(zip(CLAIM_COLUMNS, r)) for r in self.run(q, params)]

    def same_pairs(self) -> list[dict[str, Any]]:
        rows = self.run("MATCH (a:Claim)-[r:SAME_AS]->(b:Claim) RETURN a.id, b.id, r.confidence, r.decided_by "
                        "ORDER BY a.id, b.id")
        return [{"a": a, "b": b, "confidence": c, "decided_by": by} for a, b, c, by in rows]

    def shifts(self) -> list[dict[str, Any]]:
        rows = self.run("MATCH (a:Claim)-[r:SHIFT]->(b:Claim) RETURN a.id, b.id, r.label, r.confidence, r.decided_by "
                        "ORDER BY a.id, b.id")
        return [{"later": a, "earlier": b, "label": lab, "confidence": c, "decided_by": by}
                for a, b, lab, c, by in rows]

    def counts(self) -> dict[str, int]:
        out = {}
        for label in ("Publisher", "Person", "Document", "Topic", "Claim"):
            out[label] = int(self.run(f"MATCH (n:{label}) RETURN count(n)")[0][0])
        out["SAME_AS"] = int(self.run("MATCH (:Claim)-[r:SAME_AS]->(:Claim) RETURN count(r)")[0][0])
        out["SHIFT"] = int(self.run("MATCH (:Claim)-[r:SHIFT]->(:Claim) RETURN count(r)")[0][0])
        return out
