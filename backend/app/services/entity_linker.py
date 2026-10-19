"""Find entity mentions in a query using an in-memory alias dictionary.

Exact matching is done on diacritic-folded tokens with longest-match-first, so
"Phạm Nhật Vượng", "pham nhat vuong" and "PHẠM NHẬT VƯỢNG" all resolve the same way.
Fuzzy matching (pg_trgm) is only a fallback for typos and is flagged as such.
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from ..textnorm import fold

# Single-token aliases that are also ordinary words would hijack queries.
MIN_SINGLE_TOKEN_LEN = 4


@dataclass(frozen=True)
class EntityRef:
    entity_id: str
    name: str
    entity_type: str
    gender: str | None


@dataclass
class Span:
    start: int  # token index, inclusive
    end: int    # token index, exclusive
    text: str
    candidates: list[EntityRef]
    fuzzy: bool = False
    score: float = 1.0

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1


@dataclass
class AliasIndex:
    by_alias: dict[str, list[EntityRef]] = field(default_factory=dict)
    by_id: dict[str, EntityRef] = field(default_factory=dict)
    max_len: int = 1

    @classmethod
    def from_rows(cls, rows) -> AliasIndex:
        """Exact aliases, plus weak aliases made of a name's leading tokens ("Sơn Tùng" for
        "Sơn Tùng M-TP"). A weak alias never overrides an exact one; when several names share
        it, it resolves to all of them and the query is asked to clarify."""
        idx = cls()
        weak: dict[str, list[EntityRef]] = {}
        for r in rows:
            ref = EntityRef(str(r["entity_id"]), r["canonical_name"], r["entity_type"], r.get("gender"))
            words = (r["alias_fold"] or "").split()
            for n in range(2, len(words)):
                bucket = weak.setdefault(" ".join(words[:n]), [])
                if ref not in bucket:
                    bucket.append(ref)
        for r in rows:
            ref = EntityRef(str(r["entity_id"]), r["canonical_name"], r["entity_type"], r.get("gender"))
            idx.by_id[ref.entity_id] = ref
            key = r["alias_fold"]
            if not key:
                continue
            n = len(key.split())
            if n == 1 and len(key) < MIN_SINGLE_TOKEN_LEN:
                continue
            bucket = idx.by_alias.setdefault(key, [])
            if ref not in bucket:
                bucket.append(ref)
            idx.max_len = max(idx.max_len, n)
        for key, refs in weak.items():
            if key not in idx.by_alias:
                idx.by_alias[key] = refs
        return idx

    def _longest_at(self, tokens: list[str], i: int) -> int:
        for n in range(min(self.max_len, len(tokens) - i), 0, -1):
            if " ".join(tokens[i:i + n]) in self.by_alias:
                return n
        return 0

    def find_spans(self, folded_tokens: list[str]) -> list[Span]:
        """Longest match first, but a match is dropped when a match starting inside it reaches further:
        in "anh tran minh dung" the name "Trần Minh Dũng" wins over "Anh Trần..." eating the word "ảnh"."""
        spans, i, L = [], 0, len(folded_tokens)
        reach = [j + self._longest_at(folded_tokens, j) for j in range(L)]
        while i < L:
            n = reach[i] - i
            if n == 0 or any(reach[j] > reach[i] for j in range(i + 1, reach[i])):
                i += 1
                continue
            key = " ".join(folded_tokens[i:i + n])
            spans.append(Span(i, i + n, key, list(self.by_alias[key])))
            i += n
        return spans


class EntityLinker:
    def __init__(self, pool):
        self.pool = pool
        self._lock = threading.Lock()
        self.index = AliasIndex()

    def reload(self) -> int:
        with self.pool.connection() as conn:
            rows = conn.execute("""
                SELECT a.alias_fold, e.entity_id, e.canonical_name, e.entity_type, e.gender
                FROM entity_aliases a JOIN entities e USING (entity_id)
            """).fetchall()
        index = AliasIndex.from_rows(rows)
        with self._lock:
            self.index = index
        return len(index.by_alias)

    def fuzzy(self, folded_tokens: list[str], threshold: float = 0.6) -> list[Span]:
        """Typo fallback over 2..4-token windows; returns at most one best span."""
        grams = []
        for n in range(2, 5):
            for i in range(0, len(folded_tokens) - n + 1):
                grams.append((i, i + n, " ".join(folded_tokens[i:i + n])))
        if not grams:
            return []
        with self.pool.connection() as conn:
            rows = conn.execute("""
                SELECT g.ord, a.alias_fold, similarity(a.alias_fold, g.txt) AS score
                FROM unnest(%s::text[]) WITH ORDINALITY AS g(txt, ord)
                JOIN entity_aliases a ON a.alias_fold %% g.txt
                WHERE similarity(a.alias_fold, g.txt) >= %s
                ORDER BY score DESC
                LIMIT 1
            """, ([g[2] for g in grams], threshold)).fetchall()
        if not rows:
            return []
        start, end, text = grams[rows[0]["ord"] - 1]
        refs = self.index.by_alias.get(rows[0]["alias_fold"], [])
        if not refs:
            return []
        return [Span(start, end, text, list(refs), fuzzy=True, score=float(rows[0]["score"]))]

    def suggest(self, q: str, limit: int = 8) -> list[EntityRef]:
        key = fold(q)
        if len(key) < 2:
            return []
        with self.pool.connection() as conn:
            rows = conn.execute("""
                SELECT DISTINCT ON (e.entity_id) e.entity_id, e.canonical_name, e.entity_type, e.gender,
                       similarity(a.alias_fold, %s) AS score
                FROM entity_aliases a JOIN entities e USING (entity_id)
                WHERE a.alias_fold LIKE %s OR a.alias_fold %% %s
                ORDER BY e.entity_id, score DESC
            """, (key, f"%{key}%", key)).fetchall()
        rows.sort(key=lambda r: -r["score"])
        return [EntityRef(str(r["entity_id"]), r["canonical_name"], r["entity_type"], r["gender"])
                for r in rows[:limit]]
