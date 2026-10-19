"""Reproducible load test: sweep concurrent users with Locust and write reports/load_report.md.

Usage: python eval/run_load.py --host http://localhost:8080 --users 1 5 10 20 --duration 60
Each step runs headless for --duration seconds after the API is warm; raw Locust CSVs are
kept under reports/load/ so the numbers can be checked.
"""
import argparse
import csv
import json
import os
import platform
import subprocess
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent


def run_step(host: str, users: int, duration: int, out: Path, cases: str) -> list[dict]:
    prefix = out / f"u{users}"
    env = {**os.environ, "CASES": cases}
    cmd = [sys.executable, "-m", "locust", "-f", str(HERE / "locustfile.py"), "--headless", "--host", host,
           "-u", str(users), "-r", str(max(1, users)), "-t", f"{duration}s", "--csv", str(prefix),
           "--only-summary", "--exit-code-on-error", "0"]
    subprocess.run(cmd, check=True, env=env, stdout=subprocess.DEVNULL)
    with open(f"{prefix}_stats.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="http://localhost:8080")
    ap.add_argument("--users", type=int, nargs="+", default=[1, 5, 10, 20])
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--cases", default=str(HERE / "testcases.jsonl"))
    ap.add_argument("--out", default="reports")
    args = ap.parse_args()
    out = Path(args.out) / "load"
    out.mkdir(parents=True, exist_ok=True)
    try:
        stats = json.loads(urllib.request.urlopen(f"{args.host}/api/corpus/stats", timeout=5).read())
    except Exception:  # noqa: BLE001
        stats = {}

    table = []
    for users in args.users:
        print(f"running {users} users for {args.duration}s ...", flush=True)
        for row in run_step(args.host, users, args.duration, out, args.cases):
            table.append({"users": users, **row})

    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["# Load test report", "",
             f"Generated {stamp} by `eval/run_load.py` (Locust, headless). Host `{args.host}`, "
             f"{stats.get('serving_images', '?')} serving images, encoder `{stats.get('encoder_online', '?')}`, "
             f"client machine {platform.machine()} / {os.cpu_count()} CPU.", "",
             f"Each step: N users, each waits 0.5–1.5 s between requests, {args.duration} s per step, "
             "result cache off. Failures include any response slower than 3 s.", "",
             "| Users | Type | Requests | Failures | RPS | p50 ms | p95 ms | p99 ms | max ms |",
             "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for r in table:
        lines.append(f"| {r['users']} | {r['Name']} | {r['Request Count']} | {r['Failure Count']} | "
                     f"{float(r['Requests/s']):.1f} | {r['50%']} | {r['95%']} | {r['99%']} | {float(r['Max Response Time']):.0f} |")
    report = Path(args.out) / "load_report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
