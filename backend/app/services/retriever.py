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

# same photo: an image counts when it is linked to every person; duplicate entities of one person share a group
ENTITY_IMAGES_ALL = """
WITH g(entity_id, grp) AS (SELECT * FROM unnest(%(ids)s::uuid[], %(groups)s::int[]))
SELECT ie.image_id
FROM image_entities ie JOIN g USING (entity_id) JOIN images i USING (image_id)
WHERE i.is_serving AND ie.approval_status = 'approved'
GROUP BY ie.image_id, i.width, i.height
HAVING count(DISTINCT g.grp) = %(n)s
ORDER BY (i.width * i.height) DESC, ie.image_id
LIMIT %(k)s
"""

SCOPE = """AND i.image_id IN (SELECT image_id FROM image_entities
                              WHERE approval_status = 'approved' AND entity_id = ANY(%(ids)s::uuid[]))"""


def images_by_entities(conn, ids: list[str], operator: str, k: int, groups: list[int] | None = None) -> list[str]:
    if not ids:
        return []
    groups = groups or list(range(len(ids)))
    sql = ENTITY_IMAGES_ALL if operator == "all" and len(set(groups)) > 1 else ENTITY_IMAGES_ANY
    rows = conn.execute(sql, {"ids": ids, "groups": groups, "n": len(set(groups)), "k": k}).fetchall()
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


def lexical_search(conn, folded_text: str, k: int, scope_ids: list[str] | None = None,
                   require_all: bool = False) -> list[tuple[str, float]]:
    """require_all: the words must appear as this phrase, in this order; used on the whole corpus, where
    matching any single word ("trang" in "Nha Trang") or the same words reordered ("Tuấn Anh Hà" for
    "Hà Anh Tuấn", "bác hồ" for "Hồ Bắc") pulls in unrelated people."""
    words = [w for w in folded_text.split() if w.isalnum()]
    if not words:
        return []
    tsq = (" <-> " if require_all else " | ").join(words)
    scope = SCOPE if scope_ids is not None else ""
    rows = conn.execute(f"""
        SELECT i.image_id, ts_rank_cd(i.search_tsv, q) AS score
        FROM images i, to_tsquery('simple', %(tsq)s) q
        WHERE i.is_serving AND i.search_tsv @@ q {scope}
        ORDER BY score DESC, i.image_id
        LIMIT %(k)s
    """, {"tsq": tsq, "k": k, "ids": scope_ids}).fetchall()
    return [(str(r["image_id"]), float(r["score"])) for r in rows]


# Words that only glue a description together; they never count as matching it on their own.
GLUE_WORDS = {"anh", "dang", "tren", "duoi", "o", "tai", "cua", "va", "cac", "mot", "nhung", "voi", "trong", "ngoai",
              "hoac", "nguoi", "la", "co", "cho", "the", "nay", "kia"}


def _units(folded_text: str, skip: set[str] = frozenset()) -> list[str]:
    """Adjacent word pairs ("san <-> khau"), plus the content words no pair covers: a Vietnamese word is
    often two syllables, so pairs keep "áo dài" from matching "áo trắng ... tóc dài"."""
    words = [w for w in folded_text.split() if w.isalnum()]
    units, covered = [], set()
    for i in range(len(words) - 1):
        pair = f"{words[i]} {words[i + 1]}"
        if words[i] not in GLUE_WORDS and words[i + 1] not in GLUE_WORDS:
            if pair not in skip:
                units.append(f"{words[i]} <-> {words[i + 1]}")
            covered |= {i, i + 1}
    return units + [w for i, w in enumerate(words) if i not in covered and w not in GLUE_WORDS]


def lexical_partial(conn, folded_text: str, k: int, extra: str = "", skip: set[str] = frozenset()) -> list[str]:
    """Images whose text matches most of a description, for whole-corpus searches where the exact phrase
    is missing ("bãi biển Nha Trang" has no caption with all four words, but beach photos and Nha Trang
    photos exist). Only the best tiers are kept, never fewer than half the pieces matched unless nothing
    matches that well. `extra` (a shared "ở <place>") adds to the ranking but cannot make an image
    eligible, so "hồ bơi ở Phú Quốc" does not return photos of a man named Phạm Phú Quốc."""
    units = _units(folded_text, skip)
    if not units:
        return []
    extra_units = [u for u in _units(extra, skip) if u not in units]
    count = " + ".join(f"(i.search_tsv @@ to_tsquery('simple', %(u{n})s))::int" for n in range(len(units)))
    params = {f"u{n}": u for n, u in enumerate(units)}
    params.update(core=" | ".join(f"({u})" for u in units),
                  every=" | ".join(f"({u})" for u in units + extra_units), k=2000)
    rows = conn.execute(f"""
        SELECT i.image_id, {count} AS n, ts_rank_cd(i.search_tsv, to_tsquery('simple', %(every)s)) AS rank
        FROM images i
        WHERE i.is_serving AND i.search_tsv @@ to_tsquery('simple', %(core)s)
        ORDER BY n DESC, rank DESC, i.image_id
        LIMIT %(k)s
    """, params).fetchall()
    if not rows:
        return []
    need = min(rows[0]["n"], max(1, -(-len(units) // 2)))
    out = []
    for r in rows:
        if r["n"] < need or (r["n"] < rows[0]["n"] and len(out) >= k):
            break
        out.append(str(r["image_id"]))
    return out[:max(k, 300)]


def rank_by_vector(conn, qvec: np.ndarray, image_ids: list[str]) -> list[str]:
    if not image_ids:
        return []
    rows = conn.execute("""
        SELECT image_id FROM images WHERE image_id = ANY(%(ids)s::uuid[])
        ORDER BY embedding <=> %(q)s, image_id
    """, {"ids": image_ids, "q": qvec}).fetchall()
    return [str(r["image_id"]) for r in rows]


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
