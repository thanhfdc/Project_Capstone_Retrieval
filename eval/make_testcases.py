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
import re
import sys
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from app.services.entity_linker import edit_distance, person_key  # noqa: E402
from app.textnorm import fold  # noqa: E402

TITLE_WORDS = ["ca sĩ", "MC", "nghệ sĩ", "ông", "bà"]
UNKNOWN_RELATIONS = ["bạn thân của", "người yêu của", "cháu của", "học trò của", "đồng nghiệp của", "ông nội của",
                     "quản lý của"]
ABSENT_PEOPLE = ["Taylor Swift", "Elon Musk", "Lionel Messi", "Barack Obama", "Bill Gates", "Lisa Blackpink",
                 "Jack Ma", "Tòng Thị Phóng", "Lý Hoàng Nam Phương", "Nguyễn Văn Không Tồn Tại",
                 "Tập Cận Bình", "Vladimir Putin", "Kim Jong Un", "Lý Hiển Long", "Hun Sen", "Joko Widodo",
                 "Donald Trump", "Cristiano Ronaldo", "Son Heung Min", "Lưu Diệc Phi", "Châu Tinh Trì",
                 "Thành Long", "Lý Tiểu Long", "Phạm Băng Băng", "Mark Zuckerberg", "Jensen Huang",
                 "Shinzo Abe", "Narendra Modi", "Đặng Tiểu Bình", "Mao Trạch Đông"]


def display_name(canonical: str) -> str:
    """What a user types for a crawled name: "Ca sĩ Bằng Kiều" -> "Bằng Kiều", "Mỹ Tâm (queen Vpop)" -> "Mỹ Tâm"."""
    head = re.split(r"\s*[(\[]|\s+[-–|,]\s+", canonical, maxsplit=1)[0].split()
    drop = len(fold(" ".join(head)).split()) - len(person_key(" ".join(head)).split())
    return " ".join(head[drop:]) or canonical


