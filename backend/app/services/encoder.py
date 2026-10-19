"""Image/text encoders sharing one embedding space.

Backends:
- siglip: SigLIP 2 through transformers + torch (used by the offline worker for images,
  and by the API when no ONNX export exists).
- onnx:   text tower exported to ONNX (`python -m app.jobs.export_onnx`), so the API image
  ships onnxruntime instead of torch.
- hash:   deterministic bag-of-words hashing; only for CI and tests without model weights.
"""
from __future__ import annotations

import hashlib
import threading
from pathlib import Path

import numpy as np

from ..textnorm import tokens

TEXT_MAX_LEN = 64
TEXT_INPUTS = ("input_ids", "attention_mask")  # some tokenizers also emit token_type_ids, which SigLIP rejects


def _l2(x: np.ndarray) -> np.ndarray:
    x = x.astype(np.float32)
    return x / np.maximum(np.linalg.norm(x, axis=-1, keepdims=True), 1e-12)


class HashEncoder:
    name = "hash-v1"

    def __init__(self, dim: int):
        self.dim = dim

    def _vec(self, words: list[str]) -> np.ndarray:
        v = np.zeros(self.dim, dtype=np.float32)
        for w in words:
            h = int.from_bytes(hashlib.blake2b(w.encode(), digest_size=8).digest(), "little")
            v[h % self.dim] += 1.0 if (h >> 63) == 0 else -1.0
        if not v.any():
            v[0] = 1.0
        return v

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        return _l2(np.stack([self._vec(tokens(t)) for t in texts]))

    def encode_images(self, images: list) -> np.ndarray:
        out = []
        for img in images:
            small = np.asarray(img.convert("RGB").resize((8, 8))).astype(np.float32).ravel()
            v = np.resize(small, self.dim) - 127.5
            out.append(v)
        return _l2(np.stack(out))


class SiglipEncoder:
    def __init__(self, model_dir: Path, threads: int):
        import torch
        from transformers import AutoModel, AutoProcessor

        torch.set_num_threads(threads)
        self.torch = torch
        self.model = AutoModel.from_pretrained(model_dir, local_files_only=True).eval()
        self.processor = AutoProcessor.from_pretrained(model_dir, local_files_only=True)
        self.name = f"siglip:{Path(model_dir).name}:{getattr(self.model.config, '_commit_hash', None) or 'local'}"
        self.dim = int(self.model.config.text_config.hidden_size
                       if not hasattr(self.model.config, "projection_dim") else self.model.config.projection_dim)

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        with self.torch.inference_mode():
            batch = self.processor(text=[t.lower() for t in texts], padding="max_length",
                                   truncation=True, max_length=TEXT_MAX_LEN, return_tensors="pt")
            vectors = self.model.get_text_features(**{k: batch[k] for k in TEXT_INPUTS if k in batch})
        return _l2(vectors.float().cpu().numpy())

    def encode_images(self, images: list) -> np.ndarray:
        with self.torch.inference_mode():
            # explicit layout: tiny or 1-pixel-wide images otherwise make the processor guess channels wrong
            batch = self.processor.image_processor([im.convert("RGB") for im in images], return_tensors="pt",
                                                   input_data_format="channels_last")
            vectors = self.model.get_image_features(**batch)
        return _l2(vectors.float().cpu().numpy())


def load_query_tokenizer(model_dir: Path):
    """Fast tokenizer configured exactly like the SigLIP processor (checked at export time)."""
    import json

    from tokenizers import Tokenizer

    meta = json.loads((model_dir / "text_onnx.json").read_text(encoding="utf-8"))
    tok = Tokenizer.from_file(str(model_dir / "query_tokenizer.json"))
    tok.enable_truncation(meta["max_len"])
    tok.enable_padding(length=meta["max_len"], pad_id=meta["pad_id"], pad_token=meta["pad_token"])
    return tok, meta.get("inputs", ["input_ids"])


class OnnxTextEncoder:
    def __init__(self, model_dir: Path, threads: int):
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(model_dir / "text.onnx"), opts,
                                            providers=["CPUExecutionProvider"])
        self.tokenizer, self.inputs = load_query_tokenizer(model_dir)
        self.name = f"siglip-onnx:{Path(model_dir).name}"

    def encode_texts(self, texts: list[str]) -> np.ndarray:
        enc = self.tokenizer.encode_batch([t.lower() for t in texts])
        feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
        (vectors,) = self.session.run(None, {k: feed[k] for k in self.inputs})
        return _l2(vectors)

    def encode_images(self, images: list) -> np.ndarray:  # pragma: no cover - API never encodes images
        raise NotImplementedError("image encoding runs in the worker with the siglip backend")


_lock = threading.Lock()
_instance = None


def get_encoder(settings=None, for_images: bool = False):
    """Load the encoder once per process."""
    global _instance
    from ..config import get_settings

    settings = settings or get_settings()
    with _lock:
        if _instance is None or (for_images and isinstance(_instance, OnnxTextEncoder)):
            backend = settings.encoder_backend
            if backend == "hash":
                _instance = HashEncoder(settings.embedding_dim)
            elif backend == "onnx" and not for_images and (settings.model_dir / "text.onnx").exists():
                _instance = OnnxTextEncoder(settings.model_dir, settings.encoder_threads)
            else:
                try:
                    _instance = SiglipEncoder(settings.model_dir, settings.encoder_threads)
                except ImportError as exc:
                    raise RuntimeError(
                        f"{settings.model_dir / 'text.onnx'} not found and torch is not installed. "
                        "Run the worker pipeline (it exports text.onnx) or set ENCODER_BACKEND=hash."
                    ) from exc
        return _instance
