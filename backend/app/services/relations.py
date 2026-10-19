"""Execute relation steps over verified facts (max 2 hops, bounded frontier)."""
from __future__ import annotations

from dataclasses import dataclass

from .query_parser import RelationStep

MAX_FRONTIER = 50


@dataclass
class Hop:
    from_id: str
    from_name: str
    to_id: str
    to_name: str
    predicate: str
    label: str
    source_url: str


def _step_sql(step: RelationStep) -> str:
    gender = "AND e.gender = %(gender)s" if step.gender else ""
    out = f"""SELECT r.subject_id AS from_id, r.object_id AS to_id, r.source_url
              FROM relations r JOIN entities e ON e.entity_id = r.object_id
              WHERE r.verified AND r.predicate = %(predicate)s AND r.subject_id = ANY(%(ids)s::uuid[]) {gender}"""
    inn = f"""SELECT r.object_id AS from_id, r.subject_id AS to_id, r.source_url
              FROM relations r JOIN entities e ON e.entity_id = r.subject_id
              WHERE r.verified AND r.predicate = %(predicate)s AND r.object_id = ANY(%(ids)s::uuid[]) {gender}"""
    if step.direction == "out":
        return out
    if step.direction == "in":
        return inn
    return f"{out} UNION {inn}"


def follow(conn, seed_ids: list[str], steps: list[RelationStep], names: dict[str, str]):
    """Return (target ids, hops used, status)."""
    frontier = list(dict.fromkeys(seed_ids))
    hops: list[Hop] = []
    for step in steps:
        rows = conn.execute(_step_sql(step), {"predicate": step.predicate, "ids": frontier,
                                              "gender": step.gender}).fetchall()
        if not rows:
            return [], hops, "no_verified_relation"
        missing = {str(r["to_id"]) for r in rows} - names.keys()
        if missing:
            for r in conn.execute("SELECT entity_id, canonical_name FROM entities WHERE entity_id = ANY(%s::uuid[])",
                                  (list(missing),)).fetchall():
                names[str(r["entity_id"])] = r["canonical_name"]
        for r in rows:
            f, t = str(r["from_id"]), str(r["to_id"])
            hops.append(Hop(f, names.get(f, f), t, names.get(t, t), step.predicate, step.label, r["source_url"]))
        frontier = list(dict.fromkeys(str(r["to_id"]) for r in rows))
        if len(frontier) > MAX_FRONTIER:
            return frontier[:MAX_FRONTIER], hops, "frontier_truncated"
    return frontier, hops, "ok"


def place_scope(conn, place_id: str) -> list[str]:
    """A place and every place located in it (recursive, verified edges only)."""
    rows = conn.execute("""
        WITH RECURSIVE scope(id, depth) AS (
          SELECT %s::uuid, 0
          UNION
          SELECT r.subject_id, s.depth + 1 FROM relations r JOIN scope s ON r.object_id = s.id
          WHERE r.verified AND r.predicate = 'located_in' AND s.depth < 4
        )
        SELECT DISTINCT id FROM scope
    """, (place_id,)).fetchall()
    return [str(r["id"]) for r in rows]
