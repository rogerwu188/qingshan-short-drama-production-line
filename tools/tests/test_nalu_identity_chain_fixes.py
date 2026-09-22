"""Roger 2026-09-18 identity chain fixes ①–④ (nalu line): source-photo likeness at the PASS threshold,
face plate first in keyframe references with a non-character cap, one headshot plate per visible
character on every video unit, and 3/4 / profile faces measured in Q1."""
import importlib.util
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))


def load(name):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


with patch.dict(os.environ, {
    "NALU_ENGINE_ROOT": str(ROOT),
    "NALU_RUNTIME_ROOT": tempfile.mkdtemp(),
}):
    lock = load("identity_qa_lock")
    kfm = load("build_keyframe_manifest")
    q1 = load("keyframe_q1_builder")


class SourceLikeness(unittest.TestCase):
    def test_suffixed_source_photo_is_found_and_never_another_character(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "CHAR-QINMING__SOURCE_V2_TANG.png").write_bytes(b"x")
            (folder / "CHAR-LIANGWANQING.png").write_bytes(b"x")
            (folder / "E05_CHAR-LUWENHUI__FRONT_NEUTRAL_HEADSHOT_1.png").write_bytes(b"x")
            self.assertEqual(lock.find_operator_source("CHAR-QINMING", folder).name, "CHAR-QINMING__SOURCE_V2_TANG.png")
            self.assertEqual(lock.find_operator_source("CHAR-LIANGWANQING", folder).name, "CHAR-LIANGWANQING.png")
            self.assertIsNone(lock.find_operator_source("CHAR-LU", folder))
            self.assertIsNone(lock.find_operator_source("CHAR-LUWENHUI", folder))

    def test_any_plate_below_pass_threshold_fails(self):
        scores = [{"plate": "/p/FRONT.png", "cosine_vs_source": 0.351},
                  {"plate": "/p/TQ.png", "cosine_vs_source": 0.407},
                  {"plate": "/p/FULL.png", "cosine_vs_source": 0.559}]
        failures = lock.source_likeness_failures(scores, 0.45)
        self.assertEqual(len(failures), 2)
        self.assertTrue(all(f.startswith("SOURCE_LIKENESS_BELOW_PASS_THRESHOLD:") for f in failures))
        self.assertEqual(lock.source_likeness_failures([{"plate": "a", "cosine_vs_source": 0.8}], 0.45), [])


LIB = {"assets": {"characters": {"CHAR-A": {"status": "LOCKED", "artifacts": [
    {"role": "FULL_BODY_STANDING", "path": "/x/E02_CHAR-A_full.png", "sha256": "1"},
    {"role": "FRONT_NEUTRAL_HEADSHOT", "path": "/x/E02_CHAR-A__FRONT_NEUTRAL_HEADSHOT_2.png", "sha256": "2"},
    {"role": "THREE_QUARTER_BUST", "path": "/x/E02_CHAR-A__THREE_QUARTER_BUST_3.png", "sha256": "3"}]}}}}


class KeyframeReferences(unittest.TestCase):
    def test_pending_binding_uses_deterministic_registration_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = root / "asset_library.json"
            library.write_text("{}\n")
            inputs = SimpleNamespace(
                asset_library={"assets": {}},
                asset_library_path=library,
                engine_root=root,
                awaited_asset_dir=root / "awaited",
            )
            row = kfm.entity_binding(
                inputs, "character", "characters", "CHAR-ZHOUQING", "周青", "CHARACTER"
            )
            self.assertEqual(
                row["path"], str((root / "awaited/characters/CHAR-ZHOUQING.json").resolve())
            )
            self.assertEqual(row["binding_status"], "PENDING_ASSET_LIBRARY_ARTIFACT")
            self.assertFalse(Path(row["path"]).exists())

    def test_face_role_leads_and_headshot_plate_is_selected(self):
        self.assertEqual(kfm.BINDING_ROLE_ORDER.index("character"), kfm.BINDING_ROLE_ORDER.index("subspace_layout") + 1)   # first slot the engine gate allows
        self.assertLess(kfm.BINDING_ROLE_ORDER.index("character"), kfm.BINDING_ROLE_ORDER.index("scene"))
        _, art = kfm.library_artifact(LIB, "characters", "CHAR-A", kfm.CHARACTER_FACE_VIEW)
        self.assertEqual(art["role"], "FRONT_NEUTRAL_HEADSHOT")
        _, art = kfm.library_artifact(LIB, "characters", "CHAR-A", kfm.CHARACTER_WARDROBE_VIEW)
        self.assertEqual(art["role"], "FULL_BODY_STANDING")
        _, art = kfm.library_artifact(LIB, "characters", "CHAR-A")
        self.assertEqual(art["role"], "FULL_BODY_STANDING")  # historical default unchanged

    def test_non_character_references_capped_at_five_face_never_dropped(self):
        rows = ([{"role": "episode_global_space_map"}, {"role": "global_space_map"}, {"role": "subspace_layout"}]
                + [{"role": "character", "entity_id": "CHAR-A"}, {"role": "character", "entity_id": "CHAR-B"}, {"role": "scene"}]
                + [{"role": "character_wardrobe", "entity_id": "CHAR-A"}, {"role": "character_wardrobe", "entity_id": "CHAR-B"}]
                + [{"role": "prop", "entity_id": f"PROP-{i}"} for i in range(4)])
        kept, dropped = kfm.cap_non_character_bindings(rows)
        non_char = [r for r in kept if r["role"] not in ("character", "character_wardrobe")]
        self.assertEqual(len(non_char), 8)   # gate-mandatory rows are never dropped, only reported
        self.assertTrue(any(str(r["dropped_reason"]).startswith("OVER_CAP_NOT_DROPPED") for r in dropped))
        self.assertEqual(sum(1 for r in kept if r["role"] == "character_wardrobe"), 0)   # only wardrobe plates drop for the total cap
        self.assertEqual(len(kept), 10)   # 3 maps + 2 faces + scene + 4 declared props: gate-mandatory rows stay even over 9
        self.assertEqual([r["role"] for r in kept][3:5], ["character", "character"])
        self.assertIn("subspace_layout", [r["role"] for r in kept]); self.assertEqual(sum(1 for r in kept if r["role"] == "prop"), 4)
        self.assertIn("scene", [r["role"] for r in kept])
        self.assertTrue(all(r["role"] in ("prop", "character_wardrobe") for r in dropped))
        self.assertIn("episode_global_space_map", [r["role"] for r in kept])
        order = [kfm.BINDING_ROLE_ORDER.index(r["role"]) for r in kept]
        self.assertEqual(order, sorted(order))


