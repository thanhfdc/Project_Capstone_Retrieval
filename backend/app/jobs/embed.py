"""Compute image embeddings for every downloaded image that has none yet.

Runs in the worker image (torch). Vectors are written straight into images.embedding,
so re-running only processes new images.
"""
import argparse
import json
import time

import numpy as np
from PIL import Image

from ..config import get_settings
from ..db import connect, migrate, set_meta
from ..services.encoder import get_encoder

MIN_SIDE = 16  # icons and tracking pixels (1x1) carry nothing to search for and confuse the processor


def encode_safely(encoder, images: list, ids: list) -> tuple[list, list, int]:
    """Encode a batch; if one image breaks the processor, encode one by one and drop the bad ones."""
    try:
        return list(encoder.encode_images(images)), ids, 0
    except Exception:  # noqa: BLE001 - isolate the faulty image instead of stopping 90K images
        vectors, kept, bad = [], [], 0
        for im, image_id in zip(images, ids):
            try:
                vectors.append(encoder.encode_images([im])[0])
                kept.append(image_id)
            except Exception as exc:  # noqa: BLE001
                bad += 1
                print(f"  skip {image_id}: {type(exc).__name__}: {str(exc)[:80]}")
        return vectors, kept, bad


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    settings = get_settings()
    migrate()
    encoder = get_encoder(settings, for_images=True)
    with connect(autocommit=True) as conn:
        sql = "SELECT image_id, thumb_path FROM images WHERE embedding IS NULL ORDER BY image_id"
        if args.limit:
            sql += f" LIMIT {int(args.limit)}"
        rows = conn.execute(sql).fetchall()
        print(f"{len(rows)} images to embed with {encoder.name}")
        started, done, failed, skipped = time.perf_counter(), 0, 0, 0
        for i in range(0, len(rows), args.batch_size):
            chunk = rows[i:i + args.batch_size]
            images, ids = [], []
            for r in chunk:
                try:
                    with Image.open(settings.media_dir / r["thumb_path"]) as im:
                        if min(im.size) < MIN_SIDE:
                            skipped += 1
                            continue
                        images.append(im.convert("RGB"))
                    ids.append(r["image_id"])
                except OSError:
                    failed += 1
            if not images:
                continue
            vectors, ids, bad = encode_safely(encoder, images, ids)
            failed += bad
            if not ids:
                continue
            if not np.isfinite(np.asarray(vectors)).all():
                raise RuntimeError("encoder produced NaN/Inf")
            with conn.cursor() as cur:
                cur.executemany("UPDATE images SET embedding = %s WHERE image_id = %s",
                                list(zip(list(vectors), ids)))
            done += len(ids)
            if (i // args.batch_size) % 20 == 0:
                rate = done / max(time.perf_counter() - started, 1e-9)
                print(f"{done}/{len(rows)} embedded, {rate:.1f} img/s")
        elapsed = time.perf_counter() - started
        set_meta(conn, "encoder", encoder.name)
    report = {"embedded": done, "failed": failed, "skipped_tiny": skipped, "seconds": round(elapsed, 1),
              "images_per_second": round(done / max(elapsed, 1e-9), 2), "encoder": encoder.name}
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    (settings.reports_dir / "embed_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
