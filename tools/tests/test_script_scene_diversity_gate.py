import unittest

from tools.script_scene_diversity_gate import evaluate


def scene(scene_id, location, time, weather, space, palette, **extra):
    return {
        "scene_id": scene_id,
        "location": location,
        "time_of_day": time,
        "weather": weather,
        "interior_exterior": space,
        "palette_temperature": palette,
        **extra,
    }


class ScriptSceneDiversityGateTests(unittest.TestCase):
    def test_diverse_three_episode_window_passes(self):
        payload = {"episodes": [
            {"episode": "E30", "scenes": [scene("A", "药铺", "day", "clear", "interior", "warm")]},
            {"episode": "E31", "scenes": [scene("B", "城门", "dusk", "wind", "exterior", "cool")]},
            {"episode": "E32", "scenes": [scene("C", "暗楼", "night", "rain", "interior", "cool")]},
        ]}
        self.assertEqual(evaluate(payload)["status"], "PASS")

    def test_adjacent_undeclared_repeat_fails(self):
        repeated = scene("A", "暗楼", "night", "rain", "interior", "cool")
        result = evaluate({"episodes": [
            {"episode": "E31", "scenes": [repeated]},
            {"episode": "E32", "scenes": [{**repeated, "scene_id": "B"}]},
        ]})
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any("adjacent_episode_scene_time_weather_repeat" in item for item in result["failures"]))


if __name__ == "__main__":
    unittest.main()
