"""Safe final boundary for tool-returned structured data.

Binary image payloads are replaced with provenance metadata before a result is
printed or persisted.  The function is deliberately dependency-free so every
tool can use it without importing a provider client.
"""
from __future__ import annotations
import base64, hashlib, re
from pathlib import Path
from typing import Any

_BINARY_KEYS = {"image_url", "input_image", "base64", "image_base64"}
_DATA_IMAGE = re.compile(r"^data:image/", re.I)

def _meta(value: Any, *, path: str | None = None) -> dict[str, Any]:
    raw = None
    if isinstance(value, str) and _DATA_IMAGE.match(value):
        try: raw = base64.b64decode(value.split(',', 1)[1], validate=True)
        except Exception: raw = None
    elif isinstance(value, str) and path and Path(path).is_file():
        raw = Path(path).read_bytes()
    return {"path": str(Path(path).resolve()) if path else None,
            "sha256": hashlib.sha256(raw).hexdigest() if raw is not None else None,
            "note": "binary image payload removed at tool output boundary"}

def sanitize_tool_output(value: Any, *, _field: str | None = None) -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            if key in _BINARY_KEYS or (isinstance(item, str) and _DATA_IMAGE.match(item)):
                path = item if key in {"path", "image_path"} else value.get("path") or value.get("image_path")
                out["image"] = _meta(item, path=path)
            else: out[key] = sanitize_tool_output(item, _field=key)
        return out
    if isinstance(value, list): return [sanitize_tool_output(item, _field=_field) for item in value]
    if isinstance(value, str) and (_field in _BINARY_KEYS or _DATA_IMAGE.match(value)):
        return _meta(value)
    return value

def serialize_tool_output(value: Any) -> str:
    import json
    return json.dumps(sanitize_tool_output(value), ensure_ascii=False, separators=(",", ":"))
