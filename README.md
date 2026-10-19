# Image Retrieval: tìm ảnh bằng câu hỏi tiếng Việt (Capstone, Phần B)

Tìm ảnh trong kho khoảng 80K ảnh bằng ngôn ngữ tự nhiên, hỗ trợ 3 loại câu hỏi:

| Loại | Ví dụ |
|---|---|
| Single intent | "ảnh Sơn Tùng đang biểu diễn", "bãi biển Nha Trang" |
| Multi-intent | "hồ bơi và công viên nước ở Phú Quốc", "Sơn Tùng chụp cùng Hà Anh Tuấn" |
| Multi-hop | "ảnh con trai chủ tịch Phạm Nhật Vượng", "con trai của người sáng lập Vingroup" |

Stack: FastAPI, PostgreSQL 16 + pgvector (HNSW) + full-text, SigLIP 2 (text tower chạy ONNX), React + Nginx, Docker Compose, GitHub Actions.

Tài liệu: [kiến trúc và sơ đồ](docs/ARCHITECTURE.md) · [cách làm test case](docs/TESTING.md) · [hiệu năng](docs/PERFORMANCE.md)

## Chạy từ đầu

Cần Docker Desktop (hoặc Docker Engine + Compose v2), khoảng 10 GB đĩa trống, RAM 8 GB trở lên.

**1. Đặt dữ liệu**

```
data/raw/*.csv              # mọi file CSV (file 24 cột có cột flag, file 8 cột có cột status đều được)
data/raw/images/...         # (tùy chọn) ảnh có sẵn trên máy, giữ nguyên thư mục con như cột local_path
data/relations/*.csv        # quan hệ cho multi-hop, xem mục "Quan hệ" bên dưới
```

Tên cột được nhận theo tên trong `backend/config/import_profiles.json`; nếu file của bạn đặt tên khác, thêm tên đó vào danh sách tương ứng.

**2. Tải model và chạy pipeline offline** (chỉ làm một lần; chạy lại sẽ tiếp tục chỗ đang dở)

```bash
docker compose --profile jobs build worker
docker compose --profile jobs run --rm worker python -m app.jobs.download_model
docker compose --profile jobs run --rm worker
```

Pipeline gồm: import CSV → tải ảnh approved và tạo thumbnail → embed ảnh bằng SigLIP 2 → nhập quan hệ → finalize (dựng index) → xuất text encoder sang ONNX. Báo cáo từng bước nằm trong `data/reports/` (`import_report.json`, `download_report.json`, `corpus_funnel.json`). Muốn thử nhanh trước: thêm `--limit 500`.

**3. Chạy hệ thống**

```bash
docker compose up -d --build
```

Mở http://localhost:8080. Kiểm tra: `curl localhost:8080/health/ready`.

**4. Đo chất lượng và hiệu năng**

```bash
pip install -r backend/requirements-dev.txt
export DATABASE_URL=postgresql://capstone:capstone@localhost:5433/capstone
python eval/make_testcases.py --per-type 40 > eval/testcases.jsonl
python eval/run_eval.py --api http://localhost:8080
python eval/run_load.py --host http://localhost:8080 --users 1 5 10 20 --duration 60
```

Kết quả ở `reports/eval_report.md` và `reports/load_report.md`.

## Quan hệ cho multi-hop

Hệ thống không đoán quan hệ giữa người với người: nó chỉ trả lời những gì có trong hai file:

- `data/relations/entities_extra.csv`: người/tổ chức/địa điểm chưa có trong CSV ảnh (`name, entity_type, gender, aliases, entity_id`; alias cách nhau bằng `|`).
- `data/relations/relations.csv`: `subject, predicate, object, source_url, evidence, verified`. Predicate gồm `parent_of`, `spouse_of`, `founded`, `member_of`, `located_in`. "Con trai" là `parent_of` + người đích có `gender=male`.

Sau khi sửa, chạy lại `docker compose --profile jobs run --rm worker python -m app.jobs.relations_import` rồi `... python -m app.jobs.finalize` và `docker compose restart api`.

Các dòng mẫu hiện có lấy từ Wikipedia và **cần kiểm tra lại trước khi nộp**.

## Cấu hình (tùy chọn, file `.env`)

Sao chép `.env.example` thành `.env`. Các biến hay dùng:

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `WEB_PORT` | 8080 | Cổng web |
| `DB_PORT` | 5433 | Cổng Postgres, chỉ mở trên 127.0.0.1 cho script đánh giá |
| `ENCODER_THREADS` | 4 | Số luồng CPU encode câu hỏi |
| `ANTHROPIC_API_KEY` | trống | Bật LLM fallback cho câu bộ luật không hiểu; để trống thì tắt |
| `LLM_MODEL` | claude-opus-5-5 | Model dùng cho fallback |

## Kiểm tra quy mô 80K khi chưa đủ ảnh thật

```bash
docker compose --profile jobs run --rm worker python -m app.jobs.synth_scale --count 80000
docker compose restart api
# ... đo latency ...
docker compose --profile jobs run --rm worker python -m app.jobs.synth_scale --remove
```

Ảnh tổng hợp được đánh dấu riêng, không lẫn vào test case (trừ khi dùng `--include-synthetic`).

## Phát triển và test

```bash
cd backend
pip install -r requirements-dev.txt
ruff check . ../eval
pytest -q          # test tích hợp cần Postgres có pgvector ở DATABASE_URL, nếu không sẽ tự bỏ qua
```

Frontend: `cd frontend && npm ci && npm run dev` (proxy `/api` sang `localhost:8000`).

## CI/CD và triển khai

`.github/workflows/ci.yml` chạy khi push hoặc mở PR:

1. **backend**: ruff + pytest với Postgres pgvector thật (encoder giả `hash`, không cần tải model).
2. **frontend**: `npm ci` + build TypeScript.
3. **docker**: build image `api` và `web`; với PR thì dựng cả stack và gọi thử `/api/search`; với push lên `main` thì đẩy image lên GitHub Container Registry.
4. **deploy** (tùy chọn): nếu repo có secret `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (và `DEPLOY_PATH`), SSH vào server, kéo image mới và khởi động lại.

Trên server có domain, chạy kèm Caddy để có HTTPS tự động:

```bash
DOMAIN=timanh.example.com IMAGE_PREFIX=ghcr.io/<user>/<repo> \
  docker compose -f compose.yaml -f compose.prod.yaml up -d
```

## Cấu trúc thư mục

```
backend/      FastAPI, job offline, migration SQL, test
frontend/     React + Vite, Nginx
eval/         sinh test case, chấm điểm, Locust
docs/         kiến trúc, test, hiệu năng
data/         dữ liệu (không đưa lên git, trừ data/relations)
models/       SigLIP 2 và text.onnx (tải bằng download_model)
```
