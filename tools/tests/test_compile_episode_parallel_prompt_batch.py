import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools.compile_episode_parallel_prompt_batch import dialogue_duration_seconds


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/compile_episode_parallel_prompt_batch.py"


def single_scene_state():
    return {"scene_state": [{
        "scene_id": "S1", "location": "day hall", "time_of_day": "day", "weather": "clear",
        "beats": ["B01"], "location_prompt_tokens": ["hall"],
    }]}


def action_beat(beat_id, **extra):
    return {
        "beat_id": beat_id,
        "payload_delivery": "ACTION_XUANHUAN",
        "action_spine": "雨中短打擒拿",
        "xuanhuan_element": "冰流显痕",
        "power_visualization": "雨幕冻结",
        **extra,
    }


def dialogue_line(dia_id="DIA-001", beat_id="B01", speaker="A", text="Line", **extra):
    return {
        "dia_id": dia_id,
        "beat_id": beat_id,
        "speaker": speaker,
        "text": text,
        "action_timeline": [
            {
                "start_seconds": 0,
                "end_seconds": 2,
                "actions": ["主体=A；动作=转身；接触点=脚下地面；方向=朝向线索；终态=面向线索"],
                "state_change": "A turns toward the clue.",
                "action_budget_seconds": 2,
            },
            {
                "start_seconds": 2,
                "end_seconds": 4,
                "actions": ["主体=A；动作=抬手；接触点=桌沿；方向=向前；终态=手停在桌沿"],
                "state_change": "A's hand reaches the table edge.",
                "action_budget_seconds": 2,
            },
        ],
        **extra,
    }


