#!/usr/bin/env python3
"""Cross-device end-to-end demonstration of the collective learning loop (requirement §14, T27).

One real command, everything local and synthetic:

    python3 tools/collective_learning_demo.py --out <dir>

A temporary cloud (``Service`` behind the real HTTP API on an ephemeral loopback port), two
device runtime roots A and B (each with its own SQLite store, outbox, bundle cache, trust
store and sync client over HTTP), a throwaway publisher key pair, and the engine's own SD2
strict prompt compile.  Every socket connect that is not loopback raises, and the provider
client is replaced by a counter that raises, so ``paid_post_count`` is proven, not assumed.

The transcript (JSON + markdown) carries the real ids, digests and counts of the run.  It
never records an absolute path.  No step fabricates an outcome: there is no real approved
film here, so OUTCOME_OBSERVED is left pending rather than simulated.

Work-agnostic: the character names below come from the engine's shared compiler test
fixture (``tools/tests/test_video_prompt_compiler._unit``), not from any production.
"""
from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import os
import shutil
import socket
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.collective_learning import adoption, bundles as b, contracts as c, device_store as ds  # noqa: E402
from tools.collective_learning import http_api as api, runtime_wiring as rw, selection, service as svc_mod  # noqa: E402
from tools.collective_learning import sync_client as sc  # noqa: E402

SD2 = "seedance-2.0-pro"
H3 = "MiniMax-H3"
API = "engine-api-1"
STAGE = rw.COMPILE_STAGE
TENANT = "demo-tenant"
RULE_ID = "R-DLG-OFFSCREEN-LISTENER-EYELINE"
BUNDLE_ID = "directing-dialogue"
# Shapes direction text only; carries none of the control words selection.CONTROL_LANGUAGE refuses.
CLAUSE_ZH = "说话者的目光与下颌始终朝向画外听者所在的方位，整段不看镜头"
FILM_SHA = hashlib.sha256(b"synthetic-final-cut-EP01-v1").hexdigest()


class Transcript:
    def __init__(self) -> None:
        self.steps: list[dict[str, Any]] = []
        self.network = {"non_loopback_connect_attempts": 0, "provider_client_calls": 0}

    def step(self, number: int, title: str, **facts: Any) -> dict[str, Any]:
        row = {"step": number, "title": title, **facts}
        self.steps.append(row)
        return row


# --------------------------------------------------------------------------- fixtures
def dialogue_unit(unit_id: str, *, listener_offscreen: bool) -> dict[str, Any]:
    """A real SD2 dialogue unit that passes the strict compile; the listener is off screen or not."""
    from tools.tests.test_video_prompt_compiler import _unit

    unit = _unit(dialogue="白鲤：你还记得那夜的雨吗")
    unit["unit_id"] = unit_id
    unit["model"] = SD2
    unit["character_entities"].append({"character_id": "CHAR-YISHI", "canonical_name": "医师", "aliases": []})
    role = unit["ordered_prompt_specs"][0]["role_semantic_disambiguation"]
    role.update(dialogue_listener="医师", dialogue_listener_id="CHAR-YISHI", dialogue_listener_side="LEFT")
    if listener_offscreen:
        role.update(listener_position_relative_to_speaker="画左之外", speaker_gaze_target="医师",
                    offscreen_listener_visual_cues="白鲤的目光与下颌转向画左外",
                    entity_presence={"CHAR-BAILI": "VISIBLE", "CHAR-YISHI": "ABSENT_REFERENCE_ONLY"},
                    entity_states={"CHAR-BAILI": "ACTIVE", "CHAR-YISHI": "在画左之外，只被看向"})
    else:
        unit["ordered_prompt_specs"][0]["cast"].append({"character": "医师", "character_id": "CHAR-YISHI"})
        proj = unit["provider_scope_projection"]
        proj.update(visible_character_ids=["CHAR-BAILI", "CHAR-YISHI"],
                    visible_entity_instance_counts={"CHAR-BAILI": 1, "CHAR-YISHI": 1},
                    visible_living_entity_instance_total=2)
        proj["reference_identity_bindings"].append({"reference_index": 2, "entity_id": "CHAR-YISHI",
                                                    "provider_entity_label": "Yishi", "exclusive_identity_owner": True})
        unit["provider_entity_token_map"]["医师"] = "SUBJECT_2"
        role.update(entity_presence={"CHAR-BAILI": "VISIBLE", "CHAR-YISHI": "VISIBLE_AND_IDENTITY_LOCKED"},
                    entity_states={"CHAR-BAILI": "ACTIVE", "CHAR-YISHI": "站在画左，看着白鲤"})
    return unit


