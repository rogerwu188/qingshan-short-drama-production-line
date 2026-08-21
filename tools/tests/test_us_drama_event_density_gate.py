import json
import hashlib
import tempfile
import unittest
from pathlib import Path

from tools.us_drama_event_density_gate import discover_history_manifests, evaluate


FIXTURES = Path(__file__).parent / "fixtures"


class UsDramaEventDensityGateTests(unittest.TestCase):
    def fixture(self, name):
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def sample(self):
        data = self.fixture("us_drama_pacing_v2_e41_positive.json")
        evidence = [
            "陈迹夺下令牌，迫使暗桩改走内库。",
            "暗桩焚掉外账，王府失去公开证据。",
            "白鲤交出红玉，陈迹被迫接下赌约。",
            "陈迹封住库门，敌方退路被切断。",
            "乌云嗅出官墨，边关货单成为新目标。",
            "皎兔截住信使，敌方传令链被掐断。",
            "云羊交出退路，换得陈迹独自追凶。",
            "陈迹公开张夏之名，幕后交易进入明战。",
        ]
        narrative = "\n".join(evidence) + "\n"
        moves = []
        agency_types = [
            "IRREVERSIBLE_ACTION",
            "POWER_SHIFT",
            "RELATIONSHIP_SHIFT",
            "FORCED_CHOICE",
            "MATERIAL_FACT",
            "IRREVERSIBLE_ACTION",
            "FORCED_CHOICE",
            "PAYOFF",
        ]
        for index, text in enumerate(evidence, 1):
            move_id = f"MOVE-{index:02d}"
            moves.append({
                "story_move_id": move_id,
                "causal_cluster_id": f"CLUSTER-{index:02d}",
                "move_type": agency_types[index - 1],
                "cause_state_token": f"STATE-{index - 1:02d}",
                "action": text.split("，", 1)[0],
                "external_change": text.split("，", 1)[1].rstrip("。"),
                "result_state_token": f"STATE-{index:02d}",
                "scene_id": f"SCENE-{index:02d}",
                "evidence_text": text,
                "predecessor_move_ids": [] if index == 1 else [f"MOVE-{index - 1:02d}"],
                "forces_next_story_move_id": "" if index == len(evidence) else f"MOVE-{index + 1:02d}",
            })
        data["narrative_canonical"] = {
            "schema": "qingshan.narrative_canonical.v3",
            "authority_path": "E41_NARRATIVE_CANONICAL_v1.md",
            "authority_sha256": hashlib.sha256(narrative.encode("utf-8")).hexdigest(),
            "production_contracts_externalized": True,
            "scene_sequence": [
                {
                    "scene_id": f"SCENE-{index:02d}",
                    "location_id": f"LOC-{((index - 1) % 4) + 1:02d}",
                    "time_block_id": "TIME-01" if index <= 4 else "TIME-02",
                    "thread_id": "THREAD-A" if index % 2 else "THREAD-B",
                    "story_move_ids": [f"MOVE-{index:02d}"],
                }
                for index in range(1, 9)
            ],
            "time_blocks": [
                {
                    "time_block_id": "TIME-01",
                    "before_condition_token": "NIGHT-OPEN",
                    "after_condition_token": "NIGHT-CURFEW",
                    "action_condition_change": "宵禁落闸，公开追查变为潜入",
                },
                {
                    "time_block_id": "TIME-02",
                    "before_condition_token": "NIGHT-CURFEW",
                    "after_condition_token": "DAWN-GATE-OPEN",
                    "action_condition_change": "城门将开，证据即将离城",
                },
            ],
            "story_moves": moves,
        }
        authority_sha = data["narrative_canonical"]["authority_sha256"]
        self.writer_receipt = {
            "schema": "qingshan.canonical_writer_run_receipt.v1",
            "status": "COMPLETED",
            "writer_run_id": "WRITER-E41-V5-TEST",
            "episode": "E41",
            "version": 5,
            "agent_id": "qingshan-claude-writer",
            "provider": "storyclaw",
            "model_id": "storyclaw/claude-opus-4-8",
            "session_or_task_id": "session-test-e41-v5",
            "input_bundle": {"path": "input.json", "sha256": "1" * 64},
            "writer_rules": {"files": [], "combined_sha256": "2" * 64},
            "authority_output": {
                "path": "E41_NARRATIVE_CANONICAL_v5.md",
                "sha256": authority_sha,
            },
            "started_at": "2026-08-21T19:00:00+00:00",
            "completed_at": "2026-08-21T19:01:00+00:00",
            "write_lease": "E41_V5.writer.lock.json",
        }
        receipt_bytes = (json.dumps(self.writer_receipt, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
        self.writer_receipt_sha256 = hashlib.sha256(receipt_bytes).hexdigest()
        data["writer_provenance"] = {
            "schema": "qingshan.canonical_writer_provenance.v1",
            "writer_run_id": self.writer_receipt["writer_run_id"],
            "receipt_path": "E41_WRITER_RUN_RECEIPT_v5.json",
            "receipt_sha256": self.writer_receipt_sha256,
            "agent_id": self.writer_receipt["agent_id"],
            "provider": self.writer_receipt["provider"],
            "model_id": self.writer_receipt["model_id"],
            "session_or_task_id": self.writer_receipt["session_or_task_id"],
            "input_bundle_sha256": "1" * 64,
            "writer_rules_sha256": "2" * 64,
            "authority_output_sha256": authority_sha,
            "started_at": self.writer_receipt["started_at"],
            "completed_at": self.writer_receipt["completed_at"],
        }
        self.narrative_text = narrative
        return data

    def run_gate(self, data, **kwargs):
        return evaluate(
            data,
            narrative_text=self.narrative_text,
            writer_receipt=getattr(self, "writer_receipt", None),
            writer_receipt_sha256=getattr(self, "writer_receipt_sha256", None),
            **kwargs,
        )

    def test_e41_v4_sanitized_structure_fixture_passes(self):
        report = self.run_gate(self.sample())
        self.assertEqual("PASS", report["status"])
        self.assertTrue(report["structure_enforcement"]["effective"])
        self.assertEqual(3.2, report["observed"]["events_per_minute"])
        self.assertEqual(
            "manifest.pacing_v2.location_list",
            report["observed"]["structure_v2_diagnostic"]["location_count_basis"],
        )

    def test_e40_v3_five_scene_single_location_is_negative_when_enforced(self):
        data = self.fixture("us_drama_pacing_v2_e40_legacy_negative.json")
        self.narrative_text = ""
        report = self.run_gate(
            data,
            structure_mode="enforce",
        )
        self.assertEqual("FAIL", report["status"])
        self.assertIn("NARRATIVE_CANONICAL_CONTRACT_MISSING", report["failures"])
        self.assertIn("DIAGNOSTIC_SCENE_COUNT_OUT_OF_REFERENCE_RANGE", report["warnings"])

    def test_e40_structure_findings_are_warning_only_in_auto_backtest(self):
        data = self.fixture("us_drama_pacing_v2_e40_legacy_negative.json")
        self.narrative_text = ""
        report = self.run_gate(data)
        self.assertEqual("PASS", report["status"])
        self.assertIn("BACKTEST_ONLY:NARRATIVE_CANONICAL_CONTRACT_MISSING", report["warnings"])

    def test_e41_missing_pacing_v2_fails_closed(self):
        data = self.sample()
        del data["pacing_v2"]
        report = self.run_gate(data)
        self.assertIn("PACING_V2_MISSING", report["failures"])

    def test_dialogue_density_is_not_a_hard_gate(self):
        data = self.sample()
        data["dialogue_draft"] = [{"text": "one line"}]
        report = self.run_gate(data)
        self.assertEqual("PASS", report["status"])
        self.assertLess(report["observed"]["dialogue_lines_per_minute_reference"], 13)

    def test_event_density_is_a_hard_gate(self):
        data = self.sample()
        data["narrative_canonical"]["story_moves"] = data["narrative_canonical"]["story_moves"][:3]
        report = self.run_gate(data)
        self.assertIn("STORY_MOVE_DENSITY_BELOW_MINIMUM", report["failures"])

    def test_non_advancing_atmosphere_is_a_hard_gate(self):
        data = self.sample()
        data["event_density"]["non_advancing_percentage"] = 16
        report = self.run_gate(data)
        self.assertIn("non_advancing_atmosphere_percentage_exceeds_15", report["failures"])

    def test_each_structure_failure_code(self):
        mutations = {
            "SCENE_TOO_LONG": ("max_scene_seconds", 23),
            "LOCATION_STAGNATION": ("max_consecutive_same_location", 3),
            "NO_PARALLEL_THREAD": ("parallel_threads", 1),
            "SCENE_WITHOUT_TURN": ("scenes_without_turn", 1),
            "LOCATION_BUDGET_EXCEEDED": ("new_locations_added", 3),
        }
        for code, (field, value) in mutations.items():
            with self.subTest(code=code):
                data = self.sample()
                data["pacing_v2"][field] = value
                self.assertIn(code, self.run_gate(data)["failures"])

    def test_gameable_structure_counts_are_diagnostic_not_speed_proof(self):
        data = self.sample()
        data["pacing_v2"]["scene_count"] = 5
        data["pacing_v2"]["distinct_locations"] = 1
        data["pacing_v2"]["location_list"] = ["same-room"]
        data["pacing_v2"]["time_jumps"] = 0
        data["pacing_v2"]["cross_cuts"] = 0
        report = self.run_gate(data)
        self.assertEqual("PASS", report["status"])
        self.assertIn("DIAGNOSTIC_SCENE_COUNT_OUT_OF_REFERENCE_RANGE", report["warnings"])
        self.assertIn("DIAGNOSTIC_LOCATION_VARIETY_LOW", report["warnings"])

    def test_dialogue_ratio_and_event_causal_form(self):
        data = self.sample()
        data["pacing_v2"]["dialogue_ratio"] = 0.36
        data["pacing_v2"]["event_list"] = ["only a description"]
        report = self.run_gate(data)
        self.assertIn("DIALOGUE_RATIO_EXCEEDED", report["failures"])
        self.assertIn("LEGACY_EVENT_LIST_NOT_IN_CAUSAL_FORM", report["warnings"])

    def test_three_equal_consecutive_scene_counts_are_diagnostic(self):
        data = self.sample()
        data["episode"] = "E43"
        history = []
        for episode in (41, 42):
            row = self.sample()
            row["episode"] = f"E{episode}"
            history.append(row)
        report = self.run_gate(data, history_manifests=history)
        self.assertEqual("PASS", report["status"])
        self.assertIn("DIAGNOSTIC_MECHANICAL_SCENE_TEMPLATE", report["warnings"])
        data["pacing_v2"]["scene_count_justification"] = "The causal braid requires eleven scenes."
        self.assertNotIn(
            "DIAGNOSTIC_MECHANICAL_SCENE_TEMPLATE",
            self.run_gate(data, history_manifests=history)["warnings"],
        )

    def test_same_causal_cluster_cannot_be_split_to_inflate_events(self):
        data = self.sample()
        data["narrative_canonical"]["story_moves"][1]["causal_cluster_id"] = "CLUSTER-01"
        report = self.run_gate(data)
        self.assertIn("CAUSAL_CLUSTER_FRAGMENTED:CLUSTER-01", report["failures"])

    def test_move_cause_must_come_from_a_declared_predecessor_result(self):
        data = self.sample()
        data["narrative_canonical"]["story_moves"][2]["cause_state_token"] = "STATE-UNRELATED"
        report = self.run_gate(data)
        self.assertIn("STORY_MOVE_CAUSE_STATE_NOT_FROM_PREDECESSOR:MOVE-03", report["failures"])

    def test_two_consecutive_discoveries_fail(self):
        data = self.sample()
        data["narrative_canonical"]["story_moves"][0]["move_type"] = "MATERIAL_FACT"
        data["narrative_canonical"]["story_moves"][1]["move_type"] = "PAYOFF"
        report = self.run_gate(data)
        self.assertIn("CONSECUTIVE_DISCOVERY_CHAIN_TOO_LONG", report["failures"])

    def test_passive_discovery_cannot_dominate_story_moves(self):
        data = self.sample()
        for move in data["narrative_canonical"]["story_moves"][:5]:
            move["move_type"] = "MATERIAL_FACT"
        report = self.run_gate(data)
        self.assertIn("AGENCY_MOVE_RATIO_BELOW_MINIMUM", report["failures"])

    def test_manifest_evidence_must_exist_once_in_real_narrative_text(self):
        data = self.sample()
        data["narrative_canonical"]["story_moves"][0]["evidence_text"] = "正文里不存在的事件"
        report = self.run_gate(data)
        self.assertIn("STORY_MOVE_EVIDENCE_NOT_EXACTLY_ONCE:MOVE-01", report["failures"])

    def test_production_metadata_is_forbidden_in_narrative_authority(self):
        data = self.sample()
        self.narrative_text += "shot_treatment\n"
        data["narrative_canonical"]["authority_sha256"] = hashlib.sha256(
            self.narrative_text.encode("utf-8")
        ).hexdigest()
        report = self.run_gate(data)
        self.assertIn("PRODUCTION_METADATA_INSIDE_NARRATIVE_CANONICAL", report["failures"])

    def test_missing_real_narrative_text_fails_e41(self):
        data = self.sample()
        report = evaluate(
            data,
            narrative_text=None,
            writer_receipt=self.writer_receipt,
            writer_receipt_sha256=self.writer_receipt_sha256,
        )
        self.assertIn("NARRATIVE_CANONICAL_TEXT_UNAVAILABLE", report["failures"])

    def test_writer_provenance_is_required_for_e41(self):
        data = self.sample()
        del data["writer_provenance"]
        report = self.run_gate(data)
        self.assertIn("WRITER_PROVENANCE_MISSING", report["failures"])

    def test_generic_writer_model_alias_is_rejected(self):
        data = self.sample()
        data["writer_provenance"]["model_id"] = "Claude"
        report = self.run_gate(data)
        self.assertIn("WRITER_MODEL_ID_NOT_EXACT", report["failures"])

    def test_writer_receipt_sha_must_match_real_receipt(self):
        data = self.sample()
        data["writer_provenance"]["receipt_sha256"] = "f" * 64
        report = self.run_gate(data)
        self.assertIn("WRITER_RUN_RECEIPT_SHA_MISMATCH", report["failures"])

    def test_history_discovery_selects_latest_prior_episode_manifests(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ("E41_manifest_v4.json", "E42_manifest_v4.json"):
                (root / name).write_text("{}\n", encoding="utf-8")
            paths = discover_history_manifests(root / "E43_manifest_v3.json", "E43")
            self.assertEqual(
                ["E41_manifest_v4.json", "E42_manifest_v4.json"],
                [path.name for path in paths],
            )


if __name__ == "__main__":
    unittest.main()
