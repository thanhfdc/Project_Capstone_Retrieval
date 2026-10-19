"""End-to-end test on the fixture corpus: import -> download -> embed -> finalize -> search.

Needs PostgreSQL with pgvector at DATABASE_URL (CI starts one). Uses the hash encoder.
"""
import functools
import http.server
import os
import shutil
import threading
from pathlib import Path

import psycopg
import pytest

FIXTURES = Path(__file__).parent / "fixtures"
DB = os.environ.get("DATABASE_URL", "")


def _db_available() -> bool:
    if not DB:
        return False
    try:
        psycopg.connect(DB, connect_timeout=2).close()
        return True
    except psycopg.Error:
        return False


pytestmark = pytest.mark.skipif(not _db_available(), reason="DATABASE_URL not reachable")


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    data = tmp_path_factory.mktemp("data")
    (data / "raw").mkdir()
    for csv_file in FIXTURES.glob("*.csv"):
        shutil.copy(csv_file, data / "raw")
    shutil.copytree(FIXTURES / "relations", data / "relations")
    # crawl rows use local files, approver rows must be downloaded over HTTP
    shutil.copytree(FIXTURES / "images", data / "raw" / "images")

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(FIXTURES / "images"))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 8765), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    os.environ.update(DATA_DIR=str(data), ENCODER_BACKEND="hash")
    from app.config import get_settings
    get_settings.cache_clear()
    with psycopg.connect(DB, autocommit=True) as conn:
        conn.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
    from app.jobs import pipeline
    assert pipeline.main([]) == 0
    server.shutdown()

    from fastapi.testclient import TestClient

    from app.main import app
    with TestClient(app) as c:
        yield c


def search(client, q, **kw):
    r = client.post("/api/search", json={"query": q, "top_k": 10, **kw})
    assert r.status_code == 200
    return r.json()


def names(result, group=0):
    g = result["groups"][group]
    return [{e["name"] for e in result["items"][i]["entities"]} for i in g["image_ids"]]


def test_corpus_stats(client):
    stats = client.get("/api/corpus/stats").json()
    assert stats["serving_images"] > 20
    assert client.get("/health/ready").status_code == 200


def test_single_entity(client):
    r = search(client, "ảnh Mỹ Tâm")
    assert r["status"] == "ok"
    assert all("Mỹ Tâm" in n for n in names(r))


def test_rejected_images_are_not_served(client):
    r = search(client, "Mỹ Tâm", top_k=50)
    assert len(r["groups"][0]["image_ids"]) == 3  # 4 rows, 1 rejected


def test_multi_intent_groups(client):
    r = search(client, "ảnh Sơn Tùng và Mỹ Tâm")
    assert r["query_type"] == "multi_intent" and len(r["groups"]) == 2
    assert all(g["image_ids"] for g in r["groups"])


def test_same_photo(client):
    r = search(client, "Sơn Tùng chụp cùng Hà Anh Tuấn")
    assert names(r) == [{"Sơn Tùng M-TP", "Hà Anh Tuấn"}]


def test_multi_hop(client):
    r = search(client, "ảnh con trai chủ tịch Phạm Nhật Vượng")
    assert r["status"] == "ok" and r["query_type"] == "multi_hop"
    assert all("Phạm Nhật Quân Anh" in n for n in names(r))
    assert r["groups"][0]["explanation"]


def test_two_hop(client):
    r = search(client, "con trai của người sáng lập Vingroup")
    assert r["status"] == "ok"
    assert len(r["groups"][0]["explanation"]) == 2


def test_missing_relation_is_reported(client):
    r = search(client, "vợ của Đen Vâu")
    assert r["status"] in ("no_verified_relation", "no_seed_entity")
    assert not r["groups"][0]["image_ids"]


def test_location_scope_includes_sub_places(client):
    r = search(client, "bãi biển ở Phú Quốc")
    assert r["status"] == "ok"
    assert all("Phú Quốc" in n for n in names(r))


def test_ambiguous_prefix_shows_all_and_offers_refinement(client):
    r = search(client, "ảnh Phạm Nhật")
    assert r["status"] == "ok" and r["groups"][0]["image_ids"]
    options = r["clarification_options"][0]["candidates"]
    assert len(options) > 1
    chosen = options[0]
    r2 = search(client, "ảnh Phạm Nhật", selected_entity_ids=[chosen["entity_id"]])
    assert r2["status"] in ("ok", "no_results") and not r2["clarification_options"]
    assert [s["name"] for s in r2["interpretation"]["intents"][0]["seeds"]] == [chosen["name"]]


def test_ambiguous_name_in_same_photo_query_asks(client):
    r = search(client, "Sơn Tùng chụp cùng Phạm Nhật")
    assert r["status"] == "needs_clarification"
