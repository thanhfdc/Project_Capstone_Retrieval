"""Rule-based query planner (no LLM on the common path).

A query becomes a QueryPlan: up to 3 intents, each with seed entities, an optional chain
of relation steps (max 2 hops), residual visual text and an optional shared location.
Parsing works on diacritic-folded tokens but keeps the original words for the encoder.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..textnorm import fold, norm
from .entity_linker import AliasIndex, EntityRef, Span

MAX_INTENTS = 3
MAX_HOPS = 2


@dataclass(frozen=True)
class RelationStep:
    predicate: str           # parent_of | spouse_of | founded | member_of | located_in
    direction: str           # out: seed is subject; in: seed is object; both
    gender: str | None = None
    label: str = ""


# Relation phrases, folded. Order matters only for longest-match (handled by length sort).
RELATION_PHRASES: dict[str, RelationStep] = {
    "con trai": RelationStep("parent_of", "out", "male", "con trai"),
    "con gai": RelationStep("parent_of", "out", "female", "con gái"),
    "con": RelationStep("parent_of", "out", None, "con"),
    "bo": RelationStep("parent_of", "in", "male", "bố"),
    "cha": RelationStep("parent_of", "in", "male", "cha"),
    "bo de": RelationStep("parent_of", "in", "male", "bố"),
    "me": RelationStep("parent_of", "in", "female", "mẹ"),
    "bo me": RelationStep("parent_of", "in", None, "bố mẹ"),
    "cha me": RelationStep("parent_of", "in", None, "cha mẹ"),
    "vo": RelationStep("spouse_of", "both", "female", "vợ"),
    "chong": RelationStep("spouse_of", "both", "male", "chồng"),
    "vo chong": RelationStep("spouse_of", "both", None, "vợ/chồng"),
    "nguoi sang lap": RelationStep("founded", "in", None, "người sáng lập"),
    "nha sang lap": RelationStep("founded", "in", None, "nhà sáng lập"),
    "sang lap vien": RelationStep("founded", "in", None, "người sáng lập"),
    "cong ty cua": RelationStep("founded", "out", None, "công ty"),
    "thanh vien": RelationStep("member_of", "in", None, "thành viên"),
    "thanh vien nhom": RelationStep("member_of", "in", None, "thành viên nhóm"),
    "nhom nhac cua": RelationStep("member_of", "out", None, "nhóm nhạc"),
    "ban nhac cua": RelationStep("member_of", "out", None, "ban nhạc"),
}
_REL_KEYS = sorted(RELATION_PHRASES, key=lambda k: -len(k.split()))
# "của" between a relation phrase and its argument is noise.
FILLER = {"cua", "la", "ong", "ba", "anh", "chi", "cac", "nhung", "nguoi"}
PHOTO_WORDS = {"ảnh", "hình", "tấm", "bức", "tìm"}
LEADING_NOISE = [("hinh", "anh"), ("buc", "anh"), ("tam", "anh"), ("anh",), ("hinh",), ("cho", "toi"),
                 ("tim",), ("tim", "kiem"), ("nhung",), ("cac",)]
# Titles written right before a name are apposition, not relations: "con trai chủ tịch Phạm Nhật Vượng".
TITLES = [("chu", "tich"), ("ty", "phu"), ("doanh", "nhan"), ("ca", "si"), ("nhac", "si"), ("dien", "vien"),
          ("nguoi", "mau"), ("rapper",), ("ong",), ("ba",), ("co",), ("chi",), ("anh",), ("em",),
          ("tap", "doan"), ("cong", "ty"), ("nhom", "nhac"), ("ban", "nhac"), ("nhom",), ("thanh", "pho"),
          ("tinh",), ("dao",)]
GROUP_SEPARATORS = {"va", "hoac", "voi", ","}
TOGETHER_PHRASES = [("chup", "cung"), ("chup", "chung", "voi"), ("chung", "voi"), ("cung", "voi"),
                    ("ben", "canh"), ("cung",)]
LOCATION_MARKERS = {"o", "tai"}
VISUAL_STOP = {"dang", "dep", "cua", "cac", "nhung", "mot", "nhieu"}


@dataclass
class Intent:
    label: str
    seeds: list[EntityRef] = field(default_factory=list)
    entity_operator: str = "any"   # any | all (same photo)
    relation_steps: list[RelationStep] = field(default_factory=list)
    visual_text: str = ""          # original words, for the encoder
    lexical_text: str = ""         # folded words, for full text search
    ambiguous: list[Span] = field(default_factory=list)
    fuzzy: bool = False


@dataclass
class QueryPlan:
    query: str
    intents: list[Intent]
    combine: str = "groups"        # groups | union
    location: EntityRef | None = None
    location_text: str = ""
    parser: str = "rule"
    query_type: str = "single"     # single | multi_intent | multi_hop (label for reporting)
    warnings: list[str] = field(default_factory=list)


def _match_at(tokens: list[str], i: int, phrase: tuple[str, ...]) -> bool:
    return tuple(tokens[i:i + len(phrase)]) == phrase


def _strip_leading(orig: list[str], folded: list[str]) -> tuple[list[str], list[str]]:
    changed = True
    while changed and folded:
        changed = False
        for phrase in sorted(LEADING_NOISE, key=len, reverse=True):
            if _match_at(folded, 0, phrase):
                orig, folded = orig[len(phrase):], folded[len(phrase):]
                changed = True
                break
    return orig, folded


class RuleParser:
    def __init__(self, index_getter, fuzzy_lookup=None):
        self._index = index_getter
        self._fuzzy = fuzzy_lookup

    def parse(self, query: str) -> QueryPlan:
        orig = norm(query).split()
        folded = fold(query).split()
        index: AliasIndex = self._index()
        # "ảnh"/"hình" typed with diacritics at the start is the word "photo", never the name "Anh"
        masked = list(folded)
        for k, word in enumerate(orig[:2]):
            if word in PHOTO_WORDS:
                masked[k] = "#"
        spans = index.find_spans(masked)
        if not spans and self._fuzzy:
            spans = self._fuzzy(masked)
        plan = QueryPlan(query=query, intents=[])

        # 1. Shared location suffix: "... ở/tại <place or free text>"
        end = len(folded)
        for i in range(len(folded) - 1, 0, -1):
            if folded[i] in LOCATION_MARKERS and not any(s.start <= i < s.end for s in spans):
                place_spans = [s for s in spans if s.start == i + 1]
                if place_spans and place_spans[0].end == len(folded):
                    refs = place_spans[0].candidates
                    places = [r for r in refs if r.entity_type == "place"]
                    if places:
                        plan.location = places[0]
                    plan.location_text = " ".join(orig[i + 1:])
                    spans = [s for s in spans if s.start < i]
                elif not place_spans:
                    plan.location_text = " ".join(orig[i + 1:])
                else:
                    continue
                end = i
                break
        orig, folded = orig[:end], folded[:end]

        # 2. Split into segments on separators outside entity spans.
        segments: list[tuple[int, int, str]] = []  # (start, end, connector-before)
        start, connector = 0, ""
        i = 0
        while i < len(folded):
            inside = any(s.start <= i < s.end for s in spans)
            if not inside and folded[i] in GROUP_SEPARATORS and i > start:
                # "chụp chung với": 'voi' belongs to a together-phrase, not a separator
                if folded[i] == "voi" and i > 0 and folded[i - 1] in ("chung", "cung"):
                    i += 1
                    continue
                segments.append((start, i, connector))
                connector, start = folded[i], i + 1
            i += 1
        segments.append((start, len(folded), connector))

        intents: list[Intent] = []
        for s_start, s_end, conn in segments:
            seg_spans = [s for s in spans if s.start >= s_start and s.end <= s_end]
            intent = self._parse_segment(orig, folded, s_start, s_end, seg_spans)
            if intent is None:
                continue
            if conn == "hoac":
                plan.combine = "union"
            # "Sơn Tùng đang hát và nhảy": a short segment without entity extends the previous intent
            if intents and not intent.seeds and not intent.relation_steps and intents[-1].seeds \
                    and len(intent.lexical_text.split()) <= 2:
                prev = intents[-1]
                prev.visual_text = f"{prev.visual_text} và {intent.visual_text}".strip()
                prev.lexical_text = f"{prev.lexical_text} {intent.lexical_text}".strip()
                continue
            intents.append(intent)

        if not intents:
            intents = [Intent(label=query, visual_text=" ".join(orig), lexical_text=" ".join(folded))]
        if len(intents) > MAX_INTENTS:
            plan.warnings.append(f"only the first {MAX_INTENTS} intents are searched")
            intents = intents[:MAX_INTENTS]
        for it in intents:
            if plan.location_text:
                it.visual_text = f"{it.visual_text} ở {plan.location_text}".strip()
                it.lexical_text = f"{it.lexical_text} {fold(plan.location_text)}".strip()
            if len(it.relation_steps) > MAX_HOPS:
                plan.warnings.append(f"relation chains longer than {MAX_HOPS} hops are not supported")
        plan.intents = intents
        if any(it.relation_steps for it in intents):
            plan.query_type = "multi_hop"
        elif len(intents) > 1 or any(it.entity_operator == "all" for it in intents):
            plan.query_type = "multi_intent"
        return plan

    def _parse_segment(self, orig, folded, s_start, s_end, seg_spans) -> Intent | None:
        o, f = orig[s_start:s_end], folded[s_start:s_end]
        spans = [Span(s.start - s_start, s.end - s_start, s.text, s.candidates, s.fuzzy, s.score)
                 for s in seg_spans]
        # leading noise ("ảnh", "hình ảnh"...) only if it is not the start of an entity
        if not spans or spans[0].start > 0:
            o2, f2 = _strip_leading(o, f)
            shift = len(f) - len(f2)
            if shift and (not spans or spans[0].start >= shift):
                o, f = o2, f2
                spans = [Span(s.start - shift, s.end - shift, s.text, s.candidates, s.fuzzy, s.score)
                         for s in spans]
        if not f:
            return None

        used = [False] * len(f)
        for s in spans:
            for k in range(s.start, s.end):
                used[k] = True

        # Relation phrases that appear before the first entity, read left to right;
        # the step nearest the entity is applied first.
        steps: list[RelationStep] = []
        first_entity = spans[0].start if spans else None
        if first_entity is not None:
            stripped = True
            while stripped:
                stripped = False
                for title in sorted(TITLES, key=len, reverse=True):
                    begin = first_entity - len(title)
                    if begin >= 0 and _match_at(f, begin, title):
                        for j in range(begin, first_entity):
                            used[j] = True
                        first_entity, stripped = begin, True
                        break
            k = 0
            while k < first_entity:
                for key in _REL_KEYS:
                    words = tuple(key.split())
                    if k + len(words) <= first_entity and _match_at(f, k, words):
                        steps.append(RELATION_PHRASES[key])
                        for j in range(k, k + len(words)):
                            used[j] = True
                        k += len(words)
                        break
                else:
                    if f[k] in FILLER and steps:
                        used[k] = True
                    k += 1
            steps.reverse()

        # "A chụp cùng B": same-photo conjunction
        operator = "any"
        if len(spans) >= 2:
            for k in range(spans[0].end, spans[1].start):
                for phrase in TOGETHER_PHRASES:
                    if _match_at(f, k, phrase):
                        operator = "all"
                        for j in range(k, min(k + len(phrase), len(f))):
                            used[j] = True
            if operator == "any":
                operator = "all"  # two names in one segment with no separator: same photo

        rest_o = [w for w, u in zip(o, used) if not u]
        rest_f = [w for w, u in zip(f, used) if not u]
        while rest_f and rest_f[0] in FILLER | VISUAL_STOP:
            rest_o, rest_f = rest_o[1:], rest_f[1:]
        visual = " ".join(rest_o).strip()
        lexical = " ".join(w for w in rest_f if w not in VISUAL_STOP)

        seeds, ambiguous, fuzzy = [], [], False
        for s in spans:
            fuzzy = fuzzy or s.fuzzy
            if s.ambiguous:
                ambiguous.append(s)
            else:
                seeds.append(s.candidates[0])
        label = " ".join(o)
        return Intent(label=label, seeds=seeds, entity_operator=operator if len(seeds) > 1 else "any",
                      relation_steps=steps, visual_text=visual, lexical_text=lexical,
                      ambiguous=ambiguous, fuzzy=fuzzy)
