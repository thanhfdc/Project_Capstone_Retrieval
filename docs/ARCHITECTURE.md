# Kiến trúc hệ thống truy xuất ảnh (Phần B)

## 1. Tổng quan

```mermaid
flowchart LR
    U[Trình duyệt] -->|HTTPS| W[web: Nginx + React build]
    W -->|/api| A[api: FastAPI + ONNX Runtime]
    W -->|/media/thumbs| M[(Thumbnail WebP<br/>data/media)]
    A --> P[(PostgreSQL 16<br/>pgvector + pg_trgm + FTS)]
    A -.->|chỉ khi luật không hiểu câu| L[LLM fallback<br/>tùy chọn]
    K[worker: torch CPU<br/>chạy offline] --> P
    K --> M
    K -->|text.onnx| O[(models/siglip2)]
    O --> A
```

| Thành phần | Lựa chọn | Lý do |
|---|---|---|
| Embedding | SigLIP 2 base (`google/siglip2-base-patch16-224`), ảnh và câu hỏi chung một không gian, đa ngôn ngữ | Một model cho cả ảnh và văn bản; pretrained, không cần fine-tune |
| Vector index | pgvector HNSW (cosine) trong PostgreSQL | 80K × 768 float chỉ ~235 MB; một DB cho metadata, quan hệ, FTS và vector nên compose chỉ 3 service, không phải đồng bộ hai nơi |
| Lexical | PostgreSQL full-text (`simple`) trên tên/alias/mô tả đã bỏ dấu | Bắt tên riêng, địa danh mà model ảnh không chắc nhận ra |
| Quan hệ (multi-hop) | Bảng `relations` + SQL, tối đa 2 bước | Sự thật phải có nguồn kiểm chứng; không để model đoán "con trai của ai" |
| Hiểu câu hỏi | Bộ luật tiếng Việt + từ điển alias trong RAM | Không tốn token, < 20 ms; LLM chỉ là fallback, tối đa 1 lần gọi |
| API image | onnxruntime + tokenizers, không có torch | Image nhỏ (~520 MB so với ~2 GB nếu có torch), khởi động nhanh |

## 2. Luồng xử lý dữ liệu (offline, `worker`)

```mermaid
flowchart TD
    C[CSV trong data/raw<br/>24 cột flag hoặc 8 cột status] --> I[import_csv<br/>map cột theo tên qua import_profiles.json]
    I --> E[(entities, entity_aliases, links)]
    E --> D[download<br/>ảnh approved: đọc local_path hoặc tải image_url<br/>32 luồng, 8 luồng mỗi host, resume được]
    D --> T[SHA-256 nội dung để dedup<br/>thumbnail WebP 480px]
    T --> IM[(images, fetches)]
    IM --> EM[embed<br/>SigLIP 2 image tower, batch 32]
    R[data/relations/*.csv<br/>quan hệ có nguồn] --> RI[relations_import]
    EM --> F[finalize<br/>gộp nhãn, search_text, is_serving, HNSW]
    RI --> F
    F --> X[export_onnx<br/>text tower sang ONNX, kiểm tra khớp torch]
```

- Nhãn theo từng cặp (ảnh, người): approved chỉ khi mọi quan sát đồng ý; vừa approved vừa rejected thành `unknown` và không được phục vụ (không "file sau ghi đè file trước").
- Ảnh trùng nội dung (cùng SHA-256) chỉ lưu và embed một lần, giữ nhiều liên kết người.
- Chạy lại bất kỳ bước nào cũng an toàn: import theo khóa (file, dòng), download bỏ qua locator đã xong, embed chỉ xử lý ảnh chưa có vector.
- `finalize` in ra phễu dữ liệu: dòng CSV → dòng approved → locator → tải được → ảnh phân biệt → có vector → đang phục vụ.

## 3. Luồng truy vấn (online, `api`)