class Q1PoseExemption(unittest.TestCase):
    def test_three_quarter_and_profile_are_measured(self):
        for marker in ("THREE_QUARTER_TURNED_TO_LUZE_NOT_MEASURABLE", "PROFILE_LISTENING_NOT_MEASURABLE",
                       "HIGH_ANGLE_HEAD_DOWN_NOT_MEASURABLE", "MEDIUM_COLLAR_SHADOW_CHIN_ONLY_NOT_MEASURABLE",
                       "UP_TILTED_PROFILE_NOT_MEASURABLE", "VISIBLE_PER_FRAME_CONTENT"):
            self.assertFalse(q1.pose_exempt(marker), marker)

    def test_only_no_face_poses_are_exempt(self):
        for marker in ("BACK_TO_CAMERA_WALKING_NOT_MEASURABLE", "BACK_THREE_QUARTER_NOT_MEASURABLE",
                       "FAR_FIGURE_FACE_NOT_MEASURABLE", "SMALL_TODDLER_BEHIND_BROTHER_NOT_MEASURABLE",
                       "OFFSCREEN_VOICE_ONLY", "ENTERS_IN_SHOT_NOT_IN_FIRST_FRAME"):
            self.assertTrue(q1.pose_exempt(marker), marker)

    def test_face_measurable_ids_uses_the_narrowed_rule(self):
        item = {"expectations": {"required_visible_character_ids": ["A", "B", "C"], "cast": [
            {"character_id": "A", "face_visibility": "THREE_QUARTER_TURNED_NOT_MEASURABLE"},
            {"character_id": "B", "face_visibility": "BACK_TO_CAMERA"},
            {"character_id": "C"}]}}
        self.assertEqual(q1.face_measurable_ids(item), ["A", "C"])


