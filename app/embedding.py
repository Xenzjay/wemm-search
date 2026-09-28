from __future__ import annotations

import threading
from pathlib import Path
from typing import Any


class EmbeddingEngine:
    """Lazy WeMM loader so the web console can start before model download."""

    def __init__(self, config: dict[str, Any], root: Path) -> None:
        self.config = config
        self.root = root
        self._model = None
        self._error = ""
        self._lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.config.get("model", {}).get("enabled", False))

    def status(self) -> dict[str, Any]:
        model = self.config.get("model", {})
        return {
            "enabled": self.enabled,
            "loaded": self._model is not None,
            "name": model.get("name", "WeMM-Embedding-2B"),
            "path": model.get("path", ""),
            "dimension": model.get("dimension", 512),
            "device": model.get("device", "cuda"),
            "error": self._error,
        }

    def _load(self) -> None:
        if self._model is not None:
            return
        with self._lock:
            if self._model is not None:
                return
            try:
                import torch
                from sentence_transformers import SentenceTransformer

                model_config = self.config.get("model", {})
                model_path = model_config.get("path") or "tencent/WeMM-Embedding-2B"
                cache_folder = str(self.root / "models")
                dtype = getattr(torch, model_config.get("dtype", "bfloat16"), torch.bfloat16)
                self._model = SentenceTransformer(
                    model_path,
                    trust_remote_code=True,
                    device=model_config.get("device", "cuda"),
                    cache_folder=cache_folder,
                    model_kwargs={"torch_dtype": dtype},
                )
                self._error = ""
            except Exception as exc:
                self._error = f"{type(exc).__name__}: {exc}"
                raise

    def encode_batch(self, values: list[str | dict[str, str]]) -> list[list[float]]:
        if not self.enabled:
            raise RuntimeError("模型适配层未启用，请在 config.json 设置 model.enabled=true")
        self._load()
        dimension = int(self.config.get("model", {}).get("dimension", 512))
        try:
            result = self._model.encode(
                values,
                batch_size=len(values),
                truncate_dim=dimension,
                normalize_embeddings=True,
                convert_to_numpy=True,
            )
        except RuntimeError:
            try:
                torch.cuda.empty_cache()
            except Exception:
                pass
            raise
        return [item.astype("float32").tolist() for item in result]

    def encode(self, value: str | dict[str, str]) -> list[float]:
        return self.encode_batch([value])[0]
