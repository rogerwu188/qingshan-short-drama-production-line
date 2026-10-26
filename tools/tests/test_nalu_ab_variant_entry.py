"""paid_stage.sh <EP> --ab-variant: one A/B task through the normal S6 guards, isolated output.

Every child process is replaced by a recorder (no network, no provider, no real ledger)."""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "lines/nalu/runtime/tools"
sys.path.insert(0, str(TOOLS))
import nalu_pipeline as pipeline  # noqa: E402

EP = "E05"
SOURCE = "E05-VU-007"
KEY = "E05-VU-007-ZH"
REFS = ["a" * 64, "b" * 64]


def _write(path: Path, payload) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload) if not isinstance(payload, str) else payload, encoding="utf-8")
    return path


class FakeCtx:
    """The attributes Ctx.paid_step / budget_check / materialize_paid_authorization read; ``run`` records."""

    budget_check = pipeline.Ctx.budget_check
    budget_release = pipeline.Ctx.budget_release
    paid_step = pipeline.Ctx.paid_step

    def __init__(self, root: Path, *, paid: bool = True, budget_exit: int = 0):
        work = root / "workflow/nalu" / EP
        pre = work / "preproduction"
        self.episode = EP
        self.p = SimpleNamespace(
            work=work, preprod=pre, preprod_reports=pre / "reports", video_media=work / "video",
            grouping_plan=pre / f"{EP}_VIDEO_UNIT_GROUPING_PLAN_V1.json",
            video_transaction=pre / f"{EP}_VIDEO_TRANSACTION_MANIFEST_V1.json",
            grouped_seedance=pre / f"{EP}_GROUPED_SEEDANCE_MANIFEST_V1.json",
            logs=root / "logs", scope={"scope_id": "lab"})
        self.p.logs.mkdir(parents=True, exist_ok=True)
        self.run_id = "TESTRUN"
        self.cap = 1800
        self.dry = False
        self.want_paid = True
        self.paid_enabled = paid
        self.config_paid_enabled = True
        self.storyclaw_paid_enabled = True
        self.paid_order = {"id": "ORDER-122", "seq": 122, "orders_file_sha256": "0" * 64, "paid_stages": ["S6"]}
        self.authority_blockers: list[str] = []
        self.authority = {"orders_path": root / "orders.json", "paid_order_seq": 122,
                          "latest_order_seq": 122, "line_owner_id": "owner"}
        self.planned_commands: list[dict] = []
        self.calls: list[tuple[str, list[str], bool]] = []
        self.budget_exit = budget_exit

    def say(self, line: str) -> None:  # noqa: D401 - quiet
        pass

    def names(self) -> list[str]:
        return [name for name, _, _ in self.calls]

    def argv(self, name: str) -> list[str]:
        return next(argv for n, argv, _ in self.calls if n == name)

    def run(self, argv, *, name, paid=False, extra_env=None, **_kw):
        argv = [str(a) for a in argv]
        self.calls.append((name, argv, paid))
        out = ""
        rc = 0
        if name.startswith("budget_check"):
            rc = self.budget_exit
            verdict = {"status": "PASS" if rc == 0 else "FAIL", "projected_total_credits": 1108, "cap_credits": 1800}
            if rc == 0 and "--reserve" in argv:
                verdict["reservation_result"] = {"reserved": True, "reservation_id": "RES-1"}
            out = json.dumps(verdict)
        elif name.endswith("materialize_paid_authorization"):
            target = Path(argv[argv.index("--manifest") + 1])
            _write(pipeline.materialised_path(target), json.loads(target.read_text(encoding="utf-8")))
            _write(Path(argv[argv.index("--report") + 1]), {"status": "PASS"})
        elif name == "ab_d11_rehearsal":
            target = Path(argv[argv.index("--manifest") + 1])
            out_dir = Path(argv[argv.index("--out-dir") + 1])
            _write(out_dir / f"{target.stem}_PAID_AUTHORIZED{target.suffix}", {"tasks": []})
        elif name == "ab_submit_giggle_video_manifest_v2":
            _write(Path(argv[argv.index("--out") + 1]), {"status": "PASS", "tasks": [{"task_key": KEY, "task_id": "T1"}]})
        elif name == "ab_poll_giggle_submit_report":
            out_dir = Path(argv[argv.index("--out-dir") + 1])
            _write(out_dir / f"{KEY}.mp4", "fake-mp4")
            _write(Path(argv[argv.index("--status-report") + 1]),
                   {"all_completed": True, "status_counts": {"completed": 1}})
        return {"name": name, "argv": argv, "exit_code": rc, "stdout_tail": out, "stderr_tail": "", "paid": paid}


