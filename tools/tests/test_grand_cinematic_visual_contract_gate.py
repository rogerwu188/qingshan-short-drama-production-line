import unittest

from tools.grand_cinematic_visual_contract_gate import validate


def valid_payload():
    return {
        "scene_lock": {"location": "山门", "time_of_day": "day", "weather": "clear", "event": "队伍抵达"},
        "shots": [{
            "duration_seconds": 9,
            "shot_scale": "extreme wide",
            "lens_intent": "24mm spatial reveal",
            "camera_height": "high crane",
            "camera_motion": "slow descending push",
            "depth_layers": ["foreground pine", "midground caravan", "background academy"],
            "scale_anchor": "six riders below the gate",
            "palette": {"dominant": "jade", "contrast": "stone white", "accent": "vermillion"},
            "key_light": "clear side daylight",
            "atmosphere": "thin valley haze",
            "environmental_motion": ["flags and horse manes move in wind"],
            "material_detail": ["weathered stone", "woven banners"],
            "still_prompt_contract": "single continuous cinematic frame",
            "video_motion_contract": "camera descends as riders cross the gate",
            "negative_constraints": ["collage", "split screen", "night", "moonlight", "plastic skin"]
        }]
    }


class GrandCinematicGateTest(unittest.TestCase):
    def test_valid_contract_passes(self):
        self.assertEqual(validate(valid_payload())["status"], "PASS")

    def test_unmotivated_night_fails(self):
        payload = valid_payload()
        payload["shots"][0]["key_light"] = "moonlight"
        report = validate(payload)
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(any(e["error"] == "unmotivated_night_or_moonlight" for e in report["errors"]))

    def test_duration_and_depth_are_hard_gates(self):
        payload = valid_payload()
        payload["shots"][0]["duration_seconds"] = 3
        payload["shots"][0]["depth_layers"] = ["subject"]
        report = validate(payload)
        self.assertTrue(any(e["error"] == "must_be_4_to_15" for e in report["errors"]))
        self.assertTrue(any(e["error"] == "minimum_3" for e in report["errors"]))


if __name__ == "__main__":
    unittest.main()
