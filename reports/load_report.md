# Load test report

Generated 2026-10-20 07:52 UTC by `eval/run_load.py` (Locust, headless). Host `http://localhost:8080`, 90327 serving images, encoder `siglip-onnx:siglip2`, client machine AMD64 / 16 CPU.

Each step: N users, each waits 0.5–1.5 s between requests, 60 s per step, result cache off. Failures include any response slower than 3 s.

| Users | Type | Requests | Failures | RPS | p50 ms | p95 ms | p99 ms | max ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | multi_hop | 17 | 0 | 0.3 | 54 | 69 | 69 | 69 |
| 1 | multi_intent | 12 | 0 | 0.2 | 59 | 110 | 110 | 108 |
| 1 | single | 21 | 0 | 0.4 | 59 | 97 | 97 | 97 |
| 1 | Aggregated | 50 | 0 | 1.0 | 58 | 97 | 110 | 108 |
| 5 | multi_hop | 100 | 0 | 1.7 | 62 | 79 | 86 | 86 |
| 5 | multi_intent | 79 | 0 | 1.3 | 62 | 82 | 110 | 113 |
| 5 | single | 108 | 0 | 1.8 | 70 | 100 | 130 | 137 |
| 5 | Aggregated | 287 | 0 | 4.8 | 65 | 100 | 110 | 137 |
| 10 | multi_hop | 189 | 0 | 3.2 | 59 | 76 | 82 | 91 |
| 10 | multi_intent | 190 | 0 | 3.2 | 60 | 78 | 110 | 149 |
| 10 | single | 181 | 0 | 3.0 | 62 | 99 | 110 | 118 |
| 10 | Aggregated | 560 | 0 | 9.4 | 60 | 90 | 100 | 149 |
| 20 | multi_hop | 411 | 0 | 6.9 | 57 | 75 | 90 | 95 |
| 20 | multi_intent | 352 | 0 | 5.9 | 59 | 78 | 99 | 141 |
| 20 | single | 359 | 0 | 6.0 | 62 | 110 | 140 | 176 |
| 20 | Aggregated | 1122 | 0 | 18.8 | 59 | 95 | 120 | 176 |
