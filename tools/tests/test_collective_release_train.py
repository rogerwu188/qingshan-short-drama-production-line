"""The collector's release train: candidate threshold, review hook, daily batch cap, canary evaluation
(promote / roll back), retirement, status -- and the resulting pointers through the release gate.

Offline: temp sqlite service, fake bucket, synthetic production events with controlled timestamps."""
from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.collective_learning import bundles as b
from tools.collective_learning import contracts as c
from tools.collective_learning import object_store as osm
from tools.collective_learning import release_train as rt
from tools.collective_learning import s3_sync as s3
from tools.collective_learning import service as svc_mod
from tools.tests.fake_s3 import FakeS3

TENANT = "nalu"
DAY = 86400.0
T0 = 1_800_000_000.0  # fixed clock


def rule_for(ft: str, n: int) -> dict:
    return {"rule_id": f"kb-r{n}", "category": "MODEL_CONSTRAINT",
            "scope": {"models": ["MiniMax-H3"], "stages": ["VIDEO_COMPILE"]},
            "trigger": f"a unit at risk of {ft}", "recommendation": "state the framing explicitly in the shot text",
            "exceptions": [], "verification": "Q1 rejects with this code drop on canary devices",
            "cost_class": "FREE_COMPILE_REPLAY", "evidence_level": "MULTI_CASE", "validation_scope": "REAL_MEDIA_REVIEW",
            "application": {"carrier": "BEAT_DIRECTION", "prompt_clause": {"zh": "人物正脸清晰入画", "en": "face clearly in frame"}}}


