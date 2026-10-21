from pathlib import Path

import pytest

from app.jobs.import_csv import canonical_rows, load_profile, resolve_columns
from app.services.entity_linker import AliasIndex, EntityRef
from app.services.query_parser import RuleParser
from app.services.relations import Hop
from app.services.retriever import fuse_rrf
from app.services.search import SearchService
from app.textnorm import fold, norm

FIXTURES = Path(__file__).parent / "fixtures"


def test_fold_removes_diacritics_and_d():
    assert fold("Phạm Nhật Vượng") == "pham nhat vuong"
    assert fold("Đen Vâu!") == "den vau"
    assert norm("  Hồ  Bơi, ") == "hồ bơi"


def test_rrf_rewards_agreement_and_dedups():
    fused = fuse_rrf([["a", "b", "c"], ["b", "a", "a"]])
    assert [i for i, _ in fused][:2] in (["a", "b"], ["b", "a"])
    assert len(fused) == 3


@pytest.mark.parametrize("name", ["crawl_sample.csv", "approver_sample.csv"])
def test_both_schemas_map_to_same_contract(name):
    rows = [r for _, r in canonical_rows(FIXTURES / name, load_profile()) if r]
    assert rows
    assert {"entity_key", "canonical_name", "approval_status", "image_url"} <= rows[0].keys()
    assert {r["approval_status"] for r in rows} <= {"approved", "rejected", "unknown"}


def test_reordered_columns_still_resolve():
    profile = load_profile()
    mapping = resolve_columns(["status", "image_url", "canonical_name", "entity_id"], profile)
    assert mapping["approval_status"] == "status"
    with pytest.raises(ValueError):
        resolve_columns(["image_url", "canonical_name"], profile)  # no id, no status


def _index():
    rows = []

    def add(i, name, etype="person", gender=None, aliases=()):
        for a in (name, *aliases):
            rows.append(dict(entity_id=f"00000000-0000-0000-0000-00000000000{i}", canonical_name=name,
                             entity_type=etype, gender=gender, alias_fold=fold(a)))

    add(1, "Phạm Nhật Vượng", gender="male")
    add(2, "Sơn Tùng M-TP")
    add(3, "Phú Quốc", "place")
    add(4, "Hà Anh Tuấn")
    add(5, "Vingroup", "organization")
    add(6, "Lê Anh")
    add(7, "Lê Anh", gender="female")
    add(8, "Anh Trần Đăng Tuấn")       # names starting with "Anh"/"Ánh" used to swallow the word "ảnh"
    add(9, "Trần Minh Dũng")
    add(10, "Ánh Minh")
    add(11, "Minh Tuyết")
    return AliasIndex.from_rows(rows)


@pytest.fixture
def parser():
    idx = _index()
    return RuleParser(lambda: idx)


def test_single_with_visual(parser):
    plan = parser.parse("ảnh Sơn Tùng đang biểu diễn trên sân khấu")
    assert plan.query_type == "single"
    (it,) = plan.intents
    assert [s.name for s in it.seeds] == ["Sơn Tùng M-TP"]  # weak alias from leading tokens
    assert it.visual_text == "biểu diễn trên sân khấu"


def test_multi_intent_shares_location(parser):
    plan = parser.parse("hồ bơi và công viên nước ở Phú Quốc")
    assert plan.query_type == "multi_intent"
    assert plan.location and plan.location.name == "Phú Quốc"
    assert [it.visual_text for it in plan.intents] == ["hồ bơi ở phú quốc", "công viên nước ở phú quốc"]


def test_same_photo_vs_two_groups(parser):
    together = parser.parse("Sơn Tùng chụp cùng Hà Anh Tuấn")
    assert len(together.intents) == 1 and together.intents[0].entity_operator == "all"
    groups = parser.parse("ảnh Sơn Tùng và Hà Anh Tuấn")
    assert len(groups.intents) == 2 and groups.combine == "groups"
    union = parser.parse("Sơn Tùng hoặc Hà Anh Tuấn")
    assert union.combine == "union"


