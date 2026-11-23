"""Per-pass Gemini models for the multi-pass final review (owner 2026-11-23, E24 A/B: Pro on picture / identity /
director, Flash on sound; budget 25 credits; Pro refused -> one Flash retry).

Offline: Gemini is a fake ``post``, the transcoder writes bytes, no ffmpeg / network / paid call."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
for entry in (str(TOOLS), str(ROOT / "tools"), str(ROOT), str(Path(__file__).resolve().parent)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import gemini_review_passes as mp  # noqa: E402
import gemini_video_review as gvr  # noqa: E402
import test_nalu_gemini_multipass as base  # noqa: E402

PRO, FLASH = mp.PRO_MODEL, mp.FLASH_MODEL
#: prompt sizes of a real plan-parity episode (E24-like: D carries one row per unit)
CHARS = {"A": 6000, "B": 5000, "C": 5500, "D": 9000}
CARDS = {"B": 4}


class ModelSelectionTest(unittest.TestCase):
    def test_default_models_per_pass(self):
        self.assertEqual(mp.resolve_pass_models({}), {"A": PRO, "B": PRO, "C": FLASH, "D": PRO})
        self.assertEqual(gvr.PRICES[PRO], (134.0, 804.0))
        self.assertEqual(gvr.PRICES[FLASH], (50.25, 251.25))

    def test_env_overrides(self):
        env = {"NALU_GEMINI_REVIEW_MODEL": "gemini-x", "NALU_GEMINI_REVIEW_MODEL_C": "gemini-c"}
        self.assertEqual(mp.resolve_pass_models(env), {"A": "gemini-x", "B": "gemini-x", "C": "gemini-c",
                                                       "D": "gemini-x"})
        self.assertEqual(mp.resolve_pass_models({"NALU_GEMINI_REVIEW_MODEL_D": FLASH}),
                         {"A": PRO, "B": PRO, "C": FLASH, "D": FLASH})
        # --model beats the global env, a per-pass env beats both
        self.assertEqual(mp.resolve_pass_models({"NALU_GEMINI_REVIEW_MODEL": "g", "NALU_GEMINI_REVIEW_MODEL_A": "a"},
                                                override="cli"),
                         {"A": "a", "B": "cli", "C": "cli", "D": "cli"})

    def test_budget_default_and_env(self):
        self.assertEqual(mp.budget_cap({}), 25.0)
        self.assertEqual(gvr.MULTIPASS_MAX_CREDITS_DEFAULT, 25.0)
        self.assertEqual(mp.budget_cap({"NALU_GEMINI_REVIEW_MAX_CREDITS": "12"}), 12.0)
        self.assertEqual(mp.budget_cap({"NALU_GEMINI_REVIEW_BUDGET": "40",
                                        "NALU_GEMINI_REVIEW_MAX_CREDITS": "12"}), 40.0)
        self.assertEqual(mp.budget_cap({"NALU_GEMINI_REVIEW_BUDGET": "junk"}), 25.0)


class EstimateTest(unittest.TestCase):
    def test_pro_estimate_carries_thinking_tokens_at_pro_prices(self):
        kw = {"pid": "A", "duration": 110, "fps": 2, "res": "HIGH", "prompt_chars": 6000}
        pro = mp.estimate_pass(PRO, gvr.PRICES, **kw)
        flash = mp.estimate_pass(FLASH, gvr.PRICES, **kw)
        tokens_in = 110 * 2 * mp.VIDEO_TOKENS["HIGH"] + 6000 / 1.6 + 300
        self.assertAlmostEqual(pro, tokens_in * 134e-6 + (mp.PASSES["A"]["expected_out"] + 8000) * 804e-6, places=2)
        self.assertAlmostEqual(flash, tokens_in * 50.25e-6 + mp.PASSES["A"]["expected_out"] * 251.25e-6, places=2)
        self.assertEqual(mp.expected_output_tokens("D", PRO) - mp.expected_output_tokens("D", FLASH), 8000)

    def test_plan_fits_25_at_110s_and_keeps_pass_a_on_pro_at_its_preferred_settings(self):
        for duration in (60.0, 110.0):
            plan = mp.plan_budget(mp.resolve_pass_models({}), gvr.PRICES, duration=duration, cap=25.0,
                                  prompt_chars=CHARS, images=CARDS)
            p = plan["passes"]
            self.assertLessEqual(plan["estimated_credits"], 25.0)
            self.assertTrue(all("skipped" not in v for v in p.values()), p)
            self.assertEqual((p["A"]["model"], p["A"]["fps"], p["A"]["res"]), (PRO, 2.0, "HIGH"))
            self.assertEqual(p["C"]["model"], FLASH)
            # a Pro pass that does not fit steps down to Flash before losing resolution
            self.assertEqual((p["B"]["model"], p["B"]["res"], p["B"]["model_planned"]), (FLASH, "HIGH", PRO))

    def test_preferred_settings_when_the_budget_allows(self):
        plan = mp.plan_budget(mp.resolve_pass_models({}), gvr.PRICES, duration=110.0, cap=60.0,
                              prompt_chars=CHARS, images=CARDS)
        p = plan["passes"]
        self.assertEqual({k: (v["model"], v["fps"], v["res"]) for k, v in p.items()},
                         {"A": (PRO, 2.0, "HIGH"), "B": (PRO, 2.0, "HIGH"), "C": (FLASH, 2.0, "LOW"),
                          "D": (PRO, 2.0, "DEFAULT")})
        self.assertTrue(all(v["degraded_steps"] == 0 for v in p.values()))

    def test_pass_ladder_steps_a_pro_pass_down_to_flash(self):
        self.assertEqual(mp.pass_ladder("D", PRO), ((PRO, 2.0, "DEFAULT"), (FLASH, 2.0, "DEFAULT"),
                                                    (FLASH, 1.0, "DEFAULT")))
        self.assertEqual(mp.pass_ladder("A", PRO)[:3], ((PRO, 2.0, "HIGH"), (PRO, 1.5, "HIGH"), (FLASH, 2.0, "HIGH")))
        self.assertEqual(mp.pass_ladder("C", FLASH), ((FLASH, 2.0, "LOW"), (FLASH, 1.0, "LOW")))

    def test_request_body_default_resolution_and_thinking(self):
        body = mp.request_body(video_bytes=b"v", prompt="p", fps=2.0, res="DEFAULT")
        self.assertNotIn("mediaResolution", body["generationConfig"])
        body = mp.request_body(video_bytes=b"v", prompt="p", fps=2.0, res="HIGH")
        self.assertEqual(body["generationConfig"]["mediaResolution"], "MEDIA_RESOLUTION_HIGH")
        self.assertIsNone(mp.thinking_budget("B", PRO))          # Pro thinks dynamically
        self.assertEqual(mp.thinking_budget("B", FLASH), 3072)


def _answer(prompt: str) -> dict:
    name = next(k for k in base.ANSWERS if f"（{k}）" in prompt)
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(base.ANSWERS[name], ensure_ascii=False)}]}}],
            "usageMetadata": {"promptTokenCount": 10000, "candidatesTokenCount": 1000, "thoughtsTokenCount": 1000}}


class RunTest(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.object(mp, "card_jpeg", side_effect=base._card)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_passes(self, post, *, models=None, cap=100.0, passes=mp.PASS_IDS):
        return mp.run_passes(video=Path("v.mp4"), duration=60.0, model=models or mp.resolve_pass_models({}),
                             prices=gvr.PRICES, cap=cap, key="sk-SECRET", base_url="https://x/v1", post=post,
                             context={"cards": []}, leads={}, suspects={}, anime=False, craft=[],
                             measured_pacing=None, transcoder=base._transcode, passes=passes,
                             sleep=lambda _s: None, response_text=gvr.response_text,
                             actual_credits=gvr.actual_credits)

    def test_each_pass_calls_and_records_its_model(self):
        urls: list = []

        def post(url, body, headers, timeout):
            urls.append(url)
            data = json.loads(body)
            return 200, json.dumps(_answer(data["contents"][0]["parts"][-1]["text"])).encode()
        out = self.run_passes(post)
        self.assertEqual(sorted(u.rsplit("/", 1)[1] for u in urls),
                         sorted(f"{m}:generateContent" for m in (PRO, PRO, FLASH, PRO)))
        self.assertEqual({p: v["model"] for p, v in out["passes"].items()},
                         {"A": PRO, "B": PRO, "C": FLASH, "D": PRO})
        self.assertAlmostEqual(out["passes"]["A"]["cost_credits"], 10000 * 134e-6 + 2000 * 804e-6, places=3)
        self.assertAlmostEqual(out["passes"]["C"]["cost_credits"], 10000 * 50.25e-6 + 2000 * 251.25e-6, places=3)

    def test_pro_refusal_is_retried_once_on_flash(self):
        calls: list = []

        def post(url, body, headers, timeout):
            calls.append(url)
            data = json.loads(body)
            if PRO in url:
                return 403, b'{"error": {"code": 403, "message": "model unavailable sk-SECRET"}}'
            return 200, json.dumps(_answer(data["contents"][0]["parts"][-1]["text"])).encode()
        out = self.run_passes(post, passes=("A", "C"))
        a = out["passes"]["A"]
        self.assertEqual(a["status"], "OK")
        self.assertEqual(a["model"], FLASH)
        self.assertEqual((a["model_fallback"]["from"], a["model_fallback"]["to"], a["model_fallback"]["http_status"]),
                         (PRO, FLASH, 403))
        self.assertNotIn("sk-SECRET", json.dumps(a))
        self.assertAlmostEqual(a["cost_credits"], 10000 * 50.25e-6 + 2000 * 251.25e-6, places=3)
        self.assertEqual(sum(1 for u in calls if PRO in u), 1)          # one Pro try, one Flash retry
        self.assertNotIn("model_fallback", out["passes"]["C"])

    def test_fallback_answer_failing_too_is_an_error_with_the_record(self):
        def post(url, body, headers, timeout):
            return (404, b'{"error": "no such model"}') if PRO in url else (400, b'{"error": "bad"}')
        out = self.run_passes(post, passes=("D",))
        d = out["passes"]["D"]
        self.assertEqual((d["status"], d["reason"]), ("ERROR", "HTTP_400"))
        self.assertEqual(d["model_fallback"]["http_status"], 404)

    def test_no_fallback_for_rate_limits_or_a_flash_pass(self):
        calls: list = []

        def post(url, body, headers, timeout):
            calls.append(url)
            return (500, b"upstream") if PRO in url else (403, b"policy")
        with mock.patch.object(mp, "RETRY_BACKOFF_S", ()):
            out = self.run_passes(post, passes=("A", "C"))
        self.assertEqual(out["passes"]["A"]["reason"], "HTTP_500")
        self.assertNotIn("model_fallback", out["passes"]["A"])
        self.assertEqual(out["passes"]["C"]["reason"], "HTTP_403")      # already Flash: nothing to fall back to
        self.assertEqual(len(calls), 2)


class RecordTest(base._Base):
    def test_gemini_review_json_records_models_per_pass(self):
        captured: list = []
        self.env["NALU_GEMINI_REVIEW_MODEL_B"] = FLASH
        self.env["NALU_GEMINI_REVIEW_BUDGET"] = "60"
        record = self.run_review(captured)
        saved = json.loads((self.root / "final_reviewer" / "gemini_review.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["models"], {"A": PRO, "B": FLASH, "C": FLASH, "D": PRO})
        self.assertEqual(saved["model"], f"{PRO}+{FLASH}")
        self.assertEqual(saved["max_credits"], 60.0)
        self.assertEqual({p: v["model"] for p, v in saved["passes"].items()},
                         {"A": PRO, "B": FLASH, "C": FLASH, "D": PRO})
        self.assertEqual({p: v["model"] for p, v in saved["budget_plan"].items()},
                         {"A": PRO, "B": FLASH, "C": FLASH, "D": PRO})
        self.assertEqual(record["status"], "OK")


if __name__ == "__main__":
    unittest.main()
