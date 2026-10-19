from pathlib import Path

import pytest

from app.jobs.import_csv import canonical_rows, load_profile, resolve_columns
from app.services.entity_linker import AliasIndex
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


def test_two_hop_order(parser):
    plan = parser.parse("con trai của người sáng lập Vingroup")
    steps = plan.intents[0].relation_steps
    assert [s.predicate for s in steps] == ["founded", "parent_of"]  # nearest to the entity first


def test_ambiguous_name_is_not_guessed(parser):
    plan = parser.parse("ảnh Lê Anh")
    (it,) = plan.intents
    assert not it.seeds and it.ambiguous and len(it.ambiguous[0].candidates) == 2


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
