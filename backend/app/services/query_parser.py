"""Rule-based query planner (no LLM on the common path).

A query becomes a QueryPlan: up to 3 intents, each with seed entities, an optional chain
of relation steps (max 2 hops), residual visual text and an optional shared location.
Parsing works on diacritic-folded tokens but keeps the original words for the encoder.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace

from ..textnorm import cased_tokens, fold, norm, tone_style
from .entity_linker import _NAME_TAIL, AliasIndex, EntityRef, Span, edit_distance

MAX_INTENTS = 3
MAX_HOPS = 2


@dataclass(frozen=True)
class RelationStep:
    predicate: str           # parent_of | spouse_of | sibling_of | founded | member_of | located_in
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
    "anh trai": RelationStep("sibling_of", "both", "male", "anh trai"),
    "em trai": RelationStep("sibling_of", "both", "male", "em trai"),
    "chi gai": RelationStep("sibling_of", "both", "female", "chị gái"),
    "em gai": RelationStep("sibling_of", "both", "female", "em gái"),
    "anh em": RelationStep("sibling_of", "both", None, "anh chị em"),
    "anh chi em": RelationStep("sibling_of", "both", None, "anh chị em"),
    "chi em": RelationStep("sibling_of", "both", None, "anh chị em"),
    "anh chi": RelationStep("sibling_of", "both", None, "anh chị"),
    # "em của X", "chị của X": before a name these are titles ("chị Mỹ Tâm"), and TITLES are stripped first,
    # so they only count as relations when "của" (or another word) separates them from the name.
    # Anh/chị/em say who is older, which the data does not record: every sibling of that gender is returned.
    "em": RelationStep("sibling_of", "both", None, "em"),
    "chi": RelationStep("sibling_of", "both", "female", "chị"),
    "anh": RelationStep("sibling_of", "both", "male", "anh"),  # only written "anh", see _anh_is_relation
    "em ruot": RelationStep("sibling_of", "both", None, "em ruột"),
    "chi ruot": RelationStep("sibling_of", "both", "female", "chị ruột"),
    "anh ruot": RelationStep("sibling_of", "both", "male", "anh ruột"),
    "em gai ruot": RelationStep("sibling_of", "both", "female", "em gái ruột"),
    "em trai ruot": RelationStep("sibling_of", "both", "male", "em trai ruột"),
    "chi gai ruot": RelationStep("sibling_of", "both", "female", "chị gái ruột"),
    "anh trai ruot": RelationStep("sibling_of", "both", "male", "anh trai ruột"),
    "con ruot": RelationStep("parent_of", "out", None, "con ruột"),
    "con trai ruot": RelationStep("parent_of", "out", "male", "con trai ruột"),
    "con gai ruot": RelationStep("parent_of", "out", "female", "con gái ruột"),
    "bo ruot": RelationStep("parent_of", "in", "male", "bố ruột"),
    "cha ruot": RelationStep("parent_of", "in", "male", "cha ruột"),
    "me ruot": RelationStep("parent_of", "in", "female", "mẹ ruột"),
    "ba xa": RelationStep("spouse_of", "both", "female", "bà xã"),
    "ong xa": RelationStep("spouse_of", "both", "male", "ông xã"),
    "phu nhan": RelationStep("spouse_of", "both", "female", "phu nhân"),
    "vo cu": RelationStep("spouse_of", "both", "female", "vợ cũ"),
    "chong cu": RelationStep("spouse_of", "both", "male", "chồng cũ"),
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
FILLER = {"cua", "la", "ong", "ba", "anh", "chi", "cac", "nhung", "nguoi", "ruot"}  # "ruột": "em ruột của X"
PHOTO_WORDS = {"ảnh", "hình", "tấm", "bức", "tìm"}
LEADING_NOISE = [("hinh", "anh"), ("buc", "anh"), ("tam", "anh"), ("anh",), ("hinh",), ("cho", "toi"),
                 ("tim",), ("tim", "kiem"), ("nhung",), ("cac",)]
# Titles written right before a name are apposition, not relations: "con trai chủ tịch Phạm Nhật Vượng".
TITLES = [("chu", "tich"), ("ty", "phu"), ("doanh", "nhan"), ("ca", "si"), ("nhac", "si"), ("dien", "vien"),
          ("nguoi", "mau"), ("rapper",), ("ong",), ("ba",), ("co",), ("chi",), ("anh",), ("em",),
          ("tap", "doan"), ("cong", "ty"), ("nhom", "nhac"), ("ban", "nhac"), ("nhom",), ("thanh", "pho"),
          ("tinh",), ("dao",), ("bau",), ("gs",), ("ts",), ("giao", "su"), ("nsnd",), ("nsut",), ("mc",)]
GROUP_SEPARATORS = {"va", "hoac", "voi", ","}
TOGETHER_PHRASES = [("chup", "cung"), ("chup", "chung", "voi"), ("chung", "voi"), ("cung", "voi"),
                    ("ben", "canh"), ("cung",)]
LOCATION_MARKERS = {"o", "tai"}
VISUAL_STOP = {"dang", "dep", "cua", "cac", "nhung", "mot", "nhieu"}
# Capitalised words that open a query without being part of a name: "Ảnh ...", "Vợ ...", "Chủ Tịch ..."
_NOT_NAME = (FILLER | VISUAL_STOP | GROUP_SEPARATORS | LOCATION_MARKERS | {fold(w) for w in PHOTO_WORDS}
             | {w for k in RELATION_PHRASES for w in k.split()} | {w for t in TITLES for w in t}
             | {w for t in TOGETHER_PHRASES for w in t} | {"cuu", "danh", "thu", "hlv"})
# Common family names, to tell "Thành Văn Lương" (a name nobody in the data has) from "Hồ Gươm" (a place).
# Hồ, Hà, Cao, Mai also open place names ("Hồ Gươm", "Hà Giang") and count only as the last word.
SURNAMES = {"nguyen", "tran", "le", "pham", "hoang", "huynh", "phan", "vu", "vo", "dang", "bui", "do", "ngo",
            "duong", "ly", "dinh", "trinh", "truong", "luong", "lam", "quach", "chu", "kieu", "doan", "thai",
            "tang", "lu", "ton", "dao", "trieu", "luu", "ta", "la"}
LAST_WORD_SURNAMES = SURNAMES | {"ho", "ha", "cao", "mai"}
# Words that open the name of a place or thing, compared with their accents: "Hồ Gươm", "Chùa Một Cột",
# "Trường Sa" are searched by look; "Tập Cận Bình", "Trương Gia Bình" are names of people.
PLACE_WORDS = {"hồ", "vịnh", "núi", "chùa", "đền", "cầu", "phố", "sông", "biển", "bãi", "đảo", "thành", "tỉnh",
               "quận", "chợ", "nhà", "cung", "lăng", "tháp", "động", "hang", "thác", "đèo", "cổng", "trường",
               "viện", "đại", "khu", "làng", "phường", "xã", "huyện", "sân", "khách", "tòa", "đồi", "rừng",
               "vườn", "công", "bảo", "hội", "lễ", "tết", "giải", "cúp", "festival", "concert", "tour", "show"}


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
    unknown_relation: str = ""     # "bạn thân của X": a relation the system cannot answer, never X's own photos
    unknown_name: str = ""         # "Jack Ma", "Taylor Swift": a name nobody in the data has, never a look-alike
    inherits_seeds: bool = False   # "Trấn Thành và vợ": the relation applies to the previous intent's person


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


# Words that, before "của", ask about a person: relation words plus ones the rules do not support ("bạn thân").
# "anh" is left out: "ảnh của Bear" (a photo of Bear) folds to the same text.
_PEOPLE_WORDS = ({w for k in RELATION_PHRASES for w in k.split()} - {"anh"}) \
    | {"ban", "than", "chau", "noi", "ngoai", "ong", "ba", "nguoi", "yeu"}


def _match_at(tokens: list[str], i: int, phrase: tuple[str, ...]) -> bool:
    return tuple(tokens[i:i + len(phrase)]) == phrase


def _relation_allowed(key: str, o: list[str], f: list[str], k: int) -> bool:
    """A relation phrase opening with "anh" must be written "anh", never "ảnh" ("ảnh chị gái X" is a photo of
    X's sister, not "anh chị" + "gái"); a lone "anh" also needs _anh_is_relation."""
    if not key.startswith("anh"):
        return True
    if k < len(o) and o[k] != "anh":
        return False
    return key != "anh" or _anh_is_relation(o, f, k)


def _anh_is_relation(o: list[str], f: list[str], k: int) -> bool:
    """"anh của X" asks for X's brother, "ảnh của X" for photos of X. Typed without any diacritics the two are
    the same text, which is read as "photo"; written "anh" in an accented query and followed by "của", it is
    the brother."""
    return (f[k] == "anh" and k < len(o) and o[k] == "anh" and k + 1 < len(f) and f[k + 1] == "cua"
            and any(fold(w) != w for w in o))


def _relations_only(f: list[str]) -> list[RelationStep]:
    """The steps when a segment is nothing but relation phrases ("vợ", "con trai của"), else []."""
    steps, k = [], 0
    while k < len(f):
        for key in _REL_KEYS:
            words = tuple(key.split())
            if key == "anh":  # a lone "anh" is the word "ảnh" typed without accents far more often
                continue
            if _match_at(f, k, words):
                steps.append(RELATION_PHRASES[key])
                k += len(words)
                break
        else:
            if f[k] not in FILLER:
                return []
            k += 1
    return list(reversed(steps))


def _strip_leading(orig: list[str], folded: list[str]) -> tuple[list[str], list[str]]:
    changed = True
    while changed and folded:
        changed = False
        if any(len(k.split()) > 1 and _match_at(folded, 0, tuple(k.split())) and _relation_allowed(k, orig, folded, 0)
               for k in RELATION_PHRASES) or _anh_is_relation(orig, folded, 0):
            break  # "anh trai của X", "anh của X": "anh" is part of the relation, not the word "ảnh"
        for phrase in sorted(LEADING_NOISE, key=len, reverse=True):
            if _match_at(folded, 0, phrase):
                orig, folded = orig[len(phrase):], folded[len(phrase):]
                changed = True
                break
    return orig, folded


def _starts_phrase(folded: list[str], i: int) -> bool:
    """Whether the words from i on are a known non-name phrase: "thành viên", "thành phố", "đang", "ở"."""
    if folded[i] in FILLER | VISUAL_STOP | GROUP_SEPARATORS | LOCATION_MARKERS:
        return True
    phrases = [tuple(k.split()) for k in RELATION_PHRASES] + list(TITLES) + list(TOGETHER_PHRASES)
    return any(_match_at(folded, i, p) for p in phrases)


def _typo_keeps_accents(words: list[str], candidates) -> bool:
    """A typo changes a letter, not an accent: "áo dài" is one letter from "ao dai" -> "Bảo Đại" and
    "đang hát" from "Đặng Tất" once accents are dropped, but typed with accents they are far from both.
    Text typed without accents is compared without them, as the fuzzy match already did."""
    typed = tone_style(" ".join(words))
    if typed == fold(typed):
        return True
    for ref in candidates:
        marked = tone_style(norm(_NAME_TAIL.split(ref.name, 1)[0])).split()
        n = len(words)
        windows = [" ".join(marked[i:i + n]) for i in range(max(1, len(marked) - n + 1))]
        # compare with the part of the name the typo matched ("Vân Đông" in "Nhạc sĩ Vân Đông"), not any part
        plain = {w: edit_distance(fold(typed), fold(w)) for w in windows}
        best = min(plain.values())
        # a wrong or missing letter with the accents kept ("Trn" for "Trần"); a changed accent makes another
        # name: "Xuân Bắc" is not "Xuân Ba"
        if any(d == best and edit_distance(typed, w) <= d for w, d in plain.items()):
            return True
    return False


def _accents_agree(words: list[str], ref: EntityRef) -> bool:
    """Whether a name typed with accents is this person's name, not another that folds to the same letters:
    "Vân Dung" is not "Văn Dung", "Phạm Minh Hàng" is not "Phạm Minh Hằng". A word typed without accents
    matches any accents ("Van Dung" may be either), and a name only reachable through a nickname alias
    cannot be compared, so it is kept."""
    words = tone_style(" ".join(words)).split()  # "Hoà" is "Hòa"
    marked = tone_style(norm(_NAME_TAIL.split(ref.name, 1)[0])).split()
    n = len(words)
    windows = [marked[i:i + n] for i in range(len(marked) - n + 1)]
    aligned = [w for w in windows if [fold(x) for x in w] == [fold(x) for x in words]]
    if not aligned:
        return True
    return any(all(t == fold(t) or t == m for t, m in zip(words, w)) for w in aligned)


class RuleParser:
    def __init__(self, index_getter, fuzzy_lookup=None):
        self._index = index_getter
        self._fuzzy = fuzzy_lookup

    def parse(self, query: str) -> QueryPlan:
        text = query.replace(",", " và ").replace(";", " và ")  # punctuation is dropped by norm, keep the split
        orig = norm(text).split()
        folded = fold(text).split()
        index: AliasIndex = self._index()
        # "ảnh"/"hình" typed with diacritics at the start is the word "photo", never the name "Anh"
        masked = list(folded)
        for k, word in enumerate(orig[:2]):
            if word in PHOTO_WORDS:
                masked[k] = "#"
        cased = cased_tokens(text)
        if len(cased) != len(folded) or text.isupper():
            cased = []  # case tells names apart only in mixed-case text
        spans = index.find_spans(masked)
        spans = self._keep_typed_accents(spans, orig, folded, index)
        if self._fuzzy and (not spans or self._name_continues(spans, folded, cased)):
            lowercase = not any(w[:1].isupper() for w in cased_tokens(text))

            def accept(start, end, alias, refs):
                words = orig[start:end]
                if _typo_keeps_accents(words, refs):
                    return refs
                # "Nguyn Huy Dũng" is Nguyễn Huy Dũng (derived from "Nguyễn Huy Dũng (Thứ trưởng)"), not Dung
                return [r for r in index.shadowed.get(alias, []) if _typo_keeps_accents(words, [r])]

            typos = self._fuzzy(masked, lowercase=lowercase, accept=accept)
            spans = self._extend_by_typo(spans, typos)
        spans, cut = self._cut_short_names(spans, folded, index)
        unknown_names = self._unknown_names(spans, folded, cased) + cut + self._lone_name_after_cua(spans, folded, cased)
        spans, unknown_names = self._name_endings(spans, unknown_names, orig, masked, index)
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
            for a, b in unknown_names:
                if s_start <= a and b <= s_end:
                    intent.unknown_name = " ".join(orig[a:b])
                    intent.ambiguous = []  # nothing to choose from: the name asked for is not in the data
            if intent.inherits_seeds:
                if not intents or not (intents[-1].seeds or intents[-1].ambiguous):
                    intent.unknown_relation = intent.label  # "vợ" alone: of whom?
                else:
                    intent.seeds, intent.ambiguous = list(intents[-1].seeds), list(intents[-1].ambiguous)
                    intent.label = f"{intent.label} của {intents[-1].label}"
            # "Sơn Tùng đang hát và nhảy": a short segment without entity extends the previous intent
            if intents and not intent.seeds and not intent.ambiguous and not intent.relation_steps \
                    and not intent.unknown_name \
                    and intents[-1].seeds \
                    and len(intent.lexical_text.split()) <= 2:
                prev = intents[-1]
                prev.visual_text = f"{prev.visual_text} và {intent.visual_text}".strip()
                prev.lexical_text = f"{prev.lexical_text} {intent.lexical_text}".strip()
                continue
            intents.append(intent)

        if not intents:
            words = [k for k, w in enumerate(orig) if w not in PHOTO_WORDS]  # "ảnh" alone describes nothing
            intents = [Intent(label=query, visual_text=" ".join(orig[k] for k in words),
                              lexical_text=" ".join(folded[k] for k in words))]
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
        if any(it.relation_steps or it.unknown_relation for it in intents):
            plan.query_type = "multi_hop"
        elif len(intents) > 1 or any(it.entity_operator == "all" for it in intents):
            plan.query_type = "multi_intent"
        return plan

    @staticmethod
    def _name_continues(spans: list[Span], folded: list[str], cased: list[str]) -> bool:
        """A word right next to a matched name may be part of a longer, mistyped one: "Pan Hà Thủy"."""
        covered = {k for s in spans for k in range(s.start, s.end)}
        for s in spans:
            for k in (s.start - 1, s.end):
                if 0 <= k < len(folded) and k not in covered and folded[k] not in _NOT_NAME \
                        and (not cased or cased[k][:1].isupper()):
                    return True
        return False

    @staticmethod
    def _extend_by_typo(spans: list[Span], typo: list[Span]) -> list[Span]:
        """Keep the exact matches unless a typo match covers one of them and more words."""
        if not spans:
            return typo
        for t in typo:
            inside = [s for s in spans if t.start <= s.start and s.end <= t.end]
            clash = [s for s in spans if s.start < t.end and t.start < s.end and s not in inside]
            if inside and not clash and t.end - t.start > max(s.end - s.start for s in inside):
                spans = sorted([s for s in spans if s not in inside] + [t], key=lambda s: s.start)
        return spans

    @staticmethod
    def _keep_typed_accents(spans: list[Span], orig: list[str], folded: list[str], index: AliasIndex) -> list[Span]:
        """Drop candidates whose accents differ from the ones typed, and bring in a person whose name only a
        derived alias spells that way ("Tuấn Hùng" is "Tuấn Hùng (Bức Tường)", not Tuấn Hưng). When none is
        left, the person typed is not in the data, but someone whose name differs only in accents is: offer
        them instead of searching."""
        kept = []
        for s in spans:
            words = orig[s.start:s.end]
            if all(w == fold(w) for w in words):
                kept.append(s)
                continue
            refs = [c for c in s.candidates if _accents_agree(words, c)]
            if not refs:
                refs = [c for c in index.shadowed.get(" ".join(folded[s.start:s.end]), []) if _accents_agree(words, c)]
            kept.append(replace(s, candidates=refs or s.candidates, confirm=not refs))
        return kept

    @staticmethod
    def _name_endings(spans: list[Span], unknown_names: list[tuple[int, int]], orig: list[str], masked: list[str],
                      index: AliasIndex) -> tuple[list[Span], list[tuple[int, int]]]:
        """"Quang Thắng" is nobody in the data, but it ends the name of Tạ Quang Thắng, and people are often
        called without their surname. Ask whether that person was meant rather than report an unknown name
        or, typed in lowercase as the whole query, search "quang thắng" as a description."""
        runs = list(unknown_names)
        if not spans and not runs:
            a = next((k for k, w in enumerate(masked) if w != "#"), len(masked))
            if 2 <= len(masked) - a <= 4:
                runs = [(a, len(masked))]  # the query is only the name ("ảnh quang thắng")
        for a, b in runs:
            refs = [r for r in index.endings.get(" ".join(masked[a:b]), []) if _accents_agree(orig[a:b], r)]
            if refs:
                spans = sorted(spans + [Span(a, b, " ".join(orig[a:b]), refs, confirm=True)], key=lambda s: s.start)
                unknown_names = [r for r in unknown_names if r != (a, b)]
        return spans, unknown_names

    @staticmethod
    def _cut_short_names(spans: list[Span], folded: list[str], index: AliasIndex):
        """"Nguyễn Chí Thanh" is nobody in the data, but its first words "Nguyễn Chí" open the names of
        Nguyễn Chí Thiện and Nguyễn Chí Dũng ("Trần Thanh Phong" likewise starts with "Trấn Thành" once accents
        are gone). When a matched name is followed by a word that ends many people's names and is not the start
        of another name, the person asked for is someone else: report the whole name as unknown rather than
        offer look-alike names and search "thanh" as a description. Works without capitals or accents."""
        kept, cut = [], []
        long_starts = {s.start for s in spans if s.end - s.start > 1}  # a one-word name ("Thanh") is no evidence
        ends = {s.end for s in spans}
        for s in spans:
            nxt = folded[s.end] if s.end < len(folded) else ""
            prev = folded[s.start - 1] if s.start > 0 else ""
            # "vợ thành viên" folds to "vo thanh vien", which opens Võ Thanh Hà's name: words that read as a
            # relation or title are left to the relation rules
            people = all(c.entity_type == "person" for c in s.candidates) and not _starts_phrase(folded, s.start)
            if people and nxt in index.given_names and s.end not in long_starts \
                    and not _starts_phrase(folded, s.end) and f"{s.text} {nxt}" not in index.by_alias:
                cut.append((s.start, s.end + 1))
            elif people and prev in SURNAMES and s.start not in ends and s.end - s.start >= 2 \
                    and not _starts_phrase(folded, s.start - 1) and f"{prev} {s.text}" not in index.by_alias:
                cut.append((s.start - 1, s.end))  # "Bùi Hải Linh" is not Hải Linh
            else:
                kept.append(s)
        cut_words = {k for a, b in cut for k in range(a, b)}
        return [s for s in kept if not cut_words & set(range(s.start, s.end))], cut

    @staticmethod
    def _lone_name_after_cua(spans: list[Span], folded: list[str], cased: list[str]) -> list[tuple[int, int]]:
        """"con trai của Bear", "bạn thân của Trang": a single capitalised word after "của", following a word about
        people, that matches no one. Without this the whole text became a description and returned photos of
        unrelated boys; a one-word name is too short for the multi-word checks in _unknown_names."""
        out = []
        if not cased:
            return out
        covered = {k for s in spans for k in range(s.start, s.end)}
        for k in range(2, len(folded)):
            w = cased[k]
            if folded[k - 1] != "cua" or k in covered or not w[:1].isupper() or (w.isupper() and len(w) > 1):
                continue
            if w.lower() in PLACE_WORDS or folded[k] in _NOT_NAME:
                continue
            if k + 1 < len(folded) and k + 1 not in covered and not _starts_phrase(folded, k + 1):
                continue  # "của Bear" must end the name; a longer run is _unknown_names' job
            if any(folded[j] in _PEOPLE_WORDS for j in range(max(0, k - 4), k - 1)):
                out.append((k, k + 1))
        return out

    @staticmethod
    def _unknown_names(spans: list[Span], folded: list[str], cased: list[str]) -> list[tuple[int, int]]:
        """Runs of capitalised words that read as a person's name but match no one in the data, either
        partly ("Jack Ma" is not "Jack", "Lý Hoàng Nam Phương" is not "Nam Phương") or not at all
        ("Thành Văn Lương"). Searching them by look would return strangers, so they are reported instead."""
        if not cased:
            return []
        covered = {k for s in spans for k in range(s.start, s.end)}

        def name_word(k: int) -> bool:
            w = cased[k]
            return w[:1].isupper() and not (w.isupper() and len(w) > 1)  # "HLV", "CEO" are not names

        runs, k = [], 0
        while k < len(cased):
            if not name_word(k):
                k += 1
                continue
            a = k
            while k < len(cased) and name_word(k):
                k += 1
            while a < k and folded[a] in _NOT_NAME and a not in covered:
                a += 1
            if k - a >= 2:
                runs.append((a, k))
        out = []
        for a, b in runs:
            loose = [j for j in range(a, b) if j not in covered]
            if not loose:
                continue
            if len(loose) < b - a:  # part of the run is a known name
                first_known = min(j for j in range(a, b) if j in covered)
                last_known = max(j for j in range(a, b) if j in covered)
                if any(j < first_known for j in loose) or (len(loose) == 1 and loose[0] == last_known + 1):
                    out.append((a, b))
                continue
            words = folded[a:b]
            ascii_name = all(cased[j].isascii() and cased[j].isalpha() for j in range(a, b))
            # the run stands alone, between the query's edges or words like "ảnh", "và", "đang": "Tập Cận Bình"
            alone = (a == 0 or folded[a - 1] in _NOT_NAME) and (b == len(folded) or folded[b] in _NOT_NAME) \
                and b - a <= 4 and cased[a].lower() not in PLACE_WORDS
            if ascii_name or alone or words[0] in SURNAMES or words[-1] in LAST_WORD_SURNAMES \
                    or "thi" in words or "van" in words:
                out.append((a, b))
        return out

    def _parse_segment(self, orig, folded, s_start, s_end, seg_spans) -> Intent | None:
        o, f = orig[s_start:s_end], folded[s_start:s_end]
        spans = [replace(s, start=s.start - s_start, end=s.end - s_start)
                 for s in seg_spans]
        # leading noise ("ảnh", "hình ảnh"...) only if it is not the start of an entity
        if not spans or spans[0].start > 0:
            o2, f2 = _strip_leading(o, f)
            shift = len(f) - len(f2)
            if shift and (not spans or spans[0].start >= shift):
                o, f = o2, f2
                spans = [replace(s, start=s.start - shift, end=s.end - shift)
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
        if first_entity is None:
            only_relations = _relations_only(f)
            if only_relations:
                return Intent(label=" ".join(o), relation_steps=only_relations, inherits_seeds=True)
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
                    if not _relation_allowed(key, o, f, k):
                        continue
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

        # "bạn thân của X", "cháu của X": words before the name end in "của" but are no relation we know
        unknown = ""
        if first_entity is not None and "cua" in f[:first_entity]:
            before = [k for k in range(first_entity) if not used[k] and f[k] not in FILLER]
            if before:
                unknown = " ".join(o[before[0]:first_entity])

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
        return Intent(label=label, seeds=seeds, entity_operator=operator if len(spans) > 1 else "any",
                      relation_steps=steps, visual_text=visual, lexical_text=lexical,
                      ambiguous=ambiguous, fuzzy=fuzzy, unknown_relation=unknown)