def test_title_is_not_a_relation(parser):
    plan = parser.parse("ảnh con trai chủ tịch Phạm Nhật Vượng")
    (it,) = plan.intents
    assert plan.query_type == "multi_hop"
    assert [(s.predicate, s.direction, s.gender) for s in it.relation_steps] == [("parent_of", "out", "male")]


def test_former_spouse_and_titles(parser):
    plan = parser.parse("vợ cũ của bầu Phạm Nhật Vượng")
    (it,) = plan.intents
    assert [s.name for s in it.seeds] == ["Phạm Nhật Vượng"] and not it.visual_text
    assert [(s.predicate, s.gender) for s in it.relation_steps] == [("spouse_of", "female")]


def test_sibling_phrases(parser):
    for q, gender in (("em gái của Phạm Nhật Vượng", "female"), ("anh trai của Phạm Nhật Vượng", "male"),
                      ("ảnh chị gái Phạm Nhật Vượng", "female")):
        (it,) = parser.parse(q).intents
        assert [s.name for s in it.seeds] == ["Phạm Nhật Vượng"] and not it.visual_text, q
        assert [(s.predicate, s.gender) for s in it.relation_steps] == [("sibling_of", gender)], q


def test_two_hop_order(parser):
    plan = parser.parse("con trai của người sáng lập Vingroup")
    steps = plan.intents[0].relation_steps
    assert [s.predicate for s in steps] == ["founded", "parent_of"]  # nearest to the entity first


def test_ambiguous_name_is_not_guessed(parser):
    plan = parser.parse("ảnh Lê Anh")
    (it,) = plan.intents
    assert not it.seeds and it.ambiguous and len(it.ambiguous[0].candidates) == 2


@pytest.mark.parametrize("query,name", [
    ("ảnh Trần Minh Dũng", "Trần Minh Dũng"),
    ("ảnh Minh Tuyết", "Minh Tuyết"),
    ("tìm ảnh Minh Tuyết", "Minh Tuyết"),
    ("anh minh tuyet", "Minh Tuyết"),
])
def test_photo_word_is_not_part_of_a_name(parser, query, name):
    plan = parser.parse(query)
    assert plan.query_type == "single"
    (it,) = plan.intents
    assert [s.name for s in it.seeds] == [name] and not it.ambiguous


def test_name_starting_with_anh_still_found(parser):
    assert [s.name for s in parser.parse("ảnh Ánh Minh").intents[0].seeds] == ["Ánh Minh"]
    assert [s.name for s in parser.parse("Anh Trần Đăng Tuấn").intents[0].seeds] == ["Anh Trần Đăng Tuấn"]


def test_edit_distance():
    from app.services.entity_linker import edit_distance
    assert edit_distance("tuan puong", "tuan phuong") == 1
    assert edit_distance("bac ho", "ho bac") > 2


def test_name_without_diacritics(parser):
    plan = parser.parse("pham nhat vuong")
    assert plan.intents[0].seeds[0].name == "Phạm Nhật Vượng"


def test_chain_to_target():
    hops = [Hop("o", "Org", "p", "Bố", "founded", "người sáng lập", "u"),
            Hop("p", "Bố", "c1", "Con 1", "parent_of", "con trai", "u"),
            Hop("p", "Bố", "c2", "Con 2", "parent_of", "con trai", "u")]
    chain = SearchService._chain_to(hops, "c2")
    assert [h.to_id for h in chain] == ["p", "c2"]


def test_inline_data_url_is_dropped(tmp_path):
    src = tmp_path / "inline.csv"
    src.write_text("entity_id,canonical_name,image_url,status\n"
                   "e1,Mỹ Tâm,\"data:image/png;base64," + "A" * 9000 + "\",approved\n"
                   "e1,Mỹ Tâm,https://x.test/a.jpg,approved\n", encoding="utf-8")
    rows = [r for _, r in canonical_rows(src, load_profile())]
    assert rows[0] == {"url_dropped": True}
    assert rows[1]["image_url"] == "https://x.test/a.jpg" and not rows[1]["url_dropped"]


