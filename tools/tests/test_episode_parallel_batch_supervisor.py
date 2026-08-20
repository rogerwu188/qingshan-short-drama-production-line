import unittest
import sys
import json
import hashlib
import struct
import threading
import zlib
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.episode_parallel_batch_supervisor import (
    cli_int_duration,
    clear_resolved_scene_block,
    confirmed_periodic_duplicate_frames,
    episode_has_release_record,
    extract_credit_observation,
    line_has_active_handle,
    mark_retry_or_terminal,
    poll_and_harvest,
    prepare_local_reference_assets,
    refresh_streaming_task_readiness,
    record_submit_credit_attempt,
    refresh_activity_state,
    refresh_credit_summary,
    run_local_tool,
    select_parallel_submission_wave,
    settle_credit_attempt,
    submit_one,
    submit_pending,
    upsert_activity_line,
    validate_script_readiness,
    validate_complete_video_prompt_manifest,
    validate_dialogue_manifest_coverage,
    validate_entity_reference_task,
    validate_initial_asset_library,
    validate_keyframe_admissions,
    validate_supervisor_script_gate,
    validate_writer_agent_provenance,
)
from tools.image_dimensions import read_image_dimensions
from tools.initial_asset_library import CATEGORIES, compile_library


def write_test_png(path: Path, width: int = 512, height: int = 512) -> None:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

    row = b"\x00" + (b"\x20\x80\xc0" * width)
    payload = b"\x89PNG\r\n\x1a\n"
    payload += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    payload += chunk(b"IDAT", zlib.compress(row * height, 9))
    payload += chunk(b"IEND", b"")
    path.write_bytes(payload)


def write_test_jpeg(path: Path, width: int = 512, height: int = 512) -> None:
    path.write_bytes(
        b"\xff\xd8"
        + b"\xff\xe0\x00\x02"
        + b"\xff\xc0\x00\x08\x08"
        + struct.pack(">HH", height, width)
        + b"\x01"
        + b"\xff\xd9"
    )


