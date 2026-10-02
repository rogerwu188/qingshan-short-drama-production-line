"""Submit-boundary prompt scope conflict gate (synthetic data only; the POST is always mocked)."""
from __future__ import annotations

import contextlib
import hashlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import prompt_scope_conflict_gate as gate
from tools import submit_giggle_video_manifest_v2 as video
from tools.grouped_camera_contract import compile_camera_prompt
from tools.prompt_shot_scope_policy import active_for

ENGINE = Path(__file__).resolve().parents[2]
POLICY = {"lines": {"synthetic": {"models": ["seedance-2.0-pro"], "active_from_episode": 11}}}
ENTITIES = [
    {"character_id": "CHAR-A", "canonical_name": "甲", "provider_entity_label": "Ava"},
    {"character_id": "CHAR-B", "canonical_name": "乙", "provider_entity_label": "Bo"},
]
LOCKED = {
    "shot_scale": "MEDIUM", "camera_height": "EYE_LEVEL", "camera_side": "AXIS_A",
    "axis_relation": "保持轴线", "lens_intent": "标准焦段", "motion_family": "LOCKED",
    "motion_direction": "NONE", "start_framing": "甲乙对坐", "end_framing": "甲乙对坐",
    "motivation": "稳定观察两人对峙的距离变化与情绪",
}
TRACK = {**LOCKED, "motion_family": "TRACK", "motion_direction": "LEFT_TO_RIGHT", "end_framing": "甲在画右"}
# Baseline from the submitter before the shot-scope gate was wired in (same sample task).
BASELINE_INACTIVE_FINGERPRINT = "b4c71a5b68730310b91977cbcdf48006b517c495b67535c296dceea441f18d30"


def spec(shot, t0, t1, *, speaker=None, partial=None, camera=None, dialogue=None):
    role = {}
    if speaker:
        role.update({"dialogue_speaker_id": speaker, "lip_owner_id": speaker})
    cast = [{"character": "甲", "character_id": "CHAR-A"}, {"character": "乙", "character_id": "CHAR-B"}]
    for row in cast:
        if partial and row["character_id"] in partial:
            row["visible_body_range"] = partial[row["character_id"]]
    row = {"shot_id": shot, "action": {"t0_seconds": t0, "t1_seconds": t1}, "cast": cast,
           "role_semantic_disambiguation": role}
    if dialogue:
        row["dialogue"] = dialogue
    if camera:
        row["camera_plan"] = camera
    return row


def task(specs, *, camera_plan=None, episode="E11"):
    row = {
        "task_key": f"{episode}-VU001", "episode": episode, "model": "seedance-2.0-pro",
        "reference_sha256": ["c" * 64],
        "machine_contract": {"character_entities": ENTITIES, "ordered_prompt_specs": specs},
    }
    if camera_plan:
        row["machine_contract"]["camera_plan"] = camera_plan
    return row


TWO_BEATS = [
    spec("S1", 10.0, 12.0, speaker="CHAR-A", partial={"CHAR-B": "HANDS_ONLY"}, dialogue="甲：你来了"),
    spec("S2", 12.0, 14.0),
]
GOOD_TEXT = (
    "【角色】\nS1：甲执行本拍主动作，只有甲开口。\nS2：乙执行本拍主动作。\n"
    "【时间轴】\n"
    "0–2秒：从对坐开始，力源=甲；乙只露双手，不露脸；甲只说一次：“你来了”，其余人物闭口。\n"
    "2–4秒：从对坐开始，力源=乙；乙抬头看向甲。\n"
    "【摄影】" + compile_camera_prompt(LOCKED, source_id="S") + "\n【环境】保持微动。\n"
)