```mermaid
flowchart TD
    Q[Câu hỏi] --> N[Chuẩn hóa: lowercase, bỏ dấu song song bản có dấu]
    N --> S[Tìm tên riêng: alias dài nhất trước<br/>alias yếu = các từ đầu của tên<br/>gõ sai: pg_trgm]
    S --> P[Bộ luật: tách ý định theo 'và/hoặc/,'<br/>'chụp cùng' = cùng một ảnh<br/>cụm quan hệ trước tên = multi-hop<br/>'ở/tại X' = địa điểm chung]
    P -->|tên trùng nhiều người| CL[Trả lựa chọn để người dùng chọn]
    P -->|có quan hệ| G[SQL relations: tối đa 2 bước<br/>lọc giới tính cho con trai/con gái]
    P --> V[Encode phần mô tả còn lại<br/>một batch cho mọi ý định]
    G --> RT
    V --> RT[Mỗi ý định: vector + full-text<br/>lọc theo người hoặc địa điểm nếu có]
    RT --> F[RRF k=60]
    F --> H[Gộp nhóm, hydrate một câu SQL]
    H --> J[JSON: groups, items, giải thích đường quan hệ, thời gian từng bước]
```

| Loại truy vấn | Cách xử lý | Ví dụ |
|---|---|---|
| Single intent, chỉ tên | Ảnh của người đó bằng SQL | "ảnh Mỹ Tâm" |
| Single intent, tên + mô tả | Vector và full-text giới hạn trong ảnh của người đó, RRF | "Sơn Tùng đang biểu diễn" |
| Single intent, chỉ mô tả | HNSW toàn kho + full-text, RRF | "bãi biển hoàng hôn" |
| Single intent, địa danh | Ảnh gắn với địa điểm và các địa điểm con (`located_in`), xếp theo mô tả | "bãi biển Nha Trang" |
| Multi-intent "A và B" | Mỗi ý định một nhóm, chia đều top-k | "hồ bơi và công viên nước ở Phú Quốc" |
| Multi-intent "A hoặc B" | Hợp nhất bằng RRF thành một danh sách | "Sơn Tùng hoặc Mỹ Tâm" |
| Multi-intent "A chụp cùng B" | Giao: ảnh gắn với cả hai người | "Sơn Tùng chụp cùng Hà Anh Tuấn" |
| Multi-hop 1 bước | Tra quan hệ ra người đích, rồi tìm ảnh người đó | "ảnh con trai chủ tịch Phạm Nhật Vượng" |
| Multi-hop 2 bước | Tra lần lượt, mỗi người đích một nhóm, có giải thích đường đi | "con trai của người sáng lập Vingroup" |

Các trạng thái trả về được tách riêng để không nhầm "không có" với "lỗi": `ok`, `partial`, `no_results`, `needs_clarification`, `no_verified_relation`, `no_images_for_target`, `no_seed_entity`.

## 4. Schema

```mermaid
erDiagram
    entities ||--o{ entity_aliases : "có tên gọi"
    entities ||--o{ links : "được quan sát trong CSV"
    links }o--|| fetches : "locator đã tải"
    fetches }o--|| images : "nội dung (SHA-256)"
    images ||--o{ image_entities : "nhãn hiệu lực"
    entities ||--o{ image_entities : ""
    entities ||--o{ relations : "chủ thể"
    entities ||--o{ relations : "đối tượng"

    entities { uuid entity_id PK text canonical_name text name_fold text entity_type text gender text category_raw }
    entity_aliases { uuid entity_id FK text alias text alias_fold }
    links { text source_file PK int row_no PK uuid entity_id FK text image_url text local_path text approval_status text reject_reason }
    fetches { text locator PK text status uuid image_id text error }
    images { uuid image_id PK text content_sha256 UK text thumb_path vector embedding tsvector search_tsv bool is_serving }
    image_entities { uuid image_id PK uuid entity_id PK text approval_status }
    relations { bigint relation_id PK uuid subject_id FK text predicate uuid object_id FK text source_url bool verified }
```

## 5. Hạn chế đã biết

- Chất lượng phụ thuộc nhãn trong CSV: dữ liệu đầu vào chưa sạch thì kết quả theo tên người cũng chưa sạch. Hệ thống không tự sửa danh tính.
- Multi-hop chỉ trả lời được quan hệ đã nhập vào `data/relations/relations.csv`; quan hệ chưa có trả `no_verified_relation` thay vì đoán.
- Truy vấn địa điểm chỉ lọc chính xác khi địa điểm là một entity trong kho; nếu không, hệ thống dựa vào mô tả và vector (xếp hạng tương đồng, không phải bộ lọc chắc chắn).
- SigLIP không hiểu phủ định ("không có người") và không nhận diện được mặt người theo tên; tên luôn đi qua metadata.
- "A chụp cùng B" dựa vào việc cùng một ảnh được gắn nhãn cho cả hai người; ảnh có hai người nhưng chỉ gắn một nhãn sẽ không được tính.
