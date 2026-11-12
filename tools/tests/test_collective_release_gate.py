"""Audit 2026-11-12 §5.2 (P1): the rule-state gate sits at the signed-pointer writer, and ``baseline: true``
is honoured only for the tenant's one explicit baseline import.  Offline: fake bucket, temp sqlite."""
from __future__ import annotations

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path

from tools.collective_learning import bundles as b
from tools.collective_learning import contracts as c
from tools.collective_learning import s3_sync as s3
from tools.collective_learning import service as svc_mod
from tools.collective_learning_demo import demo_rule
from tools.tests.test_collective_s3_sync import API, ENV, SD2, TENANT, Fixture, advance_rule


class GateHarness(unittest.TestCase):
    def setUp(self) -> None:
        self.fx = Fixture(Path(tempfile.mkdtemp()))
        self.pub = s3.principal(TENANT, "pub-1", "publisher")
        self.admin = s3.principal(TENANT, "admin-t", "admin")
        self.channel = s3.S3Channel(self.fx.store, tenant_id=TENANT)
        self.gate = s3.ServiceReleaseGate(self.fx.svc, TENANT)

    def upload(self, version: int, rules: list[dict], *, label: str = "CANARY", manifest_rules: bool = True,
               baseline: bool = False, bundle_id: str = "kb") -> dict:
        bundle = {"schema": c.BUNDLE_SCHEMA, "bundle_id": bundle_id, "version": version, "created_at": c.now_iso(),
                  "release_channel": label, "compat": {"engine_api_versions": [API], "models": [SD2]}, "rules": rules}
        envelope = b.sign_bundle(bundle, key_id="pub-1", private_raw=self.fx.private)
        raw = json.dumps(envelope).encode()
        manifest = {"scope": {"models": [SD2], "stages": ["VIDEO_COMPILE"]}}
        if manifest_rules:
            manifest["rules"] = [{"rule_id": r["rule_id"], "rule_version": r["rule_version"]} for r in rules]
        if baseline:
            manifest["baseline"] = True
        self.fx.svc.upload_bundle(self.pub, {
            "bundle_id": bundle_id, "version": str(version), "digest": c.sha256_bytes(raw),
            "payload_b64": base64.b64encode(raw).decode(), "signature_b64": envelope["signature"]["value_b64"],
            "key_id": "pub-1", "manifest": manifest})
        return {"envelope": envelope, "raw": raw, "version": str(version), "bundle_id": bundle_id}

    def publish(self, channel: str, up: dict, *, gate=None, use_gate: bool = True) -> dict:
        return self.channel.publish(channel, bundle_id=up["bundle_id"], version=up["version"],
                                    bundle_digest=up["envelope"]["digest"], payload_sha256=c.sha256_bytes(up["raw"]),
                                    key_id="pub-1", private_raw=self.fx.private,
                                    release_gate=(gate or self.gate) if use_gate else None)

    def refused(self, fn) -> list[str]:
        with self.assertRaises(b.BundleError) as ctx:
            fn()
        self.assertIsNone(self.channel.get_json("channels/canary.json"), "nothing may be signed on refusal")
        return ctx.exception.codes


