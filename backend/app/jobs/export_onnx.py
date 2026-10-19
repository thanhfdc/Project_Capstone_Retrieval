"""Export the SigLIP 2 text tower to models/siglip2/text.onnx and check it matches torch.

The API image then encodes queries with onnxruntime and does not need torch at all.
"""
import argparse
import json

import numpy as np

from ..config import get_settings
from ..services.encoder import TEXT_MAX_LEN, SiglipEncoder

PROBES = ["bãi biển Nha Trang", "ca sĩ đang biểu diễn trên sân khấu", "hồ bơi", "a dog"]


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    settings = get_settings()
    target = settings.model_dir / "text.onnx"
    if target.exists() and not args.force:
        print(f"{target} exists, skipping (use --force to rebuild)")
        return 0
    import torch

    enc = SiglipEncoder(settings.model_dir, settings.encoder_threads)

    class TextTower(torch.nn.Module):
        def __init__(self, model):
            super().__init__()
            self.model = model

        def forward(self, input_ids, attention_mask=None):
            return self.model.get_text_features(input_ids=input_ids, attention_mask=attention_mask)

    batch = enc.processor(text=[p.lower() for p in PROBES], padding="max_length", truncation=True,
                          max_length=TEXT_MAX_LEN, return_tensors="pt")
    # Export exactly the inputs the processor produces (SigLIP 2 may or may not use a mask).
    inputs = [k for k in ("input_ids", "attention_mask") if k in batch]
    torch.onnx.export(TextTower(enc.model).eval(), tuple(batch[k] for k in inputs), str(target),
                      input_names=inputs, output_names=["text_embeds"],
                      dynamic_axes={**{k: {0: "batch"} for k in inputs}, "text_embeds": {0: "batch"}},
                      opset_version=17, dynamo=False)

    # The API tokenizes with the `tokenizers` package only; prove it gives the same ids.
    tok = enc.processor.tokenizer
    tok.backend_tokenizer.save(str(settings.model_dir / "query_tokenizer.json"))
    meta = {"max_len": TEXT_MAX_LEN, "pad_id": tok.pad_token_id, "pad_token": tok.pad_token, "inputs": inputs}
    (settings.model_dir / "text_onnx.json").write_text(json.dumps(meta), encoding="utf-8")
    from ..services.encoder import OnnxTextEncoder, load_query_tokenizer
    fast, _ = load_query_tokenizer(settings.model_dir)
    for probe, ref_ids in zip(PROBES, batch["input_ids"].tolist()):
        if fast.encode(probe.lower()).ids != ref_ids:
            target.unlink()
            raise SystemExit(f"tokenizer mismatch on {probe!r}; export removed")

    reference = enc.encode_texts(PROBES)
    exported = OnnxTextEncoder(settings.model_dir, settings.encoder_threads).encode_texts(PROBES)
    cosine = (reference * exported).sum(axis=1)
    report = {"onnx": str(target), "min_cosine_vs_torch": float(cosine.min())}
    print(json.dumps(report, indent=2))
    if not np.all(cosine > 0.999):
        target.unlink()
        raise SystemExit("ONNX output differs from torch, export removed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
