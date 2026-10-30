"""tools/image_model_policy.py — one registry-backed source of truth for the paid image SKU
(Roger 2026-10-30, SUPERVISOR_ORDERS seq=54: 所有图片生成都改为 giggle 的 gptimage2 便宜档)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from tools import image_model_policy as policy

ROOT = Path(__file__).resolve().parents[2]


class ImageModelPolicyTest(unittest.TestCase):
    def test_active_model_is_the_cheaper_gpt_image_2_sku(self) -> None:
        self.assertEqual(policy.active_image_model(), "gpt-image-2-fast")
        self.assertEqual(policy.ACTIVE_IMAGE_MODEL, "gpt-image-2-fast")
        # Roger 2026-10-30 seq=56: 「生产线引擎默认只使用gptimage 1k 版本，这样成本最低」
        self.assertEqual(policy.active_image_resolution(), "1K")
        self.assertEqual(policy.ACTIVE_IMAGE_RESOLUTION, "1K")

    def test_retired_2k_resolution_stays_recognised_for_bound_transactions(self) -> None:
        self.assertEqual(policy.known_image_resolutions(), ("1K", "2K"))
        self.assertIn("1K", policy.active_profile()["provider_limits"]["resolution_values"])

    def test_nalu_call_sites_do_not_pin_an_image_resolution_literal(self) -> None:
        pinned = []
        for rel in ("lines/nalu/runtime/tools/nalu_pipeline.py", "lines/nalu/runtime/tools/build_keyframe_manifest.py",
                    "lines/nalu/runtime/tools/bootstrap_identity_cards.py", "lines/nalu/runtime/tools/generate_period_look.py"):
            for number, line in enumerate((ROOT / rel).read_text("utf-8").splitlines(), 1):
                stripped = line.strip()
                if ('"--image-resolution", "2K"' in stripped or '"resolution": "2K"' in stripped
                        or 'resolution="2K"' in stripped) and not stripped.startswith("#"):
                    pinned.append(f"{rel}:{number}")
        self.assertEqual(pinned, [], f"call sites still pin 2K: {pinned}")

    def test_registry_policy_names_exactly_the_active_deployed_profile(self) -> None:
        registry = json.loads((ROOT / "configs/IMAGE_MODEL_CAPABILITY_REGISTRY_v1.json").read_text("utf-8"))
        allowed = registry["active_execution_policy"]["allowed_paid_profile_ids"]
        self.assertEqual(allowed, ["GPT_IMAGE_2_FAST_GIGGLE"])
        profile = policy.active_profile()
        self.assertEqual(profile["profile_id"], "GPT_IMAGE_2_FAST_GIGGLE")
        self.assertEqual(profile["adapter_status"], "DEPLOYED")
        self.assertEqual(profile["provider"], "giggle")

    def test_bare_gpt_image_2_is_not_a_giggle_model(self) -> None:
        # Probe 2026-10-30: POST text-to-image model=gpt-image-2 -> 500 "failed to get model price".
        self.assertNotIn("gpt-image-2", policy.known_image_models())
        with self.assertRaises(RuntimeError):
            policy.image_model_pricing("gpt-image-2")

    def test_retired_pro_sku_stays_recognised_but_not_allowed_for_new_submits(self) -> None:
        self.assertIn("gpt-image-2-pro", policy.known_image_models())
        self.assertNotIn("gpt-image-2-pro", policy.allowed_image_models())
        self.assertEqual(policy.allowed_image_models(), frozenset({"gpt-image-2-fast"}))

    def test_reserve_price_is_conservative_until_a_statement_row_is_seen(self) -> None:
        pricing = policy.image_model_pricing()
        self.assertGreaterEqual(int(pricing["hard_upper"]), 1)
        # the pro price is the only observed GPT Image 2 charge; the fast reserve must not be below
        # a figure the registry has no evidence for
        if pricing.get("credits") is None:
            self.assertEqual(int(pricing["hard_upper"]), policy.image_hard_upper_credits("gpt-image-2-pro"))
        else:
            self.assertLessEqual(int(pricing["credits"]), int(pricing["hard_upper"]))

    def test_call_sites_do_not_pin_the_retired_sku(self) -> None:
        pinned = []
        for rel in (
            "tools/giggle_api_client.py", "tools/giggle_asset_factory.py", "tools/giggle_credit_statements.py",
            "tools/submit_giggle_character_asset_plan.py", "tools/submit_giggle_image_manifest.py",
            "tools/storyclaw_asset_plan_gate.py", "tools/episode_parallel_batch_supervisor.py",
            "lines/nalu/runtime/tools/nalu_pipeline.py", "lines/nalu/runtime/tools/materialize_paid_authorization.py",
            "lines/nalu/runtime/tools/build_keyframe_manifest.py", "lines/nalu/runtime/tools/bootstrap_identity_cards.py",
            "lines/nalu/runtime/tools/nalu_budget_ledger.py",
        ):
            path = ROOT / rel
            if not path.is_file():
                continue
            for number, line in enumerate(path.read_text("utf-8").splitlines(), 1):
                stripped = line.strip()
                if '"gpt-image-2-pro"' in stripped and not stripped.startswith("#") and "LEGACY" not in stripped \
                        and "image_gpt_image_2_pro" not in stripped:
                    pinned.append(f"{rel}:{number}")
        self.assertEqual(pinned, [], f"call sites still pin the retired SKU: {pinned}")


if __name__ == "__main__":
    unittest.main()
