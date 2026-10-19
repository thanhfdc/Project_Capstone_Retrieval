"""Candidate generation (SQL by entity, lexical FTS, vector) and rank fusion."""
from __future__ import annotations

from collections import defaultdict

import numpy as np

ENTITY_IMAGES_ANY = """
SELECT ie.image_id
FROM image_entities ie JOIN images i USING (image_id)
WHERE i.is_serving AND ie.approval_status = 'approved' AND ie.entity_id = ANY(%(ids)s::uuid[])
GROUP BY ie.image_id, i.width, i.height
ORDER BY count(*) DESC, (i.width * i.height) DESC, ie.image_id
LIMIT %(k)s
"""

ENTITY_IMAGES_ALL = """
SELECT ie.image_id
FROM image_entities ie JOIN images i USING (image_id)
WHERE i.is_serving AND ie.approval_status = 'approved' AND ie.entity_id = ANY(%(ids)s::uuid[])
GROUP BY ie.image_id, i.width, i.height
HAVING count(DISTINCT ie.entity_id) = %(n)s
ORDER BY (i.width * i.height) DESC, ie.image_id
LIMIT %(k)s
"""

SCOPE = """AND i.image_id IN (SELECT image_id FROM image_entities
                              WHERE approval_status = 'approved' AND entity_id = ANY(%(ids)s::uuid[]))"""


def images_by_entities(conn, ids: list[str], operator: str, k: int) -> list[str]:
    if not ids:
        return []
    sql = ENTITY_IMAGES_ALL if operator == "all" and len(ids) > 1 else ENTITY_IMAGES_ANY
    rows = conn.execute(sql, {"ids": ids, "n": len(set(ids)), "k": k}).fetchall()
    return [str(r["image_id"]) for r in rows]


def vector_search(conn, qvec: np.ndarray, k: int, scope_ids: list[str] | None = None) -> list[tuple[str, float]]:
    scope = SCOPE if scope_ids is not None else ""
    rows = conn.execute(f"""
        SELECT i.image_id, 1 - (i.embedding <=> %(q)s) AS score
        FROM images i
        WHERE i.is_serving {scope}
        ORDER BY i.embedding <=> %(q)s
        LIMIT %(k)s
    """, {"q": qvec, "k": k, "ids": scope_ids}).fetchall()
    return [(str(r["image_id"]), float(r["score"])) for r in rows]


def lexical_search(conn, folded_text: str, k: int, scope_ids: list[str] | None = None) -> list[tuple[str, float]]:
    words = [w for w in folded_text.split() if w.isalnum()]
    if not words:
        return []
    tsq = " | ".join(words)
    scope = SCOPE if scope_ids is not None else ""
    rows = conn.execute(f"""
        SELECT i.image_id, ts_rank_cd(i.search_tsv, q) AS score
        FROM images i, to_tsquery('simple', %(tsq)s) q
        WHERE i.is_serving AND i.search_tsv @@ q {scope}
        ORDER BY score DESC, i.image_id
        LIMIT %(k)s
    """, {"tsq": tsq, "k": k, "ids": scope_ids}).fetchall()
    return [(str(r["image_id"]), float(r["score"])) for r in rows]


def fuse_rrf(rankings: list[list[str]], weights: list[float] | None = None, k_rrf: int = 60) -> list[tuple[str, float]]:
    weights = weights or [1.0] * len(rankings)
    scores: dict[str, float] = defaultdict(float)
    for ranking, weight in zip(rankings, weights, strict=True):
        for rank, image_id in enumerate(dict.fromkeys(ranking), start=1):
            scores[image_id] += weight / (k_rrf + rank)
    return sorted(scores.items(), key=lambda item: (-item[1], item[0]))


def hydrate(conn, image_ids: list[str]) -> dict[str, dict]:
    if not image_ids:
        return {}
    rows = conn.execute("""
        SELECT i.image_id, i.thumb_path, i.width, i.height, i.description, i.source_url, i.image_url,
               COALESCE(json_agg(json_build_object('id', e.entity_id, 'name', e.canonical_name))
                        FILTER (WHERE e.entity_id IS NOT NULL), '[]') AS entities
        FROM images i
        LEFT JOIN image_entities ie ON ie.image_id = i.image_id AND ie.approval_status = 'approved'
        LEFT JOIN entities e ON e.entity_id = ie.entity_id
        WHERE i.image_id = ANY(%s::uuid[]) AND i.is_serving
        GROUP BY i.image_id
    """, (image_ids,)).fetchall()
    out = {}
    for r in rows:
        out[str(r["image_id"])] = {
            "image_id": str(r["image_id"]),
            "thumb_url": f"/media/{r['thumb_path']}",
            "width": r["width"],
            "height": r["height"],
            "entities": r["entities"],
            "description": (r["description"] or "")[:300],
            "source_url": r["source_url"],
            "image_url": r["image_url"],
        }
    return out
