import json
import tempfile
import unittest
from pathlib import Path

import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from scene_authority_lock import evaluate_batch, evaluate_sequence


class SceneAuthorityLockTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def prompt(self, text):
        path = self.root / f"prompt-{len(list(self.root.iterdir()))}.txt"
        path.write_text(text, encoding="utf-8")
        return str(path)

    def state(self, time_of_day="clear_afternoon", weather="clear", reason=None):
        scene = {
            "scene_id": "S1",
            "location": "Buddhist hall",
            "time_of_day": time_of_day,
            "weather": weather,
            "event_summary": "Evidence is compared.",
            "allowed_time_terms": ["afternoon", "daylight"] if "night" not in time_of_day else ["night"],
            "allowed_weather_terms": ["clear"] if weather == "clear" else [weather],
            "location_prompt_tokens": ["Buddhist hall"],
        }
        if reason:
            scene["time_continuity_reason"] = reason
        return {"episode": "E22", "scene_state": [scene]}

    def task(self, prompt, **overrides):
        task = {"task_key": "T1", "scene_id": "S1", "visual_zone": "ZONE-A", "prompt_file": prompt,
                "spatial_layout_stage": "CHARACTER_IDENTITY"}
        task.update(overrides)
        return {"episode": "E22", "tasks": [task]}

    def test_missing_scene_state_fails(self):
        report = evaluate_batch({"episode": "E22"}, self.task(self.prompt("Afternoon Buddhist hall")))
        self.assertEqual(report["status"], "FAIL")

    def test_affirmative_moonlight_in_afternoon_fails(self):
        report = evaluate_batch(self.state(), self.task(self.prompt("Afternoon moonlight inside Buddhist hall")))
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(row["check"] == "undeclared_time_term" for row in report["failures"]))

    def test_negative_night_terms_do_not_fail(self):
        report = evaluate_batch(self.state(), self.task(self.prompt("Afternoon daylight in Buddhist hall; no night, no moon, no blue moonlight.")))
        self.assertEqual(report["status"], "PASS")

    def test_do_not_invent_clause_does_not_create_scene_facts(self):
        report = evaluate_batch(
            self.state(time_of_day="day", weather="snow"),
            self.task(
                self.prompt(
                    "Daytime snow outside Buddhist hall. "
                    "Do not invent moonlight, night, rain, locations, or events."
                )
            ),
        )
        self.assertEqual(report["status"], "PASS")

    def test_exact_clear_weather_category_accepts_natural_prompt_phrase(self):
        report = evaluate_batch(self.state(), self.task(self.prompt("Afternoon Buddhist hall in clear weather.")))
        self.assertEqual(report["status"], "PASS")

    def test_structured_no_rain_contract_is_not_affirmative_rain(self):
        report = evaluate_batch(
            self.state(weather="interior_clear"),
            self.task(self.prompt("Afternoon Buddhist hall. weather=INTERIOR_CLEAR_NO_RAIN. Interior clear; no rain is visible.")),
        )
        self.assertEqual(report["status"], "PASS")

    def test_task_requires_scene_id_and_visual_zone(self):
        report = evaluate_batch(self.state(), self.task(self.prompt("Afternoon Buddhist hall"), scene_id=None, visual_zone=None))
        self.assertEqual(report["status"], "FAIL")

    def test_adjacent_zone_repeat_fails(self):
        prompt = self.prompt("Afternoon Buddhist hall")
        config = self.task(prompt)
        config["tasks"].append({"task_key": "T2", "scene_id": "S1", "visual_zone": "ZONE-A", "prompt_file": prompt,
                                "spatial_layout_stage": "CHARACTER_IDENTITY"})
        report = evaluate_batch(self.state(), config)
        self.assertTrue(any(row["check"] == "adjacent_visual_zone" for row in report["failures"]))

    def test_declared_nup_variants_may_share_zone(self):
        prompt = self.prompt("Afternoon Buddhist hall")
        config = self.task(prompt, variant_group="B03-R3", variant_label="FRONTAL")
        config["tasks"].append({
            "task_key": "T2",
            "scene_id": "S1",
            "visual_zone": "ZONE-A",
            "variant_group": "B03-R3",
            "variant_label": "PROFILE",
            "prompt_file": prompt,
            "spatial_layout_stage": "CHARACTER_IDENTITY",
        })
        report = evaluate_batch(self.state(), config)
        self.assertEqual(report["status"], "PASS")

    def test_declared_nup_variants_require_unique_labels(self):
        prompt = self.prompt("Afternoon Buddhist hall")
        config = self.task(prompt, variant_group="B03-R3", variant_label="FRONTAL")
        config["tasks"].append({
            "task_key": "T2",
            "scene_id": "S1",
            "visual_zone": "ZONE-A",
            "variant_group": "B03-R3",
            "variant_label": "FRONTAL",
            "prompt_file": prompt,
            "spatial_layout_stage": "CHARACTER_IDENTITY",
        })
        report = evaluate_batch(self.state(), config)
        self.assertTrue(any(row["check"] == "adjacent_visual_zone" for row in report["failures"]))

    def test_three_nights_require_continuity_reason(self):
        paths = []
        for episode in ("E20", "E21", "E22"):
            state = self.state(time_of_day="night", weather="dry", reason="continuation" if episode != "E21" else None)
            state["episode"] = episode
            path = self.root / f"{episode}.json"
            path.write_text(json.dumps(state), encoding="utf-8")
            paths.append(path)
        self.assertEqual(evaluate_sequence(paths)["status"], "FAIL")


if __name__ == "__main__":
    unittest.main()
