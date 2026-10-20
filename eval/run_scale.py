"""Scale test on one host: how throughput grows with the number of API processes.

Usage (from the repo root, stack already running with `docker compose up -d`):
    python eval/run_scale.py --workers 1 2 4 --users 32 --duration 60
    python eval/run_scale.py --workers 1 2 4 --users 32 --duration 60 --in-docker   # Locust on the compose network

For each worker count the script recreates the api container with API_WORKERS=N (same ENCODER_THREADS and
image), restarts Nginx so it picks up the new container, waits until /api/corpus/stats reports N workers,
then runs Locust with no pause between requests (closed loop, so RPS is the saturation throughput).
While Locust runs it samples `docker stats` for the api and db containers (CPU and RAM).
At the end the api goes back to the settings in .env and the report is written to reports/scale_report.md.
"""
import argparse
import os
import platform
import re
import subprocess
import sys
import threading
import time
from datetime import UTC, datetime
from pathlib import Path

from run_load import LOCUST_IMAGE, get_stats, row_line, run_step

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def compose(*args: str, env: dict | None = None, capture: bool = False) -> str:
    proc = subprocess.run(["docker", "compose", *args], cwd=ROOT, env=env or os.environ, check=True,
                          capture_output=capture, text=True)
    return proc.stdout if capture else ""


def wait_ready(host: str, workers: int | None, timeout: float = 300) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        stats = get_stats(host)
        if stats and (workers is None or stats.get("api_workers") == workers):
            return stats
        time.sleep(3)
    raise SystemExit(f"api did not become ready with {workers} workers within {timeout:.0f} s")


def start_api(host: str, workers: int | None, threads: int | None, pool: int | None) -> dict:
    env = dict(os.environ)
    if workers is not None:
        env.update(API_WORKERS=str(workers), ENCODER_THREADS=str(threads), DB_POOL_MAX=str(pool))
    compose("up", "-d", "api", env=env)
    compose("restart", "web")  # Nginx resolves the api address once at startup
    return wait_ready(host, workers)


_SIZE = {"b": 1, "kib": 2**10, "mib": 2**20, "gib": 2**30, "kb": 1e3, "mb": 1e6, "gb": 1e9}


def _bytes(text: str) -> float:
    m = re.match(r"([\d.]+)\s*([a-zA-Z]+)", text.strip())
    return float(m.group(1)) * _SIZE.get(m.group(2).lower(), 1) if m else 0.0


