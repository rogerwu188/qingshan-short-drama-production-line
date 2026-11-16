"""Collective knowledge at the authoring stage (「本集导演经验」 in Codex's start prompt) and the 成功样例库.

Offline: signed bundles in a temp cache, the real line_upgrade_gate preflight, a fake codex CLI, the fake bucket
for the release gate / channel pointers.  No network, no provider, no paid call."""
from __future__ import annotations

import base64
import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from tools.collective_learning import adoption, authoring, bundles as b, contracts as c, exemplars as ex
from tools.collective_learning import object_store as osm
from tools.collective_learning import release_train as rt
from tools.collective_learning import s3_sync as s3
from tools.collective_learning import selection
from tools.tests.fake_s3 import FakeS3
from tools.tests.test_collective_bundles import API, H3, Kit, rule
from tools.tests.test_collective_release_train import Harness, T0, TENANT

ROOT = Path(__file__).resolve().parents[2]
RT_TOOLS = ROOT / "lines/nalu/runtime/tools"
SCRIPTS = ROOT / "skills/nalu-claude-code/scripts"
for _p in (str(ROOT / "tools"), str(RT_TOOLS), str(SCRIPTS)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

OPENING_ZH = "每集开场 3 秒内给出画面内的冲突：人物动作或对立先于任何交代"
OPENING_EN = "Open every episode on an on-screen conflict within the first 3 seconds"
EXPO_ZH = "每场交代性对白不超过 3 句，其余改为动作或画面信息"


def directing(rule_id: str, *, clause: dict[str, str], stages=("SCRIPT_AUTHORING",), **scope) -> dict:
    row = rule(rule_id, models=[H3], carrier="DIRECTING_GUIDANCE", clause=clause, evidence="MULTI_CASE",
               validation="REAL_MEDIA_REVIEW", exceptions=["a flashback-opening episode set by the line owner"])
    row["scope"] = {"models": [H3], "stages": list(stages), **scope}
    return row


# --------------------------------------------------------------------------- fixtures
def spec(*, names=("林照", "周叔"), primary="林照猛地拍桌，质问周叔账本去了哪里", dialogue="林照：账本到底在哪里？你说清楚！",
         shot_scale="MEDIUM_CLOSE_UP", location="LOC-TEAHOUSE-INTERIOR", time="TIME-NIGHT", negatives=None) -> dict:
    return {
        "space": {"location": location, "subspace": "SUBSPACE-E02-S01-01"},
        "scene_state": {"time": time, "lighting": "室内暖黄灯光，桌面一盏油灯"},
        "cast": [{"character": n, "character_id": f"CHAR-{i}"} for i, n in enumerate(names)],
        "camera": f"{shot_scale}／DOLLY PUSH_IN；机位 ANGLE-TEA-01，轴线 AXIS-TEA-01",
        "camera_plan": {"shot_scale": shot_scale, "camera_height": "EYE_LEVEL", "motion_family": "DOLLY",
                        "motion_direction": "PUSH_IN", "signature": "DOLLY:PUSH_IN",
                        "start_framing": f"{names[0]}在画面左三分之一，{names[-1]}背对镜头",
                        "end_framing": f"{names[0]}的脸占满画面上半，眼神压向{names[-1]}",
                        "motivation": "推近强调质问的压迫感，不游移空墙"},
        "action": {"primary_action": primary, "action_kind": "NON_COMBAT",
                   "physical_action_design": f"「{primary}」一次完成并停住，禁止循环或复位"},
        "performance": {"emotion": "怒", "body_sync": "掌根先落桌，肩颈随后前压，视线最后锁定对方并保持"},
        "dialogue": dialogue,
        "negative_prompts": negatives if negatives is not None else
        ["冻结帧、速度斜坡或慢动作", f"{names[0]}出现两次", "画面出现可读文字", "/Users/x/secret.png"],
    }


def unit(uid: str, shots: list[str], **kw) -> dict:
    return {"unit_id": uid, "model": H3, "editorial_shot_ids": shots, "ordered_prompt_specs": [spec(**kw)],
            "reference_images": [{"path": "/Users/x/E02/plates/a.png", "entity_id": "CHAR-0",
                                  "provider_entity_label": "Lin Zhao"}]}


def good_review(overall=4.4, **dims) -> dict:
    d = {k: 4.0 for k in ex.PRACTICE_DIMENSIONS}
    d.update(dims)
    return {"verdict": "PASS", "overall": overall, "hard_fail": [], "dimensions": d, "media_sha256": "f" * 64,
            "dimension_reasons": {"opening": "开场林照一掌拍桌质问「账本到底在哪里？」，3 秒内冲突成立，钩子强 https://x.y/z",
                                  "pacing": "每场只交代一件事，动作推动信息，节奏紧凑无拖沓"}}


def shot_ex(i: int, *, language="zh", action="CONFRONTATION", size="MEDIUM", setting="INTERIOR", genre="悬疑",
            overall=4.2, beat=None, model=H3) -> dict:
    body = {"schema": ex.EXEMPLAR_SCHEMA, "kind": "SHOT",
            "tags": {"language": language, "genre": ex.genre_key(genre), "model": model, "setting": setting,
                     "time_of_day": "NIGHT", "shot_size": size, "camera_move": "DOLLY:PUSH_IN", "action_type": action,
                     "cast_count": 2, "dialogue": True},
            "spec": {"camera": f"{size} / DOLLY PUSH_IN / EYE_LEVEL", "blocking": "角色A在左三分之一 → 角色A的脸占满画面上半",
                     "action_beat": beat or f"角色A拍桌质问角色B，第{i}种落点", "performance": "掌根先落桌，肩颈随后前压"},
            "qa": {"q1": "FIRST_PASS", "q2": "FIRST_PASS", "postgen": "FIRST_PASS"},
            "final_review": {"overall": overall}}
    body["exemplar_id"] = ex._exemplar_id(body)  # noqa: SLF001
    return ex.validate_exemplar(body)


class CollectiveRuntime:
    """A device runtime opted into collective learning: config + trust + signed bundles in the cache."""

    def __init__(self, *, rules: list[dict] | None = None, library: list[dict] | None = None,
                 genre: str = "悬疑", language: str = "zh") -> None:
        self.kit = Kit()
        self.runtime = self.kit.root / "nalu_runtime"
        self.reports = self.runtime / "runtime" / "reports"
        self.reports.mkdir(parents=True)
        (self.reports / "COLLECTIVE_LEARNING_CONFIG.json").write_text(json.dumps({
            "tenant_id": "nalu", "line_id": "nalu", "trust_store": str(self.kit.trust_path),
            "cache_dir": str(self.kit.root / "cache"), "channel": "RELEASED", "engine_api_version": API,
            "capabilities": {"model": H3}, "batch_id": "B1", "device_store": True}), encoding="utf-8")
        (self.runtime / "briefs").mkdir()
        (self.runtime / "briefs" / "E01_PRODUCTION_BRIEF.json").write_text(
            json.dumps({"genre": genre, "dialogue_language": language}, ensure_ascii=False), encoding="utf-8")
        if rules is not None:
            self.kit.publish(rules, bundle_id="nalu-kb")
        if library is not None:
            bundle = {**self.kit.bundle([], bundle_id="nalu-exemplars"), "exemplars": library}
            self.kit.cache.admit(self.kit.signed_bytes(bundle))

    def prepare(self, episode: str = "E02") -> dict:
        return authoring.prepare(engine=ROOT, runtime=self.runtime, episode=episode)


# --------------------------------------------------------------------------- item 1: authoring injection
class AuthoringInjectionTest(unittest.TestCase):
    def test_directing_rules_injected_with_scope_filter_and_cap(self) -> None:
        long_rules = [directing(f"kb-dg-long-{i}", clause={"zh": f"第{i}条：" + "镜头先给反应再给动作，" * 8})
                      for i in range(6)]
        for row in long_rules:  # weaker evidence: ranked after the two short rules
            row["evidence_level"] = "SINGLE_CASE"
        long_rules.append(directing("kb-dg-too-long", clause={"zh": "过长条款，" * 60}))
        rules = [directing("kb-dg-opening", clause={"zh": OPENING_ZH, "en": OPENING_EN}, languages=["zh"]),
                 directing("kb-dg-en-only", clause={"en": "Keep the English lines short"}, languages=["en"]),
                 directing("kb-dg-romance", clause={"zh": "感情戏先给眼神再给台词"}, genres=["都市甜宠"]),
                 directing("kb-dg-suspense", clause={"zh": EXPO_ZH}, genres=["悬疑"]),
                 directing("kb-dg-video-only", clause={"zh": "视频阶段规则"}, stages=("VIDEO_COMPILE",)),
                 rule("kb-video-face", models=[H3], clause={"en": "the face stays in frame"}), *long_rules]
        env = CollectiveRuntime(rules=rules, library=[shot_ex(1), shot_ex(2, action="CHASE", setting="EXTERIOR")])
        prepared = env.prepare()
        self.assertEqual(prepared["status"], "READY", prepared)
        section = prepared["section"]
        self.assertTrue(section.startswith(authoring.SECTION_TITLE))
        self.assertLessEqual(len(section), authoring.MAX_SECTION_CHARS)
        self.assertIn(OPENING_ZH, section)
        self.assertIn(EXPO_ZH, section)                       # genre 悬疑 matches the brief
        for absent in ("Keep the English lines short", "感情戏先给眼神", "视频阶段规则", "the face stays in frame"):
            self.assertNotIn(absent, section)
        self.assertIn("_KNOWLEDGE_BRIEFING_SHORT.md", section)  # Codex is pointed at the <= 5 KB S1 briefing (not the 62 KB one)
        self.assertTrue(Path(prepared["briefing"]).is_file())
        self.assertIn("参考写法", section)
        used = [r["rule_id"] for r in prepared["rules"]]
        self.assertEqual(used[:2], ["kb-dg-opening", "kb-dg-suspense"])
        states = {d["rule_id"]: (d["state"], d["reason"]) for d in prepared["decisions"]}
        self.assertTrue(states["kb-dg-en-only"][1].startswith("OUT_OF_SCOPE:language"))
        self.assertIn("OUT_OF_SCOPE:genre", states["kb-dg-romance"][1])
        self.assertIn("kb-dg-video-only", states)
        self.assertNotIn("kb-video-face", states)               # video carriers stay with the S2 compile path
        self.assertTrue(any(s == "DEFERRED" and ("CHAR_CAP" in r or "RULE_CAP" in r) for s, r in states.values()))
        self.assertTrue(states["kb-dg-too-long"][1].startswith("CLAUSE_TOO_LONG"))
        self.assertEqual(len(prepared["exemplar_ids"]), 2)   # rules never crowd the exemplars out
        for word in ("预算", "积分", "付费", "授权", "api_key", "密钥"):
            self.assertNotIn(word, section)

    def test_applied_receipt_recorded_once(self) -> None:
        env = CollectiveRuntime(rules=[directing("kb-dg-opening", clause={"zh": OPENING_ZH})])
        prepared = env.prepare()
        base = "你是 NALU 短剧生产线的生产执行者。合同"
        out = authoring.record_applied(prepared, prompt_with=base + "\n\n" + prepared["section"], prompt_without=base)
        self.assertEqual(out["status"], "RECORDED", out)
        self.assertEqual(out["applied"], ["kb-dg-opening"])
        lock = Path(prepared["lock"]["path"])
        rows = [json.loads(x) for x in lock.with_suffix(".adoption.jsonl").read_text().splitlines()]
        applied = [r for r in rows if r["state"] == "APPLIED"]
        self.assertEqual(len(applied), 1)
        self.assertEqual(applied[0]["stage"], "SCRIPT_AUTHORING")
        self.assertEqual(applied[0]["entrypoint"], "codex_production.start")
        self.assertTrue(applied[0]["change_evidence"]["absent_without_rule"])
        self.assertEqual(adoption.strongest_state(rows, "kb-dg-opening"), "APPLIED")
        guidance = json.loads((env.reports / "E02_AUTHORING_GUIDANCE.json").read_text())
        self.assertEqual((guidance["status"], guidance["rule_ids"]), ("INJECTED", ["kb-dg-opening"]))
        import sqlite3
        db = sqlite3.connect(env.reports / "COLLECTIVE_DEVICE_STORE.sqlite")
        try:  # queued for the collector (recurrence / retirement read APPLIED receipts)
            kinds = [r[0] for r in db.execute("SELECT kind FROM receipts")]
        finally:
            db.close()
        self.assertIn("ADOPTION", kinds)
        again = authoring.record_applied(prepared, prompt_with=base + "\n\n" + prepared["section"], prompt_without=base)
        self.assertEqual(again["status"], "ALREADY_RECORDED")
        self.assertEqual(len(lock.with_suffix(".adoption.jsonl").read_text().splitlines()), len(rows))

    def test_nothing_injected_without_knowledge(self) -> None:
        bare = Kit().root / "rt"
        (bare / "runtime" / "reports").mkdir(parents=True)
        self.assertEqual(authoring.prepare(engine=ROOT, runtime=bare, episode="E02")["status"], "INACTIVE")
        env = CollectiveRuntime(rules=[rule("kb-video-face", models=[H3], clause={"en": "the face stays in frame"})])
        prepared = env.prepare()
        self.assertEqual((prepared["status"], prepared["section"]), ("NO_KNOWLEDGE", ""))
        self.assertEqual(authoring.record_applied(prepared, prompt_with="a", prompt_without="a")["status"],
                         "NOTHING_INJECTED")
        self.assertFalse((env.reports / "E02_AUTHORING_GUIDANCE.json").exists())

    def test_directing_carrier_never_reaches_a_video_prompt(self) -> None:
        both = directing("kb-dg-both", clause={"zh": OPENING_ZH, "en": OPENING_EN},
                         stages=("VIDEO_COMPILE", "SCRIPT_AUTHORING"))
        unit_ = {"unit_id": "E02-VU-001", "model": H3, "ordered_prompt_specs": [{"action": {"primary_action": "x"}}]}
        out = selection.select_for_unit(unit_, [both], stage="VIDEO_COMPILE", engine_api_version=API)
        self.assertEqual(out["clauses"], [])
        self.assertEqual(out["decisions"][0]["reason"], "AUTHORING_CARRIER_NOT_A_VIDEO_PROMPT_CLAUSE")


class CodexStartPromptTest(unittest.TestCase):
    """codex_production.start: the section is in the prompt Codex receives; nothing changes without knowledge."""

    FAKE_CODEX = "#!/bin/sh\n[ \"$1\" = \"--version\" ] && { echo codex-cli-test; exit 0; }\ncat >/dev/null\nexit 0\n"

    def setUp(self) -> None:
        self.saved = dict(os.environ)
        self.bindir = Path(tempfile.mkdtemp()) / "bin"
        self.bindir.mkdir()
        (self.bindir / "codex").write_text(self.FAKE_CODEX)
        (self.bindir / "codex").chmod(0o755)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.saved)

    def _start(self, runtime: Path, episode: str = "E02"):
        (runtime / "credentials").mkdir(parents=True, exist_ok=True)
        (runtime / "credentials/llm_provider.json").write_text(json.dumps(
            {"base_url": "https://relay.example/v1", "api_key": "sk-test-1234", "model": "gpt-5.6"}))
        os.environ.update(NALU_RUNTIME_ROOT=str(runtime), NALU_ENGINE_ROOT=str(ROOT), HOME=str(runtime / "home"),
                          PATH=f"{self.bindir}:{os.environ['PATH']}")
        import codex_production as cp
        out = cp.start(episode, "派单附加说明")
        self.assertEqual(out["status"], "STARTED", out)
        try:
            os.waitpid(out["pid"], 0)
        except ChildProcessError:
            pass
        prompts = sorted((runtime / "claude_code" / episode).glob("run_*.prompt.md"))
        return cp, out, prompts[-1].read_text(encoding="utf-8")

    def test_start_prompt_carries_section_and_status_reports_it(self) -> None:
        env = CollectiveRuntime(rules=[directing("kb-dg-opening", clause={"zh": OPENING_ZH})],
                                library=[shot_ex(1)])
        cp, out, prompt = self._start(env.runtime)
        self.assertIn(authoring.SECTION_TITLE, prompt)
        self.assertIn(OPENING_ZH, prompt)
        self.assertEqual(out["knowledge_guidance"]["rules"], ["kb-dg-opening"])
        self.assertEqual(out["knowledge_guidance"]["record"]["status"], "RECORDED")
        self.assertTrue(prompt.endswith(next(iter([
            json.loads((env.runtime / "claude_code/E02/knowledge_guidance.prepared.json").read_text())["section"]]))))
        import knowledge_status as ks
        report = ks.report(ROOT, env.runtime, episode="E02", network=False)
        run = report["episode_run"]
        self.assertEqual(run["authoring_applied"], 1)
        self.assertTrue(run["authoring_guidance"]["last_start_prompt_has_guidance"])
        self.assertFalse(run["kb_injected_in_provider_prompts"])
        self.assertEqual(report["collective"]["exemplars"]["count"], 1)
        self.assertEqual(report["collective"]["cached_pack"], "nalu-kb@1")
        summary = ks.summary(report)
        self.assertEqual((summary["ex"], summary["gd"]), (1, 1))

    def test_no_config_prompt_is_unchanged(self) -> None:
        runtime = Path(tempfile.mkdtemp()) / "nalu_runtime"
        cp, out, prompt = self._start(runtime)
        self.assertEqual(prompt, cp.build_prompt("E02", "派单附加说明"))
        self.assertNotIn("knowledge_guidance", out)
        self.assertFalse((runtime / "claude_code/E02/knowledge_guidance.prepared.json").exists())


