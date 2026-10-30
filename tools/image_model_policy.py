#!/usr/bin/env python3
"""Single source of truth for the paid image model (Roger 2026-10-30).

Roger: 「所有图片生成都改为giggle api的gptimage2 接口，这样图片成本可以大幅度降低。」

Every image call site used to carry its own literal ``"gpt-image-2-pro"``.  A model
switch then meant editing ~20 files and hoping none was missed, and the budget ledger
priced images with a constant that no longer matched the SKU.  This module reads the
active profile from ``configs/IMAGE_MODEL_CAPABILITY_REGISTRY_v1.json`` so a switch is
one registry edit plus the order that authorised it.

Giggle GPT Image 2 SKUs observed 2026-10-30 (probe by invalid params: 400 = model exists,
500 "failed to get model price: record not found" = unknown):
  gpt-image-2-pro   exists  (11 credits / 2K image, 394 statement rows)
  gpt-image-2-fast  exists  (price taken from the first statement rows, see registry)
  gpt-image-2       does NOT exist on Giggle.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "configs/IMAGE_MODEL_CAPABILITY_REGISTRY_v1.json"

# Model ids this engine has ever submitted for paid image generation.  Transaction
# recovery (fingerprint match) must keep recognising rows written under a retired
# SKU, otherwise a re-run would re-POST and re-charge an already bound unit.
LEGACY_IMAGE_MODELS: tuple[str, ...] = ("gpt-image-2-pro",)
PROVIDER = "giggle"


@lru_cache(maxsize=1)
def _registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def active_profile() -> dict[str, Any]:
    registry = _registry()
    policy = registry.get("active_execution_policy") or {}
    allowed = [str(value) for value in policy.get("allowed_paid_profile_ids") or []]
    if len(allowed) != 1:
        raise RuntimeError("IMAGE_MODEL_POLICY_REQUIRES_EXACTLY_ONE_ACTIVE_PROFILE:" + ",".join(allowed))
    for profile in registry.get("profiles") or []:
        if str(profile.get("profile_id")) == allowed[0]:
            if profile.get("adapter_status") != "DEPLOYED":
                raise RuntimeError("IMAGE_MODEL_ACTIVE_PROFILE_NOT_DEPLOYED:" + allowed[0])
            if not profile.get("provider_model_id"):
                raise RuntimeError("IMAGE_MODEL_ACTIVE_PROFILE_HAS_NO_PROVIDER_MODEL_ID:" + allowed[0])
            return profile
    raise RuntimeError("IMAGE_MODEL_ACTIVE_PROFILE_NOT_IN_REGISTRY:" + allowed[0])


def active_image_model() -> str:
    """Provider model id every new paid image task must carry."""
    return str(active_profile()["provider_model_id"])


def active_image_resolution() -> str:
    return str(active_profile().get("default_resolution") or "2K")


def image_model_pricing(model: str | None = None) -> dict[str, Any]:
    """Planning price for ``model`` (default: active).  ``hard_upper`` is the figure the
    ledger reserves per bound task; ``credits`` is the typical observed charge or None
    when no statement row has been seen yet.  Actual charges always come from the
    statement ledger."""
    wanted = str(model or active_image_model())
    for profile in _registry().get("profiles") or []:
        if str(profile.get("provider_model_id") or "") == wanted:
            pricing = dict(profile.get("pricing") or {})
            if "hard_upper" not in pricing:
                raise RuntimeError("IMAGE_MODEL_PRICING_MISSING_HARD_UPPER:" + wanted)
            return pricing
    raise RuntimeError("IMAGE_MODEL_PRICING_UNKNOWN_MODEL:" + wanted)


def image_hard_upper_credits(model: str | None = None) -> int:
    return int(image_model_pricing(model)["hard_upper"])


def known_image_models() -> frozenset[str]:
    """Active model plus every retired SKU — for recognising historical transactions,
    statements and manifests; NOT a list of models allowed for new paid submits."""
    return frozenset({active_image_model(), *LEGACY_IMAGE_MODELS})


def allowed_image_models() -> frozenset[str]:
    """Models a NEW paid image submission may carry: the active profile only."""
    return frozenset({active_image_model()})


ACTIVE_IMAGE_MODEL = active_image_model()
ACTIVE_IMAGE_RESOLUTION = active_image_resolution()


if __name__ == "__main__":
    print(json.dumps({
        "active_image_model": ACTIVE_IMAGE_MODEL,
        "active_resolution": ACTIVE_IMAGE_RESOLUTION,
        "pricing": image_model_pricing(),
        "known_models": sorted(known_image_models()),
    }, ensure_ascii=False, indent=2))
