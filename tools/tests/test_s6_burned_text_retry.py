#!/usr/bin/env python3
"""S6 burned-text detection + perturbed retry (line owner 2026-11-19).  Offline: no provider, no credits.

MiniMax-H3 sometimes burns the spoken line into the clip; HopsAPI returns a byte-identical clip for an identical
request, so the engine (1) detects the burn right after a clip lands in S6, before its tail is cut, (2) retries at
most NALU_S6_BURN_RETRY_MAX (2) times with perturbed @Image1 bytes and a retry-indexed prompt sentence, within the
episode budget, (3) keeps the best take and flags QA-BURNED-TEXT when the burn persists, and (4) never turns the
blur cover on by episode number.
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

import numpy as np  # noqa: E402

import burned_text_cover as btc  # noqa: E402
import build_nalu_preproduction as bnp  # noqa: E402
import h3_burn_retry as br  # noqa: E402
import nalu_pipeline as P  # noqa: E402
import nalu_qa_defect_checklist as qadc  # noqa: E402
from tools import h3_provider_prompt_renderer as h3  # noqa: E402
from tools.h3_provider_english_contract import validate_h3_provider_text_boundary  # noqa: E402
from tools.tests.test_h3_director_performance import unit_plan  # noqa: E402
from tools.tests.test_h3_director_prompt_v2 import fixture  # noqa: E402

W, H = 720, 1280


# ----------------------------------------------------------------------------------------------- detection
def _frames(n):
    def reader(_video, fps):
        for i in range(n):
            yield round((i + 0.5) / fps, 3), np.zeros((H, W, 3), dtype=np.uint8)
    return reader


def _ocr(flags, *, glyph=56, x0=260, text="陆王爷", score=0.9):
    """RapidOCR stand-in over the band crop (y 0.55-0.95): one caption box on the frames flagged True."""
    seq = iter(flags)

    def ocr(_crop):
        if not next(seq):
            return []
        y = 0.74 * H - 0.55 * H - glyph / 2
        return [([[x0, y], [x0 + 200, y], [x0 + 200, y + glyph], [x0, y + glyph]], text, score)]
    return ocr


class DetectionTest(unittest.TestCase):
    def _detect(self, flags, **kw):
        return br.detect(Path("clip.mp4"), frames=_frames(len(flags)), ocr=_ocr(flags, **kw))

    def test_positive_two_consecutive_samples(self):
        res = self._detect([False, True, True, True, False])
        self.assertEqual(res["status"], "BURNED")
        self.assertEqual((res["burned_frames"], res["longest_run"], res["frames_sampled"]), (3, 3, 5))
        self.assertAlmostEqual(res["hits"][0]["y_centre"], 0.74, places=2)
        self.assertGreaterEqual(res["hits"][0]["glyph_px_at_720"], 40)

    def test_negative_clean_small_offcentre_lowscore_single_char(self):
        self.assertEqual(self._detect([False] * 6)["status"], "CLEAN")
        self.assertEqual(self._detect([True] * 4, glyph=30)["status"], "CLEAN")       # set dressing size
        self.assertEqual(self._detect([True] * 4, x0=20)["status"], "CLEAN")          # not centred
        self.assertEqual(self._detect([True] * 4, score=0.4)["status"], "CLEAN")      # low confidence
        self.assertEqual(self._detect([True] * 4, text="能")["status"], "CLEAN")       # one character

    def test_one_frame_flicker_is_not_a_burn(self):
        res = self._detect([False, True, False, True, False, False])
        self.assertEqual(res["status"], "CLEAN")
        self.assertEqual((res["burned_frames"], res["longest_run"]), (2, 1))

    def test_latin_counts_and_detector_fails_open(self):
        self.assertEqual(self._detect([True, True], text="Hello")["status"], "BURNED")

        def boom(_video, _fps):
            raise RuntimeError("no decoder")
            yield  # pragma: no cover
        res = br.detect(Path("clip.mp4"), frames=boom, ocr=_ocr([]))
        self.assertEqual(res["status"], "FAIL_OPEN")
        self.assertEqual(br.plan({"attempts": [{}]}, res, retry_max=2, headroom=999, cost=10)["action"], "KEEP")


# ------------------------------------------------------------------------------------- perturbation + prompt
def _jpeg(color=(120, 90, 60)) -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (90, 160), color).save(out, format="JPEG", quality=92)
    return out.getvalue()


class PerturbationTest(unittest.TestCase):
    def test_bytes_differ_per_retry_and_pixels_barely(self):
        from PIL import Image
        data = _jpeg()
        one, n1 = br.perturb_start_frame(data, 1)
        two, n2 = br.perturb_start_frame(data, 2)
        self.assertEqual((n1["status"], n2["status"]), ("PERTURBED", "PERTURBED"))
        self.assertEqual(len({data, one, two}), 3)
        a = np.asarray(Image.open(io.BytesIO(data)).convert("RGB"), dtype=float)
        b = np.asarray(Image.open(io.BytesIO(one)).convert("RGB"), dtype=float)
        self.assertLess(np.abs(a - b).mean(), 1.0)
        self.assertEqual(br.perturb_start_frame(data, 0)[0], data)
        # undecodable JPEG-looking bytes still change (lossless comment segment)
        junk = b"\xff\xd8garbage"
        self.assertNotEqual(br.perturb_start_frame(junk, 1)[0], junk)

    def test_submitter_sends_perturbed_image1_only_on_a_retry(self):
        import tools.submit_giggle_video_manifest_v2 as sub
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "start.jpg"
            ref.write_bytes(_jpeg())
            other = Path(tmp) / "plate.jpg"
            other.write_bytes(_jpeg((10, 20, 30)))
            sent: list[bytes] = []

            def upload(data, **_kw):
                sent.append(data)
                return {"url": f"https://x/{len(sent)}"}
            base = {"task_key": "E99-VU-001", "reference_images": [str(ref), str(other)]}
            with mock.patch.object(sub.hopsapi, "upload_bytes", upload), \
                    mock.patch.object(sub, "_portrait_start_frame", lambda d: (d, {"status": "UNCHANGED"})):
                _, _, notes0 = sub._hopsapi_reference_uploads(dict(base))
                _, _, notes1 = sub._hopsapi_reference_uploads({**base, "h3_burn_retry": 1})
                _, _, notes2 = sub._hopsapi_reference_uploads({**base, "h3_burn_retry": 2})
        self.assertEqual(len({sent[0], sent[2], sent[4]}), 3)       # @Image1: original, retry 1, retry 2
        self.assertEqual(sent[1], sent[3])                            # other references untouched
        self.assertEqual(sent[1], sent[5])
        self.assertNotIn("burn_retry_perturbation", notes0[0])
        self.assertEqual(notes1[0]["burn_retry_perturbation"]["status"], "PERTURBED")
        self.assertNotIn("burn_retry_perturbation", notes1[1])

    def test_prompt_gets_retry_sentence_v1_and_v2_and_nothing_otherwise(self):
        for make in (lambda: unit_plan(stamped=True, performance=None), lambda: fixture()):
            base, _ = h3.render_h3_prompt(*make())
            texts = []
            for n in (1, 2):
                unit, plan = make()
                unit["h3_burn_retry"] = n
                text, receipt = h3.render_h3_prompt(unit, plan)
                self.assertEqual(receipt["h3_burn_retry"]["retry"], n)
                # escalation (2026-11-22): the burn sentence leads the prompt; retry 2 frames the line as heard
                self.assertTrue(text.startswith(br.retry_sentence(n) + "\n"))
                self.assertEqual(br.DIALOGUE_HEARD_MARK in text, n >= br.DIALOGUE_MARK_FROM and "</d>" in base)
                self.assertEqual(br.strip_retry_sentence(text), (base, n))
                self.assertEqual(validate_h3_provider_text_boundary(text, source_id="T")["status"], "PASS")
                texts.append(text)
            self.assertNotEqual(texts[0], texts[1])
            unit, plan = make()
            self.assertEqual(h3.render_h3_prompt(unit, plan)[0], base)  # absent field: byte-identical

    def test_field_transport(self):
        from tools.submit_giggle_video_manifest_v2 import provider_prompt_unit
        with mock.patch("tools.submit_giggle_video_manifest_v2.grouped_sequence_unit", lambda _t: {}):
            self.assertEqual(provider_prompt_unit({"h3_burn_retry": 2}).get("h3_burn_retry"), 2)
            self.assertNotIn("h3_burn_retry", provider_prompt_unit({}))
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "reports").mkdir()
            (out / "reports" / "E99_S6_WAVE_STATE.json").write_text(json.dumps({"s6_burn_retry": {
                "E99-VU-001": {"attempts": [{}, {}]}, "E99-VU-002": {"checks": {}}}}))
            self.assertEqual(bnp.s6_burn_retry_indices(out, "E99"), {"E99-VU-001": 2})
            fin = out / "prompt_batch_finalization"
            fin.mkdir()
            (fin / "U.burn_retry.json").write_text(json.dumps({"status": "PASS", "final_prompt_sha256": "f"}))
            self.assertEqual(bnp.finalization_receipt_for(out, "U", "f").name, "U.burn_retry.json")
            (fin / "U.json").write_text(json.dumps({"status": "PASS", "final_prompt_sha256": "f"}))
            self.assertEqual(bnp.finalization_receipt_for(out, "U", "f").name, "U.json")
            self.assertIsNone(bnp.finalization_receipt_for(out, "U", "other"))

    def test_env_max_and_plan(self):
        self.assertEqual(br.max_retries({}), 2)
        self.assertEqual(br.max_retries({br.ENV_MAX: "0"}), 0)
        self.assertEqual(br.max_retries({br.ENV_MAX: "junk"}), 2)
        burned = {"status": "BURNED"}
        self.assertEqual(br.plan(None, burned, retry_max=2, headroom=100, cost=10),
                         {"action": "RETRY", "reason": "BURNED_TEXT_DETECTED", "retry": 1, "cost": 10})
        self.assertEqual(br.plan({"attempts": [{}, {}]}, burned, retry_max=2, headroom=100, cost=10)["reason"],
                         "RETRY_MAX_REACHED")
        self.assertEqual(br.plan(None, burned, retry_max=0, headroom=100, cost=10)["reason"], "RETRY_DISABLED")
        self.assertEqual(br.plan(None, burned, retry_max=2, headroom=5, cost=10)["reason"], "BUDGET_HEADROOM_SHORT")
        self.assertEqual(br.plan(None, burned, retry_max=2, headroom=None, cost=10)["reason"],
                         "BUDGET_HEADROOM_UNKNOWN")
        self.assertEqual(br.plan(None, burned, retry_max=2, headroom=100, cost=10, owner_accepted=True)["reason"],
                         "LINE_OWNER_ACCEPTED_THIS_CLIP")


# ------------------------------------------------------------------------------------------ S6 wave loop
class _Provider:
    """Paid submit + poll stand-in: every POST of a unit renders the next scripted take after ``polls`` polls."""

    def __init__(self, video: Path, polls: int = 1):
        self.video = video
        self.polls_needed = polls
        self.in_flight: dict[str, int] = {}
        self.posts: list[str] = []
        self.post_tail_state: dict[str, bool] = {}

    def body(self, _ctx, *, ready_units=None, run_qa=True, final_pass=False):
        units = list(ready_units or [])
        if final_pass:
            return P.StageResult(P.PASS)
        new = [u for u in units if u not in self.in_flight and not (self.video / f"{u}.mp4").is_file()]
        for u in new:
            self.in_flight[u] = self.polls_needed
            self.posts.append(u)
            # which predecessor tail existed when this unit was POSTed (it would be its start frame)
            self.post_tail_state[f"{u}#{self.posts.count(u)}"] = True
        for u in list(self.in_flight):
            if u in units:
                self.in_flight[u] -= 1
                if self.in_flight[u] <= 0:
                    del self.in_flight[u]
                    (self.video / f"{u}.mp4").write_bytes(f"{u}-take{self.posts.count(u)}".encode())
        res = P.StageResult(P.PASS)
        if not all((self.video / f"{u}.mp4").is_file() for u in units):
            res.status = P.BLOCKED
            res.blockers.append("VIDEO_NOT_ALL_COMPLETED")
        if new:
            res.details["posted_task_keys"] = new
        return res


class _Harness:
    def __init__(self, tmp: Path, deps, burned: dict[str, int], *, headroom=1000, polls=1):
        """``burned``: clip content -> burned frames (absent = clean)."""
        self.tmp = tmp
        self.video = tmp / "video"
        self.preprod = tmp / "preproduction"
        self.reports = self.preprod / "reports"
        for d in (self.video, self.reports):
            d.mkdir(parents=True, exist_ok=True)
        self.tails = self.preprod / "real_final_frames"
        self.provider = _Provider(self.video, polls)
        self.said: list[str] = []
        self.extracted_from: list[str] = []
        self.detected: list[str] = []
        self.budget_calls = 0
        self.ctx = SimpleNamespace(
            episode="E99", dry=False, paid_enabled=True, say=self.said.append, run_id="RUN",
            budget_check=self._budget,
            p=SimpleNamespace(preprod=self.preprod, video_media=self.video, preprod_reports=self.reports,
                              video_submit=tmp / "submit.json", video_remote_status=tmp / "status.json",
                              video_transaction=tmp / "tx.json", contract=tmp / "contract.json"))
        self.headroom = headroom
        self.burned = burned
        deps = list(deps)

        def extract(_ctx, uid):
            clip = self.video / f"{uid}.mp4"
            if not clip.is_file():
                return {"unit_id": uid, "status": "SOURCE_MISSING"}
            self.tails.mkdir(parents=True, exist_ok=True)
            dst = self.tails / f"{uid}.png"
            marker = dst.with_suffix(".source.sha256")
            sha = P.sha256_file(clip)
            if dst.is_file() and marker.is_file() and marker.read_text().strip() == sha:
                return {"unit_id": uid, "status": "ALREADY_PRESENT"}
            dst.write_bytes(clip.read_bytes())
            marker.write_text(sha + "\n")
            self.extracted_from.append(clip.read_text())
            return {"unit_id": uid, "status": "EXTRACTED"}

        def detect(clip, **_kw):
            content = Path(clip).read_text()
            self.detected.append(content)
            frames = self.burned.get(content, 0)
            return {"status": "BURNED" if frames else "CLEAN", "frames_sampled": 18, "burned_frames": frames,
                    "longest_run": frames, "elapsed_ms": 1.0, "hits": []}

        def park_stale(_ctx, unit_ids):  # the real rule: a tail whose clip is gone is parked
            for uid in unit_ids:
                tail = self.tails / f"{uid}.png"
                if tail.is_file() and not (self.video / f"{uid}.mp4").is_file():
                    tail.unlink()
            return []

        self.patches = [
            mock.patch.object(P, "ENGINE", tmp / "engine"),
            mock.patch.object(P, "previs_gate", lambda _c, _s: {}),
            mock.patch.object(P, "unit_dependency_order", lambda _c: deps),
            mock.patch.object(P, "park_stale_real_final_frames", park_stale),
            mock.patch.object(P, "redo_switch_start_frames", lambda _c: []),
            mock.patch.object(P, "materialise_derived_keyframes", lambda _c: []),
            mock.patch.object(P, "own_keyframes_needed", lambda _c: []),
            mock.patch.object(P, "derived_units_pending_q1", lambda _c: []),
            mock.patch.object(P, "tail_sourced_units", lambda _c: {}),
            mock.patch.object(P, "release_unposted_waves", lambda _c, _s: []),
            mock.patch.object(P, "_stage_s6_body", self._body),
            mock.patch.object(P, "_s6_live_bound_wave", lambda _c, _u: None),
            mock.patch.object(P, "extract_real_final_frame", extract),
            mock.patch.object(P, "_s6_sleep", lambda _s: None),
            mock.patch.object(P, "episode_video_model", lambda _e: "MiniMax-H3"),
            mock.patch.object(P, "episode_video_resolution", lambda _e: "480p"),
            mock.patch.object(P, "video_task_credits", lambda *_a, **_k: 40),
            mock.patch.object(br, "detect", detect),
        ]

    def _body(self, ctx, **kw):
        units = list(kw.get("ready_units") or [])
        # a successor POST records which predecessor take its tail came from (the start frame it would bind)
        for uid, prev, needs in P.unit_dependency_order(ctx):
            if uid in units and needs and prev and not (self.video / f"{uid}.mp4").is_file() \
                    and uid not in self.provider.in_flight:
                tail = self.tails / f"{prev}.png"
                self.bound_tails.append((uid, tail.read_text() if tail.is_file() else None))
        return self.provider.body(ctx, **kw)

    def _budget(self, _planned, *, label):
        self.budget_calls += 1
        return {"budget_verdict": {"headroom_credits": self.headroom}}

    def __enter__(self):
        self.bound_tails: list[tuple[str, str | None]] = []
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        return False

    def state(self):
        return json.loads((self.reports / "E99_S6_WAVE_STATE.json").read_text())

    def run(self, passes=6):
        res = None
        for _ in range(passes):
            res = P.stage_s6(self.ctx)
            if res.status == P.PASS:
                break
        return res


CHAIN = [("A1", None, False), ("A2", "A1", True)]


class WaveLoopTest(unittest.TestCase):
    def test_burned_take_retried_and_successor_binds_only_the_clean_take(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {br.ENV_MAX: "2"}):
            with _Harness(Path(tmp), CHAIN, {"A1-take1": 7}) as h:
                h.run()
                self.assertEqual(h.provider.posts, ["A1", "A1", "A2"])
                self.assertEqual((h.video / "A1.mp4").read_text(), "A1-take2")
                # the burned take never became a tail and A2 was POSTed on the clean take's tail
                self.assertNotIn("A1-take1", h.extracted_from)
                self.assertEqual(h.bound_tails, [("A2", "A1-take2")])
                rec = h.state()["s6_burn_retry"]["A1"]
                self.assertEqual(rec["status"], "RESOLVED")
                self.assertFalse(rec["burned_text_unresolved"])
                self.assertEqual(len(rec["attempts"]), 1)
                self.assertTrue(rec["attempts"][0]["submitted_at"])
                self.assertTrue(Path(rec["attempts"][0]["parked_clip"]).is_file())
                self.assertIn("_superseded_RUN_burn_retry1", rec["attempts"][0]["parked_clip"])
                said = "\n".join(h.said)
                for tag in ("S6_BURN_DETECTED unit=A1 frames=7/18 retry=0/2", "S6_BURN_RETRY_SUBMITTED unit=A1 retry=1/2",
                            "S6_BURN_RESOLVED unit=A1"):
                    self.assertIn(tag, said)

    def test_max_two_retries_then_best_take_kept_and_qa_flagged(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {br.ENV_MAX: "2"}):
            burned = {"A1-take1": 5, "A1-take2": 2, "A1-take3": 4}
            with _Harness(Path(tmp), CHAIN, burned) as h:
                h.run(passes=8)
                self.assertEqual(h.provider.posts.count("A1"), 3)       # 1 take + 2 retries, never more
                self.assertEqual((h.video / "A1.mp4").read_text(), "A1-take2")   # fewest burned frames
                self.assertEqual(h.bound_tails, [("A2", "A1-take2")])
                rec = h.state()["s6_burn_retry"]["A1"]
                self.assertEqual((rec["status"], rec["unresolved_reason"]), ("UNRESOLVED", "RETRY_MAX_REACHED"))
                self.assertTrue(rec[br.UNRESOLVED_FLAG])
                self.assertEqual(rec["kept_take_burned_frames"], 2)
                self.assertIn("S6_BURN_UNRESOLVED unit=A1 retry=2/2 reason=RETRY_MAX_REACHED", "\n".join(h.said))
                # S8 QA-BURNED-TEXT surfaces it
                measured = qadc.measure(shots=[], s6_wave_state_path=h.reports / "E99_S6_WAVE_STATE.json")
                self.assertEqual([r["unit_id"] for r in measured["s6_burn_unresolved"]["units"]], ["A1"])
                record = qadc.build_record({}, measured, episode="E99")
                self.assertEqual(record["items"]["QA-BURNED-TEXT"]["status"], "MEASURED_FLAG_UNREVIEWED")
                self.assertIn("A1", "\n".join(qadc.checkpoint_lines(record)))
                lines = P.qa_defect_checkpoint_lines(SimpleNamespace(
                    episode="E99", p=SimpleNamespace(assembly=Path(tmp) / "asm", identity=Path(tmp) / "id",
                                                     preprod_reports=h.reports)))
                self.assertIn("QA-BURNED-TEXT", "\n".join(lines))

    def test_budget_cap_blocks_the_retry_and_records_it(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {br.ENV_MAX: "2"}):
            with _Harness(Path(tmp), CHAIN, {"A1-take1": 6}, headroom=10) as h:
                h.run()
                self.assertEqual(h.provider.posts, ["A1", "A2"])
                rec = h.state()["s6_burn_retry"]["A1"]
                self.assertEqual((rec["status"], rec["unresolved_reason"]), ("UNRESOLVED", "BUDGET_HEADROOM_SHORT"))
                self.assertEqual(rec.get("attempts") or [], [])
                self.assertGreaterEqual(h.budget_calls, 1)
                self.assertEqual(h.bound_tails, [("A2", "A1-take1")])

    def test_env_zero_disables_retries(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.dict(os.environ, {br.ENV_MAX: "0"}):
            with _Harness(Path(tmp), CHAIN, {"A1-take1": 6}) as h:
                h.run()
                self.assertEqual(h.provider.posts, ["A1", "A2"])
                self.assertEqual(h.budget_calls, 0)
                self.assertEqual(h.state()["s6_burn_retry"]["A1"]["unresolved_reason"], "RETRY_DISABLED")

    def test_clip_whose_tail_is_already_current_is_never_rechecked(self):
        with tempfile.TemporaryDirectory() as tmp:
            with _Harness(Path(tmp), CHAIN, {"A1-old": 9}) as h:
                (h.video / "A1.mp4").write_text("A1-old")
                h.tails.mkdir(parents=True)
                (h.tails / "A1.png").write_text("A1-old")
                (h.tails / "A1.source.sha256").write_text(P.sha256_file(h.video / "A1.mp4") + "\n")
                self.assertEqual(P.s6_burn_check_landed(h.ctx, ["A1"]), [])
                self.assertEqual(h.detected, [])


class FinalizationReceiptTest(unittest.TestCase):
    def _ctx(self, tmp: Path, final_text: str, planned_text: str):
        pre = tmp / "preproduction"
        (pre / "reports").mkdir(parents=True)
        prompt = tmp / "final.txt"
        prompt.write_text(final_text, encoding="utf-8")
        tx = tmp / "tx.json"
        tx.write_text(json.dumps({"tasks": [{"unit_id": "U1", "task_key": "U1", "prompt_file": str(prompt)}]}))
        (pre / "reports" / "E99_S6_WAVE_STATE.json").write_text(json.dumps(
            {"s6_burn_retry": {"U1": {"attempts": [{"retry": 1}]}}}))
        digest = tmp / "digest.json"
        digest.write_text("{}")
        row = {"unit_id": "U1", "status": "CHANGED", "planned_sha256": P.sha256_text(planned_text),
               "final_sha256": P.sha256_file(prompt)}
        ctx = SimpleNamespace(episode="E99", p=SimpleNamespace(preprod=pre, preprod_reports=pre / "reports",
                                                               video_transaction=tx))
        return ctx, {"rows": [row]}, digest, tx

    def test_engine_receipt_only_for_the_exact_sentence_delta(self):
        base = "References:\nline one\n"
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(P, "ENGINE", Path(tmp) / "engine"):
            ctx, report, digest, tx = self._ctx(Path(tmp), br.apply_retry_sentence(base, 1), base)
            done = P.s6_burn_retry_finalization_receipts(ctx, ["U1"], report, digest)
            self.assertEqual(done["U1"]["base_authority"], "PLANNED_PROMPT")
            receipt = json.loads(Path(done["U1"]["receipt"]).read_text())
            self.assertEqual((receipt["status"], receipt["scope"], receipt["final_prompt_sha256"]),
                             ("PASS", "INCREMENTAL_EXACT_MATERIALIZATION_QA", report["rows"][0]["final_sha256"]))
            self.assertIn("prompt_batch_finalization", json.loads(tx.read_text())["tasks"][0])
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(P, "ENGINE", Path(tmp) / "engine"):
            ctx, report, digest, tx = self._ctx(Path(tmp), br.apply_retry_sentence(base + "extra\n", 1), base)
            self.assertEqual(P.s6_burn_retry_finalization_receipts(ctx, ["U1"], report, digest), {})


class CoverOffByDefaultTest(unittest.TestCase):
    def test_cover_never_enabled_by_episode_number(self):
        for ep in ("E12", "E13", "E14"):
            self.assertFalse(btc.active({}, episode=ep))
        self.assertTrue(btc.active({btc.FIELD: btc.POLICY_ID}, episode="E12"))
        self.assertNotIn("enabled_episodes", btc.policy())


if __name__ == "__main__":
    unittest.main()
