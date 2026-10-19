"""Generate test cases for the 3 query types from ground truth in the database.

Method (see docs/TESTING.md):
- Ground truth comes from two places only: approved image-entity labels from the CSVs, and
  verified relations in data/relations. Expected answers are entity ids, so relevance of a
  returned image is checked automatically (is it linked to the expected entity?).
- Queries are written from templates with variations real users type: full name, no
  diacritics, a typo, name + scene words, "A và B", "A chụp cùng B", "A hoặc B",
  relation phrases with titles ("con trai chủ tịch X"), one and two hops.
- Negative cases: relation that is not in the knowledge base, names that do not exist.
- Hand-written cases in eval/manual_cases.jsonl are appended as-is (scene-only queries,
  the examples from the brief) and are judged by looking at the report.

Usage: DATABASE_URL=... python eval/make_testcases.py --per-type 40 > eval/testcases.jsonl
"""
import argparse
import json
import os
import random
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.textnorm import fold  # noqa: E402

SCENES = ["đang biểu diễn", "trên sân khấu", "chụp ngoài trời", "cười tươi", "tại sự kiện"]
LABEL = {("parent_of", "male"): "con trai của", ("parent_of", "female"): "con gái của",
         ("parent_of", None): "con của", ("spouse_of", None): "vợ/chồng của"}


