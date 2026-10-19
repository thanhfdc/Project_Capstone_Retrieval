# Hiệu năng: cách đo và số liệu hiện có

## 1. Con số trong file này là gì

Các số dưới đây đo trong môi trường phát triển (máy cloud, không GPU) với **encoder giả `hash`** và **80.023 ảnh tổng hợp** (`synth_scale.py` sinh vector ngẫu nhiên). Chúng chứng minh phần tìm kiếm (HNSW, full-text, SQL quan hệ, API) chạy dưới 3 giây ở quy mô 80K, **chưa** gồm thời gian encode câu hỏi bằng SigLIP thật và **chưa** nói gì về độ chính xác.

Số dùng để nộp phải đo lại trên máy chạy demo, với dữ liệu thật và `ENCODER_BACKEND=onnx`, bằng các lệnh ở mục 4. Các script tự ghi số ảnh đang phục vụ, encoder và cấu hình máy vào đầu báo cáo.

## 2. Kết quả trong môi trường phát triển (hash encoder, 80.023 ảnh)

| Loại truy vấn | Server time |
|---|---|
| Theo tên người / quan hệ (SQL) | khoảng 5–15 ms |
| Mô tả tự do toàn kho (HNSW + full-text + RRF) | khoảng 110–230 ms |

`run_eval.py`: 0 câu ≥ 3 s; single-intent p99 228 ms.

Locust 20 người dùng (nghỉ 0,5–1,5 s), cache tắt: khoảng 20 RPS, p99 tổng 290 ms, max 336 ms, 0 failure.

Docker: image `api` khoảng 527 MB (không torch), `web` 74 MB; từ `docker compose up` đến `/health/ready` khoảng 12 s.

Pipeline: `finalize` trên 80K ảnh mất khoảng 86 s (xóa HNSW trước khi cập nhật hàng loạt rồi dựng lại).

## 3. Ước lượng phần còn thiếu khi dùng SigLIP thật

Encode một câu hỏi bằng text tower SigLIP 2 base (ONNX, CPU 4 luồng) thường vài chục ms; câu multi-intent gom các ý định vào một batch nên chỉ encode một lần. Đây là ước lượng, cần đo lại: API trả `encode_ms` riêng trong mỗi response để kiểm tra.

Phần tốn thời gian nhất là **offline**: embed 80K ảnh bằng image tower trên CPU có thể mất vài giờ; trên GPU nhanh hơn nhiều. Bước này chạy một lần, resume được.

## 4. Đo lại trên máy của bạn

```bash
pip install -r backend/requirements-dev.txt
export DATABASE_URL=postgresql://capstone:capstone@localhost:5433/capstone

# sinh test case từ dữ liệu thật
python eval/make_testcases.py --per-type 40 > eval/testcases.jsonl

# độ chính xác + latency từng câu
python eval/run_eval.py --api http://localhost:8080          # -> reports/eval_report.md

# throughput theo số người dùng
python eval/run_load.py --host http://localhost:8080 --users 1 5 10 20 --duration 60   # -> reports/load_report.md
THINK=0 python eval/run_load.py --host http://localhost:8080 --users 10 --duration 60 --out reports/saturation
```

Khi chưa đủ 80K ảnh thật, có thể thêm ảnh tổng hợp để kiểm tra latency ở quy mô yêu cầu, rồi xóa đi:

```bash
docker compose --profile jobs run --rm worker python -m app.jobs.synth_scale --count 80000
docker compose --profile jobs run --rm worker python -m app.jobs.synth_scale --remove
```

Báo cáo nộp cần ghi rõ phần nào là ảnh thật, phần nào là ảnh tổng hợp.
