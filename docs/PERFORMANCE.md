# Hiệu năng: cách đo và số liệu hiện có

## 1. Con số trong file này là gì

Số ở mục 2 đo trên máy chạy demo ngày 20/10/2026 với **dữ liệu thật** (90.327 ảnh đang phục vụ) và **SigLIP 2 thật** (`siglip-onnx:siglip2`, ONNX trên CPU), bằng `eval/run_eval.py`. Mục 3 là throughput từ load test Locust (`eval/run_load.py`). Đầu mỗi báo cáo tự ghi số ảnh, encoder và cấu hình máy.

## 2. Latency từng câu (dữ liệu thật, SigLIP thật)

Đo ở client: từ lúc gửi HTTP request đến khi nhận đủ JSON, cache kết quả tắt, gửi tuần tự, top_k = 10, 5 câu warm-up không tính.

| Loại | Số câu | p50 | p95 | p99 | max | ≥ 3 s |
|---|---:|---:|---:|---:|---:|---:|
| Single intent | 1.507 | 3,0 ms | 40,5 ms | 55,0 ms | 95,3 ms | 0 |
| Multi-intent | 842 | 2,9 ms | 5,6 ms | 46,2 ms | 123,9 ms | 0 |
| Multi-hop | 605 | 2,8 ms | 4,0 ms | 5,4 ms | 52,5 ms | 0 |
| Robustness | 222 | 10,9 ms | 60,7 ms | 84,0 ms | 168,2 ms | 0 |

Câu theo tên người và quan hệ chạy bằng SQL trên chỉ mục nên chỉ vài ms. Câu mô tả tự do toàn kho (encode SigLIP + HNSW + full-text + RRF) là nhóm chậm nhất, vẫn dưới 0,5 giây (lần chạy lúc 07:47 cùng ngày có câu chậm nhất 438 ms). 0 lần gọi LLM. Nguồn: `reports/eval_report.md` (20/10/2026 08:57, 3.176 câu).

## 3. Throughput (load test)

Đo bằng `eval/run_load.py` (Locust headless) trên máy demo ngày 20/10/2026 07:52, qua Nginx `http://localhost:8080`, 90.327 ảnh, SigLIP 2 ONNX, máy 16 CPU. Mỗi mức chạy 60 giây, mỗi người dùng nghỉ 0,5 đến 1,5 giây giữa hai request, trộn đều 3 loại câu, cache kết quả tắt; request quá 3 giây tính là failure.

| Người dùng | Request | Failure | RPS | p50 | p95 | p99 | max |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 50 | 0 | 1,0 | 58 ms | 97 ms | 110 ms | 108 ms |
| 5 | 287 | 0 | 4,8 | 65 ms | 100 ms | 110 ms | 137 ms |
| 10 | 560 | 0 | 9,4 | 60 ms | 90 ms | 100 ms | 149 ms |
| 20 | 1.122 | 0 | 18,8 | 59 ms | 95 ms | 120 ms | 176 ms |

RPS tăng gần tuyến tính theo số người dùng và latency không tăng, nên ở 20 người hệ thống chưa bão hòa. Muốn đo trần thì chạy thêm với `THINK=0`. Latency ở đây cao hơn mục 2 vì đi qua Nginx và Locust chạy chung máy. Nguồn: `reports/load_report.md`, CSV gốc trong `reports/load/`.

## 3b. Scale trên một máy: số process API

**Cách làm.** Mỗi process API giữ một bản model ONNX, một khe encode (semaphore 1, mỗi lần encode dùng `ENCODER_THREADS` luồng) và một pool kết nối DB. Python có GIL nên một process chỉ dùng tốt khoảng một nhân cho phần parse và ghép kết quả; tăng throughput trên một máy là chạy nhiều process uvicorn (`API_WORKERS`, biến `WEB_CONCURRENCY` của uvicorn) sau cùng Nginx. Không cần thêm container, load balancer hay Kubernetes; đây là "Mức 1–2" ở mục 19.3 của file hướng dẫn.

Ràng buộc khi chọn số worker:
- `API_WORKERS × ENCODER_THREADS` không vượt số nhân CPU, nếu không các lần encode tranh nhau CPU.
- `API_WORKERS × DB_POOL_MAX` dưới `max_connections = 50` của Postgres.
- RAM tăng theo số worker vì mỗi worker nạp một bản text encoder.
- Migration chạy lúc khởi động có advisory lock nên nhiều worker không chạy chồng nhau.