def robustness_cases(people: list[dict], aliases: set[str], m: int, rnd: random.Random) -> list[dict]:
    """Each kind has a fixed right answer that does not depend on ranking quality."""
    cases = []
    sample = people[:m]
    for p in sample:  # a relation the system has no table for must not return the person's own photos
        cases.append({"query": f"{rnd.choice(UNKNOWN_RELATIONS)} {p['name']}", "query_type": "robustness",
                      "variant": "unknown_relation", "expected_status": "no_verified_relation", "expected_groups": [],
                      "forbid": p["ids"]})
    for k, name in enumerate(ABSENT_PEOPLE):  # nobody in the data: no look-alike name may be returned instead
        if fold(name) not in aliases:
            q = [f"ảnh {name}", name, f"{name} đang phát biểu"][k % 3]
            cases.append({"query": q, "query_type": "robustness", "variant": "not_in_data",
                          "expected_status": "no_results", "expected_groups": []})
    for p in [p for p in people if len(p["name"].split()) >= 3][:m]:  # words reordered are a different name
        reordered = " ".join(reversed(p["name"].split()))
        if fold(reordered) not in aliases:
            cases.append({"query": reordered, "query_type": "robustness", "variant": "reordered_name",
                          "expected_status": "no_results", "expected_groups": [], "forbid": p["ids"]})
    # a real person's first words with another given name ("Nguyễn Chí Thanh" from Nguyễn Chí Dũng): someone
    # else, so neither the person whose name it starts like nor any description match may be returned
    endings = ["Thanh", "Hùng", "Linh", "Hương", "Tuấn", "Nam", "Hà", "Phong"]
    prefixes = {" ".join(fold(a).split()[:-1]) for a in aliases if len(a.split()) >= 3}
    near = {3: [a for a in aliases if len(a.split()) == 3]}
    for k, p in enumerate([p for p in people if len(p["name"].split()) == 3][:m // 3]):
        head = p["name"].split()[:2]
        if not all(w.isalpha() for w in head):
            continue
        # skip names a letter or two from a real one: "Lê Thanh Nam" may well be a typo of Lê Thanh Tâm
        other = next((e for e in rnd.sample(endings, len(endings)) if fold(" ".join(head + [e])) not in prefixes
                      and not any(edit_distance(fold(" ".join(head + [e])), a) <= 2 for a in near[len(head) + 1])),
                     None)
        if other:
            q = " ".join(head + [other])
            cases.append({"query": q.lower() if k % 2 else q, "query_type": "robustness", "variant": "partial_name",
                          "expected_status": "no_results", "expected_groups": [], "forbid": p["ids"]})
    for _ in range(max(3, m // 3)):
        junk = "".join(rnd.choice("qwrtzxcvbnmlkjhgfdsp") for _ in range(rnd.randrange(6, 12)))
        cases.append({"query": junk, "query_type": "robustness", "variant": "gibberish", "expected_status": "no_results",
                      "expected_groups": []})
    for q in ("ảnh", "hình ảnh", "tìm ảnh"):
        cases.append({"query": q, "query_type": "robustness", "variant": "photo_word_only",
                      "expected_status": "no_results", "expected_groups": []})
    return cases


SCENES = ["đang biểu diễn", "trên sân khấu", "chụp ngoài trời", "cười tươi", "tại sự kiện"]

def typo(name: str, rnd: random.Random) -> str:
    words = name.split()
    w = max(range(len(words)), key=lambda i: len(words[i]))
    if len(words[w]) > 3:
        k = rnd.randrange(1, len(words[w]) - 1)
        words[w] = words[w][:k] + words[w][k + 1:]
    return " ".join(words)


# (predicate, direction from the seed, gender of the target) -> how a user asks for it
ASK = {("parent_of", "out", "male"): "con trai của", ("parent_of", "out", "female"): "con gái của",
       ("parent_of", "in", "male"): "bố của", ("parent_of", "in", "female"): "mẹ của",
       ("spouse_of", "both", "male"): "chồng của", ("spouse_of", "both", "female"): "vợ của",
       ("sibling_of", "both", "male"): "anh trai của", ("sibling_of", "both", "female"): "em gái của",
       ("founded", "in", None): "người sáng lập", ("member_of", "in", None): "thành viên nhóm",
       # the same relations asked without a gender: every target of that relation is the answer
       ("parent_of", "out", "any"): ("con của", "con ruột của"), ("parent_of", "in", "any"): ("bố mẹ của",),
       ("spouse_of", "both", "any"): ("vợ chồng của",),
       ("sibling_of", "both", "any"): ("em của", "anh chị em của", "anh chị em ruột của", "em ruột của")}


def speakable(aliases: list[str], canonical: str) -> str:
    """The name a user would type: the longest clean alias of at most 4 words, not "Chân dung studio X Forbes"."""
    relational = ("vo", "chong", "con", "bo", "me", "cha")
    clean = [a for a in aliases if "(" not in a and len(a.split()) <= 4
             and not set(fold(a).split()) & set(relational)] or [canonical]
    return max(clean, key=lambda a: (len(a.split()), -len(a)))


def ask(kind: tuple, rnd: random.Random) -> str:
    words = ASK[kind]
    return words if isinstance(words, str) else rnd.choice(words)


def multi_hop_cases(conn, with_images: set[str], people: list[dict], n: int, rnd: random.Random) -> list[dict]:
    """Every relation is asked from each side it can be asked from, then chained into 2-hop questions.

    Expected targets are computed here by walking the relations table, independently of the API, and only
    targets that have photos count (otherwise the right answer is "no images")."""
    rels = conn.execute("SELECT subject_id::text AS s, predicate AS p, object_id::text AS o FROM relations "
                        "WHERE verified").fetchall()
    ents = {r["entity_id"]: r for r in conn.execute(
        "SELECT entity_id::text, canonical_name, gender, entity_type FROM entities "
        "WHERE entity_id = ANY(%s::uuid[])", ([x for r in rels for x in (r["s"], r["o"])],)).fetchall()}
    aliases: dict[str, list[str]] = {}
    for r in conn.execute("SELECT entity_id::text, alias FROM entity_aliases WHERE entity_id = ANY(%s::uuid[])",
                          (list(ents),)).fetchall():
        aliases.setdefault(r["entity_id"], []).append(r["alias"])
    name = {i: speakable(aliases.get(i, []), e["canonical_name"]) for i, e in ents.items()}
    for i, e in ents.items():  # "thành viên nhóm Nhóm X" -> "thành viên nhóm X"
        if e["entity_type"] != "person" and fold(name[i]).split()[0] in ("nhom", "ban"):
            name[i] = name[i].split(" ", 1)[-1] if fold(name[i]).split()[0] == "nhom" else name[i]

    # edges[(seed, kind)] = targets, kind = key of ASK
    edges: dict[tuple, set[str]] = {}
    for r in rels:
        s, p, o = r["s"], r["p"], r["o"]
        if p == "parent_of":
            moves = [(s, ("parent_of", "out", ents[o]["gender"]), o), (o, ("parent_of", "in", ents[s]["gender"]), s)]
        elif p in ("spouse_of", "sibling_of"):
            moves = [(s, (p, "both", ents[o]["gender"]), o), (o, (p, "both", ents[s]["gender"]), s)]
        elif p in ("founded", "member_of"):
            moves = [(o, (p, "in", None), s)]
        else:
            continue
        for seed, kind, target in moves:
            if kind in ASK:
                edges.setdefault((seed, kind), set()).add(target)
            edges.setdefault((seed, kind[:2] + ("any",)), set()).add(target)

    children: dict[str, set[str]] = {}
    for r in rels:
        if r["p"] == "parent_of":
            children.setdefault(r["s"], set()).add(r["o"])
    for kids in children.values():  # children of one parent are siblings even without a sibling row
        for a in kids:
            for b in kids - {a}:
                kind = ("sibling_of", "both", ents[b]["gender"])
                if kind in ASK:
                    edges.setdefault((a, kind), set()).add(b)
                edges.setdefault((a, ("sibling_of", "both", "any")), set()).add(b)

    def phrase(text: str, variant: str) -> str:
        if variant == "no_diacritics":
            return fold(text)
        if variant == "no_cua":
            return text.replace(" của ", " ")
        if variant == "photo_prefix":
            return f"ảnh {text}"
        return text

    variants = ["plain", "no_diacritics", "no_cua", "photo_prefix"]
    cases = []
    for (seed, kind), targets in sorted(edges.items(), key=str):
        if "(" in name[seed]:
            continue
        expected = sorted(t for t in targets if t in with_images)
        if kind not in ASK:
            continue
        variant = rnd.choice(variants)
        q = phrase(f"{ask(kind, rnd)} {name[seed]}", variant)
        tag = f"{kind[0]}_no_gender" if kind[2] == "any" else kind[0]
        cases.append({"query": q, "query_type": "multi_hop", "variant": f"1_hop/{tag}/{variant}",
                      "expected_status": "ok" if expected else "no_images_for_target",
                      "expected_groups": [[t] for t in expected]})
    chains = []
    for (seed, k1), mids in edges.items():
        for (mid, k2), ends in edges.items():
            if "any" in (k1[2], k2[2]) or k1 not in ASK or k2 not in ASK:
                continue
            if mid in mids and "(" not in name[seed] and not (k1[0] == k2[0] and k1[1] != k2[1] or k1[0] == k2[0] and k1[0] in ("spouse_of", "sibling_of")):
                ends = {e for e in ends if e != seed}
                expected = sorted(e for e in ends if e in with_images)
                if expected:
                    chains.append((seed, k1, k2, expected))
    rnd.shuffle(chains)
    for seed, k1, k2, expected in chains[:n]:
        variant = rnd.choice(variants[:3])
        q = phrase(f"{ASK[k2]} {ASK[k1]} {name[seed]}", variant)
        cases.append({"query": q, "query_type": "multi_hop", "variant": f"2_hop/{k1[0]}>{k2[0]}/{variant}",
                      "expected_status": "ok", "expected_groups": [[t] for t in expected]})
    # negatives: a relation the knowledge base does not have, and the wrong gender for a real relation
    for p in [p for p in people if not set(p["ids"]) & set(ents)][:max(5, n // 8)]:
        cases.append({"query": f"con trai của {p['name']}", "query_type": "multi_hop",
                      "variant": "negative/missing_relation", "expected_status": "no_verified_relation",
                      "expected_groups": []})
    for (seed, kind), _ in list(edges.items()):
        if kind[0] == "parent_of" and kind[1] == "out" and kind[2] != "any":
            other = ("parent_of", "out", "female" if kind[2] == "male" else "male")
            if other not in {k for (sd, k) in edges if sd == seed}:
                cases.append({"query": f"{ASK[other]} {name[seed]}", "query_type": "multi_hop",
                              "variant": "negative/wrong_gender", "expected_status": "no_verified_relation",
                              "expected_groups": []})
                if sum(c["variant"] == "negative/wrong_gender" for c in cases) >= 5:
                    break
    return cases


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
        # Crawled data holds one person under several entities ("Mỹ Tâm", "Mỹ Tâm (queen Vpop)"); the search
        # answers with all of them, so a person (all entities with one person_key) is the unit of truth.
        persons: dict[str, dict] = {}
        for e in ents:
            if e["entity_type"] != "person":
                continue
            key = person_key(e["canonical_name"])
            p = persons.setdefault(key, {"key": key, "ids": [], "name": display_name(e["canonical_name"]), "n": 0})
            p["ids"].append(e["entity_id"])
            p["n"] += e["n"]
        people = sorted(persons.values(), key=lambda p: p["key"])
        rnd.shuffle(people)
        places = [e for e in ents if e["entity_type"] == "place"]
        n = args.per_type

        # ---- single intent: one case per person, cycling through the ways people type a name
        variants = ["name", "no_diacritics", "typo", "name+scene", "title", "case_space_punct"]
        for i, p in enumerate(people[:n]):
            name, variant = p["name"], variants[i % len(variants)]
            q = {"name": f"ảnh {name}", "no_diacritics": fold(name), "typo": typo(name, rnd),
                 "name+scene": f"{name} {rnd.choice(SCENES)}", "title": f"{rnd.choice(TITLE_WORDS)} {name}",
                 "case_space_punct": f"  {name.upper()}  !!"}[variant]
            cases.append({"query": q, "query_type": "single", "variant": variant, "expected_status": "ok",
                          "expected_groups": [p["ids"]]})
        for pl in places[: max(2, n // 10)]:
            cases.append({"query": f"bãi biển {pl['canonical_name']}", "query_type": "single", "variant": "place+scene",
                          "expected_status": "ok", "expected_groups": [[pl["entity_id"]]]})

        # ---- multi-intent: two groups, union, comma list, same photo
        rest = people[n:] or people
        pairs = [(rest[i], rest[i + 1]) for i in range(0, len(rest) - 1, 2)][: n // 2]
        for j, (a, b) in enumerate(pairs):
            kind = ["two_groups", "union", "comma"][j % 3]
            q = {"two_groups": f"ảnh {a['name']} và {b['name']}", "union": f"{a['name']} hoặc {b['name']}",
                 "comma": f"{a['name']}, {b['name']}"}[kind]
            groups = [a["ids"] + b["ids"]] if kind == "union" else [a["ids"], b["ids"]]
            cases.append({"query": q, "query_type": "multi_intent", "variant": kind, "expected_status": "ok",
                          "expected_groups": groups})
        key_of = {i: p["key"] for p in persons.values() for i in p["ids"]}
        # a pair filed together on most of their photos is one person under two crawled names
        # ("Jack" and "Jack J97"), not two people photographed together
        together = conn.execute("""
            WITH n AS (SELECT entity_id, count(*) AS c FROM image_entities WHERE approval_status = 'approved'
                       GROUP BY 1)
            SELECT a.entity_id::text AS a, b.entity_id::text AS b
            FROM image_entities a JOIN image_entities b ON a.image_id = b.image_id AND a.entity_id < b.entity_id
            JOIN images i ON i.image_id = a.image_id
            JOIN n na ON na.entity_id = a.entity_id JOIN n nb ON nb.entity_id = b.entity_id
            WHERE i.is_serving AND a.approval_status = 'approved' AND b.approval_status = 'approved'
            GROUP BY 1, 2, na.c, nb.c
            HAVING count(*) * 2 < least(na.c, nb.c)
        """).fetchall()
        seen = set()
        for t in together:  # two different people in one photo, not two duplicates of one person
            ka, kb = key_of.get(t["a"]), key_of.get(t["b"])
            if not ka or not kb or ka == kb or (ka, kb) in seen:
                continue
            # "Hương Giang" / "Hương Giang Idol", "Thanh Thủy" / "Huỳnh Thị Thanh Thủy", "Nguyên Khang" / "Nguyễn Khang":
            # typed the usual way, one name is the other or part of it, so no query can tell them apart
            wa, wb = set(fold(persons[ka]["name"]).split()), set(fold(persons[kb]["name"]).split())
            if wa <= wb or wb <= wa:
                continue
            seen.add((ka, kb))
            if len(seen) > max(2, n // 6):
                break
            a, b = persons[ka], persons[kb]
            cases.append({"query": f"{a['name']} chụp cùng {b['name']}", "query_type": "multi_intent",
                          "variant": "same_photo", "expected_status": "ok", "expected_groups": [a["ids"] + b["ids"]],
                          "require_all_groups": [a["ids"], b["ids"]]})

        # ---- robustness: inputs that tempt the system into confident wrong answers
        aliases = {r["alias_fold"] for r in conn.execute("SELECT alias_fold FROM entity_aliases").fetchall()}
        cases += robustness_cases(people, aliases, max(10, n // 20), rnd)

        # ---- multi-hop from verified relations
        cases += multi_hop_cases(conn, {e["entity_id"] for e in ents}, people, n, rnd)

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