class PointerGateTest(GateHarness):
    def test_raw_publish_without_a_gate_is_refused(self) -> None:
        rule = demo_rule()
        advance_rule(self.fx.svc, TENANT, rule, "CANARY")
        up = self.upload(1, [rule])
        self.assertEqual(self.refused(lambda: self.publish("CANARY", up, use_gate=False)), ["RELEASE_GATE_REQUIRED"])
        with self.assertRaises(b.BundleError):
            self.channel.publish_entries("CANARY", {}, key_id="pub-1", private_raw=self.fx.private)
        self.assertEqual(self.publish("CANARY", up)["sequence"], 1)

    def test_rule_not_in_candidate_state_cannot_be_signed_even_bypassing_service_release(self) -> None:
        rule = demo_rule()
        up = self.upload(1, [rule])  # rule never became a candidate
        codes = self.refused(lambda: self.publish("CANARY", up))
        self.assertIn(f"RULE_UNKNOWN:{rule['rule_id']}", codes)
        # validated but not yet CANARY: still refused
        rev = s3.principal(TENANT, "rev-t", "reviewer")
        cand = {k: v for k, v in rule.items() if k not in ("rule_id", "rule_version", "validation_scope", "application")}
        cand.update(candidate_id=rule["rule_id"], revision=1, status="CANDIDATE")
        rec = self.fx.svc.put_candidate(rev, cand, origin_line_id="line-x")
        self.fx.svc.transition_candidate(rev, rule["rule_id"], to="VALIDATED", if_match=rec["etag"],
                                         validation_scope="CROSS_CASE_EFFECT")
        codes = self.refused(lambda: self.publish("CANARY", up))
        self.assertIn(f"RULE_STATE:{rule['rule_id']}:VALIDATED", codes)

    def test_released_pointer_needs_released_rules_and_released_label(self) -> None:
        rule = demo_rule()
        advance_rule(self.fx.svc, TENANT, rule, "CANARY")
        canary_label = self.upload(1, [rule], label="CANARY")
        released_label = self.upload(2, [rule], label="RELEASED")
        codes = self.refused(lambda: self.publish("RELEASED", canary_label))
        self.assertTrue(any(x.startswith("BUNDLE_LABEL_NOT_ACCEPTED_ON_CHANNEL") for x in codes), codes)
        codes = self.refused(lambda: self.publish("RELEASED", released_label))
        self.assertIn(f"RULE_STATE:{rule['rule_id']}:CANARY", codes)
        # a CANARY pointer may carry a RELEASED-labelled bundle (canary devices accept RELEASED too)
        self.assertEqual(self.publish("CANARY", released_label)["sequence"], 1)

    def test_manifest_without_rules_no_longer_smuggles_rules_past_the_gate(self) -> None:
        """The service release checks only the stored manifest; the pointer gate checks the SIGNED rules."""
        rule = demo_rule()
        up = self.upload(1, [rule], manifest_rules=False)
        self.fx.svc.release(self.pub, bundle_id="kb", version="1", channel="CANARY")  # old path: passes
        codes = self.refused(lambda: self.publish("CANARY", up))
        self.assertIn(f"RULE_UNKNOWN:{rule['rule_id']}", codes)
        # and sync_channels (the collector path) refuses the same pointer instead of signing it
        with self.assertRaises(b.BundleError):
            s3.sync_channels(self.fx.svc, self.fx.store, self.fx.root, TENANT)
        self.assertIsNone(self.channel.get_json("channels/canary.json"))

    def test_swapped_bucket_object_and_revoked_version_are_refused(self) -> None:
        rule = demo_rule()
        advance_rule(self.fx.svc, TENANT, rule, "CANARY")
        up = self.upload(1, [rule])
        key = s3.tenant_key(TENANT, "bundles/kb/1.json")
        self.fx.store.put_bytes(key, b'{"schema":"x"}', "application/json")
        codes = self.refused(lambda: self.publish("CANARY", up))
        self.assertIn("BUNDLE_OBJECT_SHA_MISMATCH:kb@1", codes)
        self.fx.store.put_bytes(key, up["raw"], "application/json")
        self.fx.svc.revoke_bundle(self.pub, bundle_id="kb", version="1", reason="test")
        self.assertIn("BUNDLE_REVOKED:kb@1", self.refused(lambda: self.publish("CANARY", up)))

    def test_unchanged_entries_and_removals_need_no_new_admission(self) -> None:
        rule = demo_rule()
        advance_rule(self.fx.svc, TENANT, rule, "CANARY")
        up = self.upload(1, [rule])
        self.publish("CANARY", up)
        # the rule is later deprecated: re-signing the same pointer (or removing the entry) still works
        pub = s3.principal(TENANT, "pub-t", "publisher")
        rec = self.fx.svc.get_candidate(pub, rule["rule_id"])
        self.fx.svc.transition_candidate(pub, rule["rule_id"], to="DEPRECATED", if_match=rec["etag"])
        current = self.channel.get_json("channels/canary.json")["body"]["bundles"]
        self.assertEqual(self.channel.publish_entries("CANARY", current, key_id="pub-1", private_raw=self.fx.private,
                                                      release_gate=self.gate)["sequence"], 2)
        self.assertEqual(self.channel.publish_entries("CANARY", {}, key_id="pub-1", private_raw=self.fx.private,
                                                      release_gate=self.gate)["sequence"], 3)
        # but adding it back is a new admission and is refused
        with self.assertRaises(b.BundleError):
            self.publish("CANARY", up)


