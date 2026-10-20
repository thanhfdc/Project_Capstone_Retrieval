# Scale report

Generated 2026-10-20 08:46 UTC by `eval/run_scale.py`. Target `http://web:8080`, Locust in a container on the compose network, 90327 serving images, encoder `siglip-onnx:siglip2`, machine AMD64 / 16 CPU (Locust, API and Postgres share it).

Each step: 32 users with no pause between requests (closed loop), 60 s after a 10 s warm-up, query mix single / multi-intent / multi-hop evenly, result cache off, 4 encoder threads per worker. Failures include any response slower than 3 s. CPU % is of one core (400% = 4 cores busy), peak over the step; RAM is the container's peak.

| API workers | DB pool / worker | Requests | Failures | RPS | x vs 1 worker | p50 ms | p95 ms | p99 ms | max ms | api CPU | api RAM | db CPU |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 10 | 17382 | 0 | 292.2 | 1.00 | 77 | 360 | 460 | 877 | 500% | 1915 MiB | 72% |
| 2 | 10 | 16377 | 0 | 276.1 | 0.94 | 84 | 360 | 480 | 1011 | 658% | 2761 MiB | 62% |
| 4 | 10 | 21486 | 0 | 361.3 | 1.24 | 22 | 530 | 910 | 1564 | 1366% | 6384 MiB | 122% |

Per query type:

| Workers | Type | Requests | Failures | RPS | p50 ms | p95 ms | p99 ms | max ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | multi_hop | 5787 | 0 | 97.3 | 75 | 130 | 170 | 694 |
| 1 | multi_intent | 5864 | 0 | 98.6 | 75 | 150 | 400 | 672 |
| 1 | single | 5731 | 0 | 96.3 | 88 | 430 | 510 | 877 |
| 2 | multi_hop | 5541 | 0 | 93.4 | 82 | 140 | 190 | 639 |
| 2 | multi_intent | 5457 | 0 | 92.0 | 82 | 160 | 420 | 703 |
| 2 | single | 5379 | 0 | 90.7 | 94 | 430 | 530 | 1011 |
| 4 | multi_hop | 7177 | 0 | 120.7 | 20 | 140 | 230 | 1027 |
| 4 | multi_intent | 7091 | 0 | 119.2 | 20 | 200 | 760 | 1188 |
| 4 | single | 7218 | 0 | 121.4 | 34 | 810 | 1000 | 1564 |