def fixture(root: Path, ctx: FakeCtx, **overrides) -> Path:
    pre = ctx.p.preprod
    prompt = _write(pre / "ab_video_prompts" / f"{KEY}.txt", "Holmes speaks. 一镜到底；机位固定。")
    import hashlib
    prompt_sha = hashlib.sha256(prompt.read_bytes()).hexdigest()
    _write(ctx.p.grouping_plan, {"units": [{"unit_id": SOURCE}, {"unit_id": "E05-VU-008"}]})
    _write(pre / f"{EP}_PROMPT_BATCH_V1.json", {"execution_id": f"{EP}-PROMPT-BATCH-V1",
                                                 "rows": [{"unit_id": SOURCE, "video_prompt": {"sha256": "c" * 64}}]})
    _write(ctx.p.video_transaction, {"tasks": [{"task_key": SOURCE, "model": "MiniMax-H3", "reference_sha256": REFS}]})
    task = {"task_key": KEY, "unit_id": SOURCE, "ab_variant_of": SOURCE, "episode": EP, "model": "MiniMax-H3",
            "duration_seconds": 5, "h3_constraint_language": "zh", "reference_sha256": list(REFS),
            "camera_plan": {"camera_grammar": "CAMERA_GRAMMAR_V1"},
            "prompt_file": str(prompt), "prompt_sha256": prompt_sha}
    doc = {"ab_variant_schema": pipeline.AB_VARIANT_SCHEMA, "episode": EP, "ab_variant_of": SOURCE,
           "h3_constraint_language": "zh", "provider_post_allowed": False, "maximum_new_submissions": 1,
           "estimated_credits": 76, "source_grouped_manifest": pipeline._engine_rel(ctx.p.grouped_seedance),
           "tasks": [task]}
    for key, value in overrides.items():
        if key.startswith("task."):
            if value is None:
                task.pop(key[5:], None)
            else:
                task[key[5:]] = value
        else:
            doc[key] = value
    return _write(pre / f"{KEY}_AB.json", doc)


class AbVariantEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = self.root / "store"
        patches = [
            mock.patch.object(pipeline, "video_store_dir", lambda _ep: self.store),
            mock.patch.object(pipeline, "ab_variant_registration", lambda _ctx, _task: None),
            mock.patch.object(pipeline, "ab_task_bound", lambda _ctx, _task: False),
            mock.patch.object(pipeline, "archive_credit_statement", lambda *_a, **_k: None),
            mock.patch.dict(os.environ, {"GIGGLE_API_KEY": "test-placeholder-not-a-key"}),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    # ------------------------------------------------------------ arguments
    def test_paid_stage_usage_requires_exactly_one_variant_path(self):
        script = TOOLS / "paid_stage.sh"
        for args in (["E05", "--ab-variant"], ["E05", "--ab-variant", "a.json", "extra"], ["E05", "S6", "--manifest"]):
            got = subprocess.run(["bash", str(script), *args], capture_output=True, text=True, timeout=30,
                                 env={"PATH": os.environ.get("PATH", "")})
            self.assertEqual(got.returncode, 2, args)
            self.assertIn("--ab-variant <variant_manifest.json>", got.stderr)

    def test_pipeline_parser_has_ab_variant_mode(self):
        args = pipeline.build_parser().parse_args(["ab-variant", "--episode", EP, "--variant", "x.json", "--paid"])
        self.assertIs(args.func, pipeline.cmd_ab_variant)
        self.assertTrue(args.paid)
        self.assertEqual(args.variant, "x.json")

    def test_paid_stage_forwards_ab_variant_to_pipeline(self):
        text = (TOOLS / "paid_stage.sh").read_text(encoding="utf-8")
        self.assertIn('ab-variant \\\n    --episode "$EPISODE" --variant "$AB_VARIANT" --paid', text)
        # the A/B branch sits after the lock and the budget preflight, like the normal run
        self.assertLess(text.index('LOCK="$NALU_RUNTIME_ROOT'), text.index('if [ -n "$AB_VARIANT" ]; then'))

    # ------------------------------------------------------------ refusals
    def test_foreign_episode_manifest_is_refused_before_any_step(self):
        ctx = FakeCtx(self.root)
        path = fixture(self.root, ctx, episode="E04", **{"task.episode": "E04"})
        self.assertEqual(pipeline.run_ab_variant(ctx, path), 2)
        self.assertEqual(ctx.calls, [])
        failures = pipeline.ab_variant_failures(ctx, path, json.loads(path.read_text()))
        self.assertIn("AB_VARIANT_FOREIGN_EPISODE:E04!=E05", failures)

    def test_unstamped_or_unknown_schema_is_refused(self):
        ctx = FakeCtx(self.root)
        path = fixture(self.root, ctx, ab_variant_schema="something.else", **{"task.camera_plan": {}})
        failures = pipeline.ab_variant_failures(ctx, path, json.loads(path.read_text()))
        self.assertIn("AB_VARIANT_SCHEMA_MISMATCH:something.else", failures)
        self.assertTrue(any(f.startswith("AB_VARIANT_NOT_CAMERA_GRAMMAR_V1") for f in failures))
        self.assertEqual(pipeline.run_ab_variant(ctx, path), 2)
        self.assertNotIn("ab_submit_giggle_video_manifest_v2", ctx.names())

    def test_source_unit_must_be_in_episode_authority(self):
        ctx = FakeCtx(self.root)
        path = fixture(self.root, ctx)
        _write(ctx.p.video_transaction, {"tasks": [{"task_key": "E05-VU-008"}]})  # narrowed wave, no bound txn
        failures = pipeline.ab_variant_failures(ctx, path, json.loads(path.read_text()))
        self.assertIn(f"AB_SOURCE_UNIT_NOT_IN_AUTHORITATIVE_MANIFEST:{SOURCE}", failures)
        # the source's bound English transaction is accepted instead, with the same references
        _write(self.store / f"{SOURCE}__0123456789abcdef.json",
               {"state": "SUBMITTED_TASK_ID_BOUND", "task_id": "T0", "model": "MiniMax-H3", "reference_sha256": REFS})
        self.assertEqual(pipeline.ab_variant_failures(ctx, path, json.loads(path.read_text())), [])

    def test_bound_english_take_wins_over_a_recompiled_manifest(self):
        # lab E05: a later recompile added a predecessor tail the English clip never had
        ctx = FakeCtx(self.root)
        path = fixture(self.root, ctx)
        _write(ctx.p.video_transaction, {"tasks": [{"task_key": SOURCE, "model": "MiniMax-H3",
                                                    "reference_sha256": [REFS[0], "e" * 64, *REFS[1:]]}]})
        _write(self.store / f"{SOURCE}__0123456789abcdef.json",
               {"state": "SUBMITTED_TASK_ID_BOUND", "task_id": "T0", "model": "MiniMax-H3", "reference_sha256": REFS})
        self.assertEqual(pipeline.ab_variant_failures(ctx, path, json.loads(path.read_text())), [])
        # a variant whose references match neither the bound take nor the manifest is still refused
        bad = fixture(self.root, ctx, **{"task.reference_sha256": ["d" * 64]})
        failures = pipeline.ab_variant_failures(ctx, bad, json.loads(bad.read_text()))
        self.assertIn("AB_VARIANT_REFERENCES_DIFFER_FROM_SOURCE:BOUND_TRANSACTION", failures)

    def test_already_authorised_or_retargeted_copy_is_refused(self):
        ctx = FakeCtx(self.root)
        path = fixture(self.root, ctx, provider_post_allowed=True, **{"task.reference_sha256": ["d" * 64]})
        failures = pipeline.ab_variant_failures(ctx, path, json.loads(path.read_text()))
        self.assertTrue(any(f.startswith("AB_VARIANT_NOT_AS_PRODUCED") for f in failures))
        self.assertIn("AB_VARIANT_REFERENCES_DIFFER_FROM_SOURCE:TRANSACTION_MANIFEST", failures)

    def test_budget_refusal_stops_before_submit(self):
        ctx = FakeCtx(self.root, budget_exit=2)
        path = fixture(self.root, ctx)
        self.assertEqual(pipeline.run_ab_variant(ctx, path), 3)
        names = ctx.names()
        self.assertTrue(any(n.startswith("budget_check_") for n in names))
        self.assertNotIn("ab_submit_giggle_video_manifest_v2", names)
        self.assertNotIn("ab_poll_giggle_submit_report", names)
        report = json.loads((ctx.p.work / "video_ab" / f"{KEY}_AB_RUN.json").read_text())
        self.assertEqual(report["status"], pipeline.HARD_STOP)

    # ------------------------------------------------------------ paid path
    def test_paid_path_is_the_s6_machinery_with_separate_outputs(self):
        ctx = FakeCtx(self.root)
        path = fixture(self.root, ctx)
        self.assertEqual(pipeline.run_ab_variant(ctx, path), 0)
        names = ctx.names()
        order = ["ab_variant_verify", "s6_materialize_paid_authorization",
                 "budget_check_ab_submit_giggle_video_manifest_v2", "ab_submit_giggle_video_manifest_v2",
                 "budget_release_ab_submit_giggle_video_manifest_v2", "ab_poll_giggle_submit_report",
                 "ab_budget_ledger_record"]
        self.assertEqual([n for n in names if n in order], order)
        auth = ctx.argv("s6_materialize_paid_authorization")
        self.assertEqual(auth[auth.index("--task-key") + 1], KEY)
        self.assertEqual(auth[auth.index("--stage") + 1], "S6")
        ab_dir = ctx.p.work / "video_ab"
        self.assertEqual(Path(auth[auth.index("--report") + 1]).parent, ab_dir)
        self.assertIn("--reserve", ctx.argv("budget_check_ab_submit_giggle_video_manifest_v2"))
        submit = ctx.argv("ab_submit_giggle_video_manifest_v2")
        self.assertEqual(Path(submit[submit.index("--manifest") + 1]), pipeline.materialised_path(path))
        self.assertEqual(Path(submit[submit.index("--out") + 1]).parent, ab_dir)
        poll = ctx.argv("ab_poll_giggle_submit_report")
        self.assertEqual(Path(poll[poll.index("--out-dir") + 1]), ab_dir)
        self.assertNotEqual(ab_dir.resolve(), ctx.p.video_media.resolve())
        self.assertTrue((ab_dir / f"{KEY}.mp4").is_file())
        self.assertFalse((ctx.p.video_media / f"{KEY}.mp4").exists())
        self.assertTrue(dict((n, p) for n, _, p in ctx.calls)["ab_submit_giggle_video_manifest_v2"])

    def test_output_paths_never_point_into_episode_video_dir(self):
        ctx = FakeCtx(self.root)
        paths = pipeline.ab_variant_paths(ctx, KEY)
        for name, value in paths.items():
            self.assertFalse(Path(value).resolve().is_relative_to(ctx.p.video_media.resolve()), name)
        self.assertEqual(paths["clip"], ctx.p.work / "video_ab" / f"{KEY}.mp4")
        self.assertNotEqual(paths["finalization_dir"], ctx.p.preprod / "prompt_batch_finalization")

    def test_missing_key_is_a_no_spend_rehearsal_that_leaves_nothing_behind(self):
        ctx = FakeCtx(self.root)
        path = fixture(self.root, ctx)
        with mock.patch.dict(os.environ, {"GIGGLE_API_KEY": ""}):
            self.assertEqual(pipeline.run_ab_variant(ctx, path), 2)
        names = ctx.names()
        self.assertIn("ab_d11_rehearsal", names)
        self.assertNotIn("s6_materialize_paid_authorization", names)
        self.assertNotIn("ab_submit_giggle_video_manifest_v2", names)
        self.assertIn("ab_submit_giggle_video_manifest_v2_precheck", names)
        self.assertNotIn("--reserve", ctx.argv("budget_check_ab_submit_giggle_video_manifest_v2"))
        self.assertFalse(pipeline.materialised_path(path).exists())
        self.assertEqual([p.name for p in (ctx.p.work / "video_ab").iterdir()], [f"{KEY}_AB_RUN.json"])
        report = json.loads((ctx.p.work / "video_ab" / f"{KEY}_AB_RUN.json").read_text())
        self.assertEqual(report["blockers"], ["PAID_STEPS_DISABLED:GIGGLE_API_KEY is not set"])

    def test_unregistered_variant_prompt_stops_for_review(self):
        ctx = FakeCtx(self.root)
        path = fixture(self.root, ctx)
        with mock.patch.object(pipeline, "ab_variant_registration",
                               lambda _c, _t: "ValueError:WHOLE_BATCH_PROMPT_QA_REQUIRED:FINALIZATION_QA_MISMATCH"):
            self.assertEqual(pipeline.run_ab_variant(ctx, path), pipeline.REVIEW_EXIT_CODE)
        diff = ctx.argv("ab_prompt_batch_finalization_diff")
        self.assertEqual(diff[diff.index("--transaction-path") + 1], str(path))
        self.assertFalse(any(n.startswith("budget_check") for n in ctx.names()))


if __name__ == "__main__":
    unittest.main()
