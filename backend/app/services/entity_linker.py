"""Find entity mentions in a query using an in-memory alias dictionary.

Exact matching is done on diacritic-folded tokens with longest-match-first, so
"Phạm Nhật Vượng", "pham nhat vuong" and "PHẠM NHẬT VƯỢNG" all resolve the same way.
Fuzzy matching (pg_trgm) is only a fallback for typos and is flagged as such.
"""
from __future__ import annotations

import re
import threading
import unicodedata
from dataclasses import dataclass, field

from ..textnorm import fold, norm

# Single-token aliases that are also ordinary words would hijack queries.
MIN_SINGLE_TOKEN_LEN = 4  # people only; "VNG", "FPT" are fine as organisation names
# Words that open many crawled names but are not part of the name: "Ca sĩ Bằng Kiều", "MC Trấn Thành",
# "Chân dung studio Phạm Nhật Vượng". They are dropped to make a derived alias ("Bằng Kiều") and never
# form a weak alias on their own ("ca sĩ ..." must not match every singer, "ông nội ..." no one).
TITLE_PREFIXES = [tuple(t.split()) for t in (
    "nghe si nhan dan", "nghe si uu tu", "nghe si", "nhac si", "ca si", "hoa hau", "a hau", "nguoi mau", "dien vien",
    "nghe nhan", "doanh nhan", "ty phu", "chu tich", "pho chu tich", "thu tuong", "tong bi thu", "giao su", "tien si",
    "dai kien tuong", "cuu danh thu", "chan dung studio", "chan dung", "toan than", "headshot doanh nhan",
    "headshot cau thu", "headshot", "ong noi", "ba noi", "ong ngoai", "ba ngoai", "cap doi", "gia dinh", "dam cuoi",
    "sinh nhat", "vo chong", "nsnd", "nsut", "mc", "gs ts", "pgs ts", "gs", "ts", "ong", "ba", "rapper", "nhom", "ban nhac")]
_NAME_TAIL = re.compile(r"\s*[(\[]|\s+[-–|,]\s+")
MAX_WEAK_FANOUT = 8  # "nguyen van" opens 166 names: as a weak alias it only produces a useless 166-way question


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
    # typed with other accents than every candidate ("Vân Dung" for Văn Dung): ask before searching
    confirm: bool = False
    alias: str = ""  # the stored alias a typo was matched to

    @property
    def ambiguous(self) -> bool:
        return len(self.candidates) > 1 or self.confirm


@dataclass
class AliasIndex:
    by_alias: dict[str, list[EntityRef]] = field(default_factory=dict)
    by_id: dict[str, EntityRef] = field(default_factory=dict)
    max_len: int = 1
    by_deletion: dict[str, list[str]] = field(default_factory=dict)  # one letter dropped -> aliases
    name_pairs: set[str] = field(default_factory=set)  # adjacent words inside people's names: "cong vien"
    weak: set[str] = field(default_factory=set)  # aliases made of a name's first words: "nguyen chi"
    given_names: set[str] = field(default_factory=set)  # words that end several people's names: "thanh"
    # derived names hidden by another person's alias with the same letters: "tuan hung" is Tuấn Hưng, but
    # "Tuấn Hùng (Bức Tường)" waits here for a query that types his accents
    shadowed: dict[str, list[EntityRef]] = field(default_factory=dict)

    @classmethod
    def from_rows(cls, rows) -> AliasIndex:
        """Exact aliases, plus weak aliases made of a name's leading tokens ("Sơn Tùng" for
        "Sơn Tùng M-TP"). A weak alias never overrides an exact one; when several names share
        it, it resolves to all of them and the query is asked to clarify."""
        idx = cls()
        refs = [(EntityRef(str(r["entity_id"]), r["canonical_name"], r["entity_type"], r.get("gender")),
                 (r["alias_fold"] or "").split()) for r in rows]
        heads = {ref.entity_id: fold(_NAME_TAIL.split(ref.name, 1)[0]).split() for ref, _ in refs}

        def add(table: dict, key: str, ref: EntityRef) -> None:
            bucket = table.setdefault(key, [])
            if ref not in bucket:
                bucket.append(ref)

        derived: dict[str, list[EntityRef]] = {}
        weak: dict[str, list[EntityRef]] = {}
        for ref, words in refs:
            head = heads[ref.entity_id]  # "Mỹ Tâm (queen Vpop)" -> "my tam", "Lê Viết Lam - Chủ tịch..." -> "le viet lam"
            core = _strip_title(head if words == fold(ref.name).split() else words)
            if 2 <= len(core) < len(words):
                add(derived, " ".join(core), ref)
            if _strip_title(words) != words:
                continue  # "ca si ...", "ong noi ...": the opening words are not a name
            for n in range(2, len(words)):
                add(weak, " ".join(words[:n]), ref)
        for ref, words in refs:
            idx.by_id[ref.entity_id] = ref
            if not words:
                continue
            if len(words) == 1 and len(words[0]) < MIN_SINGLE_TOKEN_LEN and ref.entity_type == "person":
                continue
            add(idx.by_alias, " ".join(words), ref)
            idx.max_len = max(idx.max_len, len(words))
        for key, bucket in derived.items():
            hidden = [ref for ref in bucket if ref not in idx.by_alias.setdefault(key, bucket)]
            if hidden:
                idx.shadowed[key] = hidden
            idx.max_len = max(idx.max_len, len(key.split()))
        for key, bucket in weak.items():
            if key not in idx.by_alias and len(bucket) <= MAX_WEAK_FANOUT:
                idx.by_alias[key] = bucket
                idx.weak.add(key)
        # a name finds every crawled entity of that person: "MC Trấn Thành" also finds the photos filed
        # under "Cặp đôi MC Trấn Thành - Hari Won", the only ones where he stands next to her
        same_person: dict[str, list[EntityRef]] = {}
        endings: dict[str, int] = {}
        for ref in idx.by_id.values():
            if ref.entity_type == "person":
                key = person_key(ref.name)
                same_person.setdefault(key, []).append(ref)
                words = [w.split("~")[0] for w in key.split()]
                if 2 <= len(words) <= 4:
                    idx.name_pairs.update(f"{a} {b}" for a, b in zip(words, words[1:]))
                    endings[words[-1]] = endings.get(words[-1], 0) + 1
        for key, bucket in idx.by_alias.items():
            extra = [r for ref in bucket if ref.entity_type == "person"
                     for r in same_person.get(person_key(ref.name), []) if r not in bucket]
            if extra:
                idx.by_alias[key] = bucket + list(dict.fromkeys(extra))
        idx.given_names = {w for w, n in endings.items() if n >= 3}
        # one-letter typos of names that exist only here ("Trần Xuân Bách" derived from
        # "Trần Xuân Bách (y học)"), which the trigram search over stored aliases cannot see
        for key in idx.by_alias:
            if " " in key and len(key) >= 6:
                for variant in _deletions(key):
                    idx.by_deletion.setdefault(variant, []).append(key)
        return idx

    def one_letter_off(self, text: str) -> list[str]:
        found = {k for v in _deletions(text) | {text} for k in self.by_deletion.get(v, ())}
        n = len(text.split())
        return [k for k in found if k != text and len(k.split()) == n and edit_distance(text, k) <= 1]

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


