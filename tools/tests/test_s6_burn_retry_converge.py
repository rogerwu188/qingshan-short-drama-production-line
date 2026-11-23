#!/usr/bin/env python3
"""S6 burned-text retries that actually re-render (E23 device 1101, 2026-11-22).  Offline: no provider, no credits.

Five units burned the spoken line on every take with near-identical burned-frame counts (VU-004 11/11/11, VU-006
14/14/14).  The requests did differ (perturbed @Image1 bytes, retry sentence), but a paid lab probe reproduced the
cause: H3 renders a near-identical clip for a near-identical request -- the one-pixel nudge (mean frame difference
3.7/255 vs the base take) and the tail retry sentence (2.4/255) both burned the same line again.  So:

* every take records the content fingerprint of the request that rendered it (prompt sha + every SENT reference
  sha) and the returned clip sha; an identical request says S6_BURN_RETRY_SAME_REQUEST, a byte-identical clip
  S6_BURN_RETRY_SAME_RENDER (and is no longer skipped as "already measured");
* the escalation ladder changes the request materially: the burn sentence leads the prompt, retry 2 frames each
  dialogue literal as heard speech and sends the identity sheets as their front-view crops, and @Image1 gets a
  1.5 % / 3 % scale jitter instead of a one-pixel nudge.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
TOOLS = REPO / "lines" / "nalu" / "runtime" / "tools"
for _p in (TOOLS, REPO / "tools", REPO):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import final_fix_round as ffr  # noqa: E402
import h3_burn_retry as br  # noqa: E402
import nalu_pipeline as P  # noqa: E402
import tools.submit_giggle_video_manifest_v2 as sub  # noqa: E402
from tools.h3_provider_english_contract import validate_h3_provider_text_boundary  # noqa: E402

PROMPT = ("TEXT-FREE FRAME: no captions.\nThe boy says exactly once <d>[Chinese] 你觉得我会看上你吗</d>.\n"
          "Offscreen voice says exactly once <d>[Chinese] 沐云儿</d>; do not show the speaker.\n")


def _jpeg(size=(720, 1280), seed=0) -> bytes:
    from PIL import Image
    image = Image.new("RGB", size, (120, 80, 60))
    for x in range(0, size[0], 24):
        for y in range(0, size[1], 24):
            image.putpixel((x, y), ((x + seed) % 255, y % 255, 9))
    out = io.BytesIO()
    image.save(out, format="JPEG", quality=95)
    return out.getvalue()


def _sent(task: dict) -> tuple[list[bytes], list[dict]]:
    sent: list[bytes] = []

    def upload(data, **_kw):
        sent.append(data)
        return {"url": f"https://x/{len(sent)}", "sha256": hashlib.sha256(data).hexdigest()}
    with mock.patch.object(sub.hopsapi, "upload_bytes", upload), \
            mock.patch.object(sub, "_portrait_start_frame", lambda d: (d, {"status": "UNCHANGED"})), \
            mock.patch.object(sub, "_sheet_front_view", lambda d: (d + b"front-crop", {"status": "CROPPED"})):
        _, _, notes = sub._hopsapi_reference_uploads(task)
    return sent, notes


def _fingerprint(prompt: str, sent: list[bytes]) -> dict:
    return br.request_content_fingerprint(prompt=prompt,
                                          sent_reference_sha256=[hashlib.sha256(b).hexdigest() for b in sent],
                                          sent_audio_sha256=[], duration=6, resolution="768p", aspect_ratio="9:16",
                                          model="MiniMax-H3")


class RequestFingerprintTest(unittest.TestCase):
    def test_request_fingerprint_changes_per_retry_prompt_and_reference_shas(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = Path(tmp) / "start.jpg"
            start.write_bytes(_jpeg())
            plate = Path(tmp) / "plate.jpg"
            plate.write_bytes(_jpeg(seed=7))
            sheet = Path(tmp) / f"CHAR-A{__import__('h3_reference_sheet_guard').SHEET_MARK}x.png"
            sheet.write_bytes(_jpeg(seed=11))
            base = {"task_key": "E23-VU-004", "reference_images": [str(start), str(plate), str(sheet)]}
            rows = []
            for n in (0, 1, 2):
                sent, notes = _sent({**base, **({"h3_burn_retry": n} if n else {})})
                rows.append((_fingerprint(br.apply_retry_sentence(PROMPT, n), sent), sent, notes))
        digests = {r[0]["digest"] for r in rows}
        self.assertEqual(len(digests), 3)                                   # every retry is a new request
        d1 = br.request_delta(rows[0][0], rows[1][0])
        self.assertEqual(d1["status"], "CHANGED")
        self.assertEqual(d1["changed"], ["prompt_sha256", "image1"])         # retry 1: prompt + @Image1 only
        d2 = br.request_delta(rows[1][0], rows[2][0])
        self.assertEqual(d2["changed"], ["prompt_sha256", "image1", "image3"])  # retry 2: + the sheet's face crop
        self.assertEqual(rows[0][1][1], rows[2][1][1])                      # a plain plate is never touched
        self.assertEqual(rows[1][2][0]["burn_retry_perturbation"]["method"], "CROP_SCALE_1.5PCT_JPEG_Q88")
        self.assertEqual(rows[2][2][0]["burn_retry_perturbation"]["method"], "CROP_SCALE_3PCT_JPEG_Q83")
        self.assertEqual(rows[2][2][2]["reference_sheet_crop"]["status"], "CROPPED")
        self.assertNotIn("reference_sheet_crop", rows[1][2][2])

    def test_final_fix_redo_starts_at_the_strongest_s6_step(self):
        with tempfile.TemporaryDirectory() as tmp:
            start = Path(tmp) / "start.jpg"
            start.write_bytes(_jpeg())
            fix = {"round": 1, "kind": "BURNED_TEXT", "sentence": "s"}
            _, notes = _sent({"task_key": "U", "reference_images": [str(start)], "h3_burn_retry": 2,
                              "h3_final_fix": fix})
            _, notes_r1 = _sent({"task_key": "U", "reference_images": [str(start)], "h3_burn_retry": 2,
                                 "h3_final_fix": {**fix, "burn_retry": 1}})
        self.assertEqual(notes[0]["burn_retry_perturbation"]["method"], "CROP_SCALE_3PCT_JPEG_Q83")
        self.assertEqual(notes_r1[0]["burn_retry_perturbation"]["method"], "CROP_SCALE_1PCT_JPEG_Q86")

    def test_same_request_detection_and_transaction_fingerprints(self):
        a = _fingerprint(PROMPT, [b"one", b"two"])
        self.assertEqual(br.request_delta(a, dict(a)), {"status": "SAME", "changed": []})
        self.assertEqual(br.request_delta(None, a)["status"], "UNKNOWN")
        # recorded by the submitter (2026-11-22) or rebuilt from an older transaction's sent shas
        self.assertEqual(br.request_fingerprint({"request_content_fingerprint": a})["digest"], a["digest"])
        old = {"prompt_sha256": a["prompt_sha256"], "sent_reference_sha256": a["sent_reference_sha256"],
               "sent_audio_sha256": [], "model": "MiniMax-H3",
               "provider_request_input": {"duration": 6, "resolution": "768p", "aspect_ratio": "9:16"}}
        self.assertEqual(br.request_fingerprint(old)["digest"], a["digest"])
        self.assertIsNone(br.request_fingerprint({"prompt_sha256": "x"}))
        # upload URLs are not part of the fingerprint: the same bytes behind a new URL render the same clip
        self.assertNotIn("uploaded_reference_urls", br.FINGERPRINT_FIELDS)


class EscalationLadderTest(unittest.TestCase):
    def test_prompt_ladder_round_trips_and_stays_inside_the_h3_boundary(self):
        one = br.apply_retry_sentence(PROMPT, 1)
        two = br.apply_retry_sentence(PROMPT, 2)
        self.assertTrue(one.startswith(br.RETRY_SENTENCES[1] + "\n"))
        self.assertNotIn(br.DIALOGUE_HEARD_MARK, one)
        self.assertTrue(two.startswith(br.RETRY_SENTENCES[2] + "\n"))
        self.assertEqual(two.count("</d>" + br.DIALOGUE_HEARD_MARK), 2)    # every literal, never inside it
        for text, n in ((one, 1), (two, 2)):
            self.assertEqual(br.strip_retry_sentence(text), (PROMPT, n))
            self.assertEqual(validate_h3_provider_text_boundary(text, source_id="T")["status"], "PASS")
        self.assertEqual(br.apply_retry_sentence(PROMPT, 0), PROMPT)
        self.assertEqual(br.apply_retry_sentence(two, 2), two)              # idempotent
        # an engine before 2026-11-22 appended the sentence: still recognised (episodes in flight)
        legacy = PROMPT.rstrip("\n") + "\n" + br.RETRY_SENTENCES[1] + "\n"
        self.assertEqual(br.strip_retry_sentence(legacy), (PROMPT, 1))
        self.assertNotRegex(br.DIALOGUE_HEARD_MARK, r"\d|[A-Z]{3,}")

    def test_ladder_steps_and_image_jitter(self):
        self.assertEqual(br.s6_escalation(0), {"retry": 0})
        self.assertEqual(br.s6_escalation(1), {"retry": 1, "prompt": "LEAD_SENTENCE",
                                               "image1": "CROP_SCALE_1.5PCT_JPEG_Q88", "sheet_front_crop": False})
        self.assertEqual(br.s6_escalation(2)["prompt"], "LEAD_SENTENCE+DIALOGUE_HEARD_MARK")
        self.assertTrue(br.s6_escalation(2)["sheet_front_crop"])
        from PIL import Image
        data = _jpeg()
        one, n1 = br.perturb_start_frame_strong(data, 1, 1, br.S6_STEPS)
        two, n2 = br.perturb_start_frame_strong(data, 2, 2, br.S6_STEPS)
        self.assertEqual(len({data, one, two}), 3)
        for blob, note, frac in ((one, n1, 0.015), (two, n2, 0.03)):
            self.assertEqual(Image.open(io.BytesIO(blob)).size, (720, 1280))   # framing kept
            x0, _, x1, _ = note["crop_box"]
            self.assertLessEqual(720 - (x1 - x0), round(720 * frac) + 1)


class SameRenderWaveTest(unittest.TestCase):
    """The S6 wave loop with a provider that renders the SAME clip for every retry."""

    def _run(self, *, same_request: bool):
        from tools.tests import test_s6_burned_text_retry as T
        CHAIN, _Harness = T.CHAIN, T._Harness
        pipeline = T.P  # the module object the harness patches (a full run may hold a re-imported copy)
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {br.ENV_MAX: "2"}):
            with _Harness(Path(tmp), CHAIN, {"A1-same": 11}) as h:
                body = h.provider.body

                def same(ctx, **kw):
                    res = body(ctx, **kw)
                    clip = h.video / "A1.mp4"
                    if clip.is_file() and clip.read_text().startswith("A1-take"):
                        clip.write_text("A1-same")
                    return res
                h.provider.body = same
                fp = _fingerprint(PROMPT, [b"img"])
                calls = iter(range(100))

                def take_request(_ctx, _uid):
                    n = next(calls)
                    return fp if same_request else _fingerprint(PROMPT + str(n), [b"img%d" % n])
                with mock.patch.object(pipeline, "_s6_take_request", take_request):
                    h.run(passes=10)
                return h, h.state()["s6_burn_retry"]["A1"]

    def test_byte_identical_retry_is_measured_flagged_and_capped(self):
        h, rec = self._run(same_request=False)
        self.assertEqual(h.provider.posts.count("A1"), 3)                  # never stuck, never more than 2 retries
        self.assertEqual((rec["status"], rec["unresolved_reason"]), ("UNRESOLVED", "RETRY_MAX_REACHED"))
        said = "\n".join(h.said)
        self.assertIn("S6_BURN_RETRY_SAME_RENDER unit=A1 retry=1", said)
        self.assertIn("S6_BURN_RETRY_SAME_RENDER unit=A1 retry=2", said)
        self.assertIn("S6_BURN_RETRY_SAME_BURN unit=A1 retry=1 frames=11", said)
        self.assertNotIn("S6_BURN_RETRY_SAME_REQUEST", said)
        for attempt in rec["attempts"]:
            self.assertTrue(attempt["landed_clip_sha256"])
            self.assertTrue(attempt["same_render"])
            self.assertEqual(attempt["request_delta"]["status"], "CHANGED")
        self.assertTrue(all(t.get("request") for t in rec["takes"]))

    def test_identical_request_says_same_request(self):
        h, rec = self._run(same_request=True)
        said = "\n".join(h.said)
        self.assertIn("S6_BURN_RETRY_SAME_REQUEST unit=A1 retry=1", said)
        self.assertTrue(rec["attempts"][0]["same_request"])
        self.assertEqual(rec["attempts"][0]["request_delta"], {"status": "SAME", "changed": []})


class TakeRequestLookupTest(unittest.TestCase):
    def test_newest_bound_transaction_of_the_unit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "store"
            store.mkdir()
            fp_old = _fingerprint("old", [b"a"])
            fp_new = _fingerprint("new", [b"b"])
            rows = {"U1__aaaa.json": {"state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t1",
                                      "response_recorded_at": "2026-11-22T01:00:00Z",
                                      "request_content_fingerprint": fp_old},
                    "U1__bbbb.json": {"state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t2",
                                      "response_recorded_at": "2026-11-22T02:00:00Z",
                                      "request_content_fingerprint": fp_new,
                                      "reference_encoding_notes": [{"burn_retry_perturbation": {
                                          "method": "CROP_SCALE_1.5PCT_JPEG_Q88"}}]},
                    "U1__cccc.json": {"state": "VERIFIED_ZERO_RETRYABLE", "task_id": None,
                                      "response_recorded_at": "2026-11-22T03:00:00Z"},
                    "U2__dddd.json": {"state": "SUBMITTED_TASK_ID_BOUND", "task_id": "t9",
                                      "response_recorded_at": "2026-11-22T04:00:00Z",
                                      "request_content_fingerprint": fp_old}}
            for name, row in rows.items():
                (store / name).write_text(json.dumps(row))
            with mock.patch.object(P, "video_store_dir", lambda _e: store):
                got = P._s6_take_request(SimpleNamespace(episode="E23"), "U1")
                self.assertIsNone(P._s6_take_request(SimpleNamespace(episode="E23"), "U9"))
        self.assertEqual((got["digest"], got["task_id"], got["perturbation"]),
                         (fp_new["digest"], "t2", "CROP_SCALE_1.5PCT_JPEG_Q88"))


class FinalFixBudgetCapTest(unittest.TestCase):
    def test_e23_cap_is_the_round_cap_not_the_episode_headroom(self):
        """E23: round cap 45, planned redos 31 -> 14 left; one 11-credit retry leaves 3, so the next burned redo is
        FINAL_FIX_BUDGET_CAP although the episode headroom (1341) is large -- the round cap is the limit."""
        record = {"paid": {"planned_credits": 31}}
        self.assertEqual(ffr.round_budget_left(record, {"units": {}}, 45), 14.0)
        first = ffr.plan_burn_retry({}, {"status": "BURNED"}, retry_max=2, budget_left=14.0, headroom=1341, cost=11)
        self.assertEqual(first["action"], "RETRY")
        left = ffr.round_budget_left(record, {"units": {"VU-006": {"burn_retries": [{"cost": 11}]}}}, 45)
        self.assertEqual(left, 3.0)
        capped = ffr.plan_burn_retry({}, {"status": "BURNED"}, retry_max=2, budget_left=left, headroom=1341, cost=11)
        self.assertEqual((capped["reason"], capped["budget_left"], capped["cost"]), ("FINAL_FIX_BUDGET_CAP", 3.0, 11))


if __name__ == "__main__":
    unittest.main()
