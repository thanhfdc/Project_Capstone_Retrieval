"""Load hand-checked knowledge for multi-hop queries.

data/relations/entities_extra.csv
    name,entity_type,gender,aliases,entity_id
    Adds people/organisations/places that are not in the image CSVs (e.g. the father in
    "con trai của X"), or sets gender/aliases on existing entities. aliases are '|'-separated.
data/relations/relations.csv
    subject,predicate,object,source_url,evidence,verified
    subject/object are an entity name/alias or entity_id. predicate is one of
    parent_of, spouse_of, founded, member_of, located_in.
Names that match zero or several entities are reported and skipped, never guessed.
"""
import csv
import json
import sys
import uuid

from ..config import get_settings
from ..db import connect, migrate
from ..textnorm import fold

PREDICATES = {"parent_of", "spouse_of", "founded", "member_of", "located_in"}


def resolve(conn, ref: str) -> tuple[uuid.UUID | None, str]:
    ref = ref.strip()
    try:
        eid = uuid.UUID(ref)
        row = conn.execute("SELECT entity_id FROM entities WHERE entity_id = %s", (eid,)).fetchone()
        return (eid, "ok") if row else (None, "unknown_id")
    except ValueError:
        pass
    rows = conn.execute("SELECT DISTINCT entity_id FROM entity_aliases WHERE alias_fold = %s",
                        (fold(ref),)).fetchall()
    if len(rows) == 1:
        return rows[0]["entity_id"], "ok"
    return None, "not_found" if not rows else "ambiguous"


def load_entities(conn, path) -> list[dict]:
    issues = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=1):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            etype = (row.get("entity_type") or "person").strip() or "person"
            gender = (row.get("gender") or "").strip().lower() or None
            if gender not in (None, "male", "female"):
                issues.append({"file": path.name, "row": n, "issue": f"bad gender {gender}"})
                gender = None
            aliases = [a.strip() for a in (row.get("aliases") or "").split("|") if a.strip()]
            if row.get("entity_id"):
                eid, status = uuid.UUID(row["entity_id"].strip()), "ok"
                exists = conn.execute("SELECT 1 FROM entities WHERE entity_id = %s", (eid,)).fetchone()
            else:
                eid, status = resolve(conn, name)
                exists = eid is not None
                if status == "ambiguous":
                    issues.append({"file": path.name, "row": n, "issue": f"ambiguous name {name}"})
                    continue
                if eid is None:
                    eid = uuid.uuid5(uuid.NAMESPACE_URL, f"extra:{fold(name)}")
            if exists:
                conn.execute("UPDATE entities SET gender = COALESCE(%s, gender), entity_type = %s "
                             "WHERE entity_id = %s", (gender, etype, eid))
            else:
                conn.execute("INSERT INTO entities(entity_id, slug, canonical_name, name_fold, entity_type, gender) "
                             "VALUES (%s, '', %s, %s, %s, %s)", (eid, name, fold(name), etype, gender))
            for alias in [name, *aliases]:
                conn.execute("INSERT INTO entity_aliases VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                             (eid, alias, fold(alias)))
    return issues


def load_relations(conn, path) -> tuple[int, list[dict]]:
    issues, loaded = [], 0
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for n, row in enumerate(csv.DictReader(fh), start=1):
            pred = (row.get("predicate") or "").strip()
            if pred not in PREDICATES:
                issues.append({"file": path.name, "row": n, "issue": f"bad predicate {pred}"})
                continue
            subj, s1 = resolve(conn, row.get("subject") or "")
            obj, s2 = resolve(conn, row.get("object") or "")
            if subj is None or obj is None:
                issues.append({"file": path.name, "row": n,
                               "issue": f"subject {s1} / object {s2}: {row.get('subject')} -> {row.get('object')}"})
                continue
            source = (row.get("source_url") or "").strip()
            if not source or source.endswith(("…", "...")):
                issues.append({"file": path.name, "row": n, "issue": "missing or truncated source_url"})
                continue
            verified = (row.get("verified") or "").strip().lower() in ("1", "true", "yes", "verified")
            conn.execute(
                """INSERT INTO relations(subject_id, predicate, object_id, source_url, evidence, verified)
                   VALUES (%s, %s, %s, %s, %s, %s)
                   ON CONFLICT (subject_id, predicate, object_id) DO UPDATE SET
                     source_url = EXCLUDED.source_url, evidence = EXCLUDED.evidence, verified = EXCLUDED.verified""",
                (subj, pred, obj, source, (row.get("evidence") or "").strip(), verified))
            loaded += 1
    return loaded, issues


def main(argv=None) -> int:
    settings = get_settings()
    migrate()
    folder = settings.data_dir / "relations"
    report = {"issues": []}
    with connect() as conn:
        extra = folder / "entities_extra.csv"
        if extra.exists():
            report["issues"] += load_entities(conn, extra)
        rel = folder / "relations.csv"
        if rel.exists():
            report["relations_loaded"], issues = load_relations(conn, rel)
            report["issues"] += issues
        conn.commit()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    (settings.reports_dir / "relations_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if report["issues"]:
        print(f"{len(report['issues'])} rows skipped, see relations_report.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
