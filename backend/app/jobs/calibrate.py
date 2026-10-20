"""Measure text-to-image similarity on the real corpus to pick MIN_VISUAL_SCORE.

Runs probe descriptions that should match photos of people and probes that should not
(objects and scenes absent from a people-only corpus), and prints the top cosine scores.
A good threshold sits above the best score of the "absent" probes and below most "present" ones.

    python -m app.jobs.calibrate            # writes data/reports/calibration.json
"""
import json

import numpy as np

from ..config import get_settings
from ..db import connect
from ..services import retriever as R
from ..services.encoder import get_encoder

PRESENT = [
    "người đàn ông mặc vest", "phụ nữ mặc áo dài", "ca sĩ đang hát trên sân khấu", "người đang cười",
    "cầu thủ bóng đá", "người đeo kính", "người mặc áo đỏ", "cô dâu chú rể", "người phát biểu trước micro",
    "chân dung đen trắng", "người mặc quân phục", "vận động viên cầm huy chương",
]
ABSENT = [
    "con mèo", "xe ô tô thể thao", "bãi biển hoàng hôn", "hồ bơi", "công viên nước", "núi tuyết",
    "đĩa thức ăn", "máy bay trên bầu trời", "bản đồ thế giới", "tòa nhà chọc trời", "bông hoa hồng", "bàn phím máy tính",
]


def probe(conn, encoder, texts: list[str]) -> list[dict]:
    out = []
    for text, vec in zip(texts, encoder.encode_texts(texts), strict=True):
        hits = R.vector_search(conn, np.asarray(vec, dtype=np.float32), 10)
        rows = conn.execute("SELECT image_id::text, thumb_path FROM images WHERE image_id = ANY(%s::uuid[])",
                            ([h[0] for h in hits[:3]],)).fetchall()
        thumbs = {r["image_id"]: r["thumb_path"] for r in rows}
        out.append({"text": text, "top1": round(hits[0][1], 4) if hits else None,
                    "top10": round(hits[-1][1], 4) if hits else None,
                    "thumbs": [thumbs.get(h[0]) for h in hits[:3]]})
    return out


def main() -> None:
    s = get_settings()
    encoder = get_encoder(s)
    with connect() as conn:
        conn.execute("SET hnsw.ef_search = 100")
        present, absent = probe(conn, encoder, PRESENT), probe(conn, encoder, ABSENT)
    absent_best = max(p["top1"] for p in absent)
    present_top1 = sorted(p["top1"] for p in present)
    report = {"present": present, "absent": absent, "absent_best_top1": absent_best,
              "present_top1_sorted": present_top1,
              "suggested_min_visual_score": round((absent_best + present_top1[len(present_top1) // 4]) / 2, 4)}
    s.reports_dir.mkdir(parents=True, exist_ok=True)
    (s.reports_dir / "calibration.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    for name, rows in (("present", present), ("absent", absent)):
        for p in rows:
            print(f"{name:8} top1={p['top1']:.4f} top10={p['top10']:.4f}  {p['text']}")
    print(json.dumps({k: report[k] for k in ("absent_best_top1", "suggested_min_visual_score")}))


if __name__ == "__main__":
    main()
