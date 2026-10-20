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
| Single | mỗi **người** một câu (các entity trùng của một người, như "Mỹ Tâm" và "Mỹ Tâm (queen Vpop)", gộp làm một), xoay vòng 6 kiểu gõ: tên đầy đủ; không dấu; gõ sai một ký tự; tên + mô tả cảnh; có danh xưng ("ca sĩ", "MC"); chữ hoa, thừa dấu cách và dấu câu; thêm địa danh + cảnh | ảnh của người/địa điểm đó (mọi entity của người đó) |
| Multi-intent | "A và B" (hai nhóm); "A hoặc B" (một danh sách); "A, B" (dấu phẩy); "A chụp cùng B" lấy từ các ảnh thật có hai **người khác nhau** | mỗi nhóm đúng người; với "chụp cùng" mỗi ảnh phải có cả hai |
| Multi-hop | mọi quan hệ trong `relations.csv`, hỏi từ mỗi phía hỏi được (con trai/con gái/bố/mẹ, vợ/chồng, anh trai/em gái, người sáng lập, thành viên nhóm; anh chị em gồm cả con chung một bố/mẹ), và cả cách hỏi **không nói giới tính** ("con của", "con ruột của", "bố mẹ của", "vợ chồng của", "em của", "anh chị em ruột của"), tách riêng thành biến thể `<quan hệ>_no_gender`; 2 bước ghép từ hai quan hệ nối nhau (tối đa 40 câu); mỗi câu một kiểu gõ ngẫu nhiên: đầy đủ, không dấu, bỏ "của", có "ảnh" ở đầu | mọi người đích có ảnh, tính độc lập với API bằng cách đi trên bảng quan hệ |
| Âm tính | hỏi quan hệ không có trong kho ("con trai của <người không có quan hệ>"); hỏi sai giới tính ("con gái của" người chỉ có con trai) | trạng thái `no_verified_relation`, không trả ảnh |
| Robustness (câu dễ sai) | quan hệ hệ thống không có ("bạn thân của", "cháu của", "học trò của"...); người không có trong data (30 tên, ví dụ "Taylor Swift", "Tòng Thị Phóng", "Tập Cận Bình", "Vladimir Putin"; hỏi xoay vòng "ảnh X", "X", "X đang phát biểu"); tên đảo thứ tự ("Tuấn Anh Hà"); tên gần giống (`partial_name`: hai chữ đầu tên một người thật ghép với tên gọi khác, như "Nguyễn Chí Thanh", bỏ những tên chỉ lệch 1–2 chữ cái với tên có thật vì có thể là gõ sai); chuỗi vô nghĩa; chỉ có chữ "ảnh" | trạng thái `no_verified_relation`, `no_seed_entity` (không nhận ra tên) hoặc `no_results`, và **không được** trả ảnh của người trong câu hay người có tên na ná |

Quy tắc chống "học thuộc đề": tên trùng nhiều người bị loại khỏi ca dương tính; câu hỏi sinh bằng template khác với template trong bộ luật (có danh xưng, không dấu, gõ sai); không có bảng câu hỏi → đáp án nào trong code.

Unit test (`backend/tests`, 58 test: 37 hàm unit test và 17 hàm integration test, vài hàm chạy với nhiều tham số) kiểm từng quy tắc của code trên dữ liệu mẫu nhỏ (31 ảnh), chạy trong vài giây ở CI; mỗi test thường gói nhiều câu hỏi (ví dụ một test kiểm 9 câu tên không có trong data). Đây là lưới an toàn khi sửa code, không phải thước đo chất lượng. Eval ở đây đo chất lượng trên toàn bộ data thật; `--per-type` quyết định quy mô: 40 để thử nhanh, 1500 cho báo cáo (khoảng 3.000 câu, vài phút).

```bash
DATABASE_URL=postgresql://capstone:capstone@localhost:5433/capstone \
  python eval/make_testcases.py --per-type 1500 > eval/testcases.jsonl
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

Lưu ý khi đọc số multi-hop: phần "suy luận" là tra bảng quan hệ đã kiểm chứng bằng SQL, không phải model đoán. Khi câu được hiểu đúng và quan hệ có trong bảng, ảnh trả về chính là ảnh của người đích nên precision gần như chắc chắn cao. Chỗ multi-hop có thể sai là **hiểu câu** (nhận sai cụm quan hệ hoặc tên) và **độ phủ** (quan hệ chưa có trong bảng thì trả `no_verified_relation`). Báo cáo có bảng "By variant" để tách 1 bước, 2 bước và câu âm tính.

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