# --------------------------------------------------------------------------- item 3: capture on device
class ExemplarCaptureTest(unittest.TestCase):
    def setUp(self) -> None:
        import knowledge_event_log as kel
        import nalu_knowledge_events as kev
        self.kel, self.kev = kel, kev
        self.rt = Path(tempfile.mkdtemp()) / "runtime"
        (self.rt / "reports").mkdir(parents=True)
        self.manifest = self.rt / "E02_GROUPED_SEEDANCE_MANIFEST_V1.json"
        self.manifest.write_text(json.dumps({"units": [
            unit("E02-VU-001", ["E02-S01-01"]),
            unit("E02-VU-002", ["E02-S01-02"], primary="林照追上周叔，一把揪住他的衣领", shot_scale="WIDE",
                 location="LOC-ALLEY-STREET"),
            unit("E02-VU-003", ["E02-S02-01"], primary="周叔转身掏出账本，摔在桌上", shot_scale="MEDIUM",
                 names=("周叔",), dialogue=""),
        ]}, ensure_ascii=False), encoding="utf-8")
        self.review = self.rt / "E02_FINAL_AUDIENCE_REPORT.json"

    def rounds(self, *, failed_q2: list[str], with_rounds: bool = True) -> None:
        if with_rounds:
            self.kev.record_review_round(self.rt, episode="E02", stage="S6", kind="Q2", round_key="r1", rows=[
                {"unit_id": u, "passed": u not in failed_q2, "codes": ["FACE_COUNT_ZERO:x"] if u in failed_q2 else []}
                for u in ("E02-VU-001", "E02-VU-002", "E02-VU-003")])
        # a Q1 keyframe failure names the editorial shot id, not the video unit
        self.kev.record_review_round(self.rt, episode="E02", stage="S5", kind="Q1", round_key="k1", rows=[
            {"unit_id": "E02-S02-01", "passed": False, "codes": ["IDENTITY_DRIFT:x"]},
            {"unit_id": "E02-S01-01", "passed": True, "codes": []}])

    def capture(self, review: dict) -> dict:
        self.review.write_text(json.dumps(review, ensure_ascii=False), encoding="utf-8")
        return self.kev.record_success_exemplars(self.rt, episode="E02", manifest_path=str(self.manifest),
                                                 review_report=str(self.review), language="zh", genre="悬疑")

    def exemplar_rows(self) -> list[dict]:
        return [r for r in self.kel.events(self.rt, episode="E02") if r.get("event_kind") == "SUCCESS_EXEMPLAR"]

    def test_first_pass_units_and_praised_practices_only(self) -> None:
        self.rounds(failed_q2=["E02-VU-002"])
        out = self.capture(good_review(opening=4.8, pacing=4.6))
        self.assertEqual(out["status"], "OK", out)
        rows = self.exemplar_rows()
        shots = [r for r in rows if r["evidence"]["exemplar"]["kind"] == "SHOT"]
        practices = [r for r in rows if r["evidence"]["exemplar"]["kind"] == "EPISODE_PRACTICE"]
        self.assertEqual([r["unit_ids"] for r in shots], [["E02-VU-001"]])   # 002 redone at Q2, 003 at Q1
        self.assertEqual(sorted(r["evidence"]["exemplar"]["practice"]["dimension"] for r in practices),
                         ["opening", "pacing"])
        tags = shots[0]["evidence"]["exemplar"]["tags"]
        self.assertEqual((tags["setting"], tags["time_of_day"], tags["shot_size"], tags["action_type"]),
                         ("INTERIOR", "NIGHT", "MEDIUM_CLOSE_UP", "CONFRONTATION"))
        profile = json.loads((self.rt / "reports" / "EXEMPLAR_SCENE_PROFILE.json").read_text())
        self.assertEqual(profile["counts"]["action_type"], {"CONFRONTATION": 1, "CHASE": 1, "REVEAL": 1})
        again = self.capture(good_review(opening=4.8, pacing=4.6))       # S7 re-entry: deduplicated
        self.assertTrue(all(e.get("status") == "DUPLICATE" for e in again["events"]))
        self.assertEqual(len(self.exemplar_rows()), len(rows))

    def test_score_threshold_and_missing_qa_history(self) -> None:
        self.rounds(failed_q2=[])
        low = self.capture(good_review(overall=3.6))
        self.assertEqual(low["status"], "BELOW_THRESHOLD")
        weak_dim = self.capture(good_review(overall=4.5, visual=2.5))
        self.assertEqual(weak_dim["status"], "BELOW_THRESHOLD")
        rejected = self.capture({**good_review(), "verdict": "REJECT_RECUT"})
        self.assertEqual(rejected["status"], "BELOW_THRESHOLD")
        self.assertEqual(self.exemplar_rows(), [])
        self.assertTrue((self.rt / "reports" / "EXEMPLAR_SCENE_PROFILE.json").is_file())  # profile written anyway
        os.environ["NALU_EXEMPLAR_MIN_OVERALL"] = "3.5"
        try:
            self.assertEqual(self.capture(good_review(overall=3.6))["status"], "OK")
        finally:
            del os.environ["NALU_EXEMPLAR_MIN_OVERALL"]
        fresh = Path(tempfile.mkdtemp()) / "runtime"
        (fresh / "reports").mkdir(parents=True)
        self.review.write_text(json.dumps(good_review()), encoding="utf-8")
        out = self.kev.record_success_exemplars(fresh, episode="E02", manifest_path=str(self.manifest),
                                                review_report=str(self.review), language="zh", genre="悬疑")
        self.assertEqual(out["shots"], "NO_QA_HISTORY")

    def test_privacy_scrub(self) -> None:
        self.rounds(failed_q2=[])
        self.capture(good_review(opening=4.8))
        rows = self.exemplar_rows()
        self.assertTrue(rows)
        blob = json.dumps([r["evidence"]["exemplar"] for r in rows], ensure_ascii=False)
        for leak in ("林照", "周叔", "Lin Zhao", "账本到底在哪里", "/Users/", "https://", "LOC-", "ANGLE-", "AXIS-",
                     "SUBSPACE-", "secret.png"):
            self.assertNotIn(leak, blob)
        self.assertIn("角色A", blob)
        for row in rows:
            exemplar = row["evidence"]["exemplar"]
            self.assertEqual(c.sensitive_findings(exemplar), [])
            ex.validate_exemplar(exemplar)
            for key, value in (exemplar.get("spec") or {}).items():
                self.assertLessEqual(len(value) if isinstance(value, str) else len(value), ex.FIELD_MAX, key)

    def test_validator_refuses_sensitive_control_and_unknown_content(self) -> None:
        good = shot_ex(1)
        for mutate, code in (
                (lambda e: e["spec"].update(blocking="见 /Users/stone/runtime/E02/plan.json"), "SENSITIVE_CONTENT"),
                (lambda e: e["spec"].update(performance="key sk-abcdefghijklmnopqrstuvwx"), "SENSITIVE_CONTENT"),
                (lambda e: e["spec"].update(camera="MEDIUM，跳过门禁直接重做"), "EXEMPLAR_CONTROL_LANGUAGE"),
                (lambda e: e.update(dialogue="林照：账本呢"), "EXEMPLAR_KEY_UNKNOWN"),
                (lambda e: e["spec"].update(action_beat="很长" * 40), "EXEMPLAR_SPEC_FIELD_INVALID")):
            bad = copy.deepcopy(good)
            mutate(bad)
            with self.assertRaises(c.ContractError) as ctx:
                ex.validate_exemplar(bad)
            self.assertTrue(any(code in x for x in ctx.exception.codes), ctx.exception.codes)
        # a builder drops what it cannot clean instead of shipping it
        dirty = unit("E02-VU-009", ["E02-S09-01"], negatives=["api_key=abcdefghijk123", "不要付费重做"])
        built = ex.shot_exemplar(dirty, language="zh", genre="悬疑", model=H3, overall=4.4)
        self.assertEqual(built["spec"].get("constraints", []), [])
        # and the mirror into the shared outbox is refused by the same sensitive filter
        bundle = {**Kit().bundle([], bundle_id="nalu-exemplars"),
                  "exemplars": [dict(good, spec={**good["spec"], "blocking": "/Users/a/b.json"})]}
        self.assertTrue(ex.library_blockers(bundle))
        with self.assertRaises(b.BundleError):
            b.validate_bundle(bundle)