def demo_rule() -> dict[str, Any]:
    return {
        "rule_id": RULE_ID, "rule_version": 1, "category": "DIRECTING_HEURISTIC",
        "scope": {"models": [SD2], "stages": [STAGE], "scene_types": ["DIALOGUE"], "requires": ["listener_offscreen"]},
        "trigger": "a dialogue unit whose declared listener is not among the visible characters",
        "recommendation": "state the speaker's gaze and jaw direction toward the off-screen listener in the source "
                          "contract and verify it survives into the compiled provider prompt",
        "exceptions": ["a designed direct-to-camera address", "a monologue", "a gaze shift that is itself the beat"],
        "known_counterexamples": [], "verification": "compile with and without the rule; clause present only with it",
        "cost_class": "FREE_COMPILE_REPLAY", "evidence_level": "REPRODUCED",
        "validation_scope": "DETERMINISTIC_REGRESSION",
        "application": {"carrier": "BEAT_DIRECTION", "prompt_clause": {"zh": CLAUSE_ZH}},
    }


def compile_text(unit: dict[str, Any], out_dir: Path) -> str:
    """The engine's own strict SD2 compile (tools/compile_grouped_seedance_manifest.compile_final_prompts)."""
    from tools.compile_grouped_seedance_manifest import compile_final_prompts

    rows = compile_final_prompts([unit], out_dir)
    return Path(rows[0]["path"]).read_text(encoding="utf-8")


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Device:
    """One device runtime root: store, outbox, cache, trust, locks, HTTP sync client."""

    def __init__(self, root: Path, *, device_id: str, line_id: str, trust: dict[str, Any], token: str, base: str):
        self.root = root
        self.device_id = device_id
        self.line_id = line_id
        self.store = ds.DeviceStore(root / "store.sqlite", tenant_id=TENANT, line_id=line_id, device_id=device_id)
        self.trust_path = root / "trust.json"
        self.trust_path.write_text(json.dumps(trust), encoding="utf-8")
        self.trust = trust
        self.cache = b.BundleCache(root / "cache", trust)
        self.locks = root / "locks"
        self.token = token
        self.client = sc.SyncClient(self.store, sc.HttpTransport(base, token, timeout=5))

    def rebase(self, base: str) -> None:
        self.client = sc.SyncClient(self.store, sc.HttpTransport(base, self.token, timeout=5))

    def accept(self, record: dict[str, Any]) -> dict[str, Any]:
        return self.cache.admit(base64.b64decode(record["payload_b64"]), source="cloud")

    def env(self, lock: dict[str, Any]) -> dict[str, str]:
        return rw.child_env(lock, cache_dir=self.root / "cache", trust_path=self.trust_path, engine_api_version=API,
                            store_path=self.store.path, tenant_id=TENANT, line_id=self.line_id)


# --------------------------------------------------------------------------- the run
def run_demo(out_dir: Path, *, keep: bool = False) -> dict[str, Any]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="collective-demo-"))
    transcript = Transcript()
    real_connect = socket.socket.connect

    def guarded_connect(sock: socket.socket, address: Any) -> Any:
        host = address[0] if isinstance(address, tuple) else str(address)
        if host not in ("127.0.0.1", "::1", "localhost"):
            transcript.network["non_loopback_connect_attempts"] += 1
            raise AssertionError(f"non-loopback connection attempted: {host}")
        return real_connect(sock, address)

    def provider_request(*_a: Any, **_k: Any) -> Any:
        transcript.network["provider_client_calls"] += 1
        raise AssertionError("provider client called during the demo")

    import tools.giggle_api_client as giggle

    with mock.patch.object(socket.socket, "connect", guarded_connect), \
            mock.patch.object(giggle, "_request", provider_request), \
            mock.patch.dict(os.environ, {}, clear=False):
        for name in rw.ENV_NAMES:
            os.environ.pop(name, None)
        try:
            result = _run(work, transcript)
        finally:
            if not keep:
                shutil.rmtree(work, ignore_errors=True)
    result["paid_post_count"] = transcript.network["provider_client_calls"]
    result["network_interception"] = {
        "method": "socket.socket.connect patched to raise for any non-loopback host; "
                  "tools.giggle_api_client._request patched to count and raise",
        **transcript.network,
    }
    result["steps"] = transcript.steps
    result["work_dir_kept"] = str(work) if keep else None
    text = json.dumps(result, ensure_ascii=False, indent=2).replace(str(work), "<demo-root>")
    (out_dir / "transcript.json").write_text(text + "\n", encoding="utf-8")
    (out_dir / "transcript.md").write_text(render_markdown(json.loads(text)), encoding="utf-8")
    return json.loads(text)


