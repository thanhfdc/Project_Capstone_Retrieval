# Image Retrieval: tìm ảnh bằng câu hỏi tiếng Việt (Capstone, Phần B)

Tìm ảnh trong kho khoảng 80K ảnh bằng ngôn ngữ tự nhiên, hỗ trợ 3 loại câu hỏi:

| Loại | Ví dụ |
|---|---|
| Single intent | "ảnh Sơn Tùng đang biểu diễn", "bãi biển Nha Trang" |
| Multi-intent | "hồ bơi và công viên nước ở Phú Quốc", "Sơn Tùng chụp cùng Hà Anh Tuấn" |
| Multi-hop | "ảnh con trai chủ tịch Phạm Nhật Vượng", "con trai của người sáng lập Vingroup" |

**Demo:** https://congthanh.tailc0ad82.ts.net (chạy trên máy demo qua Tailscale Funnel, mở được khi máy đang bật).

Stack: FastAPI, PostgreSQL 16 + pgvector (HNSW) + full-text, SigLIP 2 (text tower chạy ONNX), React + Nginx, Docker Compose, GitHub Actions.

Tài liệu: [hướng dẫn triển khai, mục 0 là trạng thái thực tế](Huong_dan_trien_khai_Phan_B_Image_Retrieval.md) · [kiến trúc và sơ đồ](docs/ARCHITECTURE.md) · [cách làm test case](docs/TESTING.md) · [hiệu năng](docs/PERFORMANCE.md)

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
python eval/make_testcases.py --per-type 1500 > eval/testcases.jsonl
python eval/run_eval.py --api http://localhost:8080
python eval/run_load.py --host http://localhost:8080 --users 1 5 10 20 --duration 60
python eval/run_scale.py --workers 1 2 4 --users 32 --duration 60   # throughput theo số process API
```

Kết quả ở `reports/eval_report.md`, `reports/load_report.md` và `reports/scale_report.md`. Số process API đặt bằng `API_WORKERS` trong `.env` (mặc định 1); xem `docs/PERFORMANCE.md` mục 3b.

## Quan hệ cho multi-hop

Hệ thống không đoán quan hệ giữa người với người: nó chỉ trả lời những gì có trong hai file:

- `data/relations/entities_extra.csv`: người/tổ chức/địa điểm chưa có trong CSV ảnh (`name, entity_type, gender, aliases, entity_id`; alias cách nhau bằng `|`).
- `data/relations/relations.csv`: `subject, predicate, object, source_url, evidence, verified`. Predicate gồm `parent_of`, `spouse_of`, `sibling_of`, `founded`, `member_of`, `located_in`. "Con trai" là `parent_of` + người đích có `gender=male`; anh chị em còn được suy ra khi hai người có chung bố hoặc mẹ.

Sau khi sửa, chạy lại `docker compose --profile jobs run --rm worker python -m app.jobs.relations_import` rồi `docker compose restart api`. Sau khi sửa code backend, build lại cả `worker` (`docker compose --profile jobs build worker`) lẫn `api`, nếu không job sẽ chạy code cũ.

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
3. **docker**: build image `api` và `web`; với PR (hoặc bấm Run workflow trong tab Actions) thì dựng cả stack, gọi thử `/api/search` rồi chạy load test Locust 5 và 20 người dùng, báo cáo hiện ở tab Summary và tải được ở artifact `load-report`; với push lên `main` thì đẩy image lên GitHub Container Registry.
4. **deploy** (tùy chọn): nếu repo có secret `DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY` (và `DEPLOY_PATH`), SSH vào server, kéo image mới và khởi động lại.

Trên server có domain, chạy kèm Caddy để có HTTPS tự động:

```bash
DOMAIN=timanh.example.com IMAGE_PREFIX=ghcr.io/<user>/<repo> \
  docker compose -f compose.yaml -f compose.prod.yaml up -d
```

### Mở web demo ra internet không cần server (Tailscale Funnel)

Máy demo đang chạy stack (`docker compose up -d`) có thể cho người khác truy cập bằng một link HTTPS cố định, miễn phí, không cần mở port hay mua domain:

```powershell
winget install --id Tailscale.Tailscale   # rồi đăng nhập
& "C:\Program Files\Tailscale\tailscale.exe" funnel --bg 8080
# lần đầu mở link nó in ra để bật HTTPS và Funnel, rồi chạy lại lệnh trên
# tắt: tailscale funnel --https=443 off
```

Lệnh in ra link `https://<tên-máy>.<tailnet>.ts.net`, giữ nguyên qua các lần khởi động lại. Link chỉ mở được khi máy demo bật và Docker đang chạy; muốn chạy 24/7 thì dùng server và `compose.prod.yaml` ở trên.

## Cấu trúc thư mục

```
backend/      FastAPI, job offline, migration SQL, test
frontend/     React + Vite, Nginx
eval/         sinh test case, chấm điểm, Locust
docs/         kiến trúc, test, hiệu năng
data/         dữ liệu (không đưa lên git, trừ data/relations)
models/       SigLIP 2 và text.onnx (tải bằng download_model)
```
