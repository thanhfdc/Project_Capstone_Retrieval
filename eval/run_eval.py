"""Run every test case against the API and write a quality + latency report.

Latency is measured on the client (request sent -> full JSON received) with the result
cache disabled (?nocache=true), one request at a time after a warm-up. Load/throughput is
measured separately with Locust (eval/run_load.py).

Usage: python eval/run_eval.py --api http://localhost:8080 --cases eval/testcases.jsonl
"""
import argparse
import json
import os
import statistics
import sys
import time
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import psycopg

SLO_MS = 3000


def post(api: str, query: str, top_k: int) -> tuple[dict, float]:
    body = json.dumps({"query": query, "top_k": top_k}).encode()
    req = urllib.request.Request(f"{api}/api/search?nocache=true", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    return data, (time.perf_counter() - t0) * 1000


def pct(values: list[float], p: float) -> float:
    if not values:
        return float("nan")
    values = sorted(values)
    k = (len(values) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(values) - 1)
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--api", default="http://localhost:8080")
    ap.add_argument("--cases", default="eval/testcases.jsonl")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()
    cases = [json.loads(line) for line in Path(args.cases).read_text(encoding="utf-8").splitlines() if line.strip()]
    db = os.environ.get("DATABASE_URL")
    links: dict[str, set[str]] = defaultdict(set)  # image_id -> approved entity ids
    if db:
        with psycopg.connect(db) as conn:
            for image_id, entity_id in conn.execute(
                    "SELECT image_id::text, entity_id::text FROM image_entities WHERE approval_status = 'approved'"):
                links[image_id].add(entity_id)

    for c in cases[:5]:  # warm-up, not measured
        post(args.api, c["query"], args.top_k)

    rows = []
    for c in cases:
        try:
            r, ms = post(args.api, c["query"], args.top_k)
        except Exception as exc:  # noqa: BLE001
            rows.append({**c, "error": str(exc), "client_ms": None})
            continue
        got_status = "ok" if r["status"] in ("ok", "partial") else r["status"]
        row = {**c, "status": r["status"], "status_ok": got_status == c.get("expected_status", "ok"),
               "client_ms": round(ms, 1), "server_ms": r["metrics"]["server_ms"], "parser": r["interpretation"]["parser"],
               "llm_calls": r["metrics"]["llm_calls"], "tokens": r["metrics"]["input_tokens"] + r["metrics"]["output_tokens"],
               "detected_type": r["query_type"], "top": []}
        expected = c.get("expected_groups") or []
        if expected and links:
            precisions, covered = [], 0
            for exp in expected:
                exp_set = set(exp)
                # the group that best matches this expectation
                best = None
                for g in r["groups"]:
                    ids = g["image_ids"][: args.top_k]
                    if not ids:
                        continue
                    if c.get("require_all"):
                        hits = [i for i in ids if exp_set <= links[i]]
                    else:
                        hits = [i for i in ids if links[i] & exp_set]
                    p = len(hits) / len(ids)
                    if best is None or p > best:
                        best = p
                precisions.append(best or 0.0)
                covered += 1 if best else 0
            row["precision_at_k"] = round(statistics.mean(precisions), 3)
            row["intent_coverage"] = round(covered / len(expected), 3)
        for g in r["groups"]:
            names = [", ".join(e["name"] for e in r["items"][i]["entities"]) for i in g["image_ids"][:3]]
            row["top"].append(f"{g['label']}: {' | '.join(names) or g['status']}")
        rows.append(row)

    by_type = defaultdict(list)
    for row in rows:
        by_type[row["query_type"]].append(row)
    summary = {}
    for qt, rs in sorted(by_type.items()):
        lat = [r["client_ms"] for r in rs if r.get("client_ms") is not None]
        prec = [r["precision_at_k"] for r in rs if "precision_at_k" in r]
        cov = [r["intent_coverage"] for r in rs if "intent_coverage" in r]
        summary[qt] = {
            "cases": len(rs),
            "status_accuracy": round(sum(r.get("status_ok", False) for r in rs) / len(rs), 3),
            "type_detected_correctly": round(sum(r.get("detected_type") == qt for r in rs) / len(rs), 3),
            "precision_at_k": round(statistics.mean(prec), 3) if prec else None,
            "intent_coverage": round(statistics.mean(cov), 3) if cov else None,
            "p50_ms": round(pct(lat, 50), 1), "p95_ms": round(pct(lat, 95), 1), "p99_ms": round(pct(lat, 99), 1),
            "max_ms": round(max(lat), 1) if lat else None,
            "over_3s": sum(1 for x in lat if x >= SLO_MS),
            "errors": sum(1 for r in rs if r.get("error")),
            "llm_calls": sum(r.get("llm_calls", 0) for r in rs),
            "tokens": sum(r.get("tokens", 0) for r in rs),
        }

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    try:
        stats = json.loads(urllib.request.urlopen(f"{args.api}/api/corpus/stats", timeout=5).read())
    except Exception:  # noqa: BLE001
        stats = {}
    (out / "eval_results.json").write_text(json.dumps({"summary": summary, "rows": rows, "corpus": stats},
                                                      ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Quality and latency report", "", f"Generated {stamp} against `{args.api}`. "
             f"Serving images: **{stats.get('serving_images', '?')}**, online encoder `{stats.get('encoder_online', '?')}`.", "",
             "Latency = client-side time from sending the request to receiving the full JSON, result cache off, "
             f"one request at a time, top_k={args.top_k}.", "",
             "| Type | Cases | Status acc. | Type detected | Precision@k | Intent coverage | p50 ms | p95 ms | p99 ms | max ms | ≥3 s | Errors | LLM calls | Tokens |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    def as_pct(v):
        return "" if v is None else f"{v:.0%}"

    for qt, s in summary.items():
        lines.append(f"| {qt} | {s['cases']} | {s['status_accuracy']:.0%} | {s['type_detected_correctly']:.0%} | "
                     f"{as_pct(s['precision_at_k'])} | {as_pct(s['intent_coverage'])} | "
                     f"{s['p50_ms']} | {s['p95_ms']} | {s['p99_ms']} | {s['max_ms']} | {s['over_3s']} | {s['errors']} | "
                     f"{s['llm_calls']} | {s['tokens']} |")
    lines += ["", "## Failed or suspicious cases", ""]
    for r in rows:
        bad = (not r.get("status_ok", False)) or r.get("precision_at_k", 1) < 0.5 or r.get("error")
        if bad:
            lines.append(f"- `{r['id']}` [{r['query_type']}/{r.get('variant')}] “{r['query']}” → {r.get('status', r.get('error'))}, "
                         f"precision {r.get('precision_at_k', '-')}; top: {' / '.join(r.get('top', []))[:200]}")
    lines += ["", "## Manual cases (judge by eye)", ""]
    for r in rows:
        if r.get("variant") == "manual":
            lines.append(f"- “{r['query']}” → {r.get('status')} ({r.get('client_ms')} ms): {' / '.join(r.get('top', []))[:300]}")
    (out / "eval_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines[:12 + len(summary)]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