class VideoUnitPlates(unittest.TestCase):
    def test_storyclaw_legacy_shot_gets_stable_states_and_location(self):
        spec = importlib.util.spec_from_file_location("bnp_storyclaw", TOOLS / "build_nalu_preproduction.py")
        try:
            bnp = importlib.util.module_from_spec(spec)
            sys.modules["bnp_storyclaw"] = bnp
            spec.loader.exec_module(bnp)
        except Exception as exc:  # noqa: BLE001 - the engine module needs the full engine tree
            self.skipTest(f"build_nalu_preproduction not importable here: {exc}")
        contract = {
            "scene_states": [{
                "scene_id": "S1", "weather": "夜", "lighting": "月光",
            }],
            "character_entities": [],
            "non_character_entities": [],
            "shots": [{
                "shot_id": "E01-S01-01", "scene_id": "S1", "target_seconds": 2,
                "shot_size": "中景", "camera": "固定", "axis": "东向西", "blocking": "主体抬手",
                "prompt_spec": {"action": {"primary_action": "主体抬手"}},
            }],
        }
        plan_rows = [{
            "shot_id": "E01-S01-01", "room_id": "ROOM-S1", "zone_id": "ZONE-S1",
            "zone_ids": ["ZONE-S1"], "angle_id": "ANGLE-S1", "axis_id": "AXIS-S1",
            "subspace_id": "SUBSPACE-S1", "global_space_map_id": "GSM-S1", "prop_ids": [],
        }]
        index = SimpleNamespace(
            episode_map_id="EGSM-E01",
            rooms={"ROOM-S1": {"name": "山洞"}},
            zones={"ZONE-S1": {"name": "洞内区"}},
            elements=lambda _room_id: [],
        )
        engine = SimpleNamespace(dialogue_limit=50, dialogue_length=len)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "NALU_POLICY_PROFILE": "LEGACY_EPISODE_COMPAT",
        }, clear=False):
            root = Path(tmp)
            contract_path, gsm_path = root / "contract.json", root / "gsm.json"
            contract_path.write_text("{}\n")
            gsm_path.write_text("{}\n")
            manifest, _ = bnp.build_editorial(
                contract, plan_rows, index, engine, "E01", contract_path, gsm_path, root
            )
        shot = manifest["shots"][0]
        self.assertEqual(shot["entry_state"], "动作开始前：主体处于初始状态")
        self.assertEqual(shot["completion_state"], "动作完成后：主体抬手")
        self.assertEqual(shot["prompt_spec"]["space"]["location"], "ROOM-S1")
        self.assertEqual(shot["prompt_spec"]["action"]["start_state"], shot["entry_state"])

    def test_current_portable_shot_requires_authored_endpoints(self):
        spec = importlib.util.spec_from_file_location(
            "bnp_current_portable", TOOLS / "build_nalu_preproduction.py"
        )
        try:
            bnp = importlib.util.module_from_spec(spec)
            sys.modules["bnp_current_portable"] = bnp
            spec.loader.exec_module(bnp)
        except Exception as exc:  # noqa: BLE001 - engine module needs full tree
            self.skipTest(f"build_nalu_preproduction not importable here: {exc}")
        contract = {
            "scene_states": [{"scene_id": "S1"}],
            "character_entities": [],
            "non_character_entities": [],
            "shots": [{
                "shot_id": "E01-S01-01", "scene_id": "S1", "target_seconds": 2,
                "prompt_spec": {"action": {"primary_action": "主体抬手"}},
            }],
        }
        plan_rows = [{
            "shot_id": "E01-S01-01", "room_id": "ROOM-S1",
            "zone_ids": [], "subspace_id": "SUBSPACE-S1",
            "global_space_map_id": "GSM-S1", "prop_ids": [],
        }]
        index = SimpleNamespace(
            episode_map_id="EGSM-E01", rooms={}, zones={},
            elements=lambda _room_id: [],
        )
        engine = SimpleNamespace(dialogue_limit=50, dialogue_length=len)
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {
            "NALU_POLICY_PROFILE": "CURRENT_PORTABLE",
        }, clear=False):
            root = Path(tmp)
            contract_path, gsm_path = root / "contract.json", root / "gsm.json"
            contract_path.write_text("{}\n")
            gsm_path.write_text("{}\n")
            with self.assertRaisesRegex(
                RuntimeError,
                r"CURRENT_PORTABLE_SHOT_ENDPOINTS_REQUIRED:E01-S01-01:entry_state,completion_state",
            ):
                bnp.build_editorial(
                    contract, plan_rows, index, engine, "E01",
                    contract_path, gsm_path, root,
                )

    def test_every_visible_character_gets_its_headshot_after_the_keyframe(self):
        spec = importlib.util.spec_from_file_location("bnp", TOOLS / "build_nalu_preproduction.py")
        try:
            bnp = importlib.util.module_from_spec(spec); sys.modules["bnp"] = bnp; spec.loader.exec_module(bnp)
        except Exception as exc:  # noqa: BLE001 - the engine module needs the full engine tree
            self.skipTest(f"build_nalu_preproduction not importable here: {exc}")
        with tempfile.TemporaryDirectory() as tmp:
            plates = {}
            for cid in ("CHAR-A", "CHAR-B"):
                p = Path(tmp) / f"{cid}__FRONT_NEUTRAL_HEADSHOT.png"; p.write_bytes(cid.encode()); plates[cid] = p
            rows, dropped, missing = bnp.identity_plate_reference_rows(
                ["CHAR-A", "CHAR-B", "CHAR-C"], lambda cid: plates.get(cid), existing_paths=["/k/E06-S01-01-keyframe-v1.png"])
            self.assertEqual([r["character_id"] for r in rows], ["CHAR-A", "CHAR-B"])
            self.assertEqual(missing, ["CHAR-C"]); self.assertEqual(dropped, [])
            rows, dropped, _ = bnp.identity_plate_reference_rows(["CHAR-A", "CHAR-B"], lambda cid: plates.get(cid),
                                                                  existing_paths=[f"/k/{i}.png" for i in range(8)])
            self.assertEqual([r["character_id"] for r in rows], ["CHAR-A"]); self.assertEqual(dropped, ["CHAR-B"])


if __name__ == "__main__":
    unittest.main()
