#!/usr/bin/env python3
"""Final fix round v7 burn escalation (2026-11-27, device 1101 E29: VU-013 still burned after the redo and its retries
held the whole episode RELEASE_HELD:BURN_UNRESOLVED).  Offline: no provider, no credits.

Covers: one escalation take per still-burned unit with a clean Img2Img first frame (cap per episode, headroom), the
compile carrying the frame, the submitter sending it as @Image1 (sha-checked, else the old perturbation), the clean
frame tool's durable single-image path, a kept take burned only inside our subtitle band reaching the S7 strict
burned-line check, and objective_defects accepting it only on ACCEPT_CORRECT.
"""
from __future__ import annotations

import hashlib
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

import build_nalu_preproduction as bnp  # noqa: E402
import burn_clean_start_frame as bcf  # noqa: E402
import final_fix_round as ffr  # noqa: E402
import h3_burn_retry as br  # noqa: E402
import nalu_pipeline as P  # noqa: E402


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class PlanTest(unittest.TestCase):
    def test_plan_burn_escalation(self):
        plan = lambda rec=None, **kw: ffr.plan_burn_escalation(  # noqa: E731
            rec, {"status": kw.pop("status", "BURNED")}, **{"cap": 15, "spent": 0, "video_cost": 10, "image_cost": 2,
                                                             "headroom": 500, **kw})
        self.assertEqual((plan()["action"], plan()["retry"], plan()["cost"]), ("ESCALATE", 3, 12))
        self.assertEqual(plan(status="CLEAN")["reason"], "NOT_BURNED")
        self.assertEqual(plan({"burn_escalation": {"status": "SKIPPED"}})["reason"], "ALREADY_ESCALATED")
        self.assertEqual(plan(cap=0)["reason"], "ESCALATION_DISABLED")
        self.assertEqual(plan(spent=4)["reason"], "ESCALATION_CAP")           # 15 - 4 = 11 < 12
        self.assertEqual(plan(headroom=None)["reason"], "BUDGET_HEADROOM_UNKNOWN")
        self.assertEqual(plan(headroom=11)["reason"], "BUDGET_HEADROOM_SHORT")
        self.assertEqual(ffr.burn_escalation_cap({ffr.BURN_ESCALATION_ENV: "0"}), 0)
        self.assertEqual(ffr.burn_escalation_cap({}), 15)
        self.assertEqual(ffr.burn_escalation_spent({"units": {"A": {"burn_escalation": {"planned_credits": 12}},
                                                              "B": {"burn_escalation": {"status": "SKIPPED"}}}}), 12)

    def test_confined_band_and_sentence(self):
        band = br.SUBTITLE_BAND
        self.assertTrue(ffr.confined_band([{"y_centre": 0.8}, {"y_centre": 0.7}], band))
        self.assertFalse(ffr.confined_band([{"y_centre": 0.8}, {"y_centre": 0.2}], band))  # a sign on the set too
        self.assertFalse(ffr.confined_band([], band))
        self.assertEqual(ffr.burn_retry_sentence(ffr.BURN_ESCALATION_RETRY), ffr.BURN_RETRY_SENTENCES[3])
        texts = [ffr.SENTENCES["BURNED_TEXT"], *ffr.BURN_RETRY_SENTENCES.values(), *br.RETRY_SENTENCES.values()]
        self.assertEqual(len(set(texts)), len(texts))


class EscalationLoopTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.root = root
        self.p = SimpleNamespace(video_media=root / "video", preprod=root / "pre", preprod_reports=root / "reports",
                                 assembly=root / "assembly", video_transaction=root / "pre" / "tx.json",
                                 grouping_plan=root / "pre" / "g.json", editorial=root / "pre" / "e.json")
        for d in (self.p.video_media, self.p.preprod, self.p.preprod_reports, self.p.assembly / "final_qa"):
            d.mkdir(parents=True, exist_ok=True)
        self.start = root / "pre" / "kf_U1.png"
        self.start.write_bytes(b"start-frame")
        (root / "pre" / "kf_U3.png").write_bytes(b"start-frame-3")
        P.write_json(self.p.video_transaction, {"tasks": [
            {"unit_id": u, "duration_seconds": 6, "reference_images": [str(root / "pre" / f"kf_{u}.png")],
             "dialogue_lines": ["别再琢磨了。"], "reference_audio_urls": ["https://cdn/voice.mp3"],
             **({"h3_prompt_format": "OFFICIAL_REF_V1"} if u == "U1" else {})} for u in ("U1", "U3")]})
        self.said: list[str] = []
        self.ctx = SimpleNamespace(episode="E29", p=self.p, run_id="RUN", say=self.said.append, dry=False,
                                   budget_check=lambda _x, label: {"budget_verdict": {"headroom_credits": 500}})
        self.burned: dict[str, int] = {}
        self.hits: dict[str, list] = {}
        self.frames: list[str] = []

        def detect(clip, **_kw):
            content = Path(clip).read_text()
            frames = self.burned.get(content, 0)
            return {"status": "BURNED" if frames else "CLEAN", "frames_sampled": 24, "burned_frames": frames,
                    "longest_run": frames, "elapsed_ms": 1.0, "hits": self.hits.get(content, [])}

        def clean_frame(ctx, uid, source):
            self.frames.append(uid)
            out = self.root / "pre" / "burn_clean_start_frames" / f"E29_{uid}_CLEAN_START_FRAME.png"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(b"clean-" + uid.encode())
            return {"status": "READY", "path": str(out), "sha256": sha(out), "task_id": "t1", "cost_credits": 1.4,
                    "text_check": {"status": "CLEAN"}}

        self.patches = [mock.patch.object(br, "detect", detect),
                        mock.patch.object(P, "episode_video_model", lambda _e: "MiniMax-H3"),
                        mock.patch.object(P, "episode_video_resolution", lambda _e: "768p"),
                        mock.patch.object(P, "video_task_credits", lambda *_a, **_k: 10),
                        mock.patch.object(P, "image_batch_credits", lambda _c, _n: 2),
                        mock.patch.object(P, "s6_final_fix_clean_start_frame", clean_frame),
                        mock.patch.dict(os.environ, {}, clear=False)]
        for patch in self.patches:
            patch.start()
        for name in ("NALU_FINAL_FIX_BUDGET_CREDITS", ffr.FIX_BURN_RETRY_ENV, ffr.BURN_ESCALATION_ENV):
            os.environ.pop(name, None)
        ffr.write_record(self.p.assembly / "final_qa" / ffr.RECORD_NAME,
                         {"status": "S6_REDO_PENDING", "paid": {"planned_credits": 20, "selected": []}})
        P.write_json(P.final_fix_redo_path(self.ctx), {"schema": ffr.REDO_SCHEMA, "units": {
            uid: {"round": 1, "kind": "BURNED_TEXT", "kinds": ["BURNED_TEXT"],
                  "sentence": ffr.redo_sentence(["BURNED_TEXT"]), "status": "PARKED", "parked_clip_sha256": "orig"}
            for uid in ("U1", "U3")}})

    def tearDown(self):
        for patch in reversed(self.patches):
            patch.stop()
        self.tmp.cleanup()

    def land(self, uid, content):
        (self.p.video_media / f"{uid}.mp4").write_text(content)
        return P.s6_burn_check_landed(self.ctx, [uid])

    def state(self):
        return json.loads(P.final_fix_redo_path(self.ctx).read_text(encoding="utf-8"))["units"]

    def test_budget_capped_unit_escalates_once_with_a_clean_frame_and_resolves(self):
        # E29 shape: the round budget leaves no retry (FINAL_FIX_BUDGET_CAP) -> the escalation has its own cap
        os.environ["NALU_FINAL_FIX_BUDGET_CREDITS"] = "25"
        self.burned = {"U1-redo": 5}
        row = self.land("U1", "U1-redo")[0]
        self.assertEqual((row["action"], row["retry"], row["kept_reason"]), ("ESCALATE", 3, "FINAL_FIX_BUDGET_CAP"))
        self.assertFalse((self.p.video_media / "U1.mp4").exists())       # parked for the escalation take
        rec = self.state()["U1"]
        self.assertEqual((rec["burn_retry"], rec["status"], rec["sentence"]),
                         (3, "BURN_RETRY_PENDING", ffr.BURN_RETRY_SENTENCES[3]))
        self.assertEqual(rec["clean_start_frame"]["source_sha256"], sha(self.start))
        esc = rec["burn_escalation"]
        self.assertEqual((esc["status"], esc["planned_credits"], esc["voice_anchor"]["present"],
                          esc["h3_prompt_format"]), ("PENDING", 12, True, "OFFICIAL_REF_V1"))
        self.assertTrue(rec["burn_retries"][-1]["escalation"])
        self.assertIn("FINAL_FIX_BURN_ESCALATE unit=U1 frames=5/24 retry=3 cost=12", "\n".join(self.said))
        # the recompile carries the clean frame for the submitter's @Image1
        fields = bnp.final_fix_redo_fields(self.root, "E29")
        self.assertEqual((fields["U1"]["burn_retry"], fields["U1"]["clean_start_frame"]["sha256"]),
                         (3, rec["clean_start_frame"]["sha256"]))
        self.assertEqual(P.s6_burn_retry_note_posted(self.ctx, ["U1"]), ["U1"])
        row = self.land("U1", "U1-esc")[0]
        self.assertEqual((row["action"], row["reason"]), ("KEEP", "RESOLVED"))
        rec = self.state()["U1"]
        self.assertEqual((rec["burn_status"], rec["burn_escalation"]["status"]), ("RESOLVED", "CLEAN"))
        summary = P.final_fix_burn_summary(json.loads(P.final_fix_redo_path(self.ctx).read_text()))
        self.assertEqual((summary["U1"]["status"], summary["U1"]["escalation"]), ("RESOLVED", "CLEAN"))
        # the second unit no longer fits the episode's escalation cap (15 - 12 = 3 < 12)
        self.burned["U3-redo"] = 4
        row = self.land("U3", "U3-redo")[0]
        self.assertEqual(row["action"], "KEEP_BEST")
        self.assertEqual(self.state()["U3"]["burn_escalation"]["reason"], "ESCALATION_CAP")
        self.assertEqual(self.frames, ["U1"])

    def test_still_burned_after_escalation_keeps_the_best_and_records_the_band(self):
        self.burned = {"U1-t1": 6, "U1-t2": 3, "U1-t3": 4, "U1-esc": 5}
        in_band = [{"y_centre": 0.82, "glyph_px_at_720": 52, "text": "别再琢磨了。"}]
        self.hits = {"U1-t2": in_band, "U1-esc": in_band}
        self.assertEqual(self.land("U1", "U1-t1")[0]["action"], "RETRY")
        self.assertEqual(self.land("U1", "U1-t2")[0]["action"], "RETRY")
        self.assertEqual(self.land("U1", "U1-t3")[0]["action"], "ESCALATE")
        row = self.land("U1", "U1-esc")[0]
        self.assertEqual((row["action"], row["reason"]), ("KEEP_BEST", "RETRY_MAX_REACHED"))
        self.assertEqual((self.p.video_media / "U1.mp4").read_text(), "U1-t2")   # fewest burned frames of all
        rec = self.state()["U1"]
        self.assertEqual((rec["burn_status"], rec["burn_escalation"]["status"]), ("UNRESOLVED", "BURNED"))
        self.assertEqual(rec["residual_text_band"]["texts"], ["别再琢磨了。"])
        self.assertEqual(self.frames, ["U1"])                                       # never a second escalation
        self.assertEqual(list(P.final_fix_band_units(self.ctx)), ["U1"])
        # S7 strict check verdicts -> objective defects: ACCEPT_CORRECT only
        P.write_json(self.p.assembly / "E29_BURNIN_SUBTITLES.json",
                     {"burned_line_checks": [{"unit_id": "U1", "verdict": "ACCEPT_CORRECT"}]})
        verdicts = P.final_fix_band_verdicts(self.ctx)
        self.assertEqual(verdicts, {"U1": ["ACCEPT_CORRECT"]})
        record = {"unresolved": [{"kind": "BURNED_TEXT", "unit_id": "U1", "window": [3.0, 5.0], "state": "PERSISTS"}]}
        self.assertEqual(ffr.objective_defects(record)["blocking_classes"], ["BURN_UNRESOLVED"])
        ok = ffr.objective_defects(record, burn_verdicts=verdicts)
        self.assertEqual((ok["blocking_classes"], ok["unresolved_burns"][0]["accepted"]), ([], "ACCEPT_CORRECT"))
        bad = ffr.objective_defects(record, burn_verdicts={"U1": ["ACCEPT_CORRECT", "REJECT_MISMATCH"]})
        self.assertEqual(bad["blocking_classes"], ["BURN_UNRESOLVED"])
        # a replaced clip drops the unit from the bands
        (self.p.video_media / "U1.mp4").write_text("other")
        self.assertEqual(P.final_fix_band_units(self.ctx), {})

    def test_burn_outside_the_band_records_no_band(self):
        os.environ["NALU_FINAL_FIX_BUDGET_CREDITS"] = "25"
        os.environ[ffr.BURN_ESCALATION_ENV] = "0"
        self.burned = {"U1-redo": 5}
        self.hits = {"U1-redo": [{"y_centre": 0.82, "text": "别再"}, {"y_centre": 0.3, "text": "药铺"}]}
        row = self.land("U1", "U1-redo")[0]
        self.assertEqual(row["action"], "KEEP_BEST")
        rec = self.state()["U1"]
        self.assertEqual(rec["burn_escalation"]["reason"], "ESCALATION_DISABLED")
        self.assertNotIn("residual_text_band", rec)
        self.assertEqual(self.frames, [])

    def test_clean_frame_failure_keeps_the_best_take(self):
        os.environ["NALU_FINAL_FIX_BUDGET_CREDITS"] = "25"
        self.burned = {"U1-redo": 5}
        with mock.patch.object(P, "s6_final_fix_clean_start_frame",
                               lambda *_a: {"status": "TEXT_IN_CLEAN_FRAME", "task_id": "t9"}):
            row = self.land("U1", "U1-redo")[0]
        self.assertEqual(row["action"], "KEEP_BEST")
        esc = self.state()["U1"]["burn_escalation"]
        self.assertEqual((esc["status"], esc["reason"], esc["planned_credits"]),
                         ("SKIPPED", "CLEAN_FRAME_TEXT_IN_CLEAN_FRAME", 2))   # the image may have been charged
        self.assertTrue((self.p.video_media / "U1.mp4").is_file())


