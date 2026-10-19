# Phương pháp làm test case và đo đạc

## 1. Nguồn đáp án

Đáp án đúng chỉ lấy từ hai nguồn có kiểm soát:

1. **Nhãn approved trong CSV** cho biết ảnh nào thuộc người nào.
2. **Quan hệ đã kiểm chứng** trong `data/relations/relations.csv`, mỗi dòng có nguồn.

Vì đáp án là **entity**, việc chấm một ảnh trả về là tự động: ảnh đó có được gắn nhãn approved cho người cần tìm hay không. Cách này không cần chấm tay hàng nghìn ảnh và chạy lại được bất cứ lúc nào.

Những gì nhãn không nói được (ví dụ "đang biểu diễn", "bãi biển") được đặt trong `eval/manual_cases.jsonl` và in riêng trong báo cáo để chấm bằng mắt.

## 2. Sinh test case (`eval/make_testcases.py`)

| Loại | Biến thể | Đáp án |
|---|---|---|
| Single | tên đầy đủ; tên không dấu; tên gõ sai một ký tự; tên + mô tả cảnh; địa danh + cảnh | ảnh của người/địa điểm đó |
| Multi-intent | "A và B" (hai nhóm); "A hoặc B" (một danh sách); "A chụp cùng B" lấy từ các ảnh thật có hai nhãn | mỗi nhóm đúng người; với "chụp cùng" mỗi ảnh phải có cả hai |
| Multi-hop | 1 bước có danh xưng ("ảnh con trai của X", "con trai x" không dấu); 1 bước ngược ("người sáng lập Y"); 2 bước ("con trai của người sáng lập Y") | người đích theo quan hệ |
| Âm tính | hỏi quan hệ không có trong kho ("con trai của <người không có quan hệ>") | trạng thái `no_verified_relation`, không trả ảnh |

Quy tắc chống "học thuộc đề": tên trùng nhiều người bị loại khỏi ca dương tính; câu hỏi sinh bằng template khác với template trong bộ luật (có danh xưng, không dấu, gõ sai); không có bảng câu hỏi → đáp án nào trong code.

```bash
DATABASE_URL=postgresql://capstone:capstone@localhost:5433/capstone \
  python eval/make_testcases.py --per-type 40 > eval/testcases.jsonl
```

## 3. Chỉ số (`eval/run_eval.py`)

| Chỉ số | Ý nghĩa |
|---|---|
| Status accuracy | Trạng thái trả về đúng như mong đợi (`ok` hoặc `no_verified_relation`...) |
| Type detected | Hệ thống nhận đúng loại câu (single / multi-intent / multi-hop) |
| Precision@k | Tỷ lệ ảnh trong top-k gắn đúng người cần tìm (với "chụp cùng": có đủ cả hai) |
| Intent coverage | Tỷ lệ ý định có ít nhất một ảnh đúng (quan trọng cho multi-intent: không được mất nhánh) |
| p50 / p95 / p99 / max, số ca ≥ 3 s | Latency phía client, gửi request đến khi nhận đủ JSON |
| LLM calls, tokens | Số lần gọi LLM và token thật từ `usage` (0 khi dùng bộ luật) |

## 4. Cách đo latency

- Đo ở client (`time.perf_counter` quanh HTTP request) để gồm cả mạng, parse, encode, SQL, JSON.
- Cache kết quả tắt (`?nocache=true`) để mỗi câu là một lần tìm thật; 5 câu warm-up không tính.
- Báo theo từng loại query, có **max và số ca vượt 3 giây**, vì đề yêu cầu "mỗi truy vấn < 3 giây" chứ không chỉ p95.
- API cũng trả thời gian từng bước (`parse_ms`, `relation_ms`, `encode_ms`, `retrieval_ms`, `hydrate_ms`) để biết chỗ chậm.

## 5. Load test (`eval/run_load.py`, Locust)

- Mỗi bước N người dùng ảo (mặc định 1, 5, 10, 20), mỗi người nghỉ 0,5 đến 1,5 giây giữa hai câu, trộn đều 3 loại query.
- `THINK=0` bỏ thời gian nghỉ để đo throughput bão hòa.
- Request chậm hơn 3 giây bị tính là failure.
- Script tự sinh `reports/load_report.md` và giữ CSV gốc của Locust trong `reports/load/`.

```bash
pip install -r backend/requirements-dev.txt
python eval/run_eval.py --api http://localhost:8080
python eval/run_load.py --host http://localhost:8080 --users 1 5 10 20 --duration 60
THINK=0 python eval/run_load.py --host http://localhost:8080 --users 10 --duration 60 --out reports/saturation
```