def test_duplicate_entity_with_same_name_is_one_person():
    from app.services.entity_linker import EntityRef, Span
    from app.services.query_parser import Intent, QueryPlan
    from app.services.search import SearchService

    dup = [EntityRef("a", "Phúc Du", "person", None), EntityRef("b", "Phúc Du", "person", None)]
    plan = QueryPlan(query="Phúc Du", intents=[Intent(label="Phúc Du", ambiguous=[Span(0, 2, "phuc du", dup)])])
    blocking, refine = SearchService._resolve_ambiguity(None, plan, set())
    assert blocking == [] and refine == []
    assert [s.entity_id for s in plan.intents[0].seeds] == ["a", "b"]


def test_downloader_backs_off_on_403_then_recovers(monkeypatch):
    import asyncio
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from types import SimpleNamespace

    import httpx

    from app.jobs import download as D

    hits = {"n": 0}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            hits["n"] += 1
            code = 403 if hits["n"] <= 2 else 200  # refuse twice, like a rate-limited CDN
            self.send_response(code)
            self.end_headers()
            self.wfile.write(b"img")

        def log_message(self, *a):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setattr(D, "COOLDOWN_BASE", 0.05)
    settings = SimpleNamespace(download_concurrency=4, download_per_host=2, download_host_rps=100.0,
                               download_max_bytes=1000)

    async def go():
        dl = D.Downloader(settings, None)
        async with httpx.AsyncClient() as client:
            data = await dl.fetch_bytes(client, f"http://127.0.0.1:{server.server_port}/a.jpg")
        return dl, data

    try:
        dl, data = asyncio.run(go())
    finally:
        server.shutdown()
    assert data == b"img" and dl.stats["throttled"] == 2
    assert dl.host_interval["127.0.0.1"] == 4 / 100.0  # rate halved twice


def test_embed_isolates_an_image_the_encoder_rejects():
    from app.jobs.embed import encode_safely

    class Fussy:
        def encode_images(self, images):
            if any(im == "bad" for im in images):
                raise ValueError("cannot handle this data type")
            return [[1.0] for _ in images]

    vectors, ids, bad = encode_safely(Fussy(), ["ok1", "bad", "ok2"], ["a", "b", "c"])
    assert ids == ["a", "c"] and bad == 1 and len(vectors) == 2


def test_unknown_relation_never_returns_the_person_themself(parser):
    plan = parser.parse("bạn thân của Phạm Nhật Vượng")
    (it,) = plan.intents
    assert plan.query_type == "multi_hop" and it.unknown_relation == "bạn thân của"


def test_relation_word_after_and_refers_to_the_previous_person(parser):
    plan = parser.parse("Phạm Nhật Vượng và vợ")
    first, second = plan.intents
    assert [s.name for s in second.seeds] == ["Phạm Nhật Vượng"]
    assert [(s.predicate, s.gender) for s in second.relation_steps] == [("spouse_of", "female")]


def test_comma_separates_people(parser):
    plan = parser.parse("Sơn Tùng, Hà Anh Tuấn")
    assert [[s.name for s in it.seeds] for it in plan.intents] == [["Sơn Tùng M-TP"], ["Hà Anh Tuấn"]]


def test_crawled_titles_and_suffixes_become_usable_aliases():
    from app.services.entity_linker import person_key
    rows = [dict(entity_id=f"00000000-0000-0000-0000-0000000001{i:02d}", canonical_name=n, entity_type="person",
                 gender=None, alias_fold=fold(n))
            for i, n in enumerate(["Ca sĩ Bằng Kiều", "Mỹ Tâm (queen Vpop)", "Ông nội Tăng Thanh Hà bồng cháu",
                                   *[f"Nguyễn Văn {c}" for c in "ABCDEFGHIJ"]])]
    idx = AliasIndex.from_rows(rows)
    assert [r.name for r in idx.by_alias["bang kieu"]] == ["Ca sĩ Bằng Kiều"]
    assert [r.name for r in idx.by_alias["my tam"]] == ["Mỹ Tâm (queen Vpop)"]
    assert "ca si" not in idx.by_alias and "ong noi" not in idx.by_alias  # titles never match on their own
    assert "nguyen van" not in idx.by_alias  # a prefix shared by 10 people is not a name
    assert person_key("Mỹ Tâm (queen Vpop)") == person_key("Ca sĩ Mỹ Tâm") == person_key("Mỹ Tâm")
    assert person_key("Cặp đôi MC Trấn Thành - Hari Won") == person_key("Trấn Thành")  # titles stack
    assert person_key("Trấn Thành") != person_key("Trần Thành")  # same letters, another person
    assert person_key("Mâu Thuỷ") == person_key("Mâu Thủy")  # the same mark written on another letter