def typo(name: str, rnd: random.Random) -> str:
    words = name.split()
    w = max(range(len(words)), key=lambda i: len(words[i]))
    if len(words[w]) > 3:
        k = rnd.randrange(1, len(words[w]) - 1)
        words[w] = words[w][:k] + words[w][k + 1:]
    return " ".join(words)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--per-type", type=int, default=40)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--include-synthetic", action="store_true")
    args = ap.parse_args()
    rnd = random.Random(args.seed)
    db = os.environ.get("DATABASE_URL", "postgresql://capstone:capstone@localhost:5433/capstone")
    synth = "" if args.include_synthetic else "AND coalesce(e.category_raw, '') <> 'synthetic'"
    cases = []
    with psycopg.connect(db, row_factory=dict_row) as conn:
        ents = conn.execute(f"""
            SELECT e.entity_id::text, e.canonical_name, e.entity_type, count(*) AS n
            FROM entities e JOIN image_entities ie USING (entity_id) JOIN images i USING (image_id)
            WHERE i.is_serving AND ie.approval_status = 'approved' {synth}
            GROUP BY 1, 2, 3 HAVING count(*) >= 2
        """).fetchall()
        # names shared by several entities would be ambiguous: keep them out of positive cases
        dup = {r["name_fold"] for r in conn.execute(
            "SELECT name_fold FROM entities GROUP BY 1 HAVING count(*) > 1").fetchall()}
        people = [e for e in ents if e["entity_type"] == "person" and fold(e["canonical_name"]) not in dup]
        places = [e for e in ents if e["entity_type"] == "place"]
        rnd.shuffle(people)

        # ---- single intent
        n = args.per_type
        for i, e in enumerate(people[:n]):
            name = e["canonical_name"]
            variant = i % 4
            q = [f"ảnh {name}", fold(name), typo(name, rnd), f"{name} {rnd.choice(SCENES)}"][variant]
            cases.append({"query": q, "query_type": "single", "variant": ["name", "no_diacritics", "typo", "name+scene"][variant],
                          "expected_status": "ok", "expected_groups": [[e["entity_id"]]]})
        for p in places[: max(2, n // 10)]:
            cases.append({"query": f"bãi biển {p['canonical_name']}", "query_type": "single", "variant": "place+scene",
                          "expected_status": "ok", "expected_groups": [[p["entity_id"]]]})

        # ---- multi-intent: two groups, union, same photo
        pairs = [(people[i], people[i + 1]) for i in range(0, min(len(people) - 1, n), 2)]
        for a, b in pairs[: n // 3]:
            cases.append({"query": f"ảnh {a['canonical_name']} và {b['canonical_name']}", "query_type": "multi_intent",
                          "variant": "two_groups", "expected_status": "ok",
                          "expected_groups": [[a["entity_id"]], [b["entity_id"]]]})
        for a, b in pairs[n // 3: n // 3 + n // 6]:
            cases.append({"query": f"{a['canonical_name']} hoặc {b['canonical_name']}", "query_type": "multi_intent",
                          "variant": "union", "expected_status": "ok",
                          "expected_groups": [[a["entity_id"], b["entity_id"]]]})
        together = conn.execute("""
            SELECT a.entity_id::text AS a, b.entity_id::text AS b, ea.canonical_name AS na, eb.canonical_name AS nb
            FROM image_entities a JOIN image_entities b ON a.image_id = b.image_id AND a.entity_id < b.entity_id
            JOIN entities ea ON ea.entity_id = a.entity_id JOIN entities eb ON eb.entity_id = b.entity_id
            JOIN images i ON i.image_id = a.image_id
            WHERE i.is_serving AND a.approval_status = 'approved' AND b.approval_status = 'approved'
              AND coalesce(ea.category_raw, '') <> 'synthetic'
            GROUP BY 1, 2, 3, 4 LIMIT %s
        """, (max(2, n // 4),)).fetchall()
        for t in together:
            cases.append({"query": f"{t['na']} chụp cùng {t['nb']}", "query_type": "multi_intent", "variant": "same_photo",
                          "expected_status": "ok", "expected_groups": [[t["a"], t["b"]]], "require_all": True})

        # ---- multi-hop from verified relations
        rels = conn.execute("""
            SELECT r.subject_id::text AS s, r.object_id::text AS o, r.predicate, es.canonical_name AS ns,
                   eo.canonical_name AS no, eo.gender AS og
            FROM relations r JOIN entities es ON es.entity_id = r.subject_id JOIN entities eo ON eo.entity_id = r.object_id
            WHERE r.verified
        """).fetchall()
        for r in rels:
            if r["predicate"] == "parent_of":
                phrase = LABEL.get(("parent_of", r["og"]), "con của")
                for q in (f"ảnh {phrase} {r['ns']}", f"{phrase.replace(' của', '')} {fold(r['ns'])}"):
                    cases.append({"query": q, "query_type": "multi_hop", "variant": "1_hop", "expected_status": "ok",
                                  "expected_groups": [[r["o"]]]})
            elif r["predicate"] == "founded":
                cases.append({"query": f"người sáng lập {r['no']}", "query_type": "multi_hop", "variant": "1_hop_inverse",
                              "expected_status": "ok", "expected_groups": [[r["s"]]]})
                for c in (x for x in rels if x["predicate"] == "parent_of" and x["s"] == r["s"]):
                    phrase = LABEL.get(("parent_of", c["og"]), "con của")
                    cases.append({"query": f"{phrase} người sáng lập {r['no']}", "query_type": "multi_hop",
                                  "variant": "2_hop", "expected_status": "ok", "expected_groups": [[c["o"]]]})
            elif r["predicate"] == "member_of":
                cases.append({"query": f"thành viên nhóm {r['no']}", "query_type": "multi_hop", "variant": "1_hop_inverse",
                              "expected_status": "ok", "expected_groups": [[r["s"]]]})
        with_rel = {r["s"] for r in rels} | {r["o"] for r in rels}
        for e in [p for p in people if p["entity_id"] not in with_rel][:5]:
            cases.append({"query": f"con trai của {e['canonical_name']}", "query_type": "multi_hop",
                          "variant": "missing_relation", "expected_status": "no_verified_relation", "expected_groups": []})

    manual = Path(__file__).with_name("manual_cases.jsonl")
    if manual.exists():
        for line in manual.read_text(encoding="utf-8").splitlines():
            if line.strip():
                cases.append({**json.loads(line), "variant": "manual"})
    for i, c in enumerate(cases, start=1):
        c["id"] = f"{c['query_type'][:2]}_{i:04d}"
        print(json.dumps(c, ensure_ascii=False))
    print(f"{len(cases)} cases", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