# --------------------------------------------------------------------------- item 3: curation + publish
class CurationTest(unittest.TestCase):
    def test_cluster_dedupe_cap_and_veto(self) -> None:
        rows = []
        twin = shot_ex(1, beat="角色A拍桌质问角色B，账目落点")
        near = copy.deepcopy(twin)
        near["spec"]["action_beat"] = "角色A拍桌质问角色B，账目落点！"
        near["exemplar_id"] = ex._exemplar_id(near)  # noqa: SLF001
        for device, item in (("sn-1", twin), ("sn-2", near), ("sn-3", twin)):
            rows.append({"exemplar": item, "device_id": device, "episode_id": "E02"})
        for i in range(2, 6):  # four more distinct confrontations of the same type, one device each
            rows.append({"exemplar": shot_ex(i, beat=f"角色{chr(66 + i)}推开门对峙第{i}次", overall=4.0 + i / 10),
                         "device_id": f"sn-{i + 10}", "episode_id": f"E0{i}"})
        rows.append({"exemplar": shot_ex(9, action="CHASE", setting="EXTERIOR", beat="角色A在巷口追上角色B"),
                     "device_id": "sn-9", "episode_id": "E09"})
        rows.append({"exemplar": shot_ex(8, language="en", beat="Character A slams the ledger down"),
                     "device_id": "sn-8", "episode_id": "E08"})
        rows.append({"exemplar": {"schema": "bogus"}, "device_id": "sn-7", "episode_id": "E07"})
        library = ex.curate(rows, config={"per_type": 2})
        by_type: dict[str, list] = {}
        for e in library:
            by_type.setdefault(ex.type_key(e), []).append(e)
        confront = by_type["zh|CONFRONTATION|MEDIUM|INTERIOR"]
        self.assertEqual(len(confront), 2)                                  # per-type cap
        self.assertEqual(confront[0]["support"] if confront[0]["support"]["devices"] == 3 else confront[1]["support"],
                         {"devices": 3, "episodes": 3})                     # near-duplicates merged, support counted
        self.assertIn("zh|CHASE|MEDIUM|EXTERIOR", by_type)
        self.assertIn("en|CONFRONTATION|MEDIUM|INTERIOR", by_type)
        self.assertEqual(len(library), 4)
        self.assertEqual(ex.curate(rows, config={"per_type": 2}), library)  # deterministic
        self.assertEqual(len(ex.curate(rows, config={"per_type": 5, "max_exemplars": 3})), 3)  # library cap
        vetoed = ex.curate(rows, config={"per_type": 2}, vetoed=[twin["exemplar_id"], near["exemplar_id"]])
        self.assertNotIn(twin["exemplar_id"], {e["exemplar_id"] for e in vetoed})