def test_a_name_finds_every_crawled_entity_of_that_person():
    rows = [dict(entity_id=f"00000000-0000-0000-0000-0000000002{i:02d}", canonical_name=n, entity_type="person",
                 gender=None, alias_fold=fold(n))
            for i, n in enumerate(["MC Trấn Thành", "Cặp đôi MC Trấn Thành - Hari Won", "Trần Thành (bột ngọt)",
                                   "Nguyễn Bảo", "Nguyễn Bảo (nhà văn)", "Trần Xuân Bách (y học)"])]
    idx = AliasIndex.from_rows(rows)
    assert {r.name for r in idx.by_alias["mc tran thanh"]} == {"MC Trấn Thành", "Cặp đôi MC Trấn Thành - Hari Won"}
    assert {r.name for r in idx.by_alias["nguyen bao"]} == {"Nguyễn Bảo", "Nguyễn Bảo (nhà văn)"}
    assert idx.one_letter_off("trn xuan bach") == ["tran xuan bach"]  # a derived alias, not stored in the DB
    assert idx.one_letter_off("tran xuan") == []  # a word count that differs is not a typo


def test_a_name_shared_by_duplicate_entities_is_still_its_own_intent():
    rows = [dict(entity_id=f"00000000-0000-0000-0000-0000000003{i:02d}", canonical_name=n, entity_type="person",
                 gender=None, alias_fold=fold(n))
            for i, n in enumerate(["Thành Lộc", "Mạc Mai Sương (indie)", "Mạc Mai Sương (ca sĩ)"])]
    idx = AliasIndex.from_rows(rows)
    plan = RuleParser(lambda: idx).parse("Thành Lộc, Mạc Mai Sương")
    assert len(plan.intents) == 2 and len(plan.intents[1].ambiguous[0].candidates) == 2


def test_a_name_nobody_has_is_reported_not_guessed(parser):
    for q in ("ảnh Jack Ma", "Taylor Swift", "Tuấn Anh Hà", "ảnh Thị Mỹ Tâm", "Tập Cận Bình",
              "ảnh Tập Cận Bình đang phát biểu"):
        assert any(it.unknown_name for it in parser.parse(q).intents), q
    for q in ("Ảnh Minh Tuyết", "Minh Tuyết đang hát", "MC Minh Tuyết", "HLV Minh Tuyết", "TAYLOR SWIFT", "taylor swift",
              "ảnh Hồ Gươm", "Sơn Tùng M-TP ở Hà Nội",
              "Chùa Một Cột", "người mặc áo dài", "Bãi Biển Mỹ Khê"):
        assert not any(it.unknown_name for it in parser.parse(q).intents), q


def test_kinship_without_gender_or_with_ruot(parser):
    cases = {"em của Minh Tuyết": ("sibling_of", None), "chị của Minh Tuyết": ("sibling_of", "female"),
             "anh của Minh Tuyết": ("sibling_of", "male"), "anh chị em ruột của Minh Tuyết": ("sibling_of", None),
             "em gái ruột của Minh Tuyết": ("sibling_of", "female"), "con ruột của Minh Tuyết": ("parent_of", None),
             "mẹ ruột của Minh Tuyết": ("parent_of", "female"), "bà xã của Minh Tuyết": ("spouse_of", "female"),
             "ông xã của Minh Tuyết": ("spouse_of", "male")}
    for q, step in cases.items():
        (it,) = parser.parse(q).intents
        assert [(s.predicate, s.gender) for s in it.relation_steps] == [step], q
        assert [s.name for s in it.seeds] and not it.unknown_relation, q


def test_anh_cua_is_a_photo_unless_written_as_the_word_anh(parser):
    for q in ("ảnh của Minh Tuyết", "anh cua minh tuyet", "em Minh Tuyết", "chị Minh Tuyết"):  # photo, or a title before the name
        (it,) = parser.parse(q).intents
        assert not it.relation_steps and [s.name for s in it.seeds] == ["Minh Tuyết"], q
    assert parser.parse("ảnh").intents[0].relation_steps == []


