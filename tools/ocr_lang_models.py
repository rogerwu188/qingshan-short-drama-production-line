#!/usr/bin/env python3
"""Language-aware RapidOCR recognition models for the strict burned-line check (owner 2026-11-23).

RapidOCR's bundled recogniser (rapidocr-onnxruntime 1.4.4, PP-OCR Chinese) reads Chinese and Latin text, but misses
kana: on the lab's Japanese H3-style clips it returned NO_BURN for a burned 「言わないでくださいまし！」 and read
「素敵ですわ、セイン様」 as 「素樣」.  The PaddleOCR Japanese / Korean recognisers (ONNX exports published by RapidAI on
ModelScope) read them exactly.  Detection stays RapidOCR's default; only the recogniser is swapped.

Delivery: the models are NOT vendored in git (9.7 MB / 13.5 MB of binary weights per device clone, forever in
history).  They are fetched from a pinned ModelScope tag and verified against a sha256 pin:

* setup time: ``skills/nalu-claude-code/scripts/setup_host.sh`` runs ``ocr_lang_models.py prefetch ja ko``
  (non-fatal);
* first use: :func:`ensure` downloads a missing model once (``NALU_OCR_MODEL_DOWNLOAD=off`` disables it) into
  ``$NALU_OCR_MODEL_DIR`` (default ``~/.cache/nalu/ocr_models``), verifies the sha256 and renames it into place.

A model that is missing / fails its sha256 raises :class:`OcrModelUnavailable`; the strict check then cannot
accept anything (REJECT_UNSTABLE -> our cue is kept): a missing asset never suppresses a caption.

  python3 tools/ocr_lang_models.py prefetch ja ko      # download + verify
  python3 tools/ocr_lang_models.py status              # what is present
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

#: model id recorded next to OCR frames made with RapidOCR's bundled recogniser (zh / en)
DEFAULT_MODEL_ID = "rapidocr_onnxruntime-1.4.4-default"
_MODELSCOPE = "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.10.0/onnx"
#: language -> recognition model (the character dict is embedded in the ONNX metadata ``character``)
MODELS: dict[str, dict[str, Any]] = {
    "ja": {"id": "japan_PP-OCRv4_rec_mobile", "file": "japan_PP-OCRv4_rec_mobile.onnx",
           "url": f"{_MODELSCOPE}/PP-OCRv4/rec/japan_PP-OCRv4_rec_mobile.onnx", "bytes": 9753335,
           "sha256": "e1075a67dba758ecfc7ebc78a10ae61c95ac8fb66a9c86fab5541e33f085cb7a"},
    "ko": {"id": "korean_PP-OCRv5_rec_mobile", "file": "korean_PP-OCRv5_rec_mobile.onnx",
           "url": f"{_MODELSCOPE}/PP-OCRv5/rec/korean_PP-OCRv5_rec_mobile.onnx", "bytes": 13488748,
           "sha256": "cd6e2ea50f6943ca7271eb8c56a877a5a90720b7047fe9c41a2e541a25773c9b"},
}
ENV_DIR = "NALU_OCR_MODEL_DIR"
ENV_DOWNLOAD = "NALU_OCR_MODEL_DOWNLOAD"


class OcrModelUnavailable(RuntimeError):
    pass


def lang_key(lang: Any) -> str:
    return str(lang or "zh").strip().lower()[:2] or "zh"


def model_id(lang: Any) -> str:
    """The recogniser id the strict check needs for ``lang`` (OCR frames made with another one are re-read)."""
    row = MODELS.get(lang_key(lang))
    return row["id"] if row else DEFAULT_MODEL_ID


def model_dir(env: dict[str, str] | None = None) -> Path:
    env = os.environ if env is None else env
    return Path(env.get(ENV_DIR) or Path.home() / ".cache" / "nalu" / "ocr_models")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


_VERIFIED: dict[str, Path] = {}


def ensure(lang: Any, *, download: bool | None = None, timeout: float = 180.0) -> Path | None:
    """Path of the verified recognition model for ``lang``; None for a language the bundled recogniser reads.
    Downloads it once when missing (unless disabled).  Raises :class:`OcrModelUnavailable`."""
    row = MODELS.get(lang_key(lang))
    if not row:
        return None
    if row["id"] in _VERIFIED and _VERIFIED[row["id"]].is_file():
        return _VERIFIED[row["id"]]
    path = model_dir() / row["file"]
    if path.is_file():
        if _sha256(path) == row["sha256"]:
            _VERIFIED[row["id"]] = path
            return path
        raise OcrModelUnavailable(f"{path}: sha256 mismatch (expected {row['sha256'][:12]})")
    if download is None:
        download = str(os.environ.get(ENV_DOWNLOAD, "1")).strip().lower() not in ("0", "off", "false", "no")
    if not download:
        raise OcrModelUnavailable(f"{path} missing and {ENV_DOWNLOAD}=off")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=row["file"] + ".", suffix=".part", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as out, urllib.request.urlopen(row["url"], timeout=timeout) as resp:  # noqa: S310
            while True:
                chunk = resp.read(1 << 20)
                if not chunk:
                    break
                out.write(chunk)
        got = _sha256(Path(tmp))
        if got != row["sha256"]:
            raise OcrModelUnavailable(f"{row['url']}: sha256 {got[:12]} != pinned {row['sha256'][:12]}")
        os.replace(tmp, path)
    except OcrModelUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001
        raise OcrModelUnavailable(f"download {row['url']} failed: {type(exc).__name__}: {str(exc)[:160]}") from exc
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    _VERIFIED[row["id"]] = path
    return path


_ENGINES: dict[str, Any] = {}


def engine(lang: Any) -> tuple[Any, str]:
    """(RapidOCR engine, model id) for ``lang``: the bundled recogniser for zh / en, the pinned language model for
    ja / ko.  Loaded once per process.  Raises :class:`OcrModelUnavailable` / ImportError."""
    mid = model_id(lang)
    if mid not in _ENGINES:
        from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
        path = ensure(lang)
        _ENGINES[mid] = RapidOCR(rec_model_path=str(path)) if path else RapidOCR()
    return _ENGINES[mid], mid


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    cmd = args[0] if args else "status"
    langs = args[1:] or sorted(MODELS)
    rows, ok = [], True
    for lang in langs:
        row = MODELS.get(lang_key(lang))
        if not row:
            rows.append({"lang": lang, "model": DEFAULT_MODEL_ID, "status": "BUNDLED"})
            continue
        path = model_dir() / row["file"]
        if cmd == "prefetch":
            try:
                ensure(lang, download=True)
                rows.append({"lang": lang, "model": row["id"], "status": "OK", "path": str(path)})
            except OcrModelUnavailable as exc:
                ok = False
                rows.append({"lang": lang, "model": row["id"], "status": "UNAVAILABLE", "error": str(exc)})
        else:
            rows.append({"lang": lang, "model": row["id"], "path": str(path),
                         "status": "PRESENT" if path.is_file() else "MISSING"})
    print(json.dumps({"command": cmd, "models": rows}, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
