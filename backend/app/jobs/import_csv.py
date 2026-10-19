"""Import every CSV under data/raw into entities, aliases and link observations.

Columns are matched by name through backend/config/import_profiles.json, so the 24-column
crawl file (`flag`) and the 8-column approver file (`status`) land in the same tables.
Re-running is idempotent: rows are keyed by (source_file, row_no).
"""
import argparse
import csv
import json
import sys
import uuid
from pathlib import Path

from ..config import get_settings
from ..db import connect, migrate
from ..textnorm import fold, norm

PROFILE_PATH = Path(__file__).resolve().parents[2] / "config" / "import_profiles.json"
BATCH = 1000
MAX_URL = 2048  # inline data: URIs and runaway URLs cannot be indexed or fetched; they are dropped and counted


def load_profile() -> dict:
    return json.loads(PROFILE_PATH.read_text(encoding="utf-8"))


def header_key(name: str) -> str:
    return norm(name).replace(" ", "_")


def resolve_columns(header: list[str], profile: dict) -> dict[str, str | None]:
    keys = [header_key(h) for h in header]
    if len(set(keys)) != len(keys):
        raise ValueError(f"duplicate column names after normalisation: {header}")
    by_key = dict(zip(keys, header))
    mapping: dict[str, str | None] = {}
    for field, aliases in profile["columns"].items():
        present = [by_key[a] for a in aliases if a in by_key]
        if len(present) > 1:
            raise ValueError(f"field {field} matches several columns: {present}")
        mapping[field] = present[0] if present else None
    missing = [f for f in profile["required"] if mapping[f] is None]
    if missing:
        raise ValueError(f"missing required columns {missing}")
    if mapping["image_url"] is None and mapping["local_path"] is None:
        raise ValueError("need image_url or local_path column")
    return mapping


def entity_uuid(key: str, namespace: str) -> uuid.UUID:
    try:
        return uuid.UUID(key)
    except ValueError:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}:{key}")


def canonical_rows(path: Path, profile: dict):
    """Yield (row_no, canonical dict) for one file; bad rows are counted, never guessed."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        mapping = resolve_columns(reader.fieldnames or [], profile)
        for row_no, raw in enumerate(reader, start=1):
            if None in raw:  # more cells than header
                yield row_no, None
                continue
            record = {f: (raw.get(col) or "").strip() if col else "" for f, col in mapping.items()}
            status_raw = record["approval_status"].lower()
            record["approval_status"] = profile["status_map"].get(status_raw, "unknown")
            url = record["image_url"]
            record["url_dropped"] = bool(url) and (url.startswith("data:") or len(url) > MAX_URL)
            if record["url_dropped"]:
                record["image_url"] = ""
            if not record["entity_key"] or not record["canonical_name"]:
                yield row_no, None
                continue
            if not record["image_url"] and not record["local_path"]:
                yield row_no, {"url_dropped": True} if record["url_dropped"] else None
                continue
            yield row_no, record


def import_file(conn, path: Path, profile: dict) -> dict:
    namespace = profile["entity_namespace"]
    stats = {"file": path.name, "rows": 0, "bad_rows": 0, "url_dropped": 0,
             "approved": 0, "rejected": 0, "unknown": 0}
    entities: dict[uuid.UUID, tuple] = {}
    links: list[tuple] = []

    def flush():
        with conn.cursor() as cur:
            cur.executemany(
                """INSERT INTO entities(entity_id, slug, canonical_name, name_fold, entity_type, category_raw)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (entity_id) DO UPDATE SET
                     slug = COALESCE(NULLIF(EXCLUDED.slug, ''), entities.slug),
                     category_raw = COALESCE(entities.category_raw, EXCLUDED.category_raw),
                     updated_at = now()""",
                list(entities.values()),
            )
            cur.executemany(
                """INSERT INTO entity_aliases(entity_id, alias, alias_fold) VALUES (%s, %s, %s)
                   ON CONFLICT DO NOTHING""",
                [(e[0], e[2], e[3]) for e in entities.values()],
            )
            cur.executemany(
                """INSERT INTO links(source_file, row_no, entity_id, image_url, local_path, source_url,
                                     description, approval_status, reject_reason)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                   ON CONFLICT (source_file, row_no) DO UPDATE SET
                     approval_status = EXCLUDED.approval_status,
                     reject_reason = EXCLUDED.reject_reason,
                     description = EXCLUDED.description""",
                links,
            )
        entities.clear()
        links.clear()

    for row_no, rec in canonical_rows(path, profile):
        stats["rows"] += 1
        if rec is None or "entity_key" not in rec:
            stats["bad_rows"] += 1
            stats["url_dropped"] += rec is not None
            continue
        stats["url_dropped"] += rec["url_dropped"]
        stats[rec["approval_status"]] += 1
        eid = entity_uuid(rec["entity_key"], namespace)
        kind = (rec.get("kind_hint") or "").lower()
        etype = kind if kind in ("person", "organization", "place") else "person"
        entities[eid] = (eid, rec["slug"], rec["canonical_name"], fold(rec["canonical_name"]),
                         etype, rec["category_raw"] or None)
        links.append((path.name, row_no, eid, rec["image_url"] or None, rec["local_path"] or None,
                      rec["source_url"] or None, rec["description"] or None,
                      rec["approval_status"], rec["reject_reason"] or None))
        if len(links) >= BATCH:
            flush()
    flush()
    conn.commit()
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", help="CSV files (default: every *.csv in data/raw)")
    args = parser.parse_args(argv)
    settings = get_settings()
    files = [Path(f) for f in args.files] or sorted(settings.raw_dir.glob("*.csv"))
    if not files:
        print(f"no CSV found in {settings.raw_dir}", file=sys.stderr)
        return 1
    migrate()
    profile = load_profile()
    report = []
    with connect() as conn:
        for path in files:
            try:
                stats = import_file(conn, path, profile)
            except ValueError as exc:
                conn.rollback()
                stats = {"file": path.name, "error": str(exc)}
            report.append(stats)
            print(json.dumps(stats, ensure_ascii=False))
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    (settings.reports_dir / "import_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if all("error" not in r for r in report) else 2


if __name__ == "__main__":
    raise SystemExit(main())