def test_typo_must_keep_the_accents_it_was_typed_with():
    from app.services.query_parser import _typo_keeps_accents
    bao_dai = [EntityRef("e1", "Bảo Đại", "person", "male")]
    assert not _typo_keeps_accents(["áo", "dài"], bao_dai)        # "người mặc áo dài"
    assert not _typo_keeps_accents(["đang", "hát"], [EntityRef("e2", "Đặng Tất", "person", "male")])
    assert _typo_keeps_accents(["ao", "dai"], bao_dai)            # typed without accents: no evidence either way
    assert _typo_keeps_accents(["trn", "thị", "thùy", "dung"],
                               [EntityRef("e3", "Trần Thị Thùy Dung", "person", "female")])
    # "Xuân Bắc" (not in the data) is another person than "Xuân Ba", not a typo of it
    assert not _typo_keeps_accents(["xuân", "bắc"], [EntityRef("e4", "Xuân Ba", "person", "male")])
    # only the matched part of a longer name counts: "nhạc sĩ" says nothing about "vân dung"
    assert not _typo_keeps_accents(["vân", "dung"], [EntityRef("e6", "Nhạc sĩ Vân Đông", "person", "male")])


def test_name_typed_with_other_accents_is_another_person():
    names = ["Nhạc sĩ Văn Dung", "Xuân Ba", "Phạm Minh Hằng", "Mỹ Tâm"]
    rows = [{"alias_fold": fold(n.replace("Nhạc sĩ ", "")), "entity_id": f"e{i}", "canonical_name": n,
             "entity_type": "person", "gender": None} for i, n in enumerate(names)]
    idx = AliasIndex.from_rows(rows)
    parser = RuleParser(lambda: idx)
    # someone whose name differs only in accents is offered for confirmation, never searched directly
    for q, name in (("Vân Dung", "Nhạc sĩ Văn Dung"), ("Phạm Minh Hàng", "Phạm Minh Hằng"),
                    ("ảnh Vân Dung đang cười", "Nhạc sĩ Văn Dung")):
        it = parser.parse(q).intents[0]
        assert not it.seeds and [c.name for s in it.ambiguous for c in s.candidates] == [name], q
        assert all(s.confirm for s in it.ambiguous), q
    # the same accents, or none typed, still find the person
    for q, name in (("Văn Dung", "Nhạc sĩ Văn Dung"), ("van dung", "Nhạc sĩ Văn Dung"), ("Mỹ Tâm", "Mỹ Tâm"),
                    ("my tam", "Mỹ Tâm")):
        assert [s.name for s in parser.parse(q).intents[0].seeds] == [name], q


def test_accents_pick_the_person_a_shared_alias_hides():
    # "tuan hung" is Tuấn Hưng's alias; Tuấn Hùng is only reachable through "Tuấn Hùng (Bức Tường)"
    names = [("Tuấn Hưng", "tuan hung"), ("Tuấn Hùng (Bức Tường)", "tuan hung buc tuong"),
             ("Nguyễn Hòa Bình", "nguyen hoa binh")]
    rows = [{"alias_fold": a, "entity_id": f"e{i}", "canonical_name": n, "entity_type": "person", "gender": None}
            for i, (n, a) in enumerate(names)]
    parser = RuleParser(lambda: AliasIndex.from_rows(rows))
    for q, name in (("Tuấn Hùng", "Tuấn Hùng (Bức Tường)"), ("Tuấn Hưng", "Tuấn Hưng"), ("tuan hung", "Tuấn Hưng"),
                    ("Nguyễn Hoà Bình", "Nguyễn Hòa Bình")):  # "Hoà" and "Hòa" are one spelling in two styles
        assert [s.name for s in parser.parse(q).intents[0].seeds] == [name], q