class BaselineImportTest(GateHarness):
    def test_baseline_flag_alone_no_longer_bypasses_rule_states(self) -> None:
        rule = demo_rule()
        self.upload(1, [rule], baseline=True, label="RELEASED")
        with self.assertRaises(svc_mod.Conflict) as ctx:
            self.fx.svc.release(self.pub, bundle_id="kb", version="1", channel="RELEASED")
        self.assertIn(f"RULE_UNKNOWN:{rule['rule_id']}", json.dumps(ctx.exception.details))

    def test_one_explicit_import_per_tenant_then_release_and_pointer_pass(self) -> None:
        rule = demo_rule()
        up = self.upload(1, [rule], baseline=True, label="RELEASED")
        with self.assertRaises(svc_mod.Forbidden):
            self.fx.svc.import_baseline(self.pub, bundle_id="kb", version="1", note="publisher may not")
        with self.assertRaises(svc_mod.PayloadInvalid):
            self.fx.svc.import_baseline(self.admin, bundle_id="kb", version="1", note="  ")
        out = self.fx.svc.import_baseline(self.admin, bundle_id="kb", version="1", note="line owner approved v1 rules")
        self.assertEqual(out["version"], "1")
        self.fx.svc.release(self.pub, bundle_id="kb", version="1", channel="RELEASED")
        self.assertEqual(self.publish("RELEASED", up)["sequence"], 1)
        # a second baseline bundle (or the same one again) cannot be imported
        self.upload(2, [rule], baseline=True, label="RELEASED")
        with self.assertRaises(svc_mod.Conflict):
            self.fx.svc.import_baseline(self.admin, bundle_id="kb", version="2", note="again")
        with self.assertRaises(svc_mod.Conflict):
            self.fx.svc.release(self.pub, bundle_id="kb", version="2", channel="RELEASED")
        outcomes = [row["outcome"] for row in self.fx.svc.audit_entries(TENANT, action="import_baseline")]
        self.assertEqual(outcomes.count("OK"), 1)
        self.assertEqual(len(outcomes), 4)  # every refusal is audited too

    def test_non_baseline_manifest_cannot_be_imported(self) -> None:
        self.upload(1, [demo_rule()])
        with self.assertRaises(svc_mod.PayloadInvalid):
            self.fx.svc.import_baseline(self.admin, bundle_id="kb", version="1", note="not a baseline")

    def test_cli_import_baseline(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        from tools.tests.fake_s3 import FakeS3
        fake = FakeS3()

        def run(*argv):
            buf = io.StringIO()
            code = s3.main(list(argv), env=ENV, client_factory=lambda cfg, creds: fake, out=buf)
            return code, json.loads(buf.getvalue())

        self.assertEqual(run("bootstrap", "--runtime-root", str(tmp / "rt"), "--tenant", "t1")[0], 0)
        root = s3.CollectiveRoot(tmp / "rt")
        svc = s3.open_service(root, None)
        key_id, private = root.publisher_key()
        bundle = {"schema": c.BUNDLE_SCHEMA, "bundle_id": "kb", "version": 1, "created_at": c.now_iso(),
                  "release_channel": "RELEASED", "compat": {"engine_api_versions": [API], "models": [SD2]},
                  "rules": [demo_rule()]}
        envelope = b.sign_bundle(bundle, key_id=key_id, private_raw=private)
        raw = json.dumps(envelope).encode()
        svc.upload_bundle(s3.principal("t1", "pub", "publisher"), {
            "bundle_id": "kb", "version": "1", "digest": c.sha256_bytes(raw), "payload_b64": base64.b64encode(raw).decode(),
            "signature_b64": envelope["signature"]["value_b64"], "key_id": key_id,
            "manifest": {"scope": {"models": [SD2], "stages": ["VIDEO_COMPILE"]}, "baseline": True,
                         "rules": [{"rule_id": demo_rule()["rule_id"], "rule_version": 1}]}})
        code, out = run("import-baseline", "--runtime-root", str(tmp / "rt"), "--tenant", "t1",
                        "--bundle-id", "kb", "--version", "1", "--note", "owner approved")
        self.assertEqual((code, out["status"]), (0, "OK"), out)
        code, out = run("import-baseline", "--runtime-root", str(tmp / "rt"), "--tenant", "t1",
                        "--bundle-id", "kb", "--version", "1", "--note", "again")
        self.assertEqual((code, out["code"]), (2, "CONFLICT"), out)
        code, out = run("publish-channel", "--runtime-root", str(tmp / "rt"), "--tenant", "t1",
                        "--channel", "RELEASED", "--bundle-id", "kb", "--version", "1")
        self.assertEqual((code, out["sequence"]), (0, 1), out)


if __name__ == "__main__":
    unittest.main()
