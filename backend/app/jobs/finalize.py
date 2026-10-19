"""Merge labels, build search text, mark serving images and build the vector index.

Label merge per (image, entity): approved only if every observation agrees; a mix of
approved and rejected becomes 'unknown' (not served) instead of last-write-wins.
An image is served when it has an embedding and at least one approved entity link.
"""
import hashlib
import json
import time

import psycopg

from ..config import get_settings
from ..db import connect, migrate, set_meta
from ..textnorm import fold

MERGE_SQL = """
TRUNCATE image_entities;
INSERT INTO image_entities(image_id, entity_id, approval_status)
SELECT f.image_id, l.entity_id,
       CASE WHEN bool_and(l.approval_status = 'approved') THEN 'approved'
            WHEN bool_and(l.approval_status = 'rejected') THEN 'rejected'
            ELSE 'unknown' END
FROM links l
JOIN fetches f ON f.locator = COALESCE(l.image_url, l.local_path) AND f.status = 'ok'
GROUP BY f.image_id, l.entity_id;
"""

SOURCE_SQL = """
UPDATE images i SET description = s.description, source_url = s.source_url
FROM (
  SELECT DISTINCT ON (f.image_id) f.image_id, l.description, l.source_url
  FROM links l
  JOIN fetches f ON f.locator = COALESCE(l.image_url, l.local_path) AND f.status = 'ok'
  WHERE l.approval_status = 'approved'
  ORDER BY f.image_id, (l.description IS NULL), length(l.description) DESC NULLS LAST
) s
WHERE s.image_id = i.image_id;
"""

SERVING_SQL = """
UPDATE images i SET is_serving = (i.embedding IS NOT NULL AND EXISTS (
  SELECT 1 FROM image_entities ie WHERE ie.image_id = i.image_id AND ie.approval_status = 'approved'));
"""


def build_search_text(conn) -> int:
    rows = conn.execute("""
        SELECT i.image_id, i.description,
               string_agg(DISTINCT a.alias, ' ') AS aliases
        FROM images i
        JOIN image_entities ie ON ie.image_id = i.image_id AND ie.approval_status = 'approved'
        JOIN entity_aliases a ON a.entity_id = ie.entity_id
        GROUP BY i.image_id, i.description
    """).fetchall()
    with conn.cursor() as cur:
        cur.executemany("UPDATE images SET search_text = %s WHERE image_id = %s",
                        [(fold(f"{r['aliases'] or ''} {r['description'] or ''}"), r["image_id"]) for r in rows])
    return len(rows)


def build_vector_index(conn, dim: int) -> None:
    conn.execute("DROP INDEX IF EXISTS images_embedding_hnsw")
    conn.execute(f"ALTER TABLE images ALTER COLUMN embedding TYPE vector({int(dim)})")
    conn.execute("SET maintenance_work_mem = '1GB'")
    create = """CREATE INDEX images_embedding_hnsw ON images
                USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 128)
                WHERE is_serving"""
    try:
        conn.execute(create)
    except psycopg.errors.DiskFull:
        # A parallel build shares maintenance_work_mem through /dev/shm, which Docker caps at 64 MB
        # unless the db service sets shm_size. Fall back to a single-process build, which uses plain memory.
        print("  /dev/shm too small for a parallel index build; building with one process")
        conn.execute("DROP INDEX IF EXISTS images_embedding_hnsw")
        conn.execute("SET max_parallel_maintenance_workers = 0")
        conn.execute(create)


def main(argv=None) -> int:
    settings = get_settings()
    migrate()
    started = time.perf_counter()
    with connect(autocommit=True) as conn:
        # Bulk updates are much faster without the vector index; it is rebuilt at the end.
        conn.execute("DROP INDEX IF EXISTS images_embedding_hnsw")
        conn.execute(MERGE_SQL)
        conn.execute(SOURCE_SQL)
        searchable = build_search_text(conn)
        conn.execute(SERVING_SQL)
        dims = conn.execute("SELECT DISTINCT vector_dims(embedding) AS d FROM images "
                            "WHERE embedding IS NOT NULL").fetchall()
        if len(dims) > 1:
            raise RuntimeError(f"mixed embedding dimensions {dims}; re-embed with one model")
        if dims:
            build_vector_index(conn, dims[0]["d"])
        conn.execute("ANALYZE")
        funnel = conn.execute("""
            SELECT
              (SELECT count(*) FROM links) AS csv_rows,
              (SELECT count(*) FROM links WHERE approval_status = 'approved') AS approved_rows,
              (SELECT count(DISTINCT COALESCE(image_url, local_path)) FROM links
                 WHERE approval_status = 'approved') AS approved_locators,
              (SELECT count(*) FROM fetches WHERE status = 'ok') AS fetched_ok,
              (SELECT count(*) FROM fetches WHERE status = 'failed') AS fetch_failed,
              (SELECT count(*) FROM images) AS distinct_images,
              (SELECT count(*) FROM images WHERE embedding IS NOT NULL) AS embedded,
              (SELECT count(*) FROM images WHERE is_serving) AS serving_images,
              (SELECT count(DISTINCT entity_id) FROM image_entities ie JOIN images i USING (image_id)
                 WHERE i.is_serving AND ie.approval_status = 'approved') AS serving_entities,
              (SELECT count(*) FROM relations WHERE verified) AS verified_relations
        """).fetchone()
        ids = conn.execute("SELECT image_id FROM images WHERE is_serving ORDER BY image_id").fetchall()
        manifest_sha = hashlib.sha256("\n".join(str(r["image_id"]) for r in ids).encode()).hexdigest()
        snapshot = {**funnel, "searchable": searchable, "manifest_sha256": manifest_sha,
                    "finalized_seconds": round(time.perf_counter() - started, 1)}
        set_meta(conn, "snapshot", json.dumps(snapshot))
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    (settings.reports_dir / "corpus_funnel.json").write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(json.dumps(snapshot, indent=2))
    if snapshot["serving_images"] < 80_000:
        print(f"WARNING: only {snapshot['serving_images']} serving images (< 80,000 required)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