class ExemplarReleaseTest(Harness):
    """The library goes through the same release gate, channels and device-sync path as the rule pack."""

    def exemplar_event(self, device: str, episode: str, exemplar: dict, *, at: float) -> None:
        from tools.collective_learning import service as svc_mod
        event = c.make_observation(
            tenant_id=TENANT, line_id="nalu", device_id=device, run_id=f"nalu.{episode}.B1", episode_id=episode,
            stage="S7", event_kind="SUCCESS_EXEMPLAR", symptom="success exemplar (SHOT)",
            evidence={"failure_type": "SUCCESS_EXEMPLAR", "exemplar": exemplar,
                      "cluster_key": f"SUCCESS_EXEMPLAR|{ex.type_key(exemplar)}"},
            detected_by="nalu_pipeline", producer_sequence=1, unit_ids=[f"{episode}-VU-001"], visibility="LINE",
            occurred_at=rt._iso(at), provider_model_version=H3)  # noqa: SLF001
        res = self.svc.ingest_events(svc_mod.Principal(device, TENANT, "device_writer", ("nalu",)), [event])
        self.assertEqual(res[0]["status"], "CREATED", res)

    def bucket(self):
        cfg = osm.ObjectStoreConfig.from_mapping({"endpoint_url": "https://s3.test", "bucket": "drama01"},
                                                 env={osm.ENV_ACCESS_KEY: "k", osm.ENV_SECRET_KEY: "s"})
        store = osm.ObjectStore(cfg, self.fake, line_id=s3.SERVICE_LINE, receipt_path=self.tmp / "pre.json")
        store.preflight()
        return store

    def test_curate_sign_canary_veto_window_promote(self) -> None:
        self.fake = FakeS3()
        first, second = shot_ex(1), shot_ex(2, action="CHASE", setting="EXTERIOR", beat="角色A在巷口追上角色B")
        for device in ("sn-c1", "sn-r1"):
            self.exemplar_event(device, "E03", first, at=T0 - 3600)
        self.exemplar_event("sn-r2", "E04", second, at=T0 - 3600)
        out = self.train.exemplar_step()
        self.assertEqual((out["status"], out["count"]), ("PUBLISHED_TO_CANARY", 2), out)
        self.assertEqual(self.train.exemplar_step()["status"], "CANARY_IN_FLIGHT")
        store = self.bucket()
        synced = s3.sync_channels(self.svc, store, self.root, TENANT)
        self.assertEqual(synced["latest_by_channel"], {"CANARY": {"nalu-exemplars": "1"}})
        # a canary device verifies and caches the signed library; the lock gives it to the authoring step
        cache = b.BundleCache(self.tmp / "dev-cache", self.trust)
        pulled = s3.S3Channel(store, tenant_id=TENANT).fetch_into_cache(cache, self.trust, channel="CANARY")
        self.assertEqual([f["status"] for f in pulled["fetched"]], ["FETCHED"], pulled)
        caps = {"model": H3, "engine_api_version": "nalu-engine-api-1"}
        self.assertEqual(len(b.resolve_local(caps, cache, channel="CANARY")["selected"]), 1)
        self.assertEqual(b.resolve_local(caps, cache, channel="RELEASED")["selected"], [])  # canary label only
        lock = b.lock_run(self.tmp / "locks", "nalu.E05.B1", resolved=b.resolve_local(caps, cache, channel="CANARY"),
                          engine_commit="0" * 40)
        self.assertEqual(len(b.locked_exemplars(Path(lock["lock_path"]), cache)), 2)
        # the patrol sees the change in the review request even with no failure cluster to decide
        request = self.request()
        self.assertEqual(request["clusters"], [])
        self.assertEqual(request["exemplar_changes"]["bundle"], "nalu-exemplars@1")
        self.assertEqual(len(request["exemplar_changes"]["added"]), 2)
        self.assertIn("DIRECTING_GUIDANCE", request["instructions"])
        self.train.import_review({"schema": rt.RESULT_SCHEMA, "request_id": request["request_id"],
                                  "reviewer": "patrol", "decisions": []})
        self.clock[0] = T0 + 25 * 3600
        promoted = self.train.exemplar_step()
        self.assertEqual((promoted["status"], promoted["released_version"]), ("PROMOTED", 2), promoted)
        synced = s3.sync_channels(self.svc, store, self.root, TENANT)
        self.assertEqual(synced["latest_by_channel"]["RELEASED"], {"nalu-exemplars": "2"})
        status = self.train.status()
        self.assertEqual((status["exemplars"]["count"], status["exemplars"]["released_version"]), (2, 2))
        self.assertTrue(status["summary_zh"].endswith("样例 2"))
        self.assertEqual(self.train.exemplar_step()["status"], "UNCHANGED")

    def test_patrol_veto_revokes_canary_and_excludes_entry(self) -> None:
        bad, good = shot_ex(1), shot_ex(2, action="CHASE", setting="EXTERIOR", beat="角色A在巷口追上角色B")
        self.exemplar_event("sn-c1", "E03", bad, at=T0 - 3600)
        self.exemplar_event("sn-r1", "E03", good, at=T0 - 3600)
        self.assertEqual(self.train.exemplar_step()["status"], "PUBLISHED_TO_CANARY")
        request = self.request()
        out = self.train.import_review({"schema": rt.RESULT_SCHEMA, "request_id": request["request_id"],
                                        "reviewer": "patrol", "decisions": [], "exemplar_veto": [bad["exemplar_id"]],
                                        "exemplar_veto_reason": "beat reads as a template"})
        self.assertEqual(out["exemplar_veto"]["revoked_canary"], 1)
        again = self.train.exemplar_step()
        self.assertEqual((again["status"], again["count"]), ("PUBLISHED_TO_CANARY", 1), again)
        state = self.train.state()
        library = next(p for p in reversed(state["exemplars"]["packs"]) if p["status"] == "CANARY")["library"]
        self.assertEqual([e["exemplar_id"] for e in library], [good["exemplar_id"]])

    def test_release_gate_refuses_a_library_with_private_content(self) -> None:
        dirty = copy.deepcopy(shot_ex(1))
        dirty["spec"]["blocking"] = "见 /Users/stone/x.json"
        bundle = {"schema": c.BUNDLE_SCHEMA, "bundle_id": "nalu-exemplars", "version": 1, "created_at": c.now_iso(),
                  "release_channel": "CANARY", "compat": {"engine_api_versions": ["nalu-engine-api-1"], "models": [H3]},
                  "rules": [], "exemplars": [dirty]}
        with self.assertRaises(b.BundleError):
            b.sign_bundle(bundle, key_id="pub-fleet", private_raw=self.private)
        gate = s3.ServiceReleaseGate(self.svc, TENANT)
        self.assertTrue(any(x.startswith("EXEMPLAR_INVALID") for x in
                            gate.blockers("CANARY", bundle, bundle_id="nalu-exemplars", version="1")))


