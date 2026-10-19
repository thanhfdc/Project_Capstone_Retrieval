"""Download (or read locally) every approved image locator, then store a WebP thumbnail.

Only the thumbnail is kept: it is what the web shows and what the encoder reads
(SigLIP works at 224px), which keeps 80K images around a few GB.
Content is deduplicated by SHA-256 of the original bytes. Progress is checkpointed in the
`fetches` table, so the job can be stopped and resumed.
"""
import argparse
import asyncio
import hashlib
import io
import json
import time
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from PIL import Image, ImageOps

from ..config import get_settings
from ..db import connect, migrate

Image.MAX_IMAGE_PIXELS = 40_000_000
USER_AGENT = "Mozilla/5.0 (capstone-image-retrieval downloader)"


def safe_url(url: str) -> str:
    """Percent-encode spaces/unicode in the path without touching the query string."""
    parts = urlsplit(url.strip())
    return urlunsplit(parts._replace(path=quote(parts.path, safe="/%:@!$&'()*+,;=-._~")))


def make_thumbnail(data: bytes, size: int) -> tuple[bytes, int, int]:
    with Image.open(io.BytesIO(data)) as probe:
        probe.verify()
    with Image.open(io.BytesIO(data)) as src:
        src.seek(0)
        img = ImageOps.exif_transpose(src)
        width, height = img.size
        rgba = img.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        rgb = Image.alpha_composite(background, rgba).convert("RGB")
    rgb.thumbnail((size, size), Image.Resampling.LANCZOS)
    out = io.BytesIO()
    rgb.save(out, format="WEBP", quality=82, method=4)
    return out.getvalue(), width, height


def store_thumbnail(media_dir: Path, sha: str, thumb: bytes) -> str:
    rel = f"thumbs/{sha[:2]}/{sha}.webp"
    target = media_dir / rel
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(f".{uuid.uuid4().hex}.part")
        tmp.write_bytes(thumb)
        tmp.replace(target)
    return rel


class Downloader:
    def __init__(self, settings, conn):
        self.s = settings
        self.conn = conn
        self.global_sem = asyncio.Semaphore(settings.download_concurrency)
        self.host_sems: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(settings.download_per_host))
        self.stats = Counter()
        self.errors = Counter()

    async def fetch_bytes(self, client: httpx.AsyncClient, url: str) -> bytes:
        if urlsplit(url).scheme not in ("http", "https"):
            raise ValueError("unsupported_scheme")
        host = urlsplit(url).hostname or ""
        async with self.global_sem, self.host_sems[host]:
            for attempt in range(3):
                try:
                    async with client.stream("GET", safe_url(url)) as resp:
                        if resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue
                        if resp.status_code != 200:
                            raise ValueError(f"http_{resp.status_code}")
                        chunks, total = [], 0
                        async for chunk in resp.aiter_bytes():
                            total += len(chunk)
                            if total > self.s.download_max_bytes:
                                raise ValueError("too_large")
                            chunks.append(chunk)
                        return b"".join(chunks)
                except (httpx.TimeoutException, httpx.TransportError):
                    if attempt == 2:
                        raise
                    await asyncio.sleep(1.5 * (attempt + 1))
        raise ValueError("retries_exhausted")

    def read_local(self, local_path: str) -> bytes | None:
        root = (self.s.raw_dir / "images").resolve()
        candidate = (root / local_path.lstrip("/\\")).resolve()
        if root in candidate.parents and candidate.is_file():
            return candidate.read_bytes()
        return None

    async def process(self, client, locator: str, url: str | None, local_path: str | None):
        try:
            data = self.read_local(local_path) if local_path else None
            if data is None:
                if not url:
                    raise ValueError("no_local_file_and_no_url")
                data = await self.fetch_bytes(client, url)
            sha = hashlib.sha256(data).hexdigest()
            thumb, width, height = await asyncio.to_thread(make_thumbnail, data, self.s.thumb_size)
            rel = await asyncio.to_thread(store_thumbnail, self.s.media_dir, sha, thumb)
            row = self.conn.execute(
                """INSERT INTO images(image_id, content_sha256, thumb_path, width, height, byte_size, image_url)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (content_sha256) DO UPDATE SET content_sha256 = EXCLUDED.content_sha256
                   RETURNING image_id""",
                (uuid.uuid4(), sha, rel, width, height, len(data), url),
            ).fetchone()
            self.record(locator, "ok", row["image_id"], None)
            self.stats["ok"] += 1
        except Exception as exc:  # noqa: BLE001 - every failure is recorded and counted
            code = str(exc) if isinstance(exc, ValueError) else type(exc).__name__
            self.record(locator, "failed", None, code[:200])
            self.stats["failed"] += 1
            self.errors[code[:60]] += 1

    def record(self, locator, status, image_id, error):
        self.conn.execute(
            """INSERT INTO fetches(locator, status, image_id, error) VALUES (%s, %s, %s, %s)
               ON CONFLICT (locator) DO UPDATE SET status = EXCLUDED.status, image_id = EXCLUDED.image_id,
                 error = EXCLUDED.error, attempts = fetches.attempts + 1, fetched_at = now()""",
            (locator, status, image_id, error),
        )


def pending_locators(conn, retry_failed: bool, limit: int | None):
    sql = """
        SELECT COALESCE(l.image_url, l.local_path) AS locator,
               min(l.image_url) AS url, min(l.local_path) AS local_path
        FROM links l
        LEFT JOIN fetches f ON f.locator = COALESCE(l.image_url, l.local_path)
        WHERE l.approval_status = 'approved'
          AND (f.locator IS NULL OR (%s AND f.status = 'failed' AND f.attempts < 3))
        GROUP BY 1
        ORDER BY 1
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (retry_failed,)).fetchall()


async def run(retry_failed: bool, limit: int | None) -> dict:
    settings = get_settings()
    settings.media_dir.mkdir(parents=True, exist_ok=True)
    with connect(autocommit=True) as conn:
        todo = pending_locators(conn, retry_failed, limit)
        print(f"{len(todo)} locators to fetch")
        dl = Downloader(settings, conn)
        timeout = httpx.Timeout(15.0, connect=5.0)
        limits = httpx.Limits(max_connections=settings.download_concurrency * 2)
        started = time.perf_counter()
        async with httpx.AsyncClient(timeout=timeout, limits=limits, follow_redirects=True,
                                     headers={"User-Agent": USER_AGENT}) as client:
            batch = 2000
            for i in range(0, len(todo), batch):
                chunk = todo[i:i + batch]
                await asyncio.gather(*(dl.process(client, r["locator"], r["url"], r["local_path"])
                                       for r in chunk))
                elapsed = time.perf_counter() - started
                done = min(i + batch, len(todo))
                print(f"{done}/{len(todo)} ok={dl.stats['ok']} failed={dl.stats['failed']} "
                      f"{done / max(elapsed, 1e-9):.1f} img/s")
        elapsed = time.perf_counter() - started
    report = {"locators": len(todo), **dl.stats, "seconds": round(elapsed, 1),
              "images_per_second": round(len(todo) / max(elapsed, 1e-9), 2),
              "top_errors": dl.errors.most_common(10)}
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    (settings.reports_dir / "download_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--retry-failed", action="store_true")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    migrate()
    print(json.dumps(asyncio.run(run(args.retry_failed, args.limit)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
