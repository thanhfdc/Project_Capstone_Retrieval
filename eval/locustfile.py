"""Load test: virtual users send queries from eval/testcases.jsonl, mixed evenly across types.

Each query type is a separate Locust task name, so the stats show latency per type.
The result cache is off unless CACHE=1 (then you measure the cache, not retrieval).
Run through eval/run_load.py, which sweeps the number of users and writes the report.
"""
import json
import os
import random
import time
from pathlib import Path

from locust import FastHttpUser, between, task

CASES = [json.loads(line) for line in
         Path(os.environ.get("CASES", "eval/testcases.jsonl")).read_text(encoding="utf-8").splitlines() if line.strip()]
BY_TYPE = {t: [c["query"] for c in CASES if c["query_type"] == t] for t in ("single", "multi_intent", "multi_hop")}
NOCACHE = "" if os.environ.get("CACHE") == "1" else "?nocache=true"


# FastHttpUser (geventhttpclient) needs several times less client CPU than HttpUser, so when Locust shares the
# machine with the API the measured ceiling is the server's rather than the load generator's.
class SearchUser(FastHttpUser):
    # THINK=0 removes the pause between requests to find the saturation throughput
    wait_time = between(0, 0) if os.environ.get("THINK") == "0" else between(0.5, 1.5)

    def _search(self, qtype: str):
        queries = BY_TYPE.get(qtype) or [c["query"] for c in CASES]
        q = random.choice(queries)
        started = time.perf_counter()
        with self.client.post(f"/api/search{NOCACHE}", json={"query": q, "top_k": 20},
                              name=qtype, catch_response=True) as resp:
            if resp.status_code != 200:
                resp.failure(f"HTTP {resp.status_code}")
            elif time.perf_counter() - started >= 3:
                resp.failure("slower than 3 s")

    @task
    def single(self):
        self._search("single")

    @task
    def multi_intent(self):
        self._search("multi_intent")

    @task
    def multi_hop(self):
        self._search("multi_hop")