class DockerSampler(threading.Thread):
    """Samples peak CPU % and memory of the given containers while a load step runs."""

    def __init__(self, containers: dict[str, str]):
        super().__init__(daemon=True)
        self.ids = {cid: label for label, cid in containers.items() if cid}
        self.cpu = {label: 0.0 for label in containers}
        self.mem = {label: 0.0 for label in containers}
        self.stop = threading.Event()

    def run(self):
        while not self.stop.is_set():
            try:
                out = subprocess.run(["docker", "stats", "--no-stream", "--format",
                                      "{{.ID}}|{{.CPUPerc}}|{{.MemUsage}}", *self.ids],
                                     capture_output=True, text=True, timeout=20).stdout
                for line in out.strip().splitlines():
                    cid, cpu, mem = line.split("|")
                    label = next((v for k, v in self.ids.items() if k.startswith(cid) or cid.startswith(k)), None)
                    if label:
                        self.cpu[label] = max(self.cpu[label], float(cpu.rstrip("%")))
                        self.mem[label] = max(self.mem[label], _bytes(mem.split("/")[0]))
            except Exception:  # noqa: BLE001 - sampling is best effort
                pass
            self.stop.wait(2)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--host", default="http://localhost:8080")
    ap.add_argument("--workers", type=int, nargs="+", default=[1, 2, 4])
    ap.add_argument("--threads", type=int, default=4, help="ENCODER_THREADS per worker, kept fixed across steps")
    ap.add_argument("--users", type=int, default=32, help="concurrent users with no pause between requests")
    ap.add_argument("--duration", type=int, default=60)
    ap.add_argument("--cases", default=str(HERE / "testcases.jsonl"))
    ap.add_argument("--out", default="reports")
    ap.add_argument("--in-docker", action="store_true",
                    help=f"run Locust in a {LOCUST_IMAGE} container on the compose network (skips host port forwarding)")
    ap.add_argument("--network", default="image-retrieval_default", help="compose network for --in-docker")
    ap.add_argument("--docker-host", default="http://web:8080", help="target URL seen from inside the network")
    args = ap.parse_args()
    net = args.network if args.in_docker else None
    target = args.docker_host if args.in_docker else args.host
    out = Path(args.out) / ("scale_docker" if net else "scale")
    out.mkdir(parents=True, exist_ok=True)

    results = []
    try:
        for n in args.workers:
            pool = min(10, max(2, 40 // n))  # all workers together stay below Postgres max_connections=50
            print(f"api with {n} workers x {args.threads} threads, pool {pool} ...", flush=True)
            stats = start_api(args.host, n, args.threads, pool)
            containers = {svc: compose("ps", "-q", svc, capture=True).strip() for svc in ("api", "db")}
            run_step(target, args.users, 10, out, args.cases, think=False, prefix_name=f"w{n}_warmup",
                     docker_network=net)
            sampler = DockerSampler(containers)
            sampler.start()
            rows, client_bound = run_step(target, args.users, args.duration, out, args.cases, think=False,
                                          prefix_name=f"w{n}", docker_network=net)
            sampler.stop.set()
            sampler.join(timeout=30)
            results.append({"workers": n, "pool": pool, "stats": stats, "rows": rows, "client_bound": client_bound,
                            "cpu": sampler.cpu, "mem": sampler.mem})
    finally:
        print("restoring api to the settings in .env ...", flush=True)
        start_api(args.host, None, None, None)

    stats = results[0]["stats"] if results else {}
    base = None
    lines = ["# Scale report", "",
             f"Generated {datetime.now(UTC).strftime('%Y-%m-%d %H:%M UTC')} by `eval/run_scale.py`. "
             f"Target `{target}`, Locust {'in a container on the compose network' if net else 'on the host'}, "
             f"{stats.get('serving_images', '?')} serving images, encoder "
             f"`{stats.get('encoder_online', '?')}`, machine {platform.machine()} / {os.cpu_count()} CPU "
             "(Locust, API and Postgres share it).", "",
             f"Each step: {args.users} users with no pause between requests (closed loop), {args.duration} s after a "
             f"10 s warm-up, query mix single / multi-intent / multi-hop evenly, result cache off, "
             f"{args.threads} encoder threads per worker. Failures include any response slower than 3 s. "
             "CPU % is of one core (400% = 4 cores busy), peak over the step; RAM is the container's peak.", "",
             "| API workers | DB pool / worker | Requests | Failures | RPS | x vs 1 worker | p50 ms | p95 ms | "
             "p99 ms | max ms | api CPU | api RAM | db CPU |",
             "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for res in results:
        agg = next((r for r in res["rows"] if r["Name"] == "Aggregated"), None)
        if agg is None:
            continue
        rps = float(agg["Requests/s"])
        base = base or rps
        lines.append(f"| {res['workers']} | {res['pool']} | {agg['Request Count']} | {agg['Failure Count']} | "
                     f"{rps:.1f} | {rps / base:.2f} | {agg['50%']} | {agg['95%']} | {agg['99%']} | "
                     f"{float(agg['Max Response Time']):.0f} | {res['cpu']['api']:.0f}% | {res['mem']['api'] / 2**20:.0f} MiB | "
                     f"{res['cpu']['db']:.0f}% |")
    lines += ["", "Per query type:", "", "| Workers | Type | Requests | Failures | RPS | p50 ms | p95 ms | p99 ms | max ms |",
              "|---:|---|---:|---:|---:|---:|---:|---:|---:|"]
    for res in results:
        lines += [row_line(f"{res['workers']} | ", r) for r in res["rows"] if r["Name"] != "Aggregated"]
    bound = [res["workers"] for res in results if res["client_bound"]]
    if bound:
        lines += ["", f"Locust reported its own CPU above 90% with {bound} workers: those steps may be limited by "
                      "the load generator, not the API."]
    report = Path(args.out) / ("scale_report_docker.md" if net else "scale_report.md")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