class Harness(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = Path(tempfile.mkdtemp())
        self.root = s3.CollectiveRoot(self.tmp / "rt")
        self.root.dir.mkdir(parents=True)
        self.private, public = b.generate_keypair()
        self.trust = b.make_trust_store({"pub-fleet": {"public_key_b64": public, "status": "ACTIVE",
                                                       "roles": [b.KNOWLEDGE_PUBLISHER]}})
        self.root._write_secret(self.root.key_path, json.dumps({
            "key_id": "pub-fleet", "algorithm": "Ed25519", "private_key_b64": base64.b64encode(self.private).decode(),
            "public_key_b64": public, "created_at": c.now_iso()}))
        self.root.trust_path.write_text(json.dumps(self.trust))
        self.svc = svc_mod.Service(self.root.db, trust_store=self.trust)
        self.svc.bootstrap_tenant(TENANT)
        self.clock = [T0]
        self.cohort = {"sn-c1": "CANARY", "sn-c2": "CANARY", "sn-c3": "CANARY",
                       "sn-r1": "RELEASED", "sn-r2": "RELEASED", "sn-r3": "RELEASED"}
        self.train = self.make_train()
        self.counter = 0

    def make_train(self, **cfg) -> rt.Train:
        return rt.Train(self.svc, TENANT, self.root.dir / "release_train", publisher_key=self.root.publisher_key,
                        config=cfg, cohort=self.cohort, now=lambda: self.clock[0])

    def event(self, device: str, episode: str, ft: str, *, at: float, kind: str = "FAILURE_OBSERVATION",
              applicable: int = 4, observed: int = 1) -> dict:
        principal = svc_mod.Principal(device, TENANT, "device_writer", ("nalu",))
        event = c.make_observation(
            tenant_id=TENANT, line_id="nalu", device_id=device, run_id=f"nalu.{episode}.B1", episode_id=episode,
            stage="S5", event_kind=kind, symptom=f"synthetic {ft} on {device} {episode}",
            evidence={"failure_type": ft, "gate": "test"}, detected_by="nalu_pipeline", producer_sequence=1,
            unit_ids=[f"{episode}-VU-001"], visibility="LINE", occurred_at=rt._iso(at),
            opportunity={"applicable_units": applicable, "observed_units": observed}, provider_model_version="MiniMax-H3")
        res = self.svc.ingest_events(principal, [event])
        self.assertEqual(res[0]["status"], "CREATED", res)
        return event

    def spread(self, ft: str, devices: list[str], episodes_per_device: int = 1, at: float | None = None) -> None:
        for d in devices:
            for e in range(episodes_per_device):
                self.event(d, f"E{e + 1:02d}", ft, at=at if at is not None else self.clock[0] - 3600)

    def approve_all(self, request: dict, limit: int | None = None) -> dict:
        decisions = []
        for cl in request["clusters"][:limit]:
            decisions.append({"cluster_id": cl["cluster_id"], "decision": "APPROVE", "reason": "prompt-level fix exists",
                              "rule": rule_for(cl["failure_type"], self.counter)})
            self.counter += 1
        return self.train.import_review({"schema": rt.RESULT_SCHEMA, "request_id": request["request_id"],
                                         "reviewer": "patrol-claude", "decisions": decisions})

    def request(self) -> dict:
        out = self.train.export_review()
        self.assertEqual(out["status"], "EXPORTED", out)
        return json.loads(Path(out["path"]).read_text())

    def rounds(self, devices: list[str], *, at: float, failed: int, units: int = 10, episodes: int = 2) -> None:
        for d in devices:
            for e in range(episodes):
                kind = "FAILURE_OBSERVATION" if failed else "SUCCESS_OBSERVATION"
                self.event(d, f"E{e + 10:02d}", "Q1_ROUND", at=at, kind=kind, applicable=units,
                           observed=failed if failed else units)

    def ship_canary(self, n: int = 1) -> dict:
        for i in range(n):
            self.spread(f"Q1_REJECT:CODE_{i}", ["sn-c1", "sn-r1", "sn-r2"])
        self.approve_all(self.request())
        out = self.train.build_pack()
        self.assertEqual(out["status"], "PUBLISHED_TO_CANARY", out)
        return out


class ClusterAndReviewTest(Harness):
    def test_threshold_three_devices_or_five_episodes_and_non_lessons_excluded(self) -> None:
        self.spread("Q1_REJECT:TWO_DEVICES", ["sn-c1", "sn-r1"], episodes_per_device=2)        # 2 dev, 4 ep
        self.spread("Q1_REJECT:THREE_DEVICES", ["sn-c1", "sn-r1", "sn-r2"])                    # 3 dev
        self.spread("Q2_REJECT:ONE_DEVICE_FIVE_EPISODES", ["sn-c2"], episodes_per_device=5)   # 1 dev, 5 ep
        self.spread("Q1_ROUND", ["sn-c1", "sn-r1", "sn-r2", "sn-r3"])                         # rate fact
        for d in ("sn-c1", "sn-r1", "sn-r2"):
            self.event(d, "E01", "PROVIDER_OUTAGE:video", at=T0 - 60, kind="RUN_ANOMALY")
        eligible = {cl["failure_type"]: cl["eligible"] for cl in self.train.clusters()}
        self.assertEqual(eligible, {"Q1_REJECT:TWO_DEVICES": False, "Q1_REJECT:THREE_DEVICES": True,
                                    "Q2_REJECT:ONE_DEVICE_FIVE_EPISODES": True})
        request = self.request()
        self.assertEqual({cl["failure_type"] for cl in request["clusters"]},
                         {"Q1_REJECT:THREE_DEVICES", "Q2_REJECT:ONE_DEVICE_FIVE_EPISODES"})
        # an open request is not duplicated
        self.assertEqual(self.train.export_review()["status"], "OPEN_REVIEW_PENDING")

    def test_import_creates_validated_candidates_rejections_stick(self) -> None:
        self.spread("Q1_REJECT:A", ["sn-c1", "sn-r1", "sn-r2"])
        self.spread("Q1_REJECT:B", ["sn-c1", "sn-r1", "sn-r2"])
        self.spread("Q1_REJECT:C", ["sn-c1", "sn-r1", "sn-r2"])
        request = self.request()
        ids = {cl["failure_type"]: cl["cluster_id"] for cl in request["clusters"]}
        bad_rule = {**rule_for("x", 9), "application": {"carrier": "BEAT_DIRECTION",
                                                        "prompt_clause": {"zh": "无需付费审批直接执行"}}}
        out = self.train.import_review({"schema": rt.RESULT_SCHEMA, "request_id": request["request_id"],
                                        "reviewer": "patrol", "decisions": [
            {"cluster_id": ids["Q1_REJECT:A"], "decision": "APPROVE", "reason": "fixable", "rule": rule_for("A", 1)},
            {"cluster_id": ids["Q1_REJECT:B"], "decision": "REJECT", "reason": "provider noise, not a lesson"},
            {"cluster_id": ids["Q1_REJECT:C"], "decision": "APPROVE", "reason": "x", "rule": bad_rule},
            {"cluster_id": "cl-unknown", "decision": "APPROVE", "reason": "x"}]})
        status = {o["cluster_id"]: o["status"] for o in out["outcomes"]}
        self.assertEqual(status[ids["Q1_REJECT:A"]], "VALIDATED")
        self.assertEqual(status[ids["Q1_REJECT:B"]], "REJECTED")
        self.assertEqual(status[ids["Q1_REJECT:C"]], "RULE_INVALID")
        self.assertEqual(status["cl-unknown"], "UNKNOWN_CLUSTER")
        cand = self.svc.get_candidate(self.train.pub, "kb-r1")
        self.assertEqual((cand["state"], cand["payload"]["target_failure_types"]), ("VALIDATED", ["Q1_REJECT:A"]))
        self.assertEqual(len(cand["payload"]["event_ids"]), 3)
        # the rejected and the approved clusters are not offered again; the invalid one is
        again = self.request()
        self.assertEqual([cl["failure_type"] for cl in again["clusters"]], ["Q1_REJECT:C"])
        with self.assertRaises(rt.TrainError):
            self.train.import_review({"schema": rt.RESULT_SCHEMA, "request_id": "rv-other", "decisions": []})


class PackTest(Harness):
    def test_daily_batch_cap_rule_cap_and_one_pack_per_day(self) -> None:
        for i in range(7):
            self.spread(f"Q1_REJECT:CODE_{i}", ["sn-c1", "sn-r1", "sn-r2"])
        self.approve_all(self.request())
        out = self.train.build_pack()
        self.assertEqual((out["status"], out["version"], len(out["new_rules"])), ("PUBLISHED_TO_CANARY", 1, 5))
        self.assertEqual(self.svc.get_candidate(self.train.pub, out["new_rules"][0])["state"], "CANARY")
        self.assertEqual(self.train.state()["backlog"], ["kb-r5", "kb-r6"])
        self.assertEqual(self.train.build_pack()["status"], "CANARY_IN_FLIGHT")
        row = self.svc._read("SELECT version FROM channels WHERE tenant_id=? AND channel='CANARY'", (TENANT,))
        self.assertEqual(row, [("1",)])

    def test_rule_cap_limits_new_rules(self) -> None:
        self.train = self.make_train(max_active_rules=2)
        for i in range(4):
            self.spread(f"Q1_REJECT:CODE_{i}", ["sn-c1", "sn-r1", "sn-r2"])
        self.approve_all(self.request())
        self.assertEqual(len(self.train.build_pack()["new_rules"]), 2)

    def test_pointers_go_through_the_release_gate(self) -> None:
        """The collector's run-cycle step (sync_channels) signs exactly what the train released."""
        out = self.ship_canary(2)
        fake = FakeS3()
        cfg = osm.ObjectStoreConfig.from_mapping({"endpoint_url": "https://s3.test", "bucket": "drama01"},
                                                 env={osm.ENV_ACCESS_KEY: "k", osm.ENV_SECRET_KEY: "s"})
        store = osm.ObjectStore(cfg, fake, line_id=s3.SERVICE_LINE, receipt_path=self.tmp / "pre.json")
        store.preflight()
        synced = s3.sync_channels(self.svc, store, self.root, TENANT)
        self.assertEqual(synced["latest_by_channel"], {"CANARY": {"nalu-kb": "1"}})
        pointer = s3.S3Channel(store, tenant_id=TENANT).verify_pointer(
            json.loads(store.get_bytes("collective/nalu/channels/canary.json")), self.trust)
        self.assertEqual(pointer["bundles"]["nalu-kb"]["version"], "1")
        self.assertEqual(out["version"], 1)


class EvaluationTest(Harness):
    def test_waits_24h_then_promotes_when_not_worse(self) -> None:
        self.ship_canary(1)
        self.clock[0] = T0 + 3600
        self.assertEqual(self.train.evaluate()["status"], "WAITING")
        window = T0 + 2 * 3600
        self.rounds(["sn-c1", "sn-c2"], at=window, failed=1)
        self.rounds(["sn-r1", "sn-r2"], at=window, failed=1)
        self.clock[0] = T0 + DAY + 60
        out = self.train.evaluate()
        self.assertEqual(out["status"], "PROMOTED", out)
        self.assertEqual((out["canary_version"], out["released_version"]), (1, 2))
        self.assertEqual(self.svc.get_candidate(self.train.pub, "kb-r0")["state"], "RELEASED")
        channels = dict(self.svc._read("SELECT channel, version FROM channels WHERE tenant_id=?", (TENANT,)))
        self.assertEqual(channels, {"CANARY": "2", "RELEASED": "2"})
        envelope = json.loads(base64.b64decode(self.svc.get_bundle(self.train.pub, "nalu-kb", "2")["payload_b64"]))
        self.assertEqual((envelope["bundle"]["release_channel"], [r["rule_id"] for r in envelope["bundle"]["rules"]]),
                         ("RELEASED", ["kb-r0"]))
        self.assertEqual(out["metrics"]["canary"]["q1_admission_rate"], 0.9)
        st = self.train.status()
        self.assertEqual((st["active_rules"], st["released_version"]), (1, 2))
        self.assertIn("昨日批次 已全量", st["summary_zh"])
        # the next day's pack starts from the released rules
        self.spread("Q1_REJECT:NEXT", ["sn-c1", "sn-r1", "sn-r2"])
        self.approve_all(self.request())
        nxt = self.train.build_pack()
        self.assertEqual((nxt["version"], nxt["new_rules"]), (3, ["kb-r1"]))
        self.assertEqual(set(self.train.state()["packs"][-1]["rules"]), {"kb-r0", nxt["new_rules"][0]})

    def test_clearly_worse_canary_rolls_back(self) -> None:
        # a released pack v1 first, so the canary channel has something to fall back to
        self.ship_canary(1)
        self.clock[0] = T0 + 2 * 3600
        self.rounds(["sn-c1", "sn-c2"], at=self.clock[0], failed=0)
        self.rounds(["sn-r1", "sn-r2"], at=self.clock[0], failed=0)
        self.clock[0] = T0 + DAY + 60
        self.assertEqual(self.train.evaluate()["status"], "PROMOTED")
        self.clock[0] = T0 + 2 * DAY
        self.spread("Q1_REJECT:WORSE", ["sn-c1", "sn-r1", "sn-r2"], at=self.clock[0] - 60)
        self.approve_all(self.request())
        canary = self.train.build_pack()
        self.assertEqual(canary["version"], 3)
        window = self.clock[0] + 3600
        self.rounds(["sn-c1", "sn-c2"], at=window, failed=6)   # canary admits 40 %
        self.rounds(["sn-r1", "sn-r2"], at=window, failed=1)   # control admits 90 %
        self.clock[0] = T0 + 3 * DAY + 60
        out = self.train.evaluate()
        self.assertEqual(out["status"], "ROLLED_BACK", out)
        self.assertTrue(out["reasons"][0].startswith("q1_admission_rate"))
        new_rule = canary["new_rules"][0]
        self.assertEqual(self.svc.get_candidate(self.train.pub, new_rule)["state"], "DEPRECATED")
        channels = dict(self.svc._read("SELECT channel, version FROM channels WHERE tenant_id=?", (TENANT,)))
        self.assertEqual(channels, {"CANARY": "2", "RELEASED": "2"}, "canary falls back to the previous pack")
        self.assertEqual(self.svc._read("SELECT version FROM revocations WHERE tenant_id=?", (TENANT,)), [("3",)])
        st = self.train.status()
        self.assertEqual(st["last_batch"]["outcome"], "ROLLED_BACK")
        self.assertIn("已回滚", st["summary_zh"])

    def test_insufficient_data_waits_then_promotes_after_max_hours(self) -> None:
        self.ship_canary(1)
        self.clock[0] = T0 + DAY + 60
        self.assertEqual(self.train.evaluate()["status"], "WAITING_FOR_DATA")
        self.clock[0] = T0 + 3 * DAY + 60
        out = self.train.evaluate()
        self.assertEqual(out["status"], "PROMOTED")
        pack = next(p for p in self.train.state()["packs"] if p["version"] == 1)
        self.assertIn("INSUFFICIENT_DATA", pack["decision"]["note"])


class RetirementTest(Harness):
    def applied(self, device: str, rule_id: str, at: float) -> None:
        receipt = {"schema": c.ADOPTION_SCHEMA, "schema_version": c.SCHEMA_VERSION, "receipt_id": c.new_uuid(),
                   "tenant_id": TENANT, "line_id": "nalu", "device_id": device, "run_id": "nalu.E20.B1",
                   "rule_id": rule_id, "rule_version": 1, "bundle_digest": "a" * 64, "stage": "VIDEO_COMPILE",
                   "state": "APPLIED", "entrypoint": "test", "unit_ids": ["E20-VU-001"], "recorded_at": rt._iso(at),
                   "source_contract_digest": "b" * 64, "compiled_output_digest": "c" * 64,
                   "change_evidence": {"clause_sha256": "d" * 64}, "evidence_scope": "COMPILED_REQUEST"}
        principal = svc_mod.Principal(device, TENANT, "device_writer", ("nalu",))
        self.assertEqual(self.svc.ingest_adoptions(principal, [receipt])[0]["status"], "CREATED")

    def test_rule_whose_target_failure_did_not_drop_is_retired_and_dropped_from_next_pack(self) -> None:
        self.train = self.make_train(retire_min_applied=4, retire_min_episodes=2)
        self.ship_canary(1)  # kb-r0 targets Q1_REJECT:CODE_0
        self.clock[0] = T0 + DAY + 3 * 3600
        self.rounds(["sn-c1", "sn-c2"], at=T0 + 3600, failed=0)
        self.rounds(["sn-r1", "sn-r2"], at=T0 + 3600, failed=0)
        self.assertEqual(self.train.evaluate()["status"], "PROMOTED")
        apply_at = T0 + 2 * DAY
        for d in ("sn-r1", "sn-r2"):
            for e in ("E30", "E31"):  # before: one target event per episode
                self.event(d, e, "Q1_REJECT:CODE_0", at=apply_at - 3600)
            for _ in range(2):
                self.applied(d, "kb-r0", apply_at)
            for e in ("E32", "E33"):  # after: still one per episode
                self.event(d, e, "Q1_REJECT:CODE_0", at=apply_at + 3600)
        self.clock[0] = apply_at + DAY
        out = self.train.retire()
        self.assertEqual(out["retired"], ["kb-r0"])
        self.assertEqual(self.svc.get_candidate(self.train.pub, "kb-r0")["state"], "DEPRECATED")
        self.assertEqual(self.train.status()["retired_total"], 1)
        self.assertEqual(self.train.status()["active_rules"], 0)
        nxt = self.train.build_pack()
        self.assertEqual((nxt["status"], nxt["dropped_rules"]), ("PUBLISHED_TO_CANARY", ["kb-r0"]))
        self.assertEqual(self.train.state()["packs"][-1]["rules"], [])

    def test_rule_that_works_is_kept(self) -> None:
        self.train = self.make_train(retire_min_applied=4, retire_min_episodes=2)
        self.ship_canary(1)
        self.clock[0] = T0 + 3 * DAY + 60
        self.train.evaluate()
        apply_at = T0 + 4 * DAY
        for d in ("sn-r1", "sn-r2"):
            for e in ("E30", "E31"):
                self.event(d, e, "Q1_REJECT:CODE_0", at=apply_at - 3600)
            for _ in range(2):
                self.applied(d, "kb-r0", apply_at)
            for e in ("E32", "E33"):
                self.event(d, e, "Q1_ROUND", at=apply_at + 3600, kind="SUCCESS_OBSERVATION", applicable=4, observed=4)
        self.clock[0] = apply_at + DAY
        self.assertEqual(self.train.retire()["retired"], [])
        rec = self.train.rule_recurrence(["kb-r0"])["kb-r0"]
        self.assertEqual((rec["applied"], rec["before"]["per_episode"], rec["after"]["per_episode"]), (4, 1.0, 0.0))


class CliTest(Harness):
    def test_daily_and_status_out(self) -> None:
        self.spread("Q1_REJECT:CLI", ["sn-c1", "sn-r1", "sn-r2"])
        cohort = self.tmp / "cohort.json"
        cohort.write_text(json.dumps({"devices": [{"device_id": d, "channel": ch} for d, ch in self.cohort.items()]}))
        status_out = self.tmp / "out" / "release_train_status.json"
        buf = io.StringIO()
        code = rt.main(["daily", "--runtime-root", str(self.tmp / "rt"), "--tenant", TENANT, "--cohort", str(cohort),
                        "--status-out", str(status_out)], out=buf)
        out = json.loads(buf.getvalue())
        self.assertEqual(code, 0, out)
        self.assertEqual(out["cohort"]["registered"], 6)
        self.assertEqual(out["review"]["status"], "EXPORTED")
        status = json.loads(status_out.read_text())
        self.assertEqual(status["new_candidates_pending_review"], 1)
        self.assertEqual(status["summary_zh"], "新增候选 1 · 灰度中 0 · 昨日批次 无 · 退役 0")
        # registration lets the collector ingest the cohort's inbox batches
        self.assertEqual(self.svc._read("SELECT role FROM principals WHERE principal_id='sn-c1'"), [("device_writer",)])


if __name__ == "__main__":
    unittest.main()
