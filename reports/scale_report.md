# Scale report

Generated 2026-10-20 08:31 UTC by `eval/run_scale.py`. Host `http://localhost:8080`, 90327 serving images, encoder `siglip-onnx:siglip2`, machine AMD64 / 16 CPU (Locust, API and Postgres share it).

Each step: 32 users with no pause between requests (closed loop), 60 s after a 10 s warm-up, query mix single / multi-intent / multi-hop evenly, result cache off, 4 encoder threads per worker. Failures include any response slower than 3 s. CPU % is of one core (400% = 4 cores busy); RAM is the api container's peak.

| API workers | DB pool / worker | Requests | Failures | RPS | x vs 1 worker | p50 ms | p95 ms | p99 ms | max ms | api CPU peak | api RAM peak |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 10 | 16742 | 0 | 277.8 | 1.00 | 82 | 370 | 500 | 822 | 502% | 1911 MiB |
| 2 | 10 | 15754 | 0 | 266.2 | 0.96 | 85 | 390 | 510 | 897 | 517% | 2773 MiB |
| 4 | 10 | 20842 | 0 | 352.0 | 1.27 | 58 | 420 | 650 | 1302 | 1115% | 5385 MiB |

Per query type:

| Workers | Type | Requests | Failures | RPS | p50 ms | p95 ms | p99 ms | max ms |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | multi_hop | 5608 | 0 | 93.1 | 79 | 140 | 190 | 775 |
| 1 | multi_intent | 5587 | 0 | 92.7 | 80 | 160 | 440 | 666 |
| 1 | single | 5547 | 0 | 92.1 | 93 | 450 | 560 | 822 |
| 2 | multi_hop | 5224 | 0 | 88.3 | 82 | 150 | 200 | 712 |
| 2 | multi_intent | 5230 | 0 | 88.4 | 83 | 180 | 450 | 715 |
| 2 | single | 5300 | 0 | 89.6 | 94 | 460 | 560 | 897 |
| 4 | multi_hop | 6882 | 0 | 116.2 | 52 | 130 | 190 | 851 |
| 4 | multi_intent | 7037 | 0 | 118.8 | 51 | 160 | 540 | 1302 |
| 4 | single | 6923 | 0 | 116.9 | 71 | 600 | 730 | 1281 |