class CheckTaskTests(unittest.TestCase):
    def test_partial_clause_on_declared_entity_passes(self):
        result = gate.check_task(task(TWO_BEATS, camera_plan=LOCKED), GOOD_TEXT)
        self.assertEqual(result["status"], "PASS", result["failures"])
        expected = gate.checked_sha256(GOOD_TEXT.encode("utf-8"), ["c" * 64])
        self.assertEqual(result["checked_sha256"], expected)

    def test_english_named_partial_clause_passes(self):
        text = ("[0s-2s] Start from seated. Ava speaks. Visibility for this beat only: "
                "Bo: only Bo's hands in frame during this beat, do not reveal Bo's face or full body.\n"
                "[2s-4s] Start from seated. Bo looks up.\n")
        self.assertEqual(gate.check_task(task(TWO_BEATS), text)["status"], "PASS")

    def test_speaker_declared_face_forbidden_fails(self):
        specs = [spec("S1", 0, 2, speaker="CHAR-A", partial={"CHAR-A": "HANDS_ONLY"}, dialogue="甲：你来了")]
        result = gate.check_task(task(specs), "0–2秒：从对坐开始；甲只说一次：“你来了”。\n")
        self.assertEqual(result["status"], "FAIL")
        self.assertIn("VISIBLE_SPEAKER_FACE_FORBIDDEN:BEAT.1:CHAR-A:PARTIAL", result["failures"])

    def test_generic_unnamed_clause_fails(self):
        text = ("[0s-2s] Start from seated. Cropped body parts belong to the named identity; "
                "do not widen the frame to reveal its face or full body.\n[2s-4s] Start from seated.\n")
        failures = gate.check_task(task(TWO_BEATS), text)["failures"]
        self.assertTrue(any(f.startswith("PARTIAL_CLAUSE_GENERIC_UNNAMED:BEAT.1") for f in failures), failures)

    def test_clause_on_normal_dialogue_entity_fails(self):
        text = GOOD_TEXT.replace("乙只露双手，不露脸；甲只说一次", "甲不露脸；甲只说一次")
        failures = gate.check_task(task(TWO_BEATS, camera_plan=LOCKED), text)["failures"]
        self.assertIn("PARTIAL_CLAUSE_NOT_DECLARED_PARTIAL:BEAT.1:CHAR-A", failures)
        self.assertIn("PARTIAL_CLAUSE_ON_VISIBLE_SPEAKER:BEAT.1:CHAR-A", failures)

    def test_clause_leaking_to_unit_scope_fails(self):
        text = GOOD_TEXT + "【限制】乙全程不露脸。\n"
        failures = gate.check_task(task(TWO_BEATS, camera_plan=LOCKED), text)["failures"]
        self.assertIn("PARTIAL_CLAUSE_NOT_DECLARED_PARTIAL:UNIT:CHAR-B", failures)

    def test_missing_visibility_is_not_face_forbidden(self):
        specs = [spec("S1", 0, 2, speaker="CHAR-A", dialogue="甲：你来了")]
        self.assertEqual(gate.check_task(task(specs), "0–2秒：从对坐开始；甲只说一次：“你来了”。\n")["status"], "PASS")

    def test_locked_unit_camera_with_move_instruction_fails(self):
        text = "【时间轴】\n0–2秒：从对坐开始。\n2–4秒：从对坐开始。\ncamera: shot scale=MEDIUM; locked camera; direction=NONE; execute the declared move once\n"
        failures = gate.check_task(task(TWO_BEATS, camera_plan=LOCKED), text)["failures"]
        self.assertIn("LOCKED_CAMERA_MOVE_INSTRUCTION:UNIT:execute the declared move", failures)

    def test_per_shot_camera_scopes_moves_to_their_own_shot(self):
        specs = [spec("S1", 0, 2, camera=LOCKED), spec("S2", 2, 4, camera=TRACK)]
        good = (
            "【摄影】按时间轴逐拍执行各自机位，不将任一拍的运镜扩展到整段。\n"
            "仅分镜S1（0–2秒）适用：" + compile_camera_prompt(LOCKED, source_id="S1").replace("全段", "本分镜") + "\n"
            "仅分镜S2（2–4秒）适用：" + compile_camera_prompt(TRACK, source_id="S2") + "\n【环境】微动。\n"
        )
        self.assertEqual(gate.check_task(task(specs), good)["status"], "PASS")
        bad = good.replace("本分镜锁定机位", "本分镜锁定机位后缓慢横移")
        failures = gate.check_task(task(specs), bad)["failures"]
        self.assertIn("LOCKED_CAMERA_MOVE_INSTRUCTION:BEAT.1:横移", failures)
        self.assertFalse(any(":BEAT.2:" in f for f in failures), failures)

    def test_renderer_partial_clause_leaks_is_used_when_present(self):
        h3 = {**task(TWO_BEATS), "model": "MiniMax-H3", "execution_plan": {"unit_id": "U"}}
        fake = types.ModuleType("h3_provider_prompt_renderer")
        fake.partial_clause_leaks = lambda text, plan, unit=None: ["PARTIAL_CLAUSE_LEAK:BEAT.1:Bo"]
        with patch.dict(sys.modules, {"tools.h3_provider_prompt_renderer": fake}):
            result = gate.check_task(h3, "[0s-2s] Start from seated.\n[2s-4s] Start from seated.\n")
        self.assertIn("H3_RENDERER:PARTIAL_CLAUSE_LEAK:BEAT.1:Bo", result["failures"])
        without = types.ModuleType("h3_provider_prompt_renderer")
        with patch.dict(sys.modules, {"tools.h3_provider_prompt_renderer": without}):
            result = gate.check_task(h3, "[0s-2s] Start from seated.\n[2s-4s] Start from seated.\n")
        self.assertEqual((result["status"], result["external_partial_clause_checker"]), ("PASS", "UNAVAILABLE"))

    def test_loaded_module_audit_marks_overlay_external(self):
        with tempfile.TemporaryDirectory() as tmp:
            overlay = Path(tmp) / "h3_provider_prompt_renderer.py"
            overlay.write_text("# overlay\n", encoding="utf-8")
            fake = types.ModuleType("h3_provider_prompt_renderer")
            fake.__file__ = str(overlay)
            with patch.dict(sys.modules, {"h3_provider_prompt_renderer": fake}):
                rows = gate.loaded_module_audit(ENGINE)
        by_name = {row["module"]: row for row in rows}
        self.assertEqual(by_name["h3_provider_prompt_renderer"]["path"], "<external>")
        self.assertEqual(by_name["h3_provider_prompt_renderer"]["sha256"],
                         hashlib.sha256(b"# overlay\n").hexdigest())
        self.assertEqual(by_name[gate.__name__]["path"], "tools/prompt_scope_conflict_gate.py")


class SubmitterWiringTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "ref.png").write_bytes(b"synthetic-reference")
        self.tx = self.root / "tx"
        self.receipts = self.root / "receipts"
        stack = contextlib.ExitStack()
        self.addCleanup(stack.close)
        self.addCleanup(self._tmp.cleanup)
        stack.enter_context(patch.object(video, "ROOT", self.root))
        stack.enter_context(patch("tools.episode_prompt_batch_gate.require_generation_batch"))
        stack.enter_context(patch.object(video, "_image_list", return_value=[]))
        stack.enter_context(patch.object(video, "paid_video_submission_context", contextlib.nullcontext))
        stack.enter_context(patch.object(
            video, "shot_scope_active_for", side_effect=lambda ep, model: active_for(ep, model, policy=POLICY)))
        self.post = stack.enter_context(patch.object(video, "_request", return_value={"data": {"task_id": "T-1"}}))
        self.check = stack.enter_context(patch.object(
            video, "check_prompt_scope_conflicts", side_effect=gate.check_task))

    def make_task(self, text, *, specs=TWO_BEATS, episode="E11", name="prompt.txt"):
        (self.root / name).write_text(text, encoding="utf-8")
        row = task(specs, camera_plan=LOCKED, episode=episode)
        row.update({
            "prompt_file": name, "prompt_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            "reference_images": ["ref.png"],
            "reference_sha256": [hashlib.sha256(b"synthetic-reference").hexdigest()],
            "duration_seconds": 4, "aspect_ratio": "9:16", "resolution": "720p",
        })
        return row

    def intent(self, row):
        return json.loads(video.transaction_path(self.tx, row).read_text(encoding="utf-8"))

    def test_conflict_blocks_before_intent_and_never_posts(self):
        conflict = [spec("S1", 0, 2, speaker="CHAR-A", partial={"CHAR-A": "HANDS_ONLY"}, dialogue="甲：你来了")]
        row = self.make_task("0–2秒：从对坐开始；甲只说一次：“你来了”。\n", specs=conflict)
        with self.assertRaises(video.PromptScopeGateBlocked):
            video.submit_one(row, self.receipts, self.tx)
        self.assertEqual(self.post.call_count, 0)
        self.assertFalse(video.transaction_path(self.tx, row).exists())
        block = json.loads(video.pre_intent_block_path(self.tx, row).read_text(encoding="utf-8"))
        self.assertEqual(block["credit_status"], "NOT_CHARGED_NO_INTENT_RECORDED")
        self.assertEqual(block["status"], "submit_failed_before_intent")
        failure = {"task_key": row["task_key"], "transaction": str(video.transaction_path(self.tx, row))}
        video.classify_failures([failure], 0, 0, self.tx)
        self.assertEqual(failure["credit_status"], "NOT_CHARGED_NO_INTENT_RECORDED")

    def test_pass_is_bound_into_intent_with_module_audit(self):
        row = self.make_task(GOOD_TEXT)
        result = video.submit_one(row, self.receipts, self.tx)
        self.assertEqual(result["task_id"], "T-1")
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(self.post.call_args[0][1]["prompt"], GOOD_TEXT)
        intent = self.intent(row)
        self.assertEqual(intent["prompt_scope_conflict_gate"]["status"], "PASS")
        self.assertEqual(intent["prompt_scope_conflict_gate"]["checked_sha256"],
                         gate.checked_sha256(GOOD_TEXT.encode("utf-8"), row["reference_sha256"]))
        # Loaded either as tools.X or bare X depending on sys.path; whichever is loaded is audited.
        modules = {r["module"].removeprefix("tools."): r for r in intent["loaded_modules"]}
        for name, rel in (("prompt_scope_conflict_gate", "tools/prompt_scope_conflict_gate.py"),
                          ("submit_giggle_video_manifest_v2", "tools/submit_giggle_video_manifest_v2.py"),
                          ("giggle_api_client", "tools/giggle_api_client.py")):
            self.assertEqual(modules[name]["path"], rel)
            self.assertEqual(modules[name]["sha256"], hashlib.sha256((ENGINE / rel).read_bytes()).hexdigest())
        self.assertFalse(any(r["path"].startswith("/") for r in intent["loaded_modules"]))

    def test_changed_prompt_after_pass_is_rechecked(self):
        first = self.make_task(GOOD_TEXT)
        video.submit_one(first, self.receipts, self.tx)
        changed_text = GOOD_TEXT.replace("乙抬头看向甲", "乙抬头看向甲，甲不露脸")
        changed = self.make_task(changed_text, name="prompt_v2.txt")
        with self.assertRaises(video.PromptScopeGateBlocked):
            video.submit_one(changed, self.receipts, self.tx)
        self.assertEqual(self.check.call_count, 2)
        self.assertEqual(self.check.call_args[0][1], changed_text)
        self.assertEqual(self.post.call_count, 1)

    def test_bound_task_recovery_never_calls_gate_or_posts(self):
        row = self.make_task(GOOD_TEXT)
        path = video.transaction_path(self.tx, row)
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"submission_fingerprint": video.task_fingerprint(row),
                                    "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "T-0"}), encoding="utf-8")
        # Even a prompt that would now FAIL must not block recovery of a bound task id.
        (self.root / "prompt.txt").write_text("甲不露脸\n", encoding="utf-8")
        result = video.submit_one(row, self.receipts, self.tx)
        self.assertEqual(result["task_id"], "T-0")
        self.assertTrue(result["recovered_from_transaction"])
        self.assertEqual(self.check.call_count, 0)
        self.assertEqual(self.post.call_count, 0)

    def test_inactive_episode_keeps_legacy_path_and_fingerprint(self):
        sample = {"task_key": "E10-VU001", "prompt_sha256": "a" * 64, "reference_sha256": ["b" * 64],
                  "reference_images": ["no/such/ref.png"], "model": "MiniMax-H3", "duration_seconds": 6,
                  "aspect_ratio": "9:16", "resolution": "768p", "episode": "E10"}
        self.assertEqual(video.task_fingerprint(sample), BASELINE_INACTIVE_FINGERPRINT)
        # A prompt that would FAIL the gate still goes out unchanged on an inactive episode.
        text = "0–2秒：从对坐开始；甲不露脸；甲只说一次：“你来了”。\n"
        row = self.make_task(text, episode="E10")
        video.submit_one(row, self.receipts, self.tx)
        self.assertEqual(self.check.call_count, 0)
        self.assertEqual(self.post.call_count, 1)
        self.assertEqual(self.post.call_args[0][1]["prompt"], text)
        self.assertEqual(set(self.intent(row)), {
            "schema", "task_key", "attempt_id", "submission_fingerprint", "state", "intent_recorded_at",
            "prompt_sha256", "reference_sha256", "model", "retry_guard", "task_id", "receipt",
            "provider_response", "response_recorded_at",
        })


if __name__ == "__main__":
    unittest.main()