def _deletions(text: str) -> set[str]:
    return {text} | {text[:i] + text[i + 1:] for i in range(len(text))}


def _strip_title(words: list[str]) -> list[str]:
    """Titles can stack: "Cặp đôi MC Trấn Thành" -> "Trấn Thành"."""
    for title in TITLE_PREFIXES:
        if tuple(words[:len(title)]) == title and len(words) > len(title):
            return _strip_title(words[len(title):])
    return words


def person_key(name: str) -> str:
    """Duplicate crawled entities of one person share this: "Mỹ Tâm (queen Vpop)", "Ca sĩ Mỹ Tâm" -> "my tam~.."

    Titles and the tail are dropped on folded words, but each word keeps its marks, so "Trấn Thành" and
    "Trần Thành" stay two people while "Thuỷ" and "Thủy" (the same mark on another letter) stay one."""
    head = _NAME_TAIL.split(name, 1)[0]
    folded = fold(head).split()
    marked = norm(head).split()
    if len(folded) != len(marked):
        return fold(name)
    core = _strip_title(folded)
    words = marked[len(folded) - len(core):]
    return " ".join(f"{f}~{_marks(w)}" for f, w in zip(core, words)) or fold(name)


def _marks(word: str) -> str:
    return "".join(sorted(c for c in unicodedata.normalize("NFD", word) if unicodedata.category(c) == "Mn"))


def edit_distance(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


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

    def fuzzy(self, folded_tokens: list[str], threshold: float = 0.45, lowercase: bool = False,
              accept=None) -> list[Span]:
        """Typo fallback over 2..4-token windows; returns at most one best span.

        Trigram similarity ignores word order and rewards shared words, so "tong thi phong" looks like
        "pham thi hong" and "bac ho" like "ho bac". A candidate counts as a typo only when it has the same
        number of words and is a character or two away, which is also what keeps the low trigram
        threshold safe: "trn xuan bach" is only 0.5 similar to "tran xuan bach".

        `accept(start, end, alias, refs)` returns the refs the typed text may mean (or none): equally close
        aliases are then tried in order, so "Hồ Văn Mời" reaches "Hồ Văn Mười" past "Hồ Văn Lợi"."""
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
                LIMIT 100
            """, ([g[2] for g in grams], threshold)).fetchall()
        found = [(grams[r["ord"] - 1], r["alias_fold"], float(r["score"])) for r in rows]
        found += [(g, alias, 0.0) for g in grams for alias in self.index.one_letter_off(g[2])]
        ranked = {}
        for (start, end, text), alias, score in found:
            if len(alias.split()) != end - start or not self.index.by_alias.get(alias) or alias in self.index.weak:
                continue  # a misspelt first-words-only alias ("pham dinh khanh" for "pham dinh thanh") is too weak
            dist = edit_distance(text, alias)
            if dist > (2 if len(alias) >= 12 else 1):
                continue
            rank = (end - start, -dist, score)
            if rank > ranked.get((start, end, text, alias), (0, 0, -1.0)):
                ranked[(start, end, text, alias)] = rank
        best = None
        for (start, end, text, alias), rank in sorted(ranked.items(), key=lambda kv: kv[1], reverse=True):
            if best is not None and rank[:2] != best[0][:2]:
                break  # only aliases as close as the best one
            refs = list(self.index.by_alias[alias])
            refs = accept(start, end, alias, refs) if accept else refs
            if refs:
                best = (rank, start, end, text, alias, refs)
                break
            best = best or (rank, start, end, text, alias, [])
        if best is None or not best[5]:
            return []
        rank, start, end, text, alias, refs = best
        score = rank[2]
        if lowercase:  # captions hold names too, so only text not written as a name is checked
            with self.pool.connection() as conn:
                # words common as typed ("ao dai" in 463 captions) are not a misspelt "Bảo Đại"
                if conn.execute("SELECT 1 FROM images WHERE search_tsv @@ phraseto_tsquery('simple', %s) LIMIT 1",
                                (text,)).fetchone():
                    return []
        return [Span(start, end, text, refs, fuzzy=True, score=score, alias=alias)]

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
