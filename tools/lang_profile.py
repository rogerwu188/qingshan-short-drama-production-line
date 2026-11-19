"""Re-export of ``lines/nalu/runtime/tools/lang_profile.py`` for engine ``tools`` modules.

``tools.*`` modules import ``from tools.lang_profile import ...`` (or flat ``lang_profile`` when only
``tools/`` is on sys.path); the profile itself has one home next to the runtime pipeline.
"""
from __future__ import annotations

import importlib.util as _importlib_util
import sys as _sys
from pathlib import Path as _Path

_IMPL = "nalu_lang_profile_impl"
_module = _sys.modules.get(_IMPL)
if _module is None:
    _path = _Path(__file__).resolve().parents[1] / "lines" / "nalu" / "runtime" / "tools" / "lang_profile.py"
    _spec = _importlib_util.spec_from_file_location(_IMPL, _path)
    _module = _importlib_util.module_from_spec(_spec)
    _sys.modules[_IMPL] = _module
    _spec.loader.exec_module(_module)  # type: ignore[union-attr]

__all__ = list(_module.__all__)
globals().update({name: getattr(_module, name) for name in __all__})