**Cách đo.** `eval/run_scale.py` dựng lại container `api` với 1, 2, 4 worker (giữ nguyên `ENCODER_THREADS`), chờ `/api/corpus/stats` báo đúng số worker, chạy Locust không nghỉ giữa các request (closed loop, 32 người dùng, 60 s sau 10 s warm-up), lấy CPU và RAM của container bằng `docker stats`, rồi trả api về cấu hình trong `.env`. Locust dùng `FastHttpUser` để chính máy phát tải không thành nút thắt; nếu Locust báo CPU của nó vượt 90% thì báo cáo ghi rõ.

**Kết quả** (máy demo 16 CPU, 20/10/2026 08:46, SigLIP 2 ONNX, 4 luồng encode mỗi worker, Locust chạy trong mạng Docker, nguồn `reports/scale_report_docker.md`):

| Worker API | RPS bão hòa | so với 1 worker | p50 | p95 | p99 | max | Lỗi | CPU api | RAM api | CPU db |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | 292 | 1,00 | 77 ms | 360 ms | 460 ms | 877 ms | 0 / 17.382 | 500% | 1,9 GB | 72% |
| 2 | 276 | 0,94 | 84 ms | 360 ms | 480 ms | 1.011 ms | 0 / 16.377 | 658% | 2,8 GB | 62% |
| 4 | 361 | 1,24 | 22 ms | 530 ms | 910 ms | 1.564 ms | 0 / 21.486 | 1.366% | 6,4 GB | 122% |

Chạy cùng lệnh với Locust trên Windows (`reports/scale_report.md`) cho gần như cùng số (278 / 266 / 352 RPS), nên đường mạng từ Windows vào Docker không phải nút thắt.

**Đọc kết quả:**
- **Một process đã đủ dư.** 32 người gửi liên tục không nghỉ, 292 RPS, không câu nào lỗi hay quá 3 giây. Tải thực tế đo ở mục 3 (20 người, có nghỉ) là 18,8 RPS, tức khoảng 6% sức chứa.
- **Thêm worker gần như không tăng throughput.** 4 worker chỉ thêm 24% RPS nhưng RAM gấp 3,3 lần và p99 gấp đôi. Câu theo tên nhanh hơn (p50 22 ms), câu mô tả cảnh chậm hơn vì mỗi worker encode 4 luồng và cùng tranh 16 nhân với Postgres, Nginx và Locust trên một máy. Nút thắt là CPU cho encoder SigLIP của câu mô tả, không phải số process.
- **Cấu hình chọn:** giữ `API_WORKERS=1` (p99 tốt nhất, ít RAM nhất). Khi cần chịu tải lớn hơn mà không tăng p99, hướng hợp lý là tách encoder ra máy riêng hoặc GPU, hoặc thêm máy chạy replica api phía sau load balancer, thay vì tăng worker trên cùng máy. Hướng thử tiếp trên máy hiện tại: `ENCODER_THREADS` 1–2 với nhiều worker, và tắt spin-wait của onnxruntime (`session.intra_op.allow_spinning=0`) để luồng chờ không đốt CPU.

Docker: image `api` khoảng 527 MB (không torch), `web` 74 MB; từ `docker compose up` đến `/health/ready` khoảng 12 s. `finalize` trên 80K ảnh khoảng 86 s (xóa HNSW trước khi cập nhật hàng loạt rồi dựng lại). Embed ảnh bằng image tower trên CPU là bước lâu nhất, chạy một lần và resume được.

## 4. Đo lại trên máy của bạn

```bash
pip install -r backend/requirements-dev.txt
export DATABASE_URL=postgresql://capstone:capstone@localhost:5433/capstone

# sinh test case từ dữ liệu thật
python eval/make_testcases.py --per-type 1500 > eval/testcases.jsonl

# độ chính xác + latency từng câu
python eval/run_eval.py --api http://localhost:8080          # -> reports/eval_report.md

# throughput theo số người dùng
python eval/run_load.py --host http://localhost:8080 --users 1 5 10 20 --duration 60   # -> reports/load_report.md
python eval/run_load.py --host http://localhost:8080 --users 10 --duration 60 --no-think --out reports/saturation

# scale theo số process API (dựng lại container api, cuối cùng trả về cấu hình .env)
python eval/run_scale.py --workers 1 2 4 --users 32 --duration 60    # -> reports/scale_report.md
python eval/run_scale.py --workers 1 2 4 --users 32 --duration 60 --in-docker   # Locust trong mạng Docker -> reports/scale_report_docker.md
```

Khi chưa đủ 80K ảnh thật, có thể thêm ảnh tổng hợp để kiểm tra latency ở quy mô yêu cầu, rồi xóa đi:

```bash
docker compose --profile jobs run --rm worker python -m app.jobs.synth_scale --count 80000
docker compose --profile jobs run --rm worker python -m app.jobs.synth_scale --remove
```

Báo cáo nộp cần ghi rõ phần nào là ảnh thật, phần nào là ảnh tổng hợp.