def _run(work: Path, t: Transcript) -> dict[str, Any]:
    # ---- cloud: tenant, roles, trust store pinning the publisher key
    private, public = b.generate_keypair()
    trust = b.make_trust_store({"pub-1": {"public_key_b64": public, "status": "ACTIVE",
                                          "roles": [b.KNOWLEDGE_PUBLISHER]}})
    db = work / "cloud.sqlite"
    svc = svc_mod.Service(db, trust_store=trust)
    admin = svc.authenticate(svc.bootstrap_tenant(TENANT)["token"])
    tokens = {}
    for pid, role, lines, canary in (("dev-a", "device_writer", ["line-a"], False),
                                     ("dev-b", "device_writer", ["line-b"], True),
                                     ("dev-c", "device_writer", ["line-c"], True),
                                     ("rev-1", "reviewer", [], False),
                                     ("pub-1", "publisher", [], False)):
        tokens[pid] = svc.register_principal(admin, principal_id=pid, role=role, line_ids=lines, canary=canary)["token"]
    reviewer, publisher = svc.authenticate(tokens["rev-1"]), svc.authenticate(tokens["pub-1"])
    server, _ = api.start_server(svc)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    t.step(0, "cloud up", tenant=TENANT, principals=sorted(tokens), signature_verification="Ed25519 via trust store",
           api="real HTTP server on loopback; devices talk only HTTP, reviewer/publisher use the service in-process")

    dev_a = Device(work / "device-a", device_id="dev-a", line_id="line-a", trust=trust, token=tokens["dev-a"], base=base)
    dev_b = Device(work / "device-b", device_id="dev-b", line_id="line-b", trust=trust, token=tokens["dev-b"], base=base)

    # approved offline baseline (empty rule set), digest-pinned by the engine release
    baseline_bundle = {"schema": c.BUNDLE_SCHEMA, "bundle_id": BUNDLE_ID, "version": 1,
                       "created_at": "2026-10-01T00:00:00Z", "release_channel": "BUILTIN",
                       "compat": {"engine_api_versions": [API], "models": [SD2, H3]}, "rules": []}
    baseline_path = work / "builtin_baseline.json"
    baseline_path.write_text(json.dumps(baseline_bundle), encoding="utf-8")
    baseline = b.builtin_baseline(baseline_path, b.bundle_digest(baseline_bundle))

    # ---- 1. device A records a fact (no root cause possible)
    unit_a = dialogue_unit("EP01-VU-003", listener_offscreen=True)
    before_text = compile_text(copy.deepcopy(unit_a), work / "a-compile-before")
    event1 = dev_a.store.record_observation(
        run_id="line-a.EP01.R1", episode_id="EP01", stage="S7", event_kind="FAILURE_OBSERVATION",
        unit_ids=["EP01-VU-003"], visibility="LINE", detected_by="independent-final-reviewer",
        symptom="speaker's eyes drift toward camera while addressing an off-screen listener in a continuous dialogue segment",
        evidence={"gate": "DIRECTOR_SCORE_V1.performance_interaction", "level": 2,
                  "timecodes": [{"video_sha256": FILM_SHA, "timeline": "FINAL_CUT", "start_ms": 41200, "end_ms": 44900}],
                  "compiled_prompt_sha256": _sha(before_text), "evidence_digest": c.digest({"frames": "contact-sheet-rows-7-9"})},
        opportunity={"applicable_units": 6, "observed_units": 1},
        engine_version="demo", provider_model_version=SD2, knowledge_bundle_digest=baseline["digest"])
    assert "root_cause" not in event1
    with_cause_refused = None
    try:
        c.validate_observation({**event1, "root_cause": "x"})
    except c.ContractError as exc:
        with_cause_refused = exc.codes
    sync1 = dev_a.client.run_once()
    t.step(1, "device A records a fact", event_id=event1["event_id"], event_kind=event1["event_kind"],
           timecodes=event1["evidence"]["timecodes"], opportunity=event1["opportunity"],
           has_root_cause_key="root_cause" in event1, root_cause_key_refused_with=with_cause_refused,
           cloud_ack=sync1["outbox"], cloud_unique_events=svc.event_counts(TENANT)["unique_events"])

    # ---- 2. review with a REAL before/after compile; a second event honestly INCONCLUSIVE
    rule = demo_rule()
    decision = selection.select_for_unit(copy.deepcopy(unit_a), [rule], stage=STAGE, engine_api_version=API)
    amended = selection.apply_to_unit(copy.deepcopy(unit_a), decision)
    after_text = compile_text(amended["unit"], work / "a-compile-after")
    dialogue_same = selection.dialogue_fingerprint(unit_a) == selection.dialogue_fingerprint(amended["unit"])
    assert CLAUSE_ZH in after_text and CLAUSE_ZH not in before_text and dialogue_same
    review1 = dev_a.store.record_review(
        event_id=event1["event_id"], reviewer_id="rev-1", status="ATTRIBUTED",
        root_cause_hypothesis="the source contract declared the listener off screen but no gaze/jaw direction reached the compiled prompt",
        basis="REPRODUCED", confidence="MEDIUM",
        supporting_evidence=[{"compile_without_rule_sha256": _sha(before_text), "compile_with_rule_sha256": _sha(after_text),
                              "clause_absent_before": CLAUSE_ZH not in before_text, "clause_present_after": CLAUSE_ZH in after_text,
                              "compiler": "tools.compile_grouped_seedance_manifest.compile_final_prompts"}],
        counter_evidence=[])
    unit_a2 = dialogue_unit("EP01-VU-005", listener_offscreen=False)
    event2 = dev_a.store.record_observation(
        run_id="line-a.EP01.R1", episode_id="EP01", stage="S7", event_kind="FAILURE_OBSERVATION",
        unit_ids=["EP01-VU-005"], visibility="LINE", detected_by="independent-final-reviewer",
        symptom="eyes drift toward camera during a line", opportunity={"applicable_units": 6, "observed_units": 1},
        evidence={"gate": "DIRECTOR_SCORE_V1.performance_interaction",
                  "timecodes": [{"video_sha256": FILM_SHA, "timeline": "FINAL_CUT", "start_ms": 58000, "end_ms": 60100}],
                  "listener_visible_in_frame": True}, provider_model_version=SD2)
    decision2 = selection.select_for_unit(copy.deepcopy(unit_a2), [rule], stage=STAGE, engine_api_version=API)
    not_applicable_reason = next(d["reason"] for d in decision2["decisions"] if d["rule_id"] == RULE_ID)
    review2 = dev_a.store.record_review(
        event_id=event2["event_id"], reviewer_id="rev-1", status="INCONCLUSIVE",
        reason=f"listener was visible in frame, so the off-screen-listener cause does not apply ({not_applicable_reason}); "
               "no reproduction isolates another cause")
    sync2 = dev_a.client.run_once()
    chain = svc.attribution_chain(TENANT, event1["event_id"])
    t.step(2, "review: attributed by reproduction / second event inconclusive",
           review_attributed={"review_id": review1["review_id"], "basis": review1["basis"], "confidence": review1["confidence"]},
           compile_without_rule_sha256=_sha(before_text), compile_with_rule_sha256=_sha(after_text),
           dialogue_byte_identical=dialogue_same, review_inconclusive={"review_id": review2["review_id"], "event_id": event2["event_id"]},
           cloud_ack=sync2["outbox"], cloud_attribution_chain_versions=[r["review_version"] for r in chain])

    # ---- 3. candidate -> VALIDATED -> (CANARY refused on structure alone) -> CANARY; signed bundle released
    candidate = {k: v for k, v in rule.items() if k not in ("rule_id", "rule_version", "validation_scope", "application")}
    candidate.update(candidate_id=RULE_ID, revision=1, status="CANDIDATE", event_ids=[event1["event_id"]])
    put = svc.put_candidate(reviewer, candidate, origin_line_id="line-a")
    validated = svc.transition_candidate(reviewer, RULE_ID, to="VALIDATED", if_match=put["etag"],
                                         validation_scope="DETERMINISTIC_REGRESSION",
                                         note="compile with/without rule: clause only with rule; dialogue unchanged")
    refusal = None
    try:
        svc.transition_candidate(publisher, RULE_ID, to="CANARY", if_match=validated["etag"])
    except svc_mod.Conflict as exc:
        refusal = exc.details
    media_reviewed = svc.transition_candidate(
        reviewer, RULE_ID, to="VALIDATED", if_match=validated["etag"], validation_scope="REAL_MEDIA_REVIEW",
        note="DEMO CAVEAT: the reviewed media is this demo's synthetic clip (timecodes above), not a real film")
    canary = svc.transition_candidate(publisher, RULE_ID, to="CANARY", if_match=media_reviewed["etag"])
    bundle = {"schema": c.BUNDLE_SCHEMA, "bundle_id": BUNDLE_ID, "version": 2, "created_at": c.now_iso(),
              "release_channel": "CANARY", "compat": {"engine_api_versions": [API], "models": [SD2]},
              "rules": [{**rule, "event_ids": [event1["event_id"]]}]}
    envelope = b.sign_bundle(bundle, key_id="pub-1", private_raw=private)
    payload = json.dumps(envelope, ensure_ascii=False).encode("utf-8")
    upload = svc.upload_bundle(publisher, {
        "bundle_id": BUNDLE_ID, "version": "2", "digest": c.sha256_bytes(payload),
        "payload_b64": base64.b64encode(payload).decode("ascii"), "signature_b64": envelope["signature"]["value_b64"],
        "key_id": "pub-1", "manifest": {"scope": {"models": [SD2], "stages": [STAGE]},
                                        "rules": [{"rule_id": RULE_ID, "rule_version": 1}]}})
    release = svc.release(publisher, bundle_id=BUNDLE_ID, version="2", channel="CANARY")
    t.step(3, "candidate validated, canary refused on deterministic scope alone, then released to CANARY",
           candidate_id=RULE_ID, scope=rule["scope"], states=[put["state"], validated["state"], canary["state"]],
           canary_refusal_on_deterministic_only=refusal, canary_basis_caveat=media_reviewed["validation_scopes"],
           renderer_positive_negative={"clause_in_compile_with_rule": CLAUSE_ZH in after_text,
                                       "clause_in_compile_without_rule": CLAUSE_ZH in before_text,
                                       "visible_listener_unit_not_applicable": not_applicable_reason},
           bundle={"bundle_id": BUNDLE_ID, "version": 2, "bundle_digest": envelope["digest"],
                   "cloud_payload_sha256": upload["digest"], "signature_check": upload["signature_check"]},
           release=release)

    # ---- 4. device B: R_old locked to the baseline before the release; R_new resolves the canary
    caps_b = {"model": SD2, "stage": STAGE, "engine_api_version": API}
    lock_old = b.lock_run(dev_b.locks, "line-b.EP02.R-old", engine_commit="demo",
                          resolved=b.resolve_local(caps_b, dev_b.cache, channel="CANARY", baseline=baseline))
    old_sha_before = lock_old["lock_sha256"]
    pulled = dev_b.client.pull_bundles(caps_b, channels=["CANARY"], accept=dev_b.accept)
    resolved_new = b.resolve_local(caps_b, dev_b.cache, channel="CANARY", baseline=baseline)
    lock_new = b.lock_run(dev_b.locks, "line-b.EP02.R-new", engine_commit="demo", resolved=resolved_new)
    old_again = b.lock_run(dev_b.locks, "line-b.EP02.R-old", engine_commit="demo", resolved=resolved_new)
    assert old_again["lock_status"] == "EXISTING_LOCK_KEPT" and old_again["lock_sha256"] == old_sha_before
    assert lock_new["knowledge_bundle_digest"] == envelope["digest"]
    t.step(4, "device B: in-flight run keeps the baseline, new run locks the released canary",
           pull={"status": pulled["status"], "fetched": [{k: f[k] for k in ("bundle_id", "version", "digest", "status")}
                                                         for f in pulled["fetched"]]},
           cache_entries=[{k: e[k] for k in ("bundle_id", "version", "digest", "release_channel")} for e in dev_b.cache.entries()],
           lock_old={"run_id": lock_old["run_id"], "knowledge_bundle_digest": lock_old["knowledge_bundle_digest"],
                     "label": lock_old["knowledge_bundles"][0].get("label"), "lock_sha256": old_sha_before,
                     "after_release_status": old_again["lock_status"], "after_release_sha256": old_again["lock_sha256"]},
           lock_new={"run_id": lock_new["run_id"], "knowledge_bundle_digest": lock_new["knowledge_bundle_digest"],
                     "rules": lock_new["knowledge_bundles"][0]["rules"]},
           lock_new_digest_equals_released_bundle=lock_new["knowledge_bundle_digest"] == envelope["digest"])

    # ---- 5. B compiles under the lock through the real entry point: APPLIED then VERIFIED, synced
    unit_b = dialogue_unit("EP02-VU-004", listener_offscreen=True)
    with mock.patch.dict(os.environ, dev_b.env(lock_new)):
        text_b = compile_text(unit_b, work / "b-compile")
    store_receipts = dev_b.store.receipts("ADOPTION")
    applied = next(r for r in store_receipts if r["state"] == "APPLIED" and r["rule_id"] == RULE_ID)
    passed = CLAUSE_ZH in text_b and applied["compiled_output_digest"] == _sha(text_b)
    verified = adoption.verified(applied, test_name="tools.tests.test_collective_e2e_demo.clause_in_locked_compile",
                                 assertion="rule clause present in the strict SD2 compile output bound by the APPLIED receipt",
                                 passed=passed, checked_output_digest=applied["compiled_output_digest"])
    dev_b.store.record_receipt("ADOPTION", verified)
    sync5 = sc.drain(dev_b.client, now=sc.far_future())
    trace = svc.trace_candidate(reviewer, RULE_ID)
    cloud_states = sorted({r["state"] for r in trace["adoptions"] if r["device_id"] == "dev-b"})
    t.step(5, "device B applies and verifies; receipts reach the cloud trace",
           applied={"receipt_id": applied["receipt_id"], "evidence_scope": applied["evidence_scope"],
                    "source_contract_digest": applied["source_contract_digest"],
                    "compiled_output_digest": applied["compiled_output_digest"], "unit_ids": applied["unit_ids"],
                    "entrypoint": applied["entrypoint"]},
           verified={"receipt_id": verified["receipt_id"], "test_name": verified["verification"]["test_name"]},
           compiled_text_sha256=_sha(text_b), clause_in_sent_text=CLAUSE_ZH in text_b,
           device_outbox=sync5["outbox"], cloud_adoption_states_for_dev_b=cloud_states,
           paid_post_count_so_far=t.network["provider_client_calls"])

    # ---- 6. no real approved film: outcome stays pending
    t.step(6, "outcome", outcome="PENDING_REAL_FILM", outcome_observed_receipts=sum(
        1 for r in dev_b.store.receipts("ADOPTION") if r["state"] == "OUTCOME_OBSERVED"),
        note="OUTCOME_OBSERVED needs a real generated media / approved film sha256; none exists in this demo")

    # ---- 7. injections: wrong model, duplicate delivery, network interruption
    dev_c = Device(work / "device-c", device_id="dev-c", line_id="line-c", trust=trust, token=tokens["dev-c"], base=base)
    other = dev_c.client.pull_bundles({"model": H3, "stage": STAGE, "engine_api_version": API}, channels=["CANARY"],
                                      accept=dev_c.accept)
    transport_a = sc.HttpTransport(base, tokens["dev-a"], timeout=5)
    before_counts = svc.event_counts(TENANT)
    status, body, _ = transport_a.request("POST", "/v1/events:batch", {"events": [event1]})
    after_counts = svc.event_counts(TENANT)
    server.shutdown()
    server.server_close()
    svc.close()
    started = time.monotonic()
    event3 = dev_a.store.record_observation(
        run_id="line-a.EP01.R1", episode_id="EP01", stage="S6", event_kind="RUN_ANOMALY", visibility="LINE",
        symptom="provider queue wait exceeded the planned window", evidence={"wait_seconds": 913}, detected_by="orchestrator")
    record_seconds = time.monotonic() - started
    offline = dev_a.client.run_once()
    svc = svc_mod.Service(db, trust_store=trust)
    server, _ = api.start_server(svc)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    reviewer, publisher = svc.authenticate(tokens["rev-1"]), svc.authenticate(tokens["pub-1"])
    for dev in (dev_a, dev_b, dev_c):
        dev.rebase(base)
    recovered = sc.drain(dev_a.client, now=sc.far_future())
    final_counts = svc.event_counts(TENANT)
    t.step(7, "injections",
           wrong_model_device={"device": "dev-c", "capabilities_model": H3, "resolved_bundles": other["resolved"]["bundles"],
                               "not_applicable": other["resolved"]["not_applicable"]},
           duplicate_delivery={"http_status": status, "ack": body["results"][0]["status"],
                               "unique_before": before_counts["unique_events"], "unique_after": after_counts["unique_events"],
                               "duplicate_deliveries_logged": after_counts["duplicate_deliveries"]},
           network_interruption={"event_id": event3["event_id"], "record_seconds_while_offline": round(record_seconds, 4),
                                 "offline_sync": {"delivered": offline["delivered"], "retry": offline["retry"]},
                                 "after_restart_outbox": recovered["outbox"],
                                 "unique_events_after": final_counts["unique_events"],
                                 "duplicate_deliveries_after": final_counts["duplicate_deliveries"]})

    # ---- 8. revoke: new run falls back, the locked run still verifies, history stays queryable
    revoke = svc.revoke_bundle(publisher, bundle_id=BUNDLE_ID, version="2", reason="demo revocation")
    pulled_next = dev_b.client.pull_bundles(caps_b, channels=["CANARY"], accept=dev_b.accept)
    revoked_digests = {e["digest"] for e in dev_b.cache.entries()
                       if any(r["bundle_id"] == e["bundle_id"] and str(r["version"]) == str(e["version"])
                              for r in pulled_next["resolved"]["revocations"])}
    resolved_next = b.resolve_local(caps_b, dev_b.cache, channel="CANARY", revoked=revoked_digests, baseline=baseline)
    lock_next = b.lock_run(dev_b.locks, "line-b.EP03.R-next", engine_commit="demo", resolved=resolved_next)
    still_valid = b.verify_lock_for_send(b.lock_ref(lock_new), dev_b.cache)
    trace_after = svc.trace_candidate(reviewer, RULE_ID)
    with urllib.request.urlopen(urllib.request.Request(
            f"{base}/admin/candidates/{RULE_ID}", headers={"Authorization": f"Bearer {tokens['rev-1']}"}), timeout=10) as resp:
        html = resp.read().decode("utf-8")
    t.step(8, "revocation",
           revoke=revoke, cloud_resolve_after={"bundles": pulled_next["resolved"]["bundles"],
                                               "revocations": pulled_next["resolved"]["revocations"]},
           lock_next={"run_id": lock_next["run_id"], "knowledge_bundle_digest": lock_next["knowledge_bundle_digest"],
                      "label": lock_next["knowledge_bundles"][0].get("label") if lock_next["knowledge_bundles"] else None},
           lock_new_still_verifies_for_its_own_run=still_valid["status"],
           trace={"candidate_state": trace_after["candidate"]["state"], "events": [e["event_id"] for e in trace_after["events"]],
                  "reviews": [r["review_id"] for e in trace_after["events"] for r in e["reviews"]],
                  "bundles": trace_after["bundles"], "adoption_receipts": len(trace_after["adoptions"]),
                  "independent_sources": trace_after["independent_sources"]},
           admin_page_mentions={"candidate": RULE_ID in html, "event": event1["event_id"] in html})
    server.shutdown()
    server.server_close()
    svc.close()
    return {"schema": "qingshan.collective.e2e_demo_transcript.v1", "ran_at": c.now_iso(),
            "demo_model": SD2, "compile_entrypoint": "tools.compile_grouped_seedance_manifest.compile_final_prompts",
            "film_sha256_synthetic": FILM_SHA}


def render_markdown(result: dict[str, Any]) -> str:
    lines = ["# Collective learning end-to-end demo transcript", "",
             f"Ran at {result['ran_at']} · demo model `{result['demo_model']}` · paid POST count **{result['paid_post_count']}**",
             f"Network interception: {result['network_interception']['method']}", ""]
    for step in result["steps"]:
        lines.append(f"## Step {step['step']}: {step['title']}")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps({k: v for k, v in step.items() if k not in ("step", "title")}, ensure_ascii=False, indent=2))
        lines.append("```")
        lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--keep", action="store_true", help="keep the temporary cloud/device directories")
    args = parser.parse_args(argv)
    result = run_demo(args.out, keep=args.keep)
    print(json.dumps({"paid_post_count": result["paid_post_count"], "steps": len(result["steps"]),
                      "transcript": str(args.out / "transcript.json"),
                      "work_dir_kept": result["work_dir_kept"]}, ensure_ascii=False, indent=2))
    return 0 if result["paid_post_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
