# Quality and latency report

Generated 2026-10-19 14:06 UTC against `http://api:8000`. Serving images: **90327**, online encoder `siglip-onnx:siglip2`.

Latency = client-side time from sending the request to receiving the full JSON, result cache off, one request at a time, top_k=10.

| Type | Cases | Status acc. | Type detected | Precision@k | Intent coverage | p50 ms | p95 ms | p99 ms | max ms | ≥3 s | Errors | LLM calls | Tokens |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| multi_hop | 14 | 100% | 100% | 100% | 100% | 3.5 | 4.9 | 5.3 | 5.4 | 0 | 0 | 0 | 0 |
| multi_intent | 30 | 97% | 97% | 97% | 97% | 3.0 | 4.9 | 137.5 | 191.6 | 0 | 0 | 0 | 0 |
| single | 43 | 95% | 100% | 88% | 88% | 4.1 | 54.7 | 93.8 | 101.8 | 0 | 0 | 0 | 0 |

## Failed or suspicious cases

- `si_0007` [single/typo] “Phạm Ngọc Phưng Anh á hậu 1 HHVN 2020” → needs_clarification, precision 0.0; top: 
- `si_0023` [single/typo] “Trn Ngọc Lan Khuê” → ok, precision 0.0; top: trn ngọc lan khuê: Lan Khuê | Lan Khuê | Lan Khuê
- `si_0031` [single/typo] “Tuấn Pương (ca sĩ)” → ok, precision 0.0; top: tuấn pương ca sĩ: Ca sĩ Tuấn Hưng | Ca sĩ Phan Mạnh Quỳnh | Ca sĩ Tuấn Hưng
- `si_0035` [single/typo] “Mai Ngc” → ok, precision 0.0; top: mai ngc: Mai Ngô | Mai Ngô | Mai Ngô
- `si_0039` [single/typo] “Nghệ sĩ piano Vn-Anh Nguyễn” → needs_clarification, precision 0.0; top: 
- `mu_0062` [multi_intent/same_photo] “Dế Choắt (Trần Tấn Phát) chụp cùng Dế Choắt” → needs_clarification, precision 0.0; top: 

## Manual cases (judge by eye)

- “bãi biển Nha Trang” → ok (101.8 ms): bãi biển nha trang: Phạm Đình Khánh Đoan | Nhạc sĩ Phong Nhã | Lý Quí Khánh, Lý Quí Khánh (thời trang)
- “hồ bơi và công viên nước ở Phú Quốc” → ok (191.6 ms): hồ bơi: Hồng Phượng (MC) | Nguyễn Quốc Hùng | Nguyễn Quốc Hùng / công viên nước: Lâm Vlog | Nguyễn Văn Hưởng | Hồng Phượng (MC)
- “ảnh con trai chủ tịch Phạm Nhật Vượng” → ok (4.4 ms): con trai của Chủ tịch Hội đồng Dân tộc Quốc hội, Phạm Nhật Vượng: Phạm Nhật Quân Anh: Phạm Nhật Quân Anh | Phạm Nhật Quân Anh | Phạm Nhật Quân Anh / con trai của Chủ tịch Hội đồng Dân tộc Quốc hội, Phạm Nhật Vượng: Phạm Nhật Minh Hoàng: Phạm Nhật Minh Hoàng | Phạm Nhật Minh Hoàng | Phạm Nhật Minh Ho
- “ca sĩ đang hát trên sân khấu” → ok (48.1 ms): ca sĩ đang hát trên sân khấu: Ca sĩ Trọng Tấn | Ca sĩ Anh Thơ | Ca sĩ chèo (nghệ sĩ chèo)
- “người mặc áo dài” → ok (82.8 ms): người mặc áo dài: Hà Quỳnh Như | Nguyễn Thị Định (cổ) | Lý Hùng — loại
- “con trai của người sáng lập Vingroup” → ok (5.4 ms): con trai của người sáng lập Vingroup: Phạm Nhật Quân Anh: Phạm Nhật Quân Anh | Phạm Nhật Quân Anh | Phạm Nhật Quân Anh / con trai của người sáng lập Vingroup: Phạm Nhật Minh Hoàng: Phạm Nhật Minh Hoàng | Phạm Nhật Minh Hoàng | Phạm Nhật Minh Hoàng
