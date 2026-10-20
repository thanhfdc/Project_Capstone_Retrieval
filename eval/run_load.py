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


LOCUST_IMAGE = "locustio/locust:2.32.4"


def run_step(host: str, users: int, duration: int, out: Path, cases: str, think: bool = True,
             prefix_name: str | None = None, docker_network: str | None = None) -> tuple[list[dict], bool]:
    """Run one Locust step. Returns the stats rows and whether Locust warned that its own CPU was saturated.

    With docker_network, Locust runs in a container on the compose network, so requests skip the host's
    port forwarding (on Docker Desktop for Windows/macOS that path adds tens of ms per request).
    """
    name = prefix_name or f"u{users}"
    prefix = out / name
    env = {**os.environ, "CASES": cases}
    if not think:
        env["THINK"] = "0"
    args = ["--headless", "--host", host, "-u", str(users), "-r", str(max(1, users)), "-t", f"{duration}s",
            "--only-summary", "--exit-code-on-error", "0"]
    if docker_network:
        cmd = ["docker", "run", "--rm", "--network", docker_network,
               "-v", f"{HERE}:/mnt/eval:ro", "-v", f"{out.resolve()}:/mnt/out",
               "-e", f"CASES=/mnt/eval/{Path(cases).name}", "-e", f"THINK={'1' if think else '0'}",
               LOCUST_IMAGE, "-f", "/mnt/eval/locustfile.py", *args, "--csv", f"/mnt/out/{name}"]
    else:
        cmd = [sys.executable, "-m", "locust", "-f", str(HERE / "locustfile.py"), *args, "--csv", str(prefix)]
    proc = subprocess.run(cmd, check=True, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
                          text=True, encoding="utf-8", errors="replace")
    with open(f"{prefix}_stats.csv", encoding="utf-8") as fh:
        return list(csv.DictReader(fh)), "CPU usage above" in proc.stderr


def get_stats(host: str) -> dict:
    try:
        return json.loads(urllib.request.urlopen(f"{host}/api/corpus/stats", timeout=5).read())
    except Exception:  # noqa: BLE001
        return {}


def row_line(prefix: str, r: dict) -> str:
    return (f"| {prefix}{r['Name']} | {r['Request Count']} | {r['Failure Count']} | "
            f"{float(r['Requests/s']):.1f} | {r['50%']} | {r['95%']} | {r['99%']} | "
            f"{float(r['Max Response Time']):.0f} |")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="http://localhost:8080")
    ap.add_argument("--users", type=int, nargs="+", default=[1, 5, 10, 20])
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--cases", default=str(HERE / "testcases.jsonl"))
    ap.add_argument("--out", default="reports")
    ap.add_argument("--no-think", action="store_true",
                    help="no pause between requests: each user sends the next query as soon as one returns")
    args = ap.parse_args()
    out = Path(args.out) / "load"
    out.mkdir(parents=True, exist_ok=True)
    stats = get_stats(args.host)

    table, client_bound = [], []
    for users in args.users:
        print(f"running {users} users for {args.duration}s ...", flush=True)
        rows, warned = run_step(args.host, users, args.duration, out, args.cases, think=not args.no_think)
        table += [{"users": users, **row} for row in rows]
        if warned:
            client_bound.append(users)

    stamp = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    pause = "no pause between requests" if args.no_think else "each waits 0.5–1.5 s between requests"
    lines = ["# Load test report", "",
             f"Generated {stamp} by `eval/run_load.py` (Locust, headless). Host `{args.host}`, "
             f"{stats.get('serving_images', '?')} serving images, encoder `{stats.get('encoder_online', '?')}`, "
             f"API workers {stats.get('api_workers', '?')} x {stats.get('encoder_threads', '?')} encoder threads, "
             f"client machine {platform.machine()} / {os.cpu_count()} CPU.", "",
             f"Each step: N users, {pause}, {args.duration} s per step, "
             "result cache off. Failures include any response slower than 3 s.", "",
             "| Users | Type | Requests | Failures | RPS | p50 ms | p95 ms | p99 ms | max ms |",
             "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    lines += [row_line(f"{r['users']} | ", r) for r in table]
    if client_bound:
        lines += ["", f"Locust reported its own CPU above 90% at {client_bound} users: those steps may be limited "
                      "by the load generator, not the API."]
    report = Path(args.out) / "load_report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
