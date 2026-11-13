"""Explicit E5 CPU smoke; synthetic texts, never official UTC information.

Run with --resolve-revision to inspect the upstream revision, then record it in
e5-model.json. Normal runs are cache-only; --download explicitly enables fetching.
This checks model compatibility, not application retrieval quality or latency.
"""

import argparse
import json
import platform
import time
from pathlib import Path

MODEL = "intfloat/multilingual-e5-small"
ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "data" / "models"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resolve-revision", action="store_true")
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()

    if args.resolve_revision:
        from huggingface_hub import HfApi

        info = HfApi().model_info(MODEL)
        print(json.dumps({"model": MODEL, "revision": info.sha,
                          "files": [item.rfilename for item in info.siblings]}))
        return

    import numpy as np
    import torch
    from huggingface_hub import snapshot_download
    from sentence_transformers import SentenceTransformer

    pin = json.loads(Path(__file__).with_name("e5-model.json").read_text())
    assert pin["model"] == MODEL
    revision = pin["revision"]
    assert len(revision) == 40 and all(c in "0123456789abcdef" for c in revision)
    assert torch.version.cuda is None and not torch.cuda.is_available()
    start = time.perf_counter()
    snapshot = snapshot_download(
        MODEL, revision=revision, cache_dir=CACHE,
        local_files_only=not args.download,
        # Load the native safetensors model, without alternate inference formats.
        allow_patterns=["*.json", "*.safetensors", "*.model", "README.md"],
        ignore_patterns=["onnx/*", "openvino/*"],
    )
    assert Path(snapshot).name == revision
    model = SentenceTransformer(snapshot, device="cpu", local_files_only=True)
    assert model.device.type == "cpu"
    assert next(model.parameters()).device.type == "cpu"
    assert model.get_embedding_dimension() == 384
    texts = [
        "query: KIỂM THỬ GIẢ LẬP: chương trình demo đào tạo lĩnh vực gì?",
        "passage: KIỂM THỬ GIẢ LẬP: chương trình demo đào tạo kỹ thuật.",
    ]
    vectors = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    assert vectors.shape == (2, 384)
    assert vectors.dtype == np.float32
    assert np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors, axis=1), 1.0, atol=1e-5)
    blob = vectors[0].astype("<f4").tobytes()
    assert len(blob) == 1536
    assert np.array_equal(np.frombuffer(blob, dtype="<f4"), vectors[0])
    again = model.encode(texts, normalize_embeddings=True, convert_to_numpy=True)
    assert np.allclose(vectors, again, atol=1e-6)
    print(json.dumps({
        "status": "PASS", "model": MODEL, "revision": revision,
        "device": str(model.device), "torch": torch.__version__,
        "python": platform.python_version(), "download_enabled": args.download,
        "shape": list(vectors.shape), "dtype": str(vectors.dtype),
        "norms": np.linalg.norm(vectors, axis=1).tolist(),
        "blob_bytes": len(blob), "repeat_encode_equal": True,
        "elapsed_seconds_including_load": round(time.perf_counter() - start, 3),
    }, indent=2))


if __name__ == "__main__":
    main()
