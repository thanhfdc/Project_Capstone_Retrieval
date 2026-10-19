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
THROTTLE_STATUS = (403, 429)
MAX_HOST_INTERVAL = 5.0     # slowest pace per host: one request every 5 s
COOLDOWN_BASE = 30.0       # first pause after a refusal; grows with each strike
MAX_COOLDOWN = 300.0
HOST_GIVE_UP = 40           # strikes without recovery: leave the host for the next run
# failures worth another try on the next run (the host may have been rate limiting us)
RETRYABLE_ERRORS = (r"^(http_403|http_429|http_5\d\d|retries_exhausted|ConnectError|ConnectTimeout|"
                    r"ReadTimeout|ReadError|RemoteProtocolError|PoolTimeout)")


def safe_url(url: str) -> str:
    """Percent-encode spaces/unicode in the path without touching the query string."""
    parts = urlsplit(url.strip())
    return urlunsplit(parts._replace(path=quote(parts.path, safe="/%:@!$&'()*+,;=-._~")))


def make_thumbnail(data: bytes, size: int) -> tuple[bytes, int, int]:
    """Shrink first, then flatten transparency: a 60 MP photo never exists in memory at full size
    as RGBA (that used to cost ~700 MB per image and could take Docker down)."""
    with Image.open(io.BytesIO(data)) as probe:
        probe.verify()
    with Image.open(io.BytesIO(data)) as src:
        width, height = src.size
        if src.format == "JPEG":
            src.draft("RGB", (size * 2, size * 2))  # decode at reduced scale (1/2..1/8)
        img = ImageOps.exif_transpose(src)
        factor = max(img.size) // (size * 2)
        if factor > 1 and img.mode in ("RGB", "RGBA", "L", "LA"):
            img = img.reduce(factor)  # cheap box downscale before any full-size conversion
        has_alpha = img.mode in ("RGBA", "LA", "PA") or (img.mode == "P" and "transparency" in img.info)
        img = img.convert("RGBA" if has_alpha else "RGB")
    img.thumbnail((size, size), Image.Resampling.LANCZOS)
    if has_alpha:
        background = Image.new("RGBA", img.size, (255, 255, 255, 255))
        img = Image.alpha_composite(background, img)
    out = io.BytesIO()
    img.convert("RGB").save(out, format="WEBP", quality=82, method=4)
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
        self.thumb_sem = asyncio.Semaphore(4)  # image decoding is the memory-heavy part
        # polite pacing: each host gets a minimum interval between requests, widened on 403/429
        self.host_interval: dict[str, float] = defaultdict(lambda: 1.0 / settings.download_host_rps)
        self.host_next: dict[str, float] = defaultdict(float)
        self.host_strikes: Counter = Counter()

    async def pace(self, host: str):
        loop = asyncio.get_running_loop()
        now = loop.time()
        slot = max(now, self.host_next[host])
        self.host_next[host] = slot + self.host_interval[host]
        if slot > now:
            await asyncio.sleep(slot - now)

    def throttled(self, host: str) -> float:
        """Host refused us: slow it down and pause it for a while. Returns the pause in seconds."""
        self.host_strikes[host] += 1
        self.host_interval[host] = min(self.host_interval[host] * 2, MAX_HOST_INTERVAL)
        cooldown = min(COOLDOWN_BASE * self.host_strikes[host], MAX_COOLDOWN)
        loop = asyncio.get_running_loop()
        self.host_next[host] = max(self.host_next[host], loop.time() + cooldown)
        self.stats["throttled"] += 1
        if self.host_strikes[host] in (1, 5, 20):
            print(f"  {host} refused requests ({self.host_strikes[host]}x): slowing to "
                  f"1 req / {self.host_interval[host]:.1f}s, pausing {cooldown:.0f}s", flush=True)
        return cooldown

    def recovered(self, host: str):
        if self.host_strikes[host]:
            self.host_strikes[host] = max(0, self.host_strikes[host] - 1)

    async def fetch_bytes(self, client: httpx.AsyncClient, url: str) -> bytes:
        if urlsplit(url).scheme not in ("http", "https"):
            raise ValueError("unsupported_scheme")
        host = urlsplit(url).hostname or ""
        async with self.host_sems[host]:
            for attempt in range(4):
                if self.host_strikes[host] >= HOST_GIVE_UP:
                    raise ValueError("http_403_host_blocked")  # retried on the next run
                await self.pace(host)
                try:
                    async with self.global_sem, client.stream("GET", safe_url(url)) as resp:
                        if resp.status_code in THROTTLE_STATUS and attempt < 3:
                            self.throttled(host)
                            continue  # pace() waits out the cooldown before the next try
                        if resp.status_code in (500, 502, 503, 504) and attempt < 3:
                            await asyncio.sleep(1.5 * (attempt + 1))
                            continue
                        if resp.status_code != 200:
                            raise ValueError(f"http_{resp.status_code}")
                        self.recovered(host)
                        chunks, total = [], 0
                        async for chunk in resp.aiter_bytes():
                            total += len(chunk)
                            if total > self.s.download_max_bytes:
                                raise ValueError("too_large")
                            chunks.append(chunk)
                        return b"".join(chunks)
                except (httpx.TimeoutException, httpx.TransportError):
                    if attempt == 3:
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
            async with self.thumb_sem:
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
          AND (f.locator IS NULL OR (%s AND f.status = 'failed' AND f.attempts < 4 AND f.error ~ %s))
        GROUP BY 1
        -- fetchable URLs first, spread across hosts so a --limit sample is representative
        ORDER BY COALESCE(l.image_url, l.local_path) !~* '^https?://', md5(COALESCE(l.image_url, l.local_path))
    """
    if limit:
        sql += f" LIMIT {int(limit)}"
    return conn.execute(sql, (retry_failed, RETRYABLE_ERRORS)).fetchall()


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
            done = 0

            async def one(r):
                # all locators run concurrently; per-host pacing keeps slow hosts from blocking the rest
                nonlocal done
                await dl.process(client, r["locator"], r["url"], r["local_path"])
                done += 1
                if done % 2000 == 0 or done == len(todo):
                    elapsed = time.perf_counter() - started
                    print(f"{done}/{len(todo)} ok={dl.stats['ok']} failed={dl.stats['failed']} "
                          f"throttled={dl.stats['throttled']} {done / max(elapsed, 1e-9):.1f} img/s", flush=True)

            await asyncio.gather(*(one(r) for r in todo))
        elapsed = time.perf_counter() - started
    report = {"locators": len(todo), **dl.stats, "seconds": round(elapsed, 1),
              "images_per_second": round(len(todo) / max(elapsed, 1e-9), 2),
              "top_errors": dl.errors.most_common(10)}
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    (settings.reports_dir / "download_report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-retry", action="store_true",
                        help="skip locators that failed earlier with a transient error (403/429/5xx/timeouts)")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args(argv)
    migrate()
    print(json.dumps(asyncio.run(run(not args.no_retry, args.limit)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