class ParallelPromptBatchTests(unittest.TestCase):
    def test_compiles_image_and_video_batches_without_scene_drift(self):
        sheet = {
            "episode": "E25", "review_status": "APPROVED_TEST", "generation_allowed": True,
            "scene_variety": {"location": "day hall", "time_of_day": "day", "weather": "clear", "palette": "warm"},
            "structure": [action_beat("B01", name="turn", must_show=["table"], new_information="clue")],
            "dialogue_draft": [dialogue_line(function="reveal", payload=["new_info"])],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); sp = tmp / "sheet.json"; st = tmp / "state.json"; out = tmp / "out"; manifest = tmp / "manifest.json"
            sp.write_text(json.dumps(sheet)); st.write_text(json.dumps(single_scene_state()))
            proc = subprocess.run(["python3", str(TOOL), "--sheet", str(sp), "--scene-state", str(st), "--out-dir", str(out), "--manifest", str(manifest)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(manifest.read_text())
            self.assertEqual(data["status"], "READY_FOR_REFERENCE_BINDING")
            self.assertEqual(len(data["image_tasks"]), 1)
            self.assertEqual(len(data["video_tasks"]), 1)
            self.assertEqual(data["video_tasks"][0]["duration_seconds"], 4)
            self.assertEqual(data["video_tasks"][0]["model"], "seedance-2.0-fast")
            self.assertEqual(data["video_tasks"][0]["duration_plan"]["policy"], "qingshan.shot_generation_duration.v5")
            self.assertEqual(data["video_tasks"][0]["action_density_gate"]["status"], "PASS")
            image_prompt = Path(data["image_tasks"][0]["prompt_file"]).read_text()
            self.assertIn("exactly one continuous photographic frame", image_prompt)
            self.assertIn("no collage", image_prompt)
            prompt = Path(data["video_tasks"][0]["prompt_file"]).read_text()
            self.assertIn("No external BGM", prompt)
            self.assertIn("do not invent moonlight", prompt.lower())
            self.assertIn("continuous 4-second shot", prompt)
            self.assertIn("Action timeline", prompt)

    def test_rejects_padding_line_without_payload(self):
        sheet = {"episode": "E99", "structure": [{"beat_id": "B01"}], "dialogue_draft": [{"dia_id": "DIA-001", "beat_id": "B01", "speaker": "A", "text": "Line"}]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); sp = tmp / "sheet.json"; st = tmp / "state.json"
            sp.write_text(json.dumps(sheet)); st.write_text(json.dumps(single_scene_state()))
            proc = subprocess.run(["python3", str(TOOL), "--sheet", str(sp), "--scene-state", str(st), "--out-dir", str(tmp / "out"), "--manifest", str(tmp / "manifest.json")], capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("payload missing", proc.stderr)

    def test_legacy_function_field_is_accepted_as_auditable_payload(self):
        sheet = {
            "episode": "E25", "review_status": "APPROVED_TEST", "generation_allowed": True,
            "structure": [action_beat("B01", new_information="clue")],
            "dialogue_draft": [dialogue_line(function="reveal clue")],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); sp = tmp / "sheet.json"; st = tmp / "state.json"; manifest = tmp / "manifest.json"
            sp.write_text(json.dumps(sheet)); st.write_text(json.dumps(single_scene_state()))
            proc = subprocess.run(["python3", str(TOOL), "--sheet", str(sp), "--scene-state", str(st), "--out-dir", str(tmp / "out"), "--manifest", str(manifest)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            task = json.loads(manifest.read_text())["video_tasks"][0]
            self.assertEqual(task["payload"], "reveal clue")
            self.assertEqual(task["payload_source"], "function")

    def test_dialogue_duration_scales_and_clamps_to_seedance_range(self):
        self.assertEqual(dialogue_duration_seconds("短句"), 4)
        self.assertGreater(dialogue_duration_seconds("这是一句明显更长、需要自然停顿并完整说完的对白。"), 4)
        self.assertEqual(dialogue_duration_seconds("很长的对白" * 30), 15)

    def test_reference_map_binds_every_video_for_parallel_submit(self):
        sheet = {
            "episode": "E25", "review_status": "APPROVED_TEST", "generation_allowed": True,
            "structure": [action_beat("B01", new_information="clue")],
            "dialogue_draft": [dialogue_line(function="reveal clue")],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); sp = tmp / "sheet.json"; st = tmp / "state.json"; manifest = tmp / "manifest.json"; ref = tmp / "ref.png"; refs = tmp / "refs.json"
            sp.write_text(json.dumps(sheet)); st.write_text(json.dumps(single_scene_state())); ref.write_bytes(b"image"); refs.write_text(json.dumps({"beats": {"B01": [str(ref)]}}))
            proc = subprocess.run(["python3", str(TOOL), "--sheet", str(sp), "--scene-state", str(st), "--out-dir", str(tmp / "out"), "--manifest", str(manifest), "--reference-map", str(refs)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(manifest.read_text())
            self.assertEqual(data["status"], "READY_FOR_PARALLEL_SUBMIT")
            self.assertEqual(data["video_tasks"][0]["reference_images"], [str(ref)])
            self.assertEqual(data["video_tasks"][0]["status"], "READY_FOR_PARALLEL_SUBMIT")

    def test_each_beat_uses_its_own_script_scene_authority(self):
        sheet = {
            "episode": "E25", "review_status": "APPROVED_TEST", "generation_allowed": True,
            "structure": [action_beat("B01"), action_beat("B02")],
            "dialogue_draft": [
                dialogue_line(function="one"),
                dialogue_line(dia_id="DIA-002", beat_id="B02", function="two"),
            ],
        }
        state = {"scene_state": [
            {"scene_id": "S1", "location": "hall", "time_of_day": "night", "weather": "clear", "beats": ["B01"], "location_prompt_tokens": ["hall"]},
            {"scene_id": "S2", "location": "alley", "time_of_day": "day", "weather": "clear", "beats": ["B02"], "location_prompt_tokens": ["alley"]},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); sp = tmp / "sheet.json"; st = tmp / "state.json"; manifest = tmp / "manifest.json"
            sp.write_text(json.dumps(sheet)); st.write_text(json.dumps(state))
            proc = subprocess.run(["python3", str(TOOL), "--sheet", str(sp), "--scene-state", str(st), "--out-dir", str(tmp / "out"), "--manifest", str(manifest)], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            tasks = json.loads(manifest.read_text())["video_tasks"]
            self.assertEqual([task["scene_id"] for task in tasks], ["S1", "S2"])
            self.assertIn("location hall", Path(tasks[0]["prompt_file"]).read_text())
            self.assertIn("location alley", Path(tasks[1]["prompt_file"]).read_text())

    def test_e26_plus_requires_final_storyboard_sheet_gate(self):
        sheet = {
            "episode": "E26", "review_status": "APPROVED_TEST", "generation_allowed": True,
            "structure": [action_beat("B01", new_information="clue")],
            "dialogue_draft": [{"dia_id": "DIA-001", "beat_id": "B01", "speaker": "A", "text": "Line", "function": "reveal clue"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); sp = tmp / "sheet.json"; st = tmp / "state.json"
            sp.write_text(json.dumps(sheet)); st.write_text(json.dumps(single_scene_state()))
            proc = subprocess.run(["python3", str(TOOL), "--sheet", str(sp), "--scene-state", str(st), "--out-dir", str(tmp / "out"), "--manifest", str(tmp / "manifest.json")], capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0)
            self.assertIn("storyboard-sheet plan and final gate report are required", proc.stderr)


if __name__ == "__main__":
    unittest.main()