class SubmitterCleanFrameTest(unittest.TestCase):
    def test_clean_frame_is_sent_as_image1_only_when_its_sha_matches(self):
        from tools import submit_giggle_video_manifest_v2 as sub
        with tempfile.TemporaryDirectory() as tmp:
            frame = Path(tmp) / "clean.png"
            from PIL import Image
            Image.new("RGB", (64, 96), (120, 80, 40)).save(frame)
            task = {"h3_final_fix": {"sentence": "s", "burn_retry": 3,
                                     "clean_start_frame": {"path": str(frame), "sha256": sha(frame)}}}
            clean = sub._final_fix_clean_start_frame(task)
            self.assertEqual(clean["path"], str(frame))
            data, note = sub._clean_start_frame_bytes(clean)
            self.assertTrue(data)
            self.assertEqual(note["status"], "SENT")
            data, note = sub._clean_start_frame_bytes({**clean, "sha256": "0" * 64})
            self.assertIsNone(data)
            self.assertEqual(note["status"], "CLEAN_START_FRAME_SHA_MISMATCH")
            self.assertIsNone(sub._final_fix_clean_start_frame({"h3_final_fix": {"sentence": "s"}}))

    def test_upload_path_substitutes_image1(self):
        from tools import submit_giggle_video_manifest_v2 as sub
        with tempfile.TemporaryDirectory() as tmp:
            from PIL import Image
            start, clean, face = (Path(tmp) / n for n in ("start.png", "clean.png", "face.png"))
            Image.new("RGB", (64, 96), (10, 10, 10)).save(start)
            Image.new("RGB", (64, 96), (200, 200, 200)).save(clean)
            Image.new("RGB", (64, 64), (90, 90, 90)).save(face)
            uploads = []

            def upload_bytes(data, *, file_name, upload_path, mime):
                uploads.append(data)
                return {"url": f"https://cdn/{file_name}", "file_name": file_name}
            task = {"task_key": "E29-VU-013", "reference_images": [str(start), str(face)],
                    "h3_final_fix": {"sentence": "s", "burn_retry": 3,
                                     "clean_start_frame": {"path": str(clean), "sha256": sha(clean)}}}
            with mock.patch.object(sub.hopsapi, "upload_bytes", upload_bytes):
                images, _audios, notes = sub._hopsapi_reference_uploads(task)
            self.assertEqual(len(images), 2)
            self.assertEqual(notes[0]["burn_escalation_clean_start_frame"]["status"], "SENT")
            self.assertNotIn("burn_retry_perturbation", notes[0])
            import io
            with Image.open(io.BytesIO(uploads[0])) as img:
                self.assertGreater(img.convert("RGB").getpixel((img.width // 2, img.height // 2))[0], 150)
            # the file changed since: the perturbed start frame goes instead (recorded)
            Image.new("RGB", (64, 96), (0, 200, 0)).save(clean)
            uploads.clear()
            with mock.patch.object(sub.hopsapi, "upload_bytes", upload_bytes):
                _i, _a, notes = sub._hopsapi_reference_uploads(task)
            self.assertEqual(notes[0]["burn_escalation_clean_start_frame"]["status"],
                             "CLEAN_START_FRAME_SHA_MISMATCH")
            self.assertIn("burn_retry_perturbation", notes[0])


class CleanFrameToolTest(unittest.TestCase):
    def test_generate_reuses_the_durable_image_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "kf.png"
            src.write_bytes(b"kf")
            posted = []

            class Hops:
                class HopsapiNotCharged(Exception):
                    pass

            class Client:
                MODEL = "gpt-image-2"
                hops = Hops

                def prepare_request(self, *, prompt, reference_paths, aspect_ratio, task_key):
                    return {"payload": {"prompt": prompt, "refs": reference_paths}, "resolution": "1K"}

                def intent_fields(self, prepared):
                    return {}

                def create_image_task(self, payload):
                    posted.append(payload)
                    return {"task_id": "T1"}

                def query_task(self, task_id):
                    return {"remote_status": "completed", "urls": ["https://cdn/x.png"]}

                def record_settlement(self, tx_path, task_id, status, now):
                    tx = json.loads(Path(tx_path).read_text())
                    tx["provider_cost_credits"] = 1.4
                    Path(tx_path).write_text(json.dumps(tx))

                def download_image(self, url, out):
                    Path(out).write_bytes(b"clean")
                    return {"bytes": 5}

                def normalise_portrait_9_16(self, out):
                    pass

            out_dir = root / "out"
            res = bcf.generate(episode="E29", unit_id="E29-VU-013", source=src, out_dir=out_dir, engine_root=root,
                               client=Client(), checker=lambda *_a: {"status": "CLEAN"})
            self.assertEqual((res["status"], res["cost_credits"]), ("READY", 1.4))
            self.assertEqual(posted[0]["prompt"], ffr.CLEAN_FRAME_PROMPT)
            self.assertEqual(posted[0]["refs"], [str(src)])
            tx = next((root / "workflow/tasks/giggle_submit_transactions/E29").glob("burn_clean_start_frame__*.json"))
            intent = json.loads(tx.read_text())
            self.assertTrue(intent["burn_clean_start_frame"])
            self.assertNotIn("scene_location_still", intent)
            again = bcf.generate(episode="E29", unit_id="E29-VU-013", source=src, out_dir=out_dir, engine_root=root,
                                 client=Client(), checker=lambda *_a: {"status": "CLEAN"})
            self.assertTrue(again["reused"])
            self.assertEqual(len(posted), 1)                                   # never a second POST
            texty = bcf.generate(episode="E29", unit_id="E29-VU-014", source=src, out_dir=out_dir, engine_root=root,
                                 client=Client(), checker=lambda *_a: {"status": "TEXT", "boxes": 1})
            self.assertEqual(texty["status"], "TEXT_IN_CLEAN_FRAME")


if __name__ == "__main__":
    unittest.main()