def test_name_without_its_surname_asks_for_the_person():
    names = ["Tạ Quang Thắng", "Tạ Quang Thắng (rock/pop-rock)", "Mỹ Tâm"]
    rows = [{"alias_fold": fold(n.split(" (")[0]), "entity_id": f"e{i}", "canonical_name": n,
             "entity_type": "person", "gender": None} for i, n in enumerate(names)]
    parser = RuleParser(lambda: AliasIndex.from_rows(rows))
    # typed capitalised, lowercase, without accents or after "ảnh": ask, never search it as a description
    for q in ("Quang Thắng", "quang thắng", "quang thang", "ảnh Quang Thắng", "Quang Thắng đang hát"):
        it = parser.parse(q).intents[0]
        assert not it.seeds and not it.unknown_name, q
        assert [(s.confirm, [c.name for c in s.candidates]) for s in it.ambiguous] == [(True, names[:2])], q
    # other accents are another person; a name ending nobody's name is still unknown
    assert parser.parse("Quang Thẳng").intents[0].unknown_name == "quang thẳng"
    assert parser.parse("Jack Ma").intents[0].unknown_name == "jack ma"


def test_label_names_each_person_once():
    from app.services.search import _short_names
    refs = [EntityRef(f"e{i}", n, "person", None) for i, n in enumerate(
        ["Chân dung studio Phạm Nhật Vượng Forbes", "Phạm Nhật Vượng", "Mỹ Linh (ca sĩ)", "Mỹ Linh", "Đen Vâu"])]
    assert _short_names(refs) == "Mỹ Linh, Đen Vâu, Phạm Nhật Vượng"


def test_tone_mark_placement_styles_are_one_spelling():
    from app.textnorm import tone_style
    assert tone_style("hoà bình thuỷ khoẻ uỷ") == "hòa bình thủy khỏe ủy"
    for word in ("quý", "hoàng", "toán", "thuế", "nguyễn", "hoa"):
        assert tone_style(word) == word


def test_description_pieces_for_partial_caption_match():
    from app.services.retriever import _units
    assert _units("ca si dang hat tren san khau") == ["ca <-> si", "san <-> khau", "hat"]
    assert _units("nguoi mac ao dai") == ["mac <-> ao", "ao <-> dai"]
    # "công viên" is also Văn Công Viễn once accents are gone: neither the pair nor its words count alone
    assert _units("cong vien nuoc", {"cong vien"}) == ["vien <-> nuoc"]
    assert _units("anh") == []


def test_full_name_not_in_data_is_not_cut_to_a_look_alike():
    names = ["Nguyễn Chí Thiện", "Nguyễn Chí Dũng", "Lê Văn Thanh", "Trần Thanh", "Phạm Thị Thanh", "Sơn Tùng M-TP"]
    rows = [{"alias_fold": fold(n), "entity_id": f"e{i}", "canonical_name": n, "entity_type": "person",
             "gender": None} for i, n in enumerate(names)]
    idx = AliasIndex.from_rows(rows)
    parser = RuleParser(lambda: idx)
    for q in ("Nguyễn Chí Thanh", "nguyen chi thanh", "ảnh nguyễn chí thanh đang phát biểu"):
        it = parser.parse(q).intents[0]
        assert it.unknown_name and not it.seeds and not it.ambiguous, q
    # the first words alone still offer the people they open, and a description after them stays a description
    assert parser.parse("Nguyễn Chí").intents[0].ambiguous
    it = parser.parse("Sơn Tùng đang hát").intents[0]
    assert [s.name for s in it.seeds] == ["Sơn Tùng M-TP"] and not it.unknown_name


def test_relation_of_a_one_word_name_nobody_has_is_not_a_description():
    rows = [{"alias_fold": fold(n), "entity_id": f"e{i}", "canonical_name": n, "entity_type": "person",
             "gender": None} for i, n in enumerate(["Mỹ Tâm", "Sơn Tùng M-TP"])]
    parser = RuleParser(lambda: AliasIndex.from_rows(rows))
    for q in ("con trai của Bear", "ông nội của Bear", "bạn thân của Trang"):
        it = parser.parse(q).intents[0]
        assert it.unknown_name and not it.seeds, q
    # a photo of someone, a place, or a known name after "của" are not flagged
    for q in ("ảnh của Bear", "áo dài của Huế", "con gái của Mỹ Tâm"):
        assert not parser.parse(q).intents[0].unknown_name, q