class EpisodeParallelBatchSupervisorActivityTest(unittest.TestCase):
    def test_e40_variant_requires_formal_start_frame_admission(self):
        report = validate_keyframe_admissions({
            "episode": "E40-REMAKE-V1",
            "tasks": [{"task_key": "R01", "tool_type": "video_generation", "state": "ready"}],
        })
        self.assertEqual(report["status"], "FAIL")
        self.assertIn("R01:start_frame_admission_ref_missing", report["failures"])

    def test_parallel_wave_runs_independent_tasks_and_one_head_per_chain(self):
        def chained(key: str, chain: str, index: int) -> dict:
            return {
                "task_key": key,
                "generation_schedule_mode": "TAIL_CHAINED_SERIAL",
                "action_sequence_contract": {"chain_id": chain, "sequence_index": index},
            }

        tasks = [
            chained("A2", "A", 2),
            chained("B1", "B", 1),
            {"task_key": "FREE", "generation_schedule_mode": "INDEPENDENT_PARALLEL"},
            chained("A1", "A", 1),
        ]

        selected, deferred = select_parallel_submission_wave(tasks)

        self.assertEqual({task["task_key"] for task in selected}, {"A1", "B1", "FREE"})
        self.assertEqual([task["task_key"] for task in deferred], ["A2"])

    @patch("tools.episode_parallel_batch_supervisor.record_submit_credit_attempt")
    @patch("tools.episode_parallel_batch_supervisor.submit_one")
    def test_input_precheck_does_not_reduce_eight_lane_submit_concurrency(
        self, mock_submit_one, _mock_credit
    ):
        barrier = threading.Barrier(8, timeout=2)
        lock = threading.Lock()
        active = 0
        max_active = 0

        def concurrent_submit(task, _receipt):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            barrier.wait()
            with lock:
                active -= 1
            return {"task_id": f"remote-{task['task_key']}"}

        mock_submit_one.side_effect = concurrent_submit
        receipt = {
            "tasks": [
                {
                    "task_key": f"U{index}",
                    "state": "pending",
                    "generation_schedule_mode": "INDEPENDENT_PARALLEL",
                    "retry_count": 0,
                }
                for index in range(8)
            ],
            "max_retries": 2,
            "max_submit_workers": 8,
        }

        submit_pending(receipt)

        self.assertEqual(max_active, 8)
        self.assertEqual(receipt["concurrency_wave"]["max_submit_workers"], 8)
        self.assertEqual(receipt["concurrency_wave"]["deferred_same_chain_task_keys"], [])

    def test_initial_asset_library_blocks_before_any_provider_submission(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            requirements = {
                "schema": "ai_drama.production_asset_requirements.v1",
                "project_id": "project-asset-gate",
                "canonical_sha256": "a" * 64,
                "series_bible_sha256": "b" * 64,
                "assets": {category: [] for category in CATEGORIES},
            }
            requirements["assets"]["characters"] = [
                {
                    "asset_id": "CHAR-001",
                    "label": "Lead",
                    "priority": "SERIES_CORE",
                    "first_use_episode": 1,
                    "required_in_episodes": [1],
                    "authority_refs": [
                        {"source_id": "canonical", "sha256": "a" * 64}
                    ],
                    "specification": {"identity": "fixed face and body"},
                }
            ]
            library, _ = compile_library(requirements, None)
            requirements_path = root / "requirements.json"
            library_path = root / "library.json"
            requirements_path.write_text(json.dumps(requirements), encoding="utf-8")
            library_path.write_text(json.dumps(library), encoding="utf-8")
            report, report_path = validate_initial_asset_library(
                {
                    "episode": "E01",
                    "qa_dir": str(root / "qa"),
                    "initial_asset_library_required": True,
                    "asset_requirements_ref": str(requirements_path),
                    "production_asset_library_ref": str(library_path),
                }
            )
            report_written = report_path.is_file()
        self.assertEqual(report["status"], "FAIL")
        self.assertTrue(report_written)
        self.assertEqual(report["failures"][0]["asset_id"], "CHAR-001")

    def test_portable_image_dimension_reader_supports_png_and_jpeg(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            png = root / "reference.png"
            jpeg = root / "reference.jpg"
            write_test_png(png, width=640, height=512)
            write_test_jpeg(jpeg, width=768, height=512)

            self.assertEqual(read_image_dimensions(png), (640, 512))
            self.assertEqual(read_image_dimensions(jpeg), (768, 512))

    def test_reference_audio_over_provider_limit_is_blocked_before_submit(self):
        task = {
            "generation_mode": "performance_generation",
            "batch_id": "E99",
            "unit_id": "E99-U01",
            "still_sequence_only_allowed": True,
            "planned_reference_image_count": 1,
            "state_reference_minimum": 1,
            "reference_images": [],
            "reference_image_sequence": [{"role": "PERFORMANCE_START", "path": "missing.png"}],
            "performance_spec": {
                "motion_beats": [{
                    "subject": "甲", "action": "说话", "contact_point": "无接触",
                    "direction": "面向前方", "end_state": "说完", "intent": "交代线索",
                    "visible_causality": "观众听清", "expression": "紧张", "viewer_read": "线索成立",
                }],
                "prop_ownership": {"single_source": "剧本"},
            },
            "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": 0},
            "native_dialogue_required": True,
            "dialogue": [{"dia_id": "D1"}, {"dia_id": "D2"}],
            "dialogue_audio_assets": [
                {"dia_id": "D1", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE", "duration_seconds": 8.0},
                {"dia_id": "D2", "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE", "duration_seconds": 7.1},
            ],
        }
        failures = validate_entity_reference_task(task)
        self.assertTrue(any(row.get("check") == "seedance_reference_audio_total_duration" for row in failures))

    def test_streaming_readiness_activates_each_unit_without_batch_barrier(self):
        receipt = {
            "tasks": [
                {"task_key": "U01", "state": "waiting_dependencies"},
                {"task_key": "U02", "state": "waiting_dependencies"},
            ]
        }
        config = {
            "qa_dir": "qa",
            "output_dir": "outputs",
            "tasks": [
                {"task_key": "U01", "status": "READY_TO_SUBMIT", "reference_images": ["u01.png"]},
                {"task_key": "U02", "status": "WAITING_DEPENDENCIES", "reference_images": ["u02.png"]},
            ],
        }

        result = refresh_streaming_task_readiness(receipt, config)

        states = {task["task_key"]: task["state"] for task in receipt["tasks"]}
        self.assertEqual(result["activated"], ["U01"])
        self.assertEqual(states, {"U01": "pending", "U02": "waiting_dependencies"})
        self.assertFalse(receipt["streaming_readiness"]["batch_barrier"])

    def test_streaming_readiness_adds_new_ready_unit_during_active_batch(self):
        receipt = {"tasks": [{"task_key": "U01", "state": "remote_running", "task_id": "task-1"}]}
        config = {
            "qa_dir": "qa",
            "output_dir": "outputs",
            "tasks": [
                {"task_key": "U01", "status": "READY_TO_SUBMIT"},
                {"task_key": "U02", "status": "READY_TO_SUBMIT"},
            ],
        }

        result = refresh_streaming_task_readiness(receipt, config)

        states = {task["task_key"]: task["state"] for task in receipt["tasks"]}
        self.assertEqual(result["added"], ["U02"])
        self.assertEqual(states["U01"], "remote_running")
        self.assertEqual(states["U02"], "pending")
    def _write_complete_prompt_fixture(self, root: Path, *, prompt_weather="INTERIOR_CLEAR_NO_RAIN", complete=True):
        prompt = root / "U01.txt"
        prompt.write_text(
            f"【天气硬合同】weather={prompt_weather}；fixture\n",
            encoding="utf-8",
        )
        plan = root / "plan.json"
        plan.write_text(json.dumps({"units": [{"unit_id": "E32-CW-U01"}]}), encoding="utf-8")
        scene = root / "scene.json"
        scene.write_text(json.dumps({
            "episode": "E32",
            "scene_state": [{"scene_id": "E32-CW-S01", "weather": "interior_clear"}],
        }), encoding="utf-8")
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps({
            "episode": "E32",
            "unit_count": 1,
            "all_units_have_prompt": complete,
            "source_plan": str(plan),
            "source_plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
            "source_scene_authority": str(scene),
            "source_scene_authority_sha256": hashlib.sha256(scene.read_bytes()).hexdigest(),
            "rows": [{
                "unit_id": "E32-CW-U01",
                "scene_id": "E32-CW-S01",
                "weather": prompt_weather,
                "prompt_path": str(prompt),
                "prompt_sha256": hashlib.sha256(prompt.read_bytes()).hexdigest(),
            }],
        }), encoding="utf-8")
        config = {
            "episode": "E32",
            "complete_video_prompt_manifest_ref": str(manifest),
            "scene_contract_ref": str(scene),
            "tasks": [{
                "task_key": "U01",
                "tool_type": "video_generation",
                "unit_id": "E32-CW-U01",
                "prompt_file": str(prompt),
            }],
        }
        return config, manifest, prompt

    def test_complete_prompt_manifest_is_required_for_e32_video(self):
        result = validate_complete_video_prompt_manifest({
            "episode": "E32",
            "tasks": [{"tool_type": "video_generation", "unit_id": "E32-CW-U01"}],
        })
        self.assertEqual(result["status"], "FAIL")
        self.assertEqual(result["failures"][0]["check"], "complete_video_prompt_manifest_ref")

    def test_complete_prompt_manifest_blocks_global_wrong_weather(self):
        with TemporaryDirectory() as tmp:
            config, _, _ = self._write_complete_prompt_fixture(Path(tmp), prompt_weather="RAIN_NIGHT")
            result = validate_complete_video_prompt_manifest(config)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(row["check"] == "scene_weather_authority" for row in result["failures"]))

    def test_complete_prompt_manifest_blocks_incomplete_episode(self):
        with TemporaryDirectory() as tmp:
            config, _, _ = self._write_complete_prompt_fixture(Path(tmp), complete=False)
            result = validate_complete_video_prompt_manifest(config)
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(row["check"] == "all_units_have_prompt" for row in result["failures"]))

    def test_complete_prompt_manifest_blocks_task_sha_drift(self):
        with TemporaryDirectory() as tmp:
            config, _, prompt = self._write_complete_prompt_fixture(Path(tmp))
            prompt.write_text("later local overwrite\n", encoding="utf-8")
            result = validate_complete_video_prompt_manifest(config)
        self.assertEqual(result["status"], "FAIL")
        checks = {row["check"] for row in result["failures"]}
        self.assertIn("prompt_sha256", checks)
        self.assertIn("task_prompt_matches_complete_manifest", checks)

    def test_complete_prompt_manifest_accepts_authoritative_prompt(self):
        with TemporaryDirectory() as tmp:
            config, _, _ = self._write_complete_prompt_fixture(Path(tmp))
            result = validate_complete_video_prompt_manifest(config)
        self.assertEqual(result["status"], "PASS")

    @patch("tools.episode_parallel_batch_supervisor.record_gate_result")
    @patch("tools.episode_parallel_batch_supervisor.subprocess.run")
    def test_agentcut_is_blocked_before_tool_when_cut_motivation_fails(self, run_mock, record_mock):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            project_path = root / "project.json"
            report_path = root / "agentcut_report.json"
            project_path.write_text(json.dumps({
                "timeline": {"videoTracks": [{"clips": [
                    {"id": "c1", "start": 0, "duration": 1, "metadata": {}},
                    {"id": "c2", "start": 1, "duration": 1, "metadata": {}},
                ]}]},
            }), encoding="utf-8")

            result = run_local_tool(
                {
                    "task_key": "agentcut",
                    "tool_type": "agentcut",
                    "project": str(project_path),
                    "report": str(report_path),
                },
                {"episode": "E32", "tasks": []},
            )

            self.assertEqual(result["state"], "tool_blocked")
            self.assertEqual(result["tool_result"]["status"], "BLOCKED_CUT_MOTIVATION_GATE")
            self.assertTrue(Path(result["tool_result"]["cut_motivation_gate"]).is_file())
            run_mock.assert_not_called()
            self.assertEqual(record_mock.call_count, 2)

    def test_video_dialogue_manifest_gate_blocks_omitted_unit_dialogue(self):
        with TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "dialogue.json"
            manifest.write_text(json.dumps({
                "episode": "E32",
                "status": "PASS",
                "rows": [{
                    "dia_id": "E32-DIA-007",
                    "video_unit_id": "E32-CW-U06",
                    "status": "PASS",
                    "audio_mode": "EXACT_DIALOGUE_AUDIO_REFERENCE",
                }],
            }), encoding="utf-8")
            result = validate_dialogue_manifest_coverage({
                "episode": "E32",
                "dialogue_manifest_ref": str(manifest),
                "tasks": [{
                    "task_key": "U06",
                    "tool_type": "video_generation",
                    "unit_id": "E32-CW-U06",
                    "native_dialogue_required": False,
                    "dialogue": [],
                }],
            })

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(row["check"] == "dialogue_manifest_unit_coverage" for row in result["failures"]))

    def test_video_dialogue_manifest_gate_rejects_unregistered_style_sample(self):
        with TemporaryDirectory() as tmp:
            manifest = Path(tmp) / "dialogue.json"
            manifest.write_text(json.dumps({
                "episode": "E32",
                "status": "PASS",
                "rows": [{
                    "dia_id": "E32-DIA-008",
                    "video_unit_id": "E32-CW-U06",
                    "status": "PASS",
                    "audio_mode": "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT",
                }],
            }), encoding="utf-8")
            result = validate_dialogue_manifest_coverage({
                "episode": "E32",
                "dialogue_manifest_ref": str(manifest),
                "tasks": [{
                    "task_key": "U06",
                    "tool_type": "video_generation",
                    "unit_id": "E32-CW-U06",
                    "native_dialogue_required": True,
                    "dialogue": [{"dia_id": "E32-DIA-008"}],
                }],
            })

        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(row["check"] == "dialogue_audio_reference_policy" for row in result["failures"]))

    def test_video_dialogue_manifest_gate_allows_registered_locked_native_voice(self):
        with TemporaryDirectory() as tmp:
            audio = Path(tmp) / "voice.wav"
            audio.write_bytes(b"locked-native-voice")
            audio_sha = hashlib.sha256(audio.read_bytes()).hexdigest()
            registry = Path(tmp) / "voice_registry.json"
            registry.write_text(json.dumps({
                "major_roles": [{
                    "entity_id": "chenji",
                    "status": "LOCKED_PRODUCTION_READY",
                    "remote_asset_id": "voice-chenji",
                }],
            }), encoding="utf-8")
            manifest = Path(tmp) / "dialogue.json"
            manifest.write_text(json.dumps({
                "episode": "E32",
                "status": "PASS",
                "rows": [{
                    "dia_id": "E32-DIA-008",
                    "video_unit_id": "E32-CW-U06",
                    "speaker_id": "chenji",
                    "status": "PASS",
                    "audio_mode": "CANONICAL_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT_PROMPT",
                    "path": str(audio),
                    "sha256": audio_sha,
                    "remote_asset_id": "voice-chenji",
                }],
            }), encoding="utf-8")
            result = validate_dialogue_manifest_coverage({
                "episode": "E32",
                "dialogue_manifest_ref": str(manifest),
                "voice_registry_ref": str(registry),
                "tasks": [{
                    "task_key": "U06",
                    "tool_type": "video_generation",
                    "unit_id": "E32-CW-U06",
                    "native_dialogue_required": True,
                    "dialogue": [{"dia_id": "E32-DIA-008"}],
                }],
            })

        self.assertEqual(result["status"], "PASS")

    def test_cli_duration_normalizes_integral_float(self):
        self.assertEqual(cli_int_duration(13.0), "13")
        self.assertEqual(cli_int_duration("4.0"), "4")

    def test_cli_duration_rejects_fractional_seconds(self):
        with self.assertRaisesRegex(ValueError, "integer number of seconds"):
            cli_int_duration(4.5)

    def test_confirmed_periodic_duplicates_are_eligible_for_local_repair(self):
        with TemporaryDirectory() as tmp:
            report = Path(tmp) / "cadence.json"
            report.write_text(json.dumps({
                "status": "FAIL",
                "periodic_duplicates": {
                    "periodic_chains": [{"verification_status": "CONFIRMED_MPDECIMATE"}],
                    "mpdecimate_removed_frames": [11, 3, 7, 7],
                },
            }), encoding="utf-8")
            self.assertEqual(confirmed_periodic_duplicate_frames(report), [3, 7, 11])

    def test_unconfirmed_cadence_failure_is_not_auto_repaired(self):
        with TemporaryDirectory() as tmp:
            report = Path(tmp) / "cadence.json"
            report.write_text(json.dumps({
                "status": "FAIL",
                "periodic_duplicates": {
                    "periodic_chains": [{"verification_status": "UNCONFIRMED"}],
                    "mpdecimate_removed_frames": [3, 7],
                },
            }), encoding="utf-8")
            self.assertEqual(confirmed_periodic_duplicate_frames(report), [])

    def test_credit_value_is_extracted_from_nested_api_response(self):
        self.assertEqual(
            extract_credit_observation({"data": {"billing": {"credits_consumed": "135"}}}),
            {"credits": 135, "response_path": "$.data.billing.credits_consumed"},
        )

    @patch(
        "tools.episode_parallel_batch_supervisor.fetch_task_credit_net_by_task_id",
        return_value={
            "status": "PASS_ZERO_REFUNDED",
            "endpoint": "/api/v1/payment/credit-statements",
            "paid_credits": 135,
            "refunded_credits": 135,
            "net_charged_credits": 0,
            "statement_rows": [
                {"event_type": "Pay", "credit": "-135"},
                {"event_type": "Refund", "credit": "+135"},
            ],
        },
    )
    @patch("tools.episode_parallel_batch_supervisor.now", return_value="2026-07-20T09:00:00-0700")
    def test_failed_generation_attempt_is_settled_at_zero_after_refund(self, _now, credit_net):
        task = {"tool_type": "video_generation", "task_id": "remote-a"}
        record_submit_credit_attempt(
            task,
            {
                "task_id": "remote-a",
                "submit_response": {"data": {"task_id": "remote-a", "credit_cost": 135}},
            },
        )
        settle_credit_attempt(task, "failed", {"status": "failed"})

        self.assertEqual(task["credit_attempts"][0]["returned_credit"], 135)
        self.assertEqual(task["credit_attempts"][0]["actual_charged_credits"], 0)
        self.assertEqual(task["credit_attempts"][0]["charge_status"], "FAILED_ZERO_NET_AFTER_REFUND")
        credit_net.assert_called_once_with("remote-a", event_description="SingleGenerateVideo")

    @patch(
        "tools.episode_parallel_batch_supervisor.fetch_task_credit_net_by_task_id",
        return_value={"status": "PASS_CHARGED", "net_charged_credits": 135},
    )
    def test_failed_generation_blocks_incomplete_refund_evidence(self, _credit_net):
        task = {"tool_type": "video_generation", "task_id": "remote-refund-pending"}
        record_submit_credit_attempt(task, {"task_id": task["task_id"], "submit_response": {"code": 200}})
        settle_credit_attempt(task, "failed", {"status": "failed"})

        attempt = task["credit_attempts"][0]
        self.assertIsNone(attempt["actual_charged_credits"])
        self.assertEqual(attempt["charge_status"], "FAILED_CREDIT_REFUND_EVIDENCE_INCOMPLETE")

    @patch("tools.episode_parallel_batch_supervisor.now", return_value="2026-07-20T09:00:00-0700")
    def test_success_without_credit_is_explicitly_unknown(self, _now):
        task = {"tool_type": "image_generation", "task_id": "remote-b"}
        record_submit_credit_attempt(task, {"task_id": "remote-b", "submit_response": {"data": {"task_id": "remote-b"}}})
        settle_credit_attempt(task, "completed", {"status": "completed"})
        receipt = {"tasks": [task]}
        refresh_credit_summary(receipt)

        self.assertIsNone(task["credit_attempts"][0]["actual_charged_credits"])
        self.assertEqual(receipt["credit_summary"]["successful_unknown_credit_count"], 1)
        self.assertFalse(receipt["credit_summary"]["actual_total_complete"])

    @patch("tools.episode_parallel_batch_supervisor.subprocess.run")
    def test_local_tool_preserves_full_stdout_in_sidecar(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = "x" * 5000
        run.return_value.stderr = ""
        with TemporaryDirectory() as tmp:
            video = Path(tmp) / "video.mp4"
            video.write_bytes(b"video")
            report = Path(tmp) / "report.json"
            result = run_local_tool(
                {
                    "task_key": "review",
                    "tool_type": "ai_review",
                    "video": str(video),
                    "command": ["review", "{video}"],
                    "report": str(report),
                },
                {"tasks": []},
            )

            self.assertEqual(len(result["tool_result"]["stdout"]), 4000)
            self.assertEqual(Path(result["tool_result"]["stdout_path"]).read_text(), "x" * 5000)

    def test_script_readiness_gate_requires_pass_when_declared(self):
        with TemporaryDirectory() as tmp:
            report = Path(tmp) / "readiness.json"
            report.write_text(json.dumps({"status": "FAIL"}), encoding="utf-8")

            ok, path, payload, failures = validate_script_readiness({"script_readiness_report": str(report)})

        self.assertFalse(ok)
        self.assertEqual(path, str(report))
        self.assertEqual(payload["status"], "FAIL")
        self.assertEqual(failures[0]["check"], "script_readiness_status")

    def test_script_readiness_gate_accepts_explicit_pass(self):
        with TemporaryDirectory() as tmp:
            report = Path(tmp) / "readiness.json"
            report.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")

            ok, path, payload, failures = validate_script_readiness({"script_readiness_report": str(report)})

        self.assertTrue(ok)
        self.assertEqual(path, str(report))
        self.assertEqual(payload["status"], "PASS")
        self.assertEqual(failures, [])

    def test_script_readiness_gate_is_optional_for_non_script_tools(self):
        self.assertEqual(validate_script_readiness({}), (True, None, None, []))

    def test_e27_media_batch_requires_writer_agent_provenance(self):
        ok, failures = validate_writer_agent_provenance({
            "episode": "E27",
            "tasks": [{"tool_type": "image_generation"}],
        })
        self.assertFalse(ok)
        self.assertTrue(any(row["check"] == "writer_agent_provenance_status" for row in failures))

    def test_e27_media_batch_accepts_exact_v030_generated_and_compiled_sha(self):
        with TemporaryDirectory() as tmp:
            paths = {}
            for name in ("generated_script", "compiled_script"):
                path = Path(tmp) / f"{name}.json"
                path.write_text(json.dumps({"agent_version": "0.3.0", "schema_version": "1.2.0"}), encoding="utf-8")
                paths[name] = str(path)
                paths[f"{name}_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            ok, failures = validate_writer_agent_provenance({
                "episode": "E27",
                "tasks": [{"tool_type": "video_generation"}],
                "writer_agent_provenance": {
                    "status": "PASS",
                    "agent_version": "0.3.0",
                    "schema_version": "1.2.0",
                    **paths,
                },
            })
        self.assertTrue(ok)
        self.assertEqual(failures, [])

    def test_e27_media_batch_rejects_retired_v020_provenance(self):
        ok, failures = validate_writer_agent_provenance({
            "episode": "E27",
            "tasks": [{"tool_type": "image_generation"}],
            "writer_agent_provenance": {
                "status": "PASS",
                "agent_version": "0.2.0",
                "schema_version": "1.1.0",
            },
        })
        self.assertFalse(ok)
        self.assertTrue(any(row["check"] == "writer_agent_version" for row in failures))
        self.assertTrue(any(row["check"] == "writer_agent_schema_version" for row in failures))

    def test_e28_batch_without_explicit_supervisor_gate_is_not_blocked(self):
        result = validate_supervisor_script_gate({
            "episode": "E28",
            "tasks": [{"tool_type": "image_generation"}],
            "writer_agent_provenance": {},
        })
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["generation_allowed"])

    def test_e28_batch_with_explicit_supervisor_gate_still_requires_report(self):
        result = validate_supervisor_script_gate({
            "episode": "E28",
            "tasks": [{"tool_type": "image_generation"}],
            "writer_agent_provenance": {},
            "supervisor_script_gate_required": True,
        })
        self.assertEqual(result["status"], "FAIL")
        self.assertFalse(result["generation_allowed"])

    def test_e29_accepts_exact_claude_script_provenance(self):
        with TemporaryDirectory() as tmp:
            script = Path(tmp) / "script.md"
            manifest = Path(tmp) / "manifest.json"
            script.write_text("claude script", encoding="utf-8")
            manifest.write_text("{}", encoding="utf-8")
            ok, failures = validate_writer_agent_provenance({
                "episode": "E29",
                "tasks": [{"tool_type": "video_generation"}],
                "writer_agent_provenance": {
                    "status": "PASS",
                    "provenance_type": "claude_writer_script",
                    "source_script": str(script),
                    "source_script_sha256": hashlib.sha256(script.read_bytes()).hexdigest(),
                    "production_manifest": str(manifest),
                    "production_manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
                },
            })
        self.assertTrue(ok)
        self.assertEqual(failures, [])

    def test_e27_batch_does_not_require_new_cl2x499_gate(self):
        result = validate_supervisor_script_gate({
            "episode": "E27",
            "tasks": [{"tool_type": "video_generation"}],
        })
        self.assertEqual(result["status"], "PASS")
        self.assertTrue(result["generation_allowed"])

    def test_e28_plus_requires_corrected_pipeline_quality_reports(self):
        from tools.episode_parallel_batch_supervisor import validate_corrected_pipeline_quality

        result = validate_corrected_pipeline_quality({"episode": "E28"})
        self.assertEqual(result["status"], "FAIL")
        self.assertIn(
            "corrected_pipeline_report_missing:dramatic_quality_report_ref",
            result["failures"],
        )
        self.assertIn(
            "corrected_pipeline_report_missing:anchor_count_plan_ref",
            result["failures"],
        )
        self.assertIn(
            "corrected_pipeline_report_missing:common_sense_causality_plan_ref",
            result["failures"],
        )
        self.assertIn(
            "corrected_pipeline_report_missing:period_lock_plan_ref",
            result["failures"],
        )

    def test_e27_is_outside_corrected_pipeline_activation(self):
        from tools.episode_parallel_batch_supervisor import validate_corrected_pipeline_quality

        result = validate_corrected_pipeline_quality({"episode": "E27"})
        self.assertEqual(result["status"], "NOT_APPLICABLE")

    def test_remote_task_ids_count_as_real_activity_without_local_pid(self):
        self.assertTrue(line_has_active_handle({"local_pid": None, "task_ids": ["remote-id"]}))
        self.assertFalse(line_has_active_handle({"local_pid": None, "task_ids": [], "task_count": 0}))

    def test_successful_scene_gate_clears_stale_block_fields(self):
        receipt = {
            "status": "BLOCKED_SCENE_AUTHORITY_LOCK",
            "scene_contract_ref": "configs/missing.json",
            "failures": [{"check": "state_bible_load"}],
            "rollback": "restore",
            "recorded_at": "old",
        }

        clear_resolved_scene_block(receipt, "configs/current.json", Path("qa/current_scene_gate.json"))

        self.assertNotIn("failures", receipt)
        self.assertNotIn("rollback", receipt)
        self.assertNotIn("recorded_at", receipt)
        self.assertEqual(receipt["scene_contract_ref"], "configs/current.json")
        self.assertEqual(receipt["scene_authority_report"], "qa/current_scene_gate.json")

    @patch("tools.episode_parallel_batch_supervisor.subprocess.run")
    def test_omni_video_forwards_all_entity_image_and_voice_asset_references(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps({"data": {"task_id": "remote-task"}})
        run.return_value.stderr = ""
        with TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "prompt.txt"
            prompt.write_text("standard storyboard prompt", encoding="utf-8")
            result = submit_one(
                {
                    "task_key": "storyboard-poc",
                    "tool_type": "video_generation",
                    "character_free_unit": True,
                    "canonical_characters": [],
                    "canonical_props": [],
                    "prompt_file": str(prompt),
                    "reference_images": [str(Path(tmp) / "char.png"), str(Path(tmp) / "scene.png")],
                    "resolved_reference_image_asset_ids": ["char-image", "scene-image"],
                    "reference_audio_asset_ids": ["voice-a", "voice-b"],
                    "model": "seedance-2.0-pro",
                    "duration": 15,
                    "aspect_ratio": "9:16",
                    "resolution": "720p",
                },
                {"tasks": []},
            )

        command = run.call_args.args[0]
        self.assertEqual(result["task_id"], "remote-task")
        self.assertEqual(command.count("--reference-image"), 0)
        self.assertEqual(command.count("--image-asset-id"), 2)
        self.assertEqual(command.count("--audio-asset-id"), 2)
        self.assertIn("voice-a", command)
        self.assertIn("voice-b", command)

    @patch("tools.episode_parallel_batch_supervisor.subprocess.run")
    def test_image_generation_uses_local_reference_paths_not_video_asset_flags(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps({"data": {"task_id": "image-task"}})
        run.return_value.stderr = ""
        with TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "prompt.txt"
            image = Path(tmp) / "reference.png"
            prompt.write_text("image prompt", encoding="utf-8")
            image.write_bytes(b"png")
            result = submit_one(
                {
                    "task_key": "image-unit",
                    "tool_type": "image_generation",
                    "canonical_characters": [],
                    "canonical_props": [],
                    "prompt_file": str(prompt),
                    "reference_images": [str(image)],
                    "resolved_reference_image_asset_ids": ["video-only-asset-id"],
                },
                {"tasks": []},
            )

        command = run.call_args.args[0]
        self.assertEqual(result["task_id"], "image-task")
        self.assertEqual(command.count("--reference-image"), 1)
        self.assertIn(str(image), command)
        self.assertNotIn("--image-asset-id", command)
        self.assertNotIn("video-only-asset-id", command)

    @patch("tools.episode_parallel_batch_supervisor.subprocess.run")
    def test_inline_image_transport_bypasses_registered_asset_ids(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps({"data": {"task_id": "inline-task"}})
        run.return_value.stderr = ""
        with TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "prompt.txt"
            image = Path(tmp) / "anchor.jpg"
            prompt.write_text("prompt", encoding="utf-8")
            image.write_bytes(b"jpeg")
            result = submit_one(
                {
                    "task_key": "inline-unit",
                    "tool_type": "video_generation",
                    "character_free_unit": True,
                    "canonical_characters": [],
                    "canonical_props": [],
                    "prompt_file": str(prompt),
                    "reference_images": [str(image)],
                    "reference_image_transport": "inline_base64",
                    "resolved_reference_image_asset_ids": ["stale-asset-id"],
                    "duration": 4,
                },
                {"tasks": []},
            )

        command = run.call_args.args[0]
        self.assertEqual(result["task_id"], "inline-task")
        self.assertEqual(command.count("--reference-image"), 1)

    @patch("tools.episode_parallel_batch_supervisor.subprocess.run")
    def test_direct_url_image_transport_bypasses_registered_asset_ids(self, run):
        run.return_value.returncode = 0
        run.return_value.stdout = json.dumps({"data": {"task_id": "remote-task"}})
        run.return_value.stderr = ""
        with TemporaryDirectory() as tmp:
            prompt = Path(tmp) / "prompt.txt"
            image = Path(tmp) / "anchor.jpg"
            prompt.write_text("prompt", encoding="utf-8")
            image.write_bytes(b"jpeg")
            result = submit_one({
                "task_key": "url-unit",
                "tool_type": "video_generation",
                "character_free_unit": True,
                "canonical_characters": [],
                "canonical_props": [],
                "prompt_file": str(prompt),
                "reference_image_transport": "direct_url",
                "reference_images": [str(image)],
                "reference_image_urls": ["https://assets.example/chenji.jpg"],
                "resolved_reference_image_asset_ids": ["stale-asset-id"],
                "duration": 4,
            }, {"tasks": []})
        self.assertEqual(result["task_id"], "remote-task")
        command = run.call_args.args[0]
        self.assertIn("--image-url", command)
        self.assertIn("https://assets.example/chenji.jpg", command)
        self.assertNotIn("--image-asset-id", command)
        self.assertNotIn("--reference-image", command)
        self.assertEqual(command.count("--image-asset-id"), 0)

    @patch("tools.episode_parallel_batch_supervisor.subprocess.run")
    def test_entity_reference_sequence_forwards_resolved_audio_and_video_asset_ids(self, run):
        def fake_run(command, **_kwargs):
            if "-show_entries" in command:
                return SimpleNamespace(returncode=0, stdout=json.dumps({"streams": [{"width": 512, "height": 512}]}), stderr="")
            return SimpleNamespace(returncode=0, stdout=json.dumps({"data": {"task_id": "remote-entity-task"}}), stderr="")

        run.side_effect = fake_run
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            prompt = root / "prompt.txt"
            prompt.write_text("entity reference sequence prompt", encoding="utf-8")
            image = root / "scene.png"
            image_b = root / "scene-result.png"
            audio = root / "line.wav"
            video_a = root / "action-a.mp4"
            video_b = root / "action-b.mp4"
            write_test_png(image)
            write_test_png(image_b)
            for path in (audio, video_a, video_b):
                path.write_bytes(path.name.encode("utf-8"))
            assets = [
                {"slot_id": path.stem, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in (image, audio, video_a, video_b)
            ]
            result = submit_one(
                {
                    "task_key": "entity-unit",
                    "tool_type": "video_generation",
                    "character_free_unit": True,
                    "canonical_characters": [],
                    "canonical_props": [],
                    "generation_mode": "entity_reference_sequence",
                    "batch_id": "E27-B01",
                    "unit_id": "U01",
                    "planned_reference_image_count": 2,
                    "state_reference_minimum": 2,
                    "action_reference_minimum": 2,
                    "prompt_file": str(prompt),
                    "reference_images": [str(image), str(image_b)],
                    "reference_image_sequence": [
                        {"state_id": "C1", "path": str(image)},
                        {"state_id": "C2", "path": str(image_b)},
                    ],
                    "reference_audios": [str(audio)],
                    "reference_videos": [str(video_a), str(video_b)],
                    "resolved_reference_audio_asset_ids": ["audio-asset"],
                    "resolved_reference_video_asset_ids": ["video-a-asset", "video-b-asset"],
                    "reference_assets": assets,
                },
                {"tasks": []},
            )

        command = run.call_args.args[0]
        self.assertEqual(result["task_id"], "remote-entity-task")
        self.assertEqual(command.count("--audio"), 0)
        self.assertEqual(command.count("--video"), 0)
        self.assertEqual(command.count("--audio-asset-id"), 1)
        self.assertEqual(command.count("--video-asset-id"), 2)

    @patch("tools.episode_parallel_batch_supervisor.upload_giggle_asset")
    def test_local_image_audio_and_video_are_registered_once_per_sha(self, upload):
        upload.side_effect = lambda path, _public: {
            "data": {
                "asset_id": {
                    ".png": "image-asset",
                    ".wav": "audio-asset",
                    ".mp4": "video-asset",
                }[Path(path).suffix],
                "signed_url": f"https://assets/{Path(path).name}",
            }
        }
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "anchor.png"
            audio = root / "line.wav"
            video = root / "action.mp4"
            image.write_bytes(b"image")
            audio.write_bytes(b"audio")
            video.write_bytes(b"video")
            receipt = {
                "tasks": [
                    {"state": "pending", "reference_images": [str(image)], "reference_audios": [str(audio)], "reference_videos": [str(video)]},
                    {"state": "pending", "reference_images": [str(image)], "reference_audios": [str(audio)], "reference_videos": [str(video)]},
                ]
            }

            prepare_local_reference_assets(receipt)

        self.assertEqual(upload.call_count, 3)
        for task in receipt["tasks"]:
            self.assertEqual(task["resolved_reference_image_asset_ids"], ["image-asset"])
            self.assertEqual(task["resolved_reference_audio_asset_ids"], ["audio-asset"])
            self.assertEqual(task["resolved_reference_video_asset_ids"], ["video-asset"])

    @patch("tools.episode_parallel_batch_supervisor.upload_giggle_asset")
    def test_complete_configured_image_asset_ids_are_reused_without_upload_or_duplication(self, upload):
        with TemporaryDirectory() as tmp:
            image_a = Path(tmp) / "a.png"
            image_b = Path(tmp) / "b.png"
            image_a.write_bytes(b"image-a")
            image_b.write_bytes(b"image-b")
            receipt = {
                "tasks": [{
                    "state": "pending",
                    "reference_image_transport": "registered_asset_id",
                    "reference_images": [str(image_a), str(image_b)],
                    "reference_image_asset_ids": ["asset-a", "asset-b"],
                }]
            }

            prepare_local_reference_assets(receipt)

        upload.assert_not_called()
        self.assertEqual(receipt["tasks"][0]["resolved_reference_image_asset_ids"], [])

    def test_entity_reference_sequence_allows_one_planned_still_but_still_requires_video_reference(self):
        failures = validate_entity_reference_task({
            "generation_mode": "entity_reference_sequence",
            "batch_id": "E27-B01",
            "unit_id": "U01",
            "planned_reference_image_count": 1,
            "state_reference_minimum": 1,
            "action_reference_minimum": 2,
            "reference_images": ["scene.png"],
            "reference_audios": ["line.wav"],
            "reference_videos": ["only-one.mp4"],
        })

        self.assertTrue(any(row["check"] == "temporal_action_references" for row in failures))
        self.assertFalse(any(row["check"] == "temporal_image_states" for row in failures))

    def test_entity_reference_sequence_accepts_ordered_still_only_mode(self):
        with TemporaryDirectory() as tmp:
            images = [Path(tmp) / f"c{index}.png" for index in range(1, 4)]
            for image in images:
                write_test_png(image)
            failures = validate_entity_reference_task({
                "generation_mode": "entity_reference_sequence",
                "batch_id": "E29-B01",
                "unit_id": "U01",
                "planned_reference_image_count": 3,
                "state_reference_minimum": 3,
                "still_sequence_only_allowed": True,
                "audio_reference_optional": True,
                "action_reference_minimum": 0,
                "reference_images": [str(image) for image in images],
                "reference_image_sequence": [
                    {"state_id": f"C{index}", "path": str(image)}
                    for index, image in enumerate(images, 1)
                ],
                "action_unit": True,
            })

        self.assertEqual(failures, [])

    def test_entity_reference_sequence_accepts_one_composite_with_multiple_temporal_segments(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "scene.png"
            audio = root / "sequence.wav"
            video = root / "action-sequence.mp4"
            write_test_png(image)
            for path in (audio, video):
                path.write_bytes(path.name.encode("utf-8"))
            assets = [
                {"slot_id": path.stem, "path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
                for path in (image, audio, video)
            ]
            failures = validate_entity_reference_task({
                "generation_mode": "entity_reference_sequence",
                "batch_id": "E27-B01",
                "unit_id": "U01",
                "planned_reference_image_count": 2,
                "state_reference_minimum": 2,
                "action_reference_minimum": 1,
                "reference_images": [str(image), str(image)],
                "reference_image_sequence": [
                    {"state_id": "C1", "path": str(image)},
                    {"state_id": "C2", "path": str(image)},
                ],
                "reference_audios": [str(audio)],
                "reference_videos": [str(video)],
                "reference_video_sequence": {
                    "segments": [{"source": "N01"}, {"source": "N02"}],
                    "single_still_only": False,
                },
                "reference_assets": assets,
            })

        self.assertEqual(failures, [])

    def test_action_entity_reference_sequence_uses_its_planned_anchor_count(self):
        failures = validate_entity_reference_task({
            "generation_mode": "entity_reference_sequence",
            "batch_id": "E29-B01",
            "unit_id": "U01",
            "planned_reference_image_count": 2,
            "state_reference_minimum": 2,
            "action_unit": True,
            "action_reference_minimum": 1,
            "reference_images": ["c1.png", "c2.png"],
            "reference_image_sequence": [
                {"state_id": "C1", "path": "c1.png"},
                {"state_id": "C2", "path": "c2.png"},
            ],
            "reference_audios": ["line.wav"],
            "reference_videos": ["action.mp4"],
            "reference_video_sequence": {"segments": [{"source": "A"}, {"source": "B"}]},
        })

        self.assertFalse(any(row["check"] == "temporal_image_states" for row in failures))

    def test_performance_generation_uses_action_design_anchor_count_and_exact_dialogue_audio(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "anchor.png"
            audio = root / "D1.wav"
            write_test_png(image)
            audio.write_bytes(b"exact line")
            failures = validate_entity_reference_task({
                "generation_mode": "performance_generation",
                "batch_id": "E30-U01-R1",
                "unit_id": "U01",
                "still_sequence_only_allowed": True,
                "planned_reference_image_count": 1,
                "state_reference_minimum": 1,
                "reference_images": [str(image)],
                "reference_image_sequence": [{"state_id": "ANCHOR", "path": str(image)}],
                "reference_audios": [str(audio)],
                "native_dialogue_required": True,
                "dialogue": [{"dia_id": "D1", "speaker": "刺客", "spoken_text": "别动。"}],
                "dialogue_audio_assets": [{
                    "dia_id": "D1", "speaker": "刺客", "spoken_text": "别动。",
                    "path": str(audio), "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                    "purpose": "EXACT_TARGET_DIALOGUE_REFERENCE",
                }],
                "performance_spec": {
                    "prop_ownership": {"knife": "刺客右手"},
                    "motion_beats": [{
                        "subject": "刺客右手", "action": "持刀",
                        "contact_point": "刀柄", "direction": "向前", "end_state": "刀停住",
                        "intent": "刺穿防御", "visible_causality": "刀尖撞上光幕并激起涟漪",
                        "expression": "刺客由自信转为惊疑", "viewer_read": "光幕阻止刀锋前进",
                    }],
                },
                "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": 0},
            })

        self.assertEqual(failures, [])

    def test_performance_generation_forwards_locked_native_voice_by_registered_asset_id(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "anchor.png"
            audio = root / "locked-native.wav"
            write_test_png(image)
            audio.write_bytes(b"locked voice")
            failures = validate_entity_reference_task({
                "generation_mode": "performance_generation",
                "batch_id": "E32-U01-V2",
                "unit_id": "E32-CW-U01",
                "still_sequence_only_allowed": True,
                "planned_reference_image_count": 1,
                "state_reference_minimum": 1,
                "reference_images": [str(image)],
                "reference_image_sequence": [{"state_id": "A1", "path": str(image)}],
                "reference_audio_asset_ids": ["locked-chenji-voice"],
                "native_dialogue_required": True,
                "dialogue": [{"dia_id": "D1", "speaker": "陈迹", "spoken_text": "名单不会。"}],
                "dialogue_audio_assets": [{
                    "dia_id": "D1", "speaker": "陈迹", "spoken_text": "名单不会。",
                    "path": str(audio), "sha256": hashlib.sha256(audio.read_bytes()).hexdigest(),
                    "remote_asset_id": "locked-chenji-voice",
                    "purpose": "LOCKED_NATIVE_VOICE_STYLE_REFERENCE_WITH_EXACT_TEXT",
                }],
                "performance_spec": {
                    "prop_ownership": {"名单": "陈迹面前案面"},
                    "motion_beats": [{
                        "subject": "陈迹", "action": "看向名单并开口",
                        "contact_point": "目光落在名单", "direction": "视线向下",
                        "end_state": "说完后仍凝视名单", "intent": "确认名单可信",
                        "visible_causality": "目光与台词共同指向名单",
                        "expression": "冷静笃定", "viewer_read": "陈迹相信名单而非印章",
                    }],
                },
                "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": 0},
            })

        self.assertEqual(failures, [])

    def test_performance_generation_blocks_unplanned_anchor_count(self):
        failures = validate_entity_reference_task({
            "generation_mode": "performance_generation",
            "batch_id": "E30-U01-R1",
            "unit_id": "U01",
            "still_sequence_only_allowed": True,
            "audio_reference_optional": True,
            "planned_reference_image_count": 1,
            "state_reference_minimum": 1,
            "reference_images": ["a.png", "b.png"],
            "reference_image_sequence": [{"state_id": "A"}, {"state_id": "B"}],
            "performance_spec": {
                "prop_ownership": {"knife": "刺客右手"},
                "motion_beats": [{
                    "subject": "刺客右手", "action": "持刀",
                    "contact_point": "刀柄", "direction": "向前", "end_state": "刀停住",
                    "intent": "刺穿防御", "visible_causality": "刀尖撞上光幕并激起涟漪",
                    "expression": "刺客由自信转为惊疑", "viewer_read": "光幕阻止刀锋前进",
                }],
            },
            "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": 1},
        })

        self.assertTrue(any(row["check"] == "dynamic_anchor_count" for row in failures))

    def test_performance_generation_excludes_reference_only_images_from_temporal_chain(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            tail = root / "previous-tail.png"
            composition = root / "owner-contact-composition.png"
            identity = root / "identity.png"
            terminal = root / "terminal-target.png"
            for path in (tail, composition, identity, terminal):
                write_test_png(path)
            failures = validate_entity_reference_task({
                "generation_mode": "performance_generation",
                "batch_id": "E37-B03-R2",
                "unit_id": "B03",
                "still_sequence_only_allowed": True,
                "audio_reference_optional": True,
                "planned_reference_image_count": 2,
                "state_reference_minimum": 2,
                "reference_images": [str(tail), str(composition), str(identity), str(terminal)],
                "reference_image_sequence": [
                    {"state_id": "TAIL", "path": str(tail), "role": "EXACT_PREVIOUS_TAIL_TEMPORAL"},
                    {
                        "state_id": "OWNER_CONTACT",
                        "path": str(composition),
                        "role": "ABILITY_OWNER_CONTACT_COMPOSITION_REFERENCE_ONLY",
                    },
                    {"state_id": "IDENTITY", "path": str(identity), "role": "CHARACTER_IDENTITY_REFERENCE"},
                    {"state_id": "TERMINAL", "path": str(terminal), "role": "TERMINAL_SPATIAL_TARGET"},
                ],
                "performance_spec": {
                    "prop_ownership": {"paper": "云阳手中"},
                    "motion_beats": [{
                        "subject": "云阳", "action": "触纸并展开纸人",
                        "contact_point": "指尖与纸面", "direction": "向下接触后向外展开",
                        "end_state": "纸人举掌承住落梁", "intent": "阻止落梁砸中众人",
                        "visible_causality": "云阳触纸导致纸人展开，纸人举掌承梁",
                        "expression": "专注", "viewer_read": "能力归属与动作因果清楚",
                    }],
                },
                "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": 1},
            })

        self.assertEqual(failures, [])

    def test_performance_generation_reports_unstructured_prop_ownership_without_crashing(self):
        failures = validate_entity_reference_task({
            "generation_mode": "performance_generation",
            "batch_id": "E33-V1",
            "unit_id": "U01",
            "still_sequence_only_allowed": True,
            "audio_reference_optional": True,
            "planned_reference_image_count": 1,
            "state_reference_minimum": 1,
            "reference_images": ["anchor.png"],
            "reference_image_sequence": [{"state_id": "ANCHOR"}],
            "performance_spec": {
                "prop_ownership": "props never teleport",
                "motion_beats": [{
                    "subject": "陈迹", "action": "向檐影撤步",
                    "contact_point": "鞋底与湿地", "direction": "向侧后方",
                    "end_state": "陈迹停在檐影", "intent": "避开合围",
                    "visible_causality": "兵潮合拢迫使他撤步",
                    "expression": "冷静警觉", "viewer_read": "退路正在消失",
                }],
            },
            "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": 0},
        })

        self.assertTrue(any(
            row["check"] == "performance_prop_ownership"
            and row["error"] == "must_be_structured_object"
            for row in failures
        ))

    def test_performance_generation_identity_reference_is_not_temporal_keyframe(self):
        with TemporaryDirectory() as tmp:
            scene = Path(tmp) / "scene.png"
            chenji = Path(tmp) / "chenji.png"
            write_test_png(scene)
            write_test_png(chenji)
            failures = validate_entity_reference_task({
            "generation_mode": "performance_generation",
            "batch_id": "E31-U18-B-R3",
            "unit_id": "U18-B",
            "still_sequence_only_allowed": True,
            "audio_reference_optional": True,
            "planned_reference_image_count": 1,
            "state_reference_minimum": 1,
            "reference_images": [str(scene), str(chenji)],
            "reference_image_sequence": [
                {"role": "A1", "path": str(scene)},
                {"role": "CHENJI_IDENTITY", "path": str(chenji)},
            ],
            "performance_spec": {
                "prop_ownership": {"token": "云羊右手"},
                "motion_beats": [{
                    "subject": "陈迹", "action": "望向骨牌后转看残火",
                    "contact_point": "双手不接触骨牌", "direction": "视线由近及远",
                    "end_state": "陈迹完成权力链判断", "intent": "辨认发令层级",
                    "visible_causality": "看见骨牌后说出判断并回看云羊",
                    "expression": "冷静推断", "viewer_read": "陈迹是唯一说话人",
                }],
            },
            "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": 0},
            })

        self.assertEqual(failures, [])

    def test_identity_references_do_not_satisfy_missing_temporal_anchor(self):
        failures = validate_entity_reference_task({
            "generation_mode": "performance_generation",
            "batch_id": "E32-U04-V2",
            "unit_id": "U04",
            "still_sequence_only_allowed": True,
            "audio_reference_optional": True,
            "planned_reference_image_count": 2,
            "state_reference_minimum": 2,
            "reference_images": ["origin.png", "jiaotu.png"],
            "reference_image_sequence": [
                {"role": "PERFORMANCE_START", "path": "origin.png"},
                {"role": "IDENTITY_REFERENCE_JIAOTU", "path": "jiaotu.png"},
            ],
            "performance_spec": {
                "prop_ownership": {"body": "皎兔肉身留在医馆"},
                "motion_beats": [{
                    "subject": "皎兔阴神", "action": "从肉身分离并飞向暗楼",
                    "contact_point": "眉心血痕", "direction": "医馆至西市暗楼",
                    "end_state": "阴神抵达暗楼窗外", "intent": "跨空间侦察",
                    "visible_causality": "沿雨城连续飞行并在目标窗框制动",
                    "expression": "冷峻警觉", "viewer_read": "阴神跨空间抵达新地点",
                }],
            },
            "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": 0},
        })

        self.assertTrue(any(row["check"] == "temporal_image_states" for row in failures))

    def test_single_image_can_be_temporal_start_and_identity_lock(self):
        with TemporaryDirectory() as tmp:
            qisan = Path(tmp) / "qisan.png"
            write_test_png(qisan)
            failures = validate_entity_reference_task({
            "generation_mode": "performance_generation",
            "batch_id": "E32-U05-V2",
            "unit_id": "U05",
            "still_sequence_only_allowed": True,
            "audio_reference_optional": True,
            "planned_reference_image_count": 1,
            "state_reference_minimum": 1,
            "reference_images": [str(qisan)],
            "reference_image_sequence": [{
                "asset_label": "@图片1",
                "role": "PERFORMANCE_START",
                "path": str(qisan),
                "identity_reference": True,
            }],
            "performance_spec": {
                "prop_ownership": {"letters": "齐三"},
                "motion_beats": [{
                    "subject": "齐三", "action": "拆分名单并装入信封",
                    "contact_point": "双手与名单信封", "direction": "由案心向左右",
                    "end_state": "数封信分列案面", "intent": "把同一消息卖给多家",
                    "visible_causality": "每份名单经齐三双手装入一封信",
                    "expression": "贪婪警觉", "viewer_read": "齐三熟练拆分同一批名单",
                }],
            },
            "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": 0},
            })

        self.assertEqual(failures, [])

    def test_performance_generation_blocks_motion_without_visible_purpose(self):
        failures = validate_entity_reference_task({
            "generation_mode": "performance_generation",
            "batch_id": "E30-U01-R2",
            "unit_id": "U01",
            "still_sequence_only_allowed": True,
            "audio_reference_optional": True,
            "planned_reference_image_count": 1,
            "state_reference_minimum": 1,
            "reference_images": ["anchor.png"],
            "reference_image_sequence": [{"state_id": "ANCHOR"}],
            "performance_spec": {
                "prop_ownership": {"knife": "刺客右手"},
                "motion_beats": [{
                    "subject": "刺客右手", "action": "推刀",
                    "contact_point": "刀柄", "direction": "向前", "end_state": "刀停住",
                }],
            },
            "keyframe_interpolation_gate": {"status": "PASS", "checked_adjacent_pairs": 0},
        })

        issue = next(row for row in failures if row["check"] == "performance_motion_beat")
        self.assertEqual(issue["missing"], ["expression", "intent", "viewer_read", "visible_causality"])

    def test_entity_reference_sequence_blocks_missing_required_slot(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "scene.png"
            audio = root / "line.wav"
            video_a = root / "action-a.mp4"
            video_b = root / "action-b.mp4"
            for path in (image, audio, video_a, video_b):
                path.write_bytes(path.name.encode("utf-8"))
            failures = validate_entity_reference_task({
                "generation_mode": "entity_reference_sequence",
                "batch_id": "E27-B01",
                "unit_id": "U01",
                "action_reference_minimum": 2,
                "reference_images": [str(image), str(image)],
                "reference_image_sequence": [
                    {"state_id": "C1", "path": str(image)},
                    {"state_id": "C2", "path": str(image)},
                ],
                "reference_audios": [str(audio)],
                "reference_videos": [str(video_a), str(video_b)],
                "required_slot_ids": ["SCENE::S01", "CHAR::lead"],
                "reference_assets": [
                    {"slot_id": "SCENE::S01", "path": str(image), "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
                ],
            })

        self.assertTrue(any(row["check"] == "required_asset_slots" and "CHAR::lead" in row["missing"] for row in failures))

    def test_released_episode_cannot_occupy_active_slot(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_dir = root / "workflow" / "release" / "e20"
            release_dir.mkdir(parents=True)
            (release_dir / "E20_RELEASE.json").write_text(
                json.dumps({"status": "RELEASED_YOUTUBE_AND_DOUYIN"}),
                encoding="utf-8",
            )

            self.assertTrue(episode_has_release_record("E20", root))
            self.assertFalse(episode_has_release_record("E21", root))

    def test_both_platforms_public_release_cannot_occupy_active_slot(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_dir = root / "workflow" / "release" / "e22"
            release_dir.mkdir(parents=True)
            (release_dir / "E22_RELEASE.json").write_text(
                json.dumps({"status": "BOTH_PLATFORMS_PUBLIC_RELEASE_COMPLETE"}),
                encoding="utf-8",
            )

            self.assertTrue(episode_has_release_record("E22", root))

    def test_grandfathered_two_platform_public_release_cannot_occupy_active_slot(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            release_dir = root / "workflow" / "release" / "e24"
            release_dir.mkdir(parents=True)
            (release_dir / "E24_RELEASE.json").write_text(
                json.dumps({
                    "status": "GRANDFATHERED_PUBLIC_CL2X380",
                    "youtube": {"status": "PUBLIC_GRANDFATHERED_FINAL"},
                    "douyin": {"status": "PUBLIC_GRANDFATHERED_FINAL"},
                }),
                encoding="utf-8",
            )

            self.assertTrue(episode_has_release_record("E24", root))

    def test_new_replacement_episode_is_appended_to_activity_snapshot(self):
        lines = [{"line_id": "LINE_E26", "episode": "E26"}]
        receipt = {
            "episode": "E27",
            "status": "BATCH_RUNNING",
            "local_pid": 123,
            "active_task_ids": ["remote-a"],
            "active_task_count": 1,
            "tasks": [{"task_key": "E27-B01", "state": "remote_running"}],
        }

        upsert_activity_line(lines, receipt, "workflow/tasks/E27.json")

        self.assertEqual([row["episode"] for row in lines], ["E26", "E27"])
        self.assertEqual(lines[1]["task_ids"], ["remote-a"])
        self.assertTrue(lines[1]["real_activity"])

    def test_zero_retry_budget_terminalizes_first_failure(self):
        task = {"state": "remote_running"}

        mark_retry_or_terminal(task, {"max_retries": 0}, "qa_failed_terminal")

        self.assertEqual(task["retry_count"], 1)
        self.assertEqual(task["state"], "qa_failed_terminal")

    @patch("tools.episode_parallel_batch_supervisor.run_qa")
    @patch("tools.episode_parallel_batch_supervisor.download")
    @patch("tools.episode_parallel_batch_supervisor.fetch_video_credit_by_task_id")
    @patch("tools.episode_parallel_batch_supervisor.query_task")
    def test_completed_video_qa_failure_never_auto_resubmits(
        self, query_task, credit_statement, download, run_qa
    ):
        query_task.return_value = {
            "data": {"status": "completed", "urls": ["https://example.test/video.mp4"]}
        }
        run_qa.return_value = {
            "status": "qa_failed",
            "failures": [{"check": "full_motion_ocr", "returncode": 1}],
        }
        credit_statement.return_value = {
            "status": "PASS",
            "endpoint": "/api/v1/payment/credit-statements",
            "charged_credits": 260,
            "matched_count": 1,
        }
        receipt = {
            "episode": "E27",
            "output_dir": "working_assets/test",
            "max_retries": 3,
            "tasks": [
                {
                    "task_key": "E27-N01",
                    "tool_type": "video_generation",
                    "task_id": "paid-remote-id",
                    "state": "remote_running",
                }
            ],
        }

        poll_and_harvest(receipt)

        task = receipt["tasks"][0]
        self.assertEqual(task["state"], "qa_failed_terminal")
        self.assertEqual(task["task_id"], "paid-remote-id")
        self.assertEqual(task["retry_count"], 1)
        self.assertEqual(task["failure_evidence"][0]["check"], "full_motion_ocr")

    @patch("tools.episode_parallel_batch_supervisor.run_qa")
    @patch("tools.episode_parallel_batch_supervisor.download")
    @patch("tools.episode_parallel_batch_supervisor.fetch_video_credit_by_task_id")
    @patch("tools.episode_parallel_batch_supervisor.query_task")
    def test_completed_video_cannot_enter_download_or_qa_without_exact_credit(
        self, query_task, credit_statement, download, run_qa
    ):
        query_task.return_value = {
            "data": {"status": "completed", "urls": ["https://example.test/video.mp4"]}
        }
        credit_statement.return_value = {
            "status": "INCOMPLETE",
            "endpoint": "/api/v1/payment/credit-statements",
            "charged_credits": None,
            "matched_count": 0,
        }
        receipt = {
            "episode": "E27",
            "output_dir": "working_assets/test",
            "tasks": [{
                "task_key": "E27-N01",
                "tool_type": "video_generation",
                "task_id": "paid-remote-id",
                "state": "remote_running",
            }],
        }

        poll_and_harvest(receipt)

        task = receipt["tasks"][0]
        self.assertEqual(task["state"], "completed_credit_accounting_incomplete")
        self.assertEqual(task["credit_accounting_block"], "EXACT_TASK_ID_STATEMENT_REQUIRED_BEFORE_DOWNLOAD_QA")
        download.assert_not_called()
        run_qa.assert_not_called()

    @patch("tools.episode_parallel_batch_supervisor.query_task")
    def test_terminal_remote_failures_are_not_polled_again(self, query_task):
        receipt = {
            "tasks": [
                {
                    "task_key": "failed-video",
                    "task_id": "remote-id",
                    "state": "remote_failed_terminal",
                    "retry_count": 1,
                }
            ]
        }

        poll_and_harvest(receipt)

        query_task.assert_not_called()
        self.assertEqual(receipt["tasks"][0]["retry_count"], 1)

    @patch("tools.episode_parallel_batch_supervisor.query_task")
    def test_transient_query_error_preserves_remote_task_for_next_poll(self, query_task):
        query_task.side_effect = TimeoutError("read timed out")
        receipt = {
            "tasks": [{
                "task_key": "image",
                "tool_type": "image_generation",
                "task_id": "remote-id",
                "state": "remote_running",
            }],
        }

        poll_and_harvest(receipt)

        task = receipt["tasks"][0]
        self.assertEqual(task["state"], "remote_running")
        self.assertEqual(task["task_id"], "remote-id")
        self.assertIn("TimeoutError", task["last_poll_error"])

    @patch("tools.episode_parallel_batch_supervisor.now", return_value="2026-07-18T18:00:00-0700")
    @patch("tools.episode_parallel_batch_supervisor.os.getpid", return_value=4321)
    def test_terminal_batch_clears_pid_and_normalizes_task_status(self, _pid, _now):
        receipt = {
            "local_pid": 1234,
            "max_retries": 1,
            "tasks": [
                {"task_key": "image", "task_id": "a", "state": "image_pass", "status": "remote_running"},
                {"task_key": "video", "task_id": "b", "state": "qa_pass", "status": "remote_running"},
            ],
        }

        refresh_activity_state(receipt)

        self.assertEqual(receipt["status"], "BATCH_COMPLETE")
        self.assertIsNone(receipt["local_pid"])
        self.assertEqual(receipt["finished_local_pid"], 1234)
        self.assertEqual(receipt["completed_at"], "2026-07-18T18:00:00-0700")
        self.assertEqual(receipt["active_task_count"], 0)
        self.assertEqual([task["status"] for task in receipt["tasks"]], ["image_pass", "qa_pass"])

    @patch("tools.episode_parallel_batch_supervisor.os.getpid", return_value=4321)
    def test_running_batch_keeps_real_pid_and_remote_ids(self, _pid):
        receipt = {
            "local_pid": None,
            "tasks": [
                {"task_key": "video", "task_id": "a", "state": "remote_running", "status": "pending"},
                {"task_key": "image", "task_id": "b", "state": "image_pass", "status": "remote_running"},
            ],
        }

        refresh_activity_state(receipt)

        self.assertEqual(receipt["status"], "BATCH_RUNNING")
        self.assertEqual(receipt["local_pid"], 4321)
        self.assertEqual(receipt["active_task_ids"], ["a"])
        self.assertEqual(receipt["active_task_count"], 1)
        self.assertEqual([task["status"] for task in receipt["tasks"]], ["remote_running", "image_pass"])


if __name__ == "__main__":
    unittest.main()
