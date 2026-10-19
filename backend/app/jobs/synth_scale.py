"""Add N synthetic images to test latency/throughput at scale (e.g. 80K) before real data is ready.

Synthetic rows go through the same tables (entities, links, fetches, images) so `finalize`
indexes them like real ones. They are tagged so they can be removed:
    python -m app.jobs.synth_scale --count 80000
    python -m app.jobs.synth_scale --remove
Never report quality metrics on synthetic rows; they only exercise the index and the API.
"""
import argparse
import random
import time
import uuid

import numpy as np

from ..config import get_settings
from ..db import connect, migrate
from ..textnorm import fold

SOURCE = "synthetic://scale-test"
WORDS = ("bãi biển hồ bơi sân khấu biểu diễn núi rừng thành phố đêm hoàng hôn công viên nước "
         "khách sạn nhà hàng lễ hội áo dài cà phê chợ đường phố cầu sông đảo").split()


def add(count: int, dim: int, entities: int, seed: int) -> None:
    rng = np.random.default_rng(seed)
    rnd = random.Random(seed)
    with connect(autocommit=False) as conn:
        thumb = conn.execute("SELECT thumb_path FROM images LIMIT 1").fetchone()
        thumb_path = thumb["thumb_path"] if thumb else "thumbs/none.webp"
        ents = [(uuid.uuid4(), f"Nguoi Tong Hop {i:05d}") for i in range(entities)]
        with conn.cursor() as cur:
            cur.executemany("INSERT INTO entities(entity_id, slug, canonical_name, name_fold, category_raw) "
                            "VALUES (%s, 'synthetic', %s, %s, 'synthetic')",
                            [(e, n, fold(n)) for e, n in ents])
            cur.executemany("INSERT INTO entity_aliases VALUES (%s, %s, %s)", [(e, n, fold(n)) for e, n in ents])
        started = time.perf_counter()
        batch = 5000
        for start in range(0, count, batch):
            n = min(batch, count - start)
            vecs = rng.standard_normal((n, dim)).astype(np.float32)
            vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
            img_rows, link_rows, fetch_rows = [], [], []
            for k in range(n):
                i = start + k
                image_id = uuid.uuid4()
                ent = ents[rnd.randrange(entities)][0]
                locator = f"{SOURCE}/{i}"
                desc = " ".join(rnd.sample(WORDS, 4))
                img_rows.append((image_id, f"synthetic{i:064d}"[-64:], thumb_path, 640, 480, 1, locator, desc, vecs[k]))
                link_rows.append((SOURCE, i + 1, ent, locator, desc))
                fetch_rows.append((locator, image_id))
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO images(image_id, content_sha256, thumb_path, width, height, byte_size, "
                                "image_url, description, embedding) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", img_rows)
                cur.executemany("INSERT INTO links(source_file, row_no, entity_id, image_url, description, "
                                "approval_status) VALUES (%s,%s,%s,%s,%s,'approved')", link_rows)
                cur.executemany("INSERT INTO fetches(locator, status, image_id) VALUES (%s,'ok',%s)", fetch_rows)
            conn.commit()
            print(f"{start + n}/{count} synthetic images ({time.perf_counter() - started:.0f}s)")


def remove() -> None:
    with connect(autocommit=True) as conn:
        conn.execute("DELETE FROM images WHERE image_url LIKE %s", (f"{SOURCE}%",))
        conn.execute("DELETE FROM fetches WHERE locator LIKE %s", (f"{SOURCE}%",))
        conn.execute("DELETE FROM links WHERE source_file = %s", (SOURCE,))
        conn.execute("DELETE FROM entities WHERE category_raw = 'synthetic'")
    print("synthetic rows removed; run finalize again")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=80_000)
    parser.add_argument("--entities", type=int, default=2_000)
    parser.add_argument("--dim", type=int, help="embedding size (default: same as existing vectors)")
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--remove", action="store_true")
    args = parser.parse_args(argv)
    migrate()
    if args.remove:
        remove()
        return 0
    dim = args.dim
    if dim is None:
        with connect() as conn:
            row = conn.execute("SELECT vector_dims(embedding) AS d FROM images WHERE embedding IS NOT NULL LIMIT 1").fetchone()
        dim = row["d"] if row else get_settings().embedding_dim
    add(args.count, dim, args.entities, args.seed)
    print("now run: python -m app.jobs.finalize")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