# --------------------------------------------------------------------------- device-side selection
class SelectionTest(unittest.TestCase):
    def test_language_required_genre_and_scene_preferred_diverse_types(self) -> None:
        library = [shot_ex(1, genre="都市甜宠", overall=4.9),
                   shot_ex(2, beat="角色A推门对峙角色B"),
                   shot_ex(3, action="CHASE", setting="EXTERIOR", beat="角色A在巷口追上角色B"),
                   shot_ex(4, action="EMBRACE", beat="角色A抱住角色B不放"),
                   shot_ex(5, language="en", beat="Character A slams the ledger down", overall=5.0),
                   ex.practice_exemplar("opening", 4.8, "开场 3 秒内对峙成立，钩子强", language="zh", genre="悬疑",
                                        model=H3, overall=4.5)]
        hints = {"action_type": {"CHASE": 5, "CONFRONTATION": 1}, "setting": {"EXTERIOR": 5}}
        chosen = ex.select_for_episode(library, language="zh", genre="悬疑", model=H3, scene_hints=hints)
        self.assertEqual([e["kind"] for e in chosen], ["SHOT", "SHOT", "EPISODE_PRACTICE"])
        self.assertEqual(chosen[0]["tags"]["action_type"], "CHASE")         # matches the upcoming scenes
        self.assertEqual(chosen[1]["tags"]["action_type"], "CONFRONTATION")  # a different type, genre match first
        self.assertEqual(chosen[1]["tags"]["genre"], "悬疑")
        self.assertTrue(all(e["tags"]["language"] == "zh" for e in chosen))
        self.assertEqual(ex.select_for_episode(library, language="fr"), [])
        line = ex.render_line(chosen[0])
        self.assertIn("外景", line)
        self.assertLessEqual(len(line), ex.RENDER_MAX)


if __name__ == "__main__":
    unittest.main()
