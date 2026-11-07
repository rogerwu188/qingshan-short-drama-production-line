"""Provider reference exclusion (device …1324 E01 S5, 2026-11-06).

HopsAPI gpt-image-2 refused, deterministically and at zero cost, one engine-rendered reference (the
place map GSM-NALU-HUT_V1.png) that every S5 task binds.  A declared non-identity reference is kept as
spatial authority but not transmitted: the provider array and the @图片N / 参考图N numbering cover the
sent files only, the layout gate records an advisory, identity plates can never be excluded.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parents[2]
for _path in (str(REPO), str(REPO / "lines" / "nalu" / "runtime" / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from tools import provider_reference_exclusions as pre  # noqa: E402
from tools import isolate_rejected_reference as iso  # noqa: E402
from tools.global_space_layout_gate import RESOLUTION_ORDER, content_sha256, evaluate_batch  # noqa: E402
from tools.image_model_adapter import compile_labeled_flat_identity_transport  # noqa: E402

import build_keyframe_manifest as builder  # noqa: E402


def entry(**selector):
    return {**selector, "reason": "HOPSAPI_DETERMINISTIC_424_SINGLE_REFERENCE",
            "evidence": {"provider": "hopsapi", "provider_code": 424, "request_ids": ["aitk-1"],
                         "single_reference_probe": True},
            "declared_by": "test", "declared_at": "2026-11-06T00:00:00Z"}


def declaration(*entries):
    return {"schema": pre.SCHEMA, "episode": "E01", "exclusions": list(entries),
            "_source_path": "/rt/preproduction/E01/provider_reference_exclusions.json", "_source_sha256": "x"}


class Media:
    def __init__(self, root: Path):
        self.root = root

    def __call__(self, name: str) -> dict:
        path = self.root / name
        path.write_bytes(name.encode("utf-8"))
        return {"path": str(path), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "qa_status": "PASS"}


class Fixture(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        media = Media(self.root)
        self.episode_map, self.place_map, self.subspace = media("ep.png"), media("GSM-NALU-HUT_V1.png"), media("sub.png")
        self.face, self.wardrobe, self.prop = media("face.png"), media("body.png"), media("prop.png")

    def bindings(self):
        return [
            {"role": "episode_global_space_map", "entity_id": "EGSM-1", **self.episode_map},
            {"role": "global_space_map", "entity_id": "GSM-NALU-HUT", **self.place_map},
            {"role": "subspace_layout", "entity_id": "SUB-1", **self.subspace},
            {"role": "character", "entity_id": "CHAR-A", "kind": "CHARACTER_IDENTITY_PLATE", **self.face},
            {"role": "scene", "entity_id": "LOC-HUT", **self.subspace},
            {"role": "character_wardrobe", "entity_id": "CHAR-A", **self.wardrobe},
            {"role": "prop", "entity_id": "PROP-BUN", **self.prop},
        ]


class ApplyExclusions(Fixture):
    def test_no_declaration_is_unchanged(self):
        rows, applied = pre.apply_exclusions(self.bindings(), None)
        self.assertEqual(rows, self.bindings())
        self.assertEqual(applied, [])

    def test_place_map_excluded_renumbers_prompt_and_transport(self):
        rows, applied = pre.apply_exclusions(self.bindings(), declaration(entry(asset_id="GSM-NALU-HUT")), task_key="T")
        self.assertEqual([r["role"] for r in rows], [r["role"] for r in self.bindings()])  # authority kept
        place = rows[1]
        self.assertIs(place["transmitted"], False)
        self.assertEqual(place["transport_excluded_reason"], "HOPSAPI_DETERMINISTIC_424_SINGLE_REFERENCE")
        self.assertEqual(len(applied), 1)
        lines = builder.reference_use_lines(rows, {})
        self.assertFalse(any("GSM-NALU-HUT" in line for line in lines))
        self.assertEqual(len(lines), 6)
        prompt = "\n".join(lines)
        sequence, contract, compiled = compile_labeled_flat_identity_transport("T", pre.transmitted_bindings(rows), prompt)
        paths = list(dict.fromkeys(r["path"] for r in sequence))
        self.assertNotIn(self.place_map["path"], paths)
        self.assertEqual(len(paths), 5)  # scene shares the subspace file
        self.assertNotIn("GSM-NALU-HUT", compiled)
        self.assertNotIn("@图片6", compiled)
        self.assertIn("参考图1 character / CHAR-A", compiled)  # identity first, renumbered

    def test_legacy_lines_number_every_binding(self):
        self.assertEqual(len(builder.reference_use_lines(self.bindings(), {})), 7)

    def test_basename_selector_excludes_every_copy_of_the_file(self):
        rows, _ = pre.apply_exclusions(self.bindings(), declaration(entry(path="GSM-NALU-HUT_V1.png")))
        self.assertEqual([r["role"] for r in rows if r.get("transmitted") is False], ["global_space_map"])

    def test_file_level_exclusion_covers_shared_path(self):
        rows, _ = pre.apply_exclusions(self.bindings(), declaration(entry(sha256=self.subspace["sha256"])))
        self.assertEqual({r["role"] for r in rows if r.get("transmitted") is False}, {"subspace_layout", "scene"})

    def test_identity_plate_exclusion_is_refused(self):
        with self.assertRaisesRegex(pre.ExclusionError, "IDENTITY_REFUSED"):
            pre.apply_exclusions(self.bindings(), declaration(entry(sha256=self.face["sha256"])))
        with self.assertRaisesRegex(pre.ExclusionError, "IDENTITY_REFUSED"):
            pre.apply_exclusions(self.bindings(), declaration(entry(asset_id="CHAR-A")))

    def test_wardrobe_and_prop_may_be_excluded(self):
        rows, applied = pre.apply_exclusions(self.bindings(), declaration(
            entry(asset_id="CHAR-A", role="character_wardrobe"), entry(asset_id="PROP-BUN")))
        self.assertEqual({r["role"] for r in rows if r.get("transmitted") is False}, {"character_wardrobe", "prop"})
        self.assertEqual(len(applied), 2)

    def test_declaration_validation(self):
        bad = {"schema": pre.SCHEMA, "exclusions": [{"asset_id": "X", "reason": "r"}]}
        failures = pre.validate_declaration(bad)
        self.assertTrue(any("EVIDENCE_REQUIRED" in f for f in failures))
        self.assertTrue(any("DECLARED_BY_REQUIRED" in f for f in failures))
        good = {"schema": pre.SCHEMA, "episode": "E01", "exclusions": [entry(asset_id="X")]}
        self.assertEqual(pre.validate_declaration(good, episode="E01"), [])
        self.assertTrue(pre.validate_declaration(good, episode="E02"))
        path = self.root / pre.FILE_NAME
        self.assertIsNone(pre.load_declaration(path))
        path.write_text(json.dumps(bad), encoding="utf-8")
        with self.assertRaises(pre.ExclusionError):
            pre.load_declaration(path)


class LayoutGate(Fixture):
    def authority(self):
        place = {
            "global_space_map_id": "GSM-NALU-HUT", "map_version": 1, "name": "hut",
            "coordinate_system": {"origin": "sw", "x_axis": "east", "y_axis": "north", "unit": "m"},
            "overall_bounds": {"width": 10, "depth": 10},
            "layout_image": {**self.place_map, "kind": "PLACE_TOP_DOWN_COMPLETE_SPACE_MAP"},
            "rooms": [{
                "room_id": "ROOM-1",
                "zones": [{"zone_id": "Z1", "polygon": [[0, 0], [9, 0], [9, 9], [0, 9]]}],
                "fixed_elements": [{"element_id": "FIX-1", "zone_id": "Z1", "position": [4, 8]}],
                "entrances": [{"entrance_id": "EN-1", "zone_id": "Z1", "position": [4, 0]}],
                "axes": [{"axis_id": "AX-1", "endpoint_a": [0, 4], "endpoint_b": [9, 4],
                          "default_screen_direction": "A_LEFT_B_RIGHT", "crossing_policy": "NO_CROSS"}],
                "camera_positions": [{"angle_id": "ANG-1", "zone_id": "Z1", "position": [4, 1], "facing": "north",
                                      "axis_id": "AX-1", "screen_direction": "A_LEFT_B_RIGHT"}],
            }],
            "scene_mappings": [{"scene_id": "S1", "room_id": "ROOM-1", "zone_ids": ["Z1"]}],
        }
        authority = {"schema": "qingshan.episode_global_space_map.v1", "episode": "E40",
                     "episode_global_space_map_id": "EGSM-1", "map_version": 1, "authority_ref": "T",
                     "status": "LOCKED", "inheritance": {"mode": "NEW"},
                     "map_image": {**self.episode_map, "kind": "EPISODE_TOP_DOWN_COMPLETE_SPACE_MAP"},
                     "space_maps": [place]}
        authority["topology_sha256"] = content_sha256(authority["space_maps"])
        return authority

    def task(self, bindings):
        subspace_ref = {**self.subspace, "kind": "SHOT_SUBSPACE_LAYOUT",
                        "derived_from_place_map_sha256": self.place_map["sha256"]}
        return {
            "task_key": "E40-S1-KF", "tool_type": "image_generation", "spatial_layout_stage": "SHOT_KEYFRAME",
            "scene_id": "S1", "episode_global_space_map_id": "EGSM-1", "global_space_map_id": "GSM-NALU-HUT",
            "room_id": "ROOM-1", "zone_id": "Z1", "angle_id": "ANG-1", "resolution_order": RESOLUTION_ORDER,
            "subspace_layout": {"subspace_id": "SUB-1", "derived_from_episode_global_space_map_id": "EGSM-1",
                                "derived_from_global_space_map_id": "GSM-NALU-HUT", "room_id": "ROOM-1",
                                "zone_ids": ["Z1"], "angle_id": "ANG-1", "camera_position_id": "ANG-1",
                                "axis_id": "AX-1", "visible_fixed_element_ids": ["FIX-1"],
                                "reference_image": subspace_ref},
            "blocking": {"resolved_after_subspace_lock": True,
                         "characters": [{"character_id": "CHAR-A", "zone_id": "Z1", "position": [4, 4], "facing": "north"}],
                         "props": []},
            "reference_bindings": bindings,
        }

    def run_gate(self, bindings):
        return evaluate_batch(self.authority(), [self.task(bindings)], episode="E40")

    def test_legacy_passes_without_advisory(self):
        report = self.run_gate(self.bindings())
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertNotIn("advisories", report)

    def test_place_map_excluded_passes_with_advisory(self):
        rows, _ = pre.apply_exclusions(self.bindings(), declaration(entry(asset_id="GSM-NALU-HUT")))
        report = self.run_gate(rows)
        self.assertEqual(report["status"], "PASS", report["failures"])
        self.assertEqual([a["code"] for a in report["advisories"]], [pre.PLACE_MAP_ADVISORY])

    def test_global_or_subspace_excluded_fails(self):
        for selector, reason in ((self.episode_map["sha256"], "episode_global_space_map_transport_excluded_not_allowed"),
                                 (self.subspace["sha256"], "subspace_layout_transport_excluded_not_allowed")):
            rows, _ = pre.apply_exclusions(self.bindings(), declaration(entry(sha256=selector)))
            report = self.run_gate(rows)
            self.assertEqual(report["status"], "FAIL")
            self.assertIn(reason, [f.get("reason") for f in report["failures"]])

    def test_missing_global_still_fails(self):
        rows = [r for r in self.bindings() if r["role"] != "episode_global_space_map"]
        report = self.run_gate(rows)
        self.assertEqual(report["status"], "FAIL")

    def test_place_map_excluded_without_reason_fails(self):
        rows = copy.deepcopy(self.bindings())
        rows[1]["transmitted"] = False
        report = self.run_gate(rows)
        self.assertIn("place_map_transport_excluded_without_declared_reason", [f.get("reason") for f in report["failures"]])


class SubmitValidation(Fixture):
    def make_task(self, rows):
        prompt = self.root / "p.txt"
        prompt.write_text("entry", encoding="utf-8")
        sequence, transport, _ = compile_labeled_flat_identity_transport("T", pre.transmitted_bindings(rows), "x")
        contract = {"schema": "qingshan.image_prompt_contract.v2", "status": "PASS", "shot_id": "S1",
                    "source_script_sha256": "s", "source_action": "entry",
                    "source_action_sha256": hashlib.sha256(b"entry").hexdigest(),
                    "visible_characters": ["CHAR-A"], "reference_bindings": rows}
        return {"task_key": "T", "shot_id": "S1", "source_script_sha256": "s", "episode": "E01",
                "tool_type": "image_generation", "prompt_file": str(prompt),
                "prompt_sha256": hashlib.sha256(b"entry").hexdigest(), "prompt_contract": contract,
                "reference_bindings": rows, "reference_image_sequence": sequence,
                "reference_images": list(dict.fromkeys(r["path"] for r in sequence))}

    def validate(self, task):
        from tools import submit_giggle_image_manifest as sub
        ok = {"status": "PASS", "failures": [], "missing_characters": [], "missing_props": []}
        with mock.patch.object(sub, "validate_submission_attempt", return_value=[]), \
             mock.patch.object(sub, "keyframe_entry_contract_required", return_value=False), \
             mock.patch.object(sub, "validate_role_semantics", return_value=[]), \
             mock.patch.object(sub, "evaluate_spatial_task", return_value={"status": "PASS", "failures": []}), \
             mock.patch.object(sub, "precheck_submission_inputs", return_value=ok):
            sub.validate_task(task)
        return sub

    def test_excluded_place_map_task_validates_and_fingerprint_uses_sent_refs(self):
        rows, _ = pre.apply_exclusions(self.bindings(), declaration(entry(asset_id="GSM-NALU-HUT")))
        task = self.make_task(rows)
        sub = self.validate(task)
        self.assertNotIn(self.place_map["path"], task["reference_images"])
        legacy = self.make_task(self.bindings())
        self.validate(legacy)
        self.assertNotEqual(sub.submission_fingerprint(task), sub.submission_fingerprint(legacy))

    def test_excluded_file_still_transported_is_rejected(self):
        rows, _ = pre.apply_exclusions(self.bindings(), declaration(entry(asset_id="GSM-NALU-HUT")))
        task = self.make_task(rows)
        task["reference_images"] = task["reference_images"] + [self.place_map["path"]]
        with self.assertRaises(ValueError):
            self.validate(task)

    def test_exclusion_without_reason_is_rejected(self):
        rows = copy.deepcopy(self.bindings())
        rows[1]["transmitted"] = False
        task = self.make_task(rows)
        with self.assertRaisesRegex(ValueError, "without a declared reason"):
            self.validate(task)


class FakeTransport:
    """prepare/create/query without a network; ``rejected`` paths settle as the zero-cost 424."""

    def __init__(self, rejected=(), outage=False):
        self.rejected = set(rejected)
        self.outage = outage
        self.posts = []
        self.by_task = {}

    def prepare(self, *, prompt, path, key):
        return {"payload": {"task": "Img2Img", "model": "gpt-image-2", "input": {"images": [path]}}, "path": path}

    def intent_fields(self, prepared):
        return {"provider": "hopsapi", "provider_model": "gpt-image-2", "estimated_credits": 0.2}

    def create(self, payload):
        task_id = f"tsk_{len(self.posts) + 1}"
        self.posts.append(payload)
        self.by_task[task_id] = payload["input"]["images"][0]
        return {"task_id": task_id}

    def query(self, task_id):
        if self.outage or self.by_task[task_id] in self.rejected:
            return {"remote_status": "failed", "cost": 0.0, "provider_code": 424,
                    "error": f"Provider error (request id: aitk-{task_id})"}
        return {"remote_status": "completed", "cost": 0.13}

    def record_settlement(self, transaction, task_id, status):
        row = json.loads(Path(transaction).read_text(encoding="utf-8"))
        row["provider_remote_status"] = status["remote_status"]
        row["provider_cost_credits"] = status.get("cost")
        Path(transaction).write_text(json.dumps(row), encoding="utf-8")

    def not_charged_error(self):
        return RuntimeError


class IsolationHelper(Fixture):
    def task(self):
        rows = self.bindings()
        sequence, _, _ = compile_labeled_flat_identity_transport("E01-S5-KF", rows, "x")
        return {"task_key": "E01-S5-KF", "reference_bindings": rows, "reference_image_sequence": sequence}

    def run_isolate(self, transport):
        store = self.root / "store"
        store.mkdir(exist_ok=True)
        declaration_path = self.root / "rt" / pre.FILE_NAME
        report = iso.isolate(episode="E01", task=self.task(), transaction_dir=store,
                             declaration_path=declaration_path, transport=transport,
                             probe_kwargs={"sleep": lambda _s: None})
        return report, declaration_path, store

    def test_candidates_never_include_identity(self):
        paths = [ref["path"] for ref in iso.candidate_references(self.task())]
        self.assertNotIn(self.face["path"], paths)
        self.assertEqual(len(paths), 5)

    def test_deterministic_rejection_is_declared(self):
        transport = FakeTransport(rejected={self.place_map["path"]})
        report, declaration_path, store = self.run_isolate(transport)
        self.assertEqual(report["verdict"], "REFERENCE_ISOLATED")
        self.assertEqual(len(transport.posts), 6)  # 4 passing refs x1 + rejected ref x2
        doc = pre.load_declaration(declaration_path, episode="E01")
        self.assertEqual([e["sha256"] for e in doc["exclusions"]], [self.place_map["sha256"]])
        self.assertEqual(doc["exclusions"][0]["evidence"]["request_ids"][0], "aitk-tsk_2")
        rows = [json.loads(p.read_text()) for p in store.glob("*.json")]
        self.assertTrue(all(r["reference_isolation_probe"] and r["state"] == "SUBMITTED_TASK_ID_BOUND" for r in rows))
        # re-running recovers every bound probe instead of POSTing again
        self.run_isolate(transport)
        self.assertEqual(len(transport.posts), 6)
        # the declaration then drives the builder path
        rows, applied = pre.apply_exclusions(self.bindings(), doc)
        self.assertEqual([a["role"] for a in applied], ["global_space_map"])

    def test_outage_declares_nothing(self):
        transport = FakeTransport(outage=True)
        report, declaration_path, _ = self.run_isolate(transport)
        self.assertTrue(report["verdict"].startswith("ALL_REFERENCES_REJECTED"))
        self.assertFalse(declaration_path.exists())
        self.assertEqual(len(transport.posts), 5)  # one round only: nothing passed, retries prove nothing

    def test_cap_fits_seven_references(self):
        # device …1324 E02: 7 non-identity references were refused up front at 7 x 2 > 12
        self.assertTrue(iso.fits_cap(7))
        self.assertFalse(iso.fits_cap(iso.MAX_PROBES))
        self.assertFalse(iso.fits_cap(0))

    def test_prompt_rejection_declares_nothing(self):
        report, declaration_path, _ = self.run_isolate(FakeTransport())
        self.assertEqual(report["verdict"], "NO_REFERENCE_DETERMINISTICALLY_REJECTED")
        self.assertFalse(declaration_path.exists())

    def test_paid_run_requires_paid_step_environment(self):
        manifest = self.root / "m.json"
        manifest.write_text(json.dumps({"tasks": [self.task()]}), encoding="utf-8")
        store = self.root / "store"
        store.mkdir()
        (store / "E01-S5-KF__abc.json").write_text(json.dumps({
            "provider": "hopsapi", "state": "SUBMITTED_TASK_ID_BOUND", "task_id": "tsk_x",
            "provider_remote_status": "failed", "provider_cost_credits": 0.0, "provider_failure_code": 424,
            "provider_failure": "Provider error (request id: aitk-9)"}), encoding="utf-8")
        argv = ["--episode", "E01", "--task-key", "E01-S5-KF", "--manifest", str(manifest),
                "--transaction-dir", str(store), "--declaration", str(self.root / "d.json")]
        with mock.patch.dict("os.environ", {}, clear=False):
            for name in iso.PAID_ENV:
                __import__("os").environ.pop(name, None)
            with mock.patch("builtins.print"):
                self.assertEqual(iso.main(argv), 0)  # plan only, no network
            with self.assertRaisesRegex(SystemExit, "paid_stage.sh E01 --isolate-reference"):
                iso.main(argv + ["--paid"])

    def test_probes_never_feed_the_outage_detector(self):
        from tools import hopsapi_image_client as client
        store = self.root / "root" / "E01"
        store.mkdir(parents=True)
        for index in range(4):
            (store / f"REFPROBE-T-R{index}-T1__x.json").write_text(json.dumps({
                "provider": "hopsapi", "provider_model": client.MODEL, "reference_isolation_probe": True,
                "task_key": f"REFPROBE-T-R{index}-T1", "state": "SUBMITTED_TASK_ID_BOUND",
                "intent_recorded_at": "2026-11-06T00:00:0%dZ" % index, "provider_remote_status": "failed",
                "provider_failure_code": 424, "provider_cost_credits": 0.0,
                "remote_terminal_observed_at": "2026-11-06T00:00:10Z"}), encoding="utf-8")
        import calendar, time as _t
        now = calendar.timegm(_t.strptime("2026-11-06T00:01:00", "%Y-%m-%dT%H:%M:%S"))
        self.assertIsNone(client.recent_provider_outage(self.root / "root", now=now, environ={}))


if __name__ == "__main__":
    unittest.main()
