"""BILI_V1 craft ledger (owner 2026-11-23, Bilibili ep3 benchmark, CHANGE_SPEC WP6).

Covers: the ep3 excerpt (第三集分析 §2c) encoded as a contract yields >= 7 threads, 1 HOOK and 2 CALLBACKs and
passes even in the REQUIRED phase; legacy-style contracts trip LEDGER_THIN and NO_IRONY; the advisory window (first
three episodes of a series) vs required; series ledger append / resolve across two episodes and open threads;
signature business 1-3 uses; TURN_TALKED; inserts <= 3 and only ledger props; object-first faceless inserts;
mirrored scenes; the screenplay YAML blocks (SCREENPLAY_V1) produce the same contract fields; S1 integration only
under BILI_V1 (LEGACY byte-identical pacing report and Codex start prompt).  Offline, no paid call."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
for _p in (ROOT / "lines" / "nalu" / "runtime" / "tools", ROOT / "skills" / "nalu-claude-code" / "scripts",
           ROOT / "tools", ROOT):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import craft_ledger as cl  # noqa: E402
import script_pacing_check as sp  # noqa: E402

BIN, ZUO, ZHOU, MI = "CHAR-BIN", "CHAR-ZUOSHOU", "CHAR-ZEUS", "CHAR-GUIMI"
ENTITIES = [{"character_id": BIN, "canonical_name": "Bin", "aliases": []},
            {"character_id": ZUO, "canonical_name": "左手", "aliases": []},
            {"character_id": ZHOU, "canonical_name": "宙斯", "aliases": []},
            {"character_id": MI, "canonical_name": "闺蜜", "aliases": []}]


def shot(sid, seconds, dialogue="", action="", cast=(), props=(), beat_role="", scale="MEDIUM", **spec_extra):
    spec = {"dialogue": dialogue, "cast": [c if isinstance(c, dict) else {"character_id": c} for c in cast],
            "camera_plan": {"motion_family": "LOCKED", "shot_scale": scale}, "action": {"primary_action": action}}
    if props:
        spec["props"] = list(props)
    if beat_role:
        spec["beat_role"] = beat_role
    spec.update(spec_extra)
    scene = sid.rsplit("-", 1)[0]
    return {"shot_id": sid, "scene_id": scene, "target_seconds": seconds, "prompt_spec": spec}


def ep3_contract() -> dict:
    """第三集分析 §2c: scenes 6-7 (dorm -> washroom), 11-12 (wire fence -> sunset), 16 (now, snow)."""
    shots = [
        # S06 dorm: the photo (object-first: hands + jacket pocket, then the phone screen)
        shot("E03-S06-01", 4, action="左手从夹克内袋掏出手机，拇指往上划", beat_role="INSERT", scale="INSERT",
             cast=[{"character_id": ZUO, "visible_body_range": "HANDS_ONLY"}], props=["PROP-PHONE"],
             object_first={"subject": "HANDS", "of": ZUO, "then": "INSERT"}),
        shot("E03-S06-02", 4, action="屏幕上眼镜女孩比心，粉色小熊发夹", beat_role="INSERT", scale="INSERT",
             props=["PROP-PHONE"]),
        shot("E03-S06-03", 4, dialogue="卷毛：就是她！没错！", action="卷毛凑过来指着手机", cast=[ZUO, BIN]),
        shot("E03-S06-04", 4, dialogue="Bin：可以啊，眼光不错。", action="Bin 的脸被屏幕光照亮，把笑重新撑起来",
             cast=[BIN, ZUO], beat_role="REVEAL"),
        shot("E03-S06-05", 4, dialogue="众人：嫂子！", action="Bin 张嘴像要笑，抬手捂住嘴，起身", cast=[BIN, ZUO]),
        # S07 washroom: the turn, played in silence
        shot("E03-S07-01", 5, action="Bin 拧开水龙头，搓手，捧一把水，抬头看镜子，抿住嘴唇；前景手实焦，后景脸虚",
             cast=[BIN], props=["PROP-TAP"]),
        shot("E03-S07-02", 5, dialogue="左手：那个……帮个忙。", action="左手探身进来，把 Bin 堵在墙边，双手合十",
             cast=[ZUO, BIN]),
        shot("E03-S07-03", 4, dialogue="Bin：说。", cast=[BIN, ZUO]),
        shot("E03-S07-04", 5, dialogue="左手：你帮我去要个电话……我不敢。", action="左手眼睛往下躲，摸后颈",
             cast=[ZUO, BIN]),
        shot("E03-S07-05", 4, dialogue="Bin：没问题。", action="Bin 停一拍，笑", cast=[BIN, ZUO], beat_role="TURN",
             lead_in_reaction_en="For the first 1.5 s Bin pauses a beat, then smiles"),
        # S11 wire fence: the misunderstanding is sealed
        shot("E03-S11-01", 4, dialogue="男生：来抢呀！", action="两个男生把宙斯的手机举过头顶", cast=[ZHOU],
             props=["PROP-ZEUS-PHONE"]),
        shot("E03-S11-02", 4, action="一只手从画外攥住举手机那人的手腕", cast=[ZUO], props=["PROP-ZEUS-PHONE"]),
        shot("E03-S11-03", 4, dialogue="宙斯：要我电话号码的人，是你一个宿舍的吧？", action="宙斯把手机抵在下巴上",
             cast=[ZHOU, ZUO], props=["PROP-ZEUS-PHONE"]),
        shot("E03-S11-04", 4, dialogue="左手：是……是的。", action="左手闭眼，手摸到后颈", cast=[ZUO, ZHOU],
             double_meaning=True),
        # S12 sunset: Bin watches them go
        shot("E03-S12-01", 9, action="远处 Bin 一个人站着，眼皮慢慢垂下；前景两人虚掉的肩", cast=[BIN, ZUO, ZHOU],
             beat_role="SILENCE"),
        # S16 now: the plan, the hook
        shot("E03-S16-01", 5, dialogue="宙斯：为什么 Bin 喜欢她……却把我当妹妹。", action="宙斯抱着靠枕哭", cast=[ZHOU, MI]),
        shot("E03-S16-02", 5, dialogue="闺蜜：Bin 看见你就把手松开了。", action="闺蜜竖起一根手指", cast=[MI, ZHOU]),
        shot("E03-S16-03", 4, action="一只手松开另一只手（第二集）", beat_role="INSERT", scale="INSERT",
             props=["PROP-HANDS-E02"]),
        shot("E03-S16-04", 5, dialogue="闺蜜：你让他拿你发誓，他也不敢。", action="闺蜜竖起第二根手指", cast=[MI, ZHOU]),
        shot("E03-S16-05", 5, dialogue="宙斯：然后呢？", action="宙斯一把抓住闺蜜的手", cast=[ZHOU, MI]),
        shot("E03-S16-06", 6, dialogue="闺蜜：Chovy 只喜欢上路最强的人。", cast=[MI, ZHOU]),
        shot("E03-S16-07", 4, dialogue="宙斯：练！", action="宙斯起身走到门口回头", cast=[ZHOU, MI], beat_role="ENDING"),
    ]
    plan = [{"scene_id": s, "objective": "o", "conflict": "c", "physical_action": "a", "time_of_day": t,
             "light": l, "set_pieces": sp_} for s, t, l, sp_ in (
        ("E03-S06", "夜", "暖灯、屏幕光", ["沙发"]), ("E03-S07", "夜", "冷白顶灯", ["水龙头", "镜子"]),
        ("E03-S11", "傍晚", "斜阳", ["铁丝网"]), ("E03-S12", "傍晚", "夕阳逆光", ["铁丝网"]),
        ("E03-S16", "现在·夜", "下雪、串灯", ["门", "纸巾"]))]
    plan[1]["turn_shot_id"], plan[1]["turn_owner"] = "E03-S07-05", BIN
    plan[3]["mirror_of"] = "E03-S11"
    ledger = [
        {"id": "photo", "kind": "SETUP", "thread": "照片", "shot_id": "E03-S06-02", "prop": "PROP-PHONE"},
        {"id": "saozi", "kind": "SETUP", "thread": "嫂子", "shot_id": "E03-S06-05"},
        {"id": "phone-ask", "kind": "SETUP", "thread": "要电话", "scene_id": "E03-S07", "anchor": "要个电话"},
        {"id": "photo-pay", "kind": "PAYOFF", "thread": "照片", "shot_id": "E03-S11-03", "pays_off": "phone-ask"},
        {"id": "hand-pay", "kind": "PAYOFF", "thread": "手", "shot_id": "E03-S11-02", "pays_off": "E02:hand",
         "prop": "PROP-ZEUS-PHONE"},
        {"id": "neck", "kind": "PAYOFF", "thread": "摸后颈", "shot_id": "E03-S11-04", "pays_off": "saozi"},
        {"id": "toplane", "kind": "SETUP", "thread": "上路", "shot_id": "E03-S16-06"},
        {"id": "release", "kind": "CALLBACK", "thread": "松开的手", "shot_id": "E03-S16-03", "from_episode": "E02",
         "prop": "PROP-HANDS-E02"},
        {"id": "oath", "kind": "CALLBACK", "thread": "发誓", "shot_id": "E03-S16-04", "from_episode": "E02"},
        {"id": "lian", "kind": "HOOK", "thread": "下集：练！", "shot_id": "E03-S16-07"},
    ]
    knowledge = [{"scene_id": "E03-S06", "who": "AUDIENCE", "knows": "照片里的人就是昨天 Bin 帮忙搬行李的女孩",
                  "hidden_from": [ZUO]},
                 {"scene_id": "E03-S11", "who": ZHOU, "believes": "要她电话的人是 Bin，左手只是他室友"}]
    card = {"characters": [
        {"character_id": ZUO, "name": "左手", "signature_business": "摸后颈", "signature_prop": "手机"},
        {"character_id": BIN, "name": "Bin", "signature_business": "捂嘴、抿嘴", "signature_prop": "篮球"},
        {"character_id": ZHOU, "name": "宙斯", "signature_business": "手机抵在下巴", "cues": ["抵在下巴"],
         "signature_prop": "紫色手机壳"}]}
    return {"schema": "qingshan.generation_contract.v3", "episode": "E03", "dialogue_language": "zh",
            "craft_profile": "BILI_V1", "character_entities": ENTITIES, "shots": shots,
            "scene_states": [{"scene_id": r["scene_id"]} for r in plan],
            "pacing": {"scene_plan": plan}, "ledger": ledger, "knowledge": knowledge, "series_card": card}


def e02_ledger(root: Path) -> None:
    cl._write_json(cl.ledger_path(root), {"schema": cl.LEDGER_SCHEMA, "episodes": {
        "E02": {"rows": [{"id": "hand", "kind": "SETUP", "thread": "手"},
                         {"id": "solo", "kind": "HOOK", "thread": "SOLO 世一上"}]}}})


def legacy_contract() -> dict:
    """An archived-style contract (E11 / E25 shape): good pacing fields, no WP6 fields at all."""
    shots = [shot(f"E11-S0{1 + i // 4}-{i + 1:02d}", 4.5, f"林岚：第{i}句话。", "林岚抓住周默的手腕",
                  cast=["CHAR-LIN", "CHAR-ZHOU"]) for i in range(16)]
    return {"episode": "E11", "shots": shots, "character_entities": [
        {"character_id": "CHAR-LIN", "canonical_name": "林岚", "aliases": []}]}


class Ep3AcceptanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(tempfile.mkdtemp())
        e02_ledger(self.root)

    def test_ep3_excerpt_threads_hook_callbacks_and_pass(self) -> None:
        r = cl.evaluate(ep3_contract(), runtime_root=self.root, phase="REQUIRED")
        m = r["metrics"]
        self.assertGreaterEqual(m["threads"], 7)
        self.assertEqual(m["hooks"], 1)
        self.assertGreaterEqual(m["callbacks"], 2)
        self.assertEqual((r["status"], r["failures"]), ("PASS", []))
        self.assertEqual(r["warnings"], [])
        self.assertEqual(m["insert_units"], 3)
        self.assertEqual(m["insert_credits_estimate"], 13.1)
        self.assertEqual(m["uses"], {ZUO: 2, BIN: 2, ZHOU: 1})
        self.assertEqual(m["irony_points"], 3)
        self.assertEqual(m["object_first_entrances"], 1)

    def test_contract_still_validates_against_the_writer_schema(self) -> None:
        import script_structure_contract_gate as ssg
        schema = ssg.load_contract_schema()
        errors = [e for e in ssg.schema_errors(ep3_contract(), schema)
                  if any(k in e for k in ("ledger", "knowledge", "series_card", "scene_plan"))]
        self.assertEqual(errors, [])

    def test_legacy_style_contracts_trip_ledger_thin_and_no_irony(self) -> None:
        for contract in (legacy_contract(), json.loads(json.dumps(ep3_contract()))):
            if contract.get("ledger"):
                contract.pop("ledger"), contract.pop("knowledge")
                for s in contract["shots"]:
                    s["prompt_spec"].pop("double_meaning", None)
            r = cl.evaluate(contract, runtime_root=self.root, phase="REQUIRED")
            heads = {c.split(":")[0] for c in r["failures"] + r["warnings"]}
            self.assertIn("LEDGER_THIN", heads)
            self.assertIn("NO_IRONY", heads)
            self.assertIn("LEDGER_THIN", {c.split(":")[0] for c in r["failures"]})


class PhaseTest(unittest.TestCase):
    def test_first_three_episodes_are_advisory_then_required(self) -> None:
        root = Path(tempfile.mkdtemp())
        c = legacy_contract()
        r = cl.evaluate(c, runtime_root=root)
        self.assertEqual((r["phase"], r["advisory_episodes_left"]), ("ADVISORY", 3))
        self.assertEqual(r["failures"], [])
        self.assertTrue(any(w.startswith("LEDGER_THIN") for w in r["warnings"]))
        for ep in ("E08", "E09", "E10"):
            cl.record_episode(root, ep, {"episode": ep, "shots": []})
        r = cl.evaluate(c, runtime_root=root)
        self.assertEqual((r["phase"], r["advisory_episodes_left"]), ("REQUIRED", 0))
        self.assertTrue(any(f.startswith("LEDGER_THIN") for f in r["failures"]))
        self.assertTrue(any(f.startswith("LEDGER_THIN") and "callback=0<1" in f for f in r["failures"]))
        # advisory codes never become failures
        self.assertIn("NO_IRONY", r["warnings"])
        self.assertNotIn("NO_IRONY", r["failures"])

    def test_insert_cap_is_taste_from_the_first_episode(self) -> None:
        c = ep3_contract()
        c["shots"].insert(1, shot("E03-S06-09", 4, action="手机特写", beat_role="INSERT", scale="INSERT",
                                  props=["PROP-PHONE"]))
        r = cl.evaluate(c, runtime_root=Path(tempfile.mkdtemp()))
        self.assertEqual(r["phase"], "ADVISORY")
        self.assertIn("INSERT_OVER:4>3", r["failures"])
        c = ep3_contract()
        c["shots"][17]["prompt_spec"]["props"] = ["PROP-TEACUP"]
        r = cl.evaluate(c, runtime_root=Path(tempfile.mkdtemp()))
        self.assertIn("INSERT_WITHOUT_LEDGER_PROP:E03-S16-03", r["failures"])


class SeriesLedgerTest(unittest.TestCase):
    def test_append_and_resolve_across_two_episodes(self) -> None:
        root = Path(tempfile.mkdtemp())
        (root / "sources" / "lpl").mkdir(parents=True)
        (root / "sources" / "lpl" / "SOURCE_INDEX.json").write_text("{}", encoding="utf-8")
        e1 = ep3_contract()
        e1["episode"] = "E01"
        e1["ledger"] = [{"id": "luggage", "kind": "SETUP", "thread": "行李", "scene_id": "E03-S06"},
                        {"id": "photo", "kind": "SETUP", "thread": "照片", "shot_id": "E03-S06-02"},
                        {"id": "lian", "kind": "HOOK", "thread": "练", "shot_id": "E03-S16-07"}]
        out = cl.record_episode(root, "E01", e1)
        self.assertEqual(out["series"], "lpl")
        self.assertTrue((root / "sources" / "lpl" / "LEDGER.json").is_file())
        self.assertEqual({t["id"] for t in out["open_threads"]}, {"luggage", "photo", "lian"})
        stored = json.loads((root / "sources" / "lpl" / "LEDGER.json").read_text())
        self.assertEqual(stored["episodes"]["E01"]["rows"][0]["shot_id"], "E03-S06-01")   # scene -> first shot
        e2 = ep3_contract()
        e2["episode"] = "E02"
        e2["ledger"] = [{"id": "p1", "kind": "PAYOFF", "thread": "行李", "shot_id": "E03-S11-03",
                         "pays_off": "luggage"},
                        {"id": "p2", "kind": "PAYOFF", "thread": "练", "shot_id": "E03-S16-02", "pays_off": "E01:lian"},
                        {"id": "p3", "kind": "PAYOFF", "thread": "?", "shot_id": "E03-S16-04", "pays_off": "nope"}]
        r = cl.evaluate(e2, runtime_root=root, phase="REQUIRED")
        self.assertEqual(r["metrics"]["callbacks"], 2)
        self.assertIn("LEDGER_PAYOFF_UNRESOLVED:p3:nope", r["failures"])
        self.assertEqual({t["id"] for t in r["open_threads"]}, {"luggage", "photo", "lian"})
        cl.record_episode(root, "E02", e2)
        ledger = cl.load_series_ledger(root, "lpl")
        self.assertEqual([t["id"] for t in cl.open_threads(ledger)], ["photo"])
        self.assertEqual(cl.prior_episodes(ledger, "E03"), ["E01", "E02"])
        cl.record_episode(root, "E02", e2)                          # re-recording replaces the row
        self.assertEqual(len(cl.load_series_ledger(root, "lpl")["episodes"]), 2)
        self.assertIn("photo", cl.codex_note_zh(root, "E03"))

    def test_record_never_raises(self) -> None:
        self.assertEqual(cl.record_episode(Path("/dev/null/x"), "E01", ep3_contract()), {})


class ChecksTest(unittest.TestCase):
    def ev(self, c):
        root = Path(tempfile.mkdtemp())
        e02_ledger(root)
        return cl.evaluate(c, runtime_root=root, phase="REQUIRED")

    def test_signature_business_unused_overused_and_missing_card(self) -> None:
        c = ep3_contract()
        c["series_card"]["characters"][2]["cues"] = ["叉腰"]
        self.assertIn(f"SIGNATURE_BUSINESS_UNUSED:{ZHOU}", self.ev(c)["failures"])
        c = ep3_contract()
        for s in c["shots"][15:19]:
            s["prompt_spec"]["signature_business"] = ZHOU
        self.assertTrue(any(f.startswith(f"SIGNATURE_BUSINESS_OVERUSED:{ZHOU}") for f in self.ev(c)["failures"]))
        c = ep3_contract()
        c.pop("series_card")
        self.assertIn("SIGNATURE_CARD_MISSING", self.ev(c)["failures"])

    def test_series_card_from_runtime_config_and_yaml_file(self) -> None:
        c = ep3_contract()
        card = c.pop("series_card")
        root = Path(tempfile.mkdtemp())
        (root / "qingshan.json").write_text(json.dumps({"project": {"series_card": card}}), encoding="utf-8")
        self.assertEqual(cl.load_series_card(c, root)["characters"][0]["cues"], ["摸后颈"])
        scripts = Path(tempfile.mkdtemp())
        (scripts / "SERIES_CARD.yaml").write_text(
            "premise: 电竞梗演韩剧\ncharacters:\n  - character_id: CHAR-ZUOSHOU\n    name: 左手\n"
            "    signature_business: 摸后颈\n    signature_prop: 手机\n", encoding="utf-8")
        loaded = cl.load_series_card(c, Path(tempfile.mkdtemp()), scripts)
        self.assertEqual((loaded["premise"], loaded["characters"][0]["signature_business"]), ("电竞梗演韩剧", "摸后颈"))

    def test_turn_talked(self) -> None:
        c = ep3_contract()
        c["pacing"]["scene_plan"][4]["turn_shot_id"] = "E03-S16-07"
        r = self.ev(c)
        self.assertTrue(any(w.startswith("TURN_TALKED:E03-S16:CHAR-ZEUS:lines=3") for w in r["warnings"]))
        c = ep3_contract()
        spec = c["shots"][9]["prompt_spec"]
        spec.pop("lead_in_reaction_en"), spec["action"].pop("primary_action")
        self.assertIn("TURN_TALKED:E03-S07:E03-S07-05:no_action_or_reaction", self.ev(c)["warnings"])

    def test_time_place_mirror_and_object_first(self) -> None:
        c = ep3_contract()
        c["pacing"]["scene_plan"][0].pop("light")
        c["pacing"]["scene_plan"][2]["mirror_of"] = "E03-S99"
        c["pacing"]["scene_plan"][4]["mirror_of"] = "E02-S05"            # an earlier episode: fine
        c["shots"][14]["prompt_spec"]["camera_plan"]["shot_scale"] = "WIDE"
        c["shots"][0]["prompt_spec"]["cast"] = [{"character_id": ZUO}]   # object-first insert showing a face
        w = self.ev(c)["warnings"]
        self.assertIn("NO_TIME_PLACE:E03-S06:light", w)
        self.assertIn("MIRROR_UNRESOLVED:E03-S11:E03-S99", w)
        self.assertIn("MIRROR_SETUP_DIFFERS:E03-S12<E03-S11:shot_scale", w)
        self.assertIn("OBJECT_FIRST_FACE_SHOWN:E03-S06-01", w)
        self.assertNotIn("OBJECT_FIRST_NONE", w)
        self.assertIn("OBJECT_FIRST_NONE", self.ev(legacy_contract())["warnings"])

    def test_director_hints(self) -> None:
        hints = cl.director_hints(ep3_contract())
        self.assertEqual(hints["object_first"][0]["shot_id"], "E03-S06-01")
        self.assertEqual(hints["mirror_setups"]["E03-S12"]["mirror_of"], "E03-S11")
        self.assertEqual(hints["mirror_setups"]["E03-S12"]["shot_scale"], "MEDIUM")
        self.assertEqual(hints["insert_max"], 3)


class ScreenplayYamlTest(unittest.TestCase):
    """SCREENPLAY_V1 (WP2): the same fields from the screenplay's YAML blocks."""

    OUTLINE = """# E03 OUTLINE
## knowledge
```yaml
knowledge:
  - {scene_id: E03-S06, who: AUDIENCE, knows: 照片里的人就是她, hidden_from: [CHAR-ZUOSHOU]}
  - scene_id: E03-S11
    who: CHAR-ZEUS
    以为: 要电话的是 Bin   # zh key
```
"""
    CAST_PROPS = """cast:
  CHAR-BIN: Bin
ledger:
  - {id: photo, kind: SETUP, thread: 照片, scene_id: E03-S06, anchor: 比心}
  - id: phone-ask
    kind: 伏笔
    thread: 要电话
    scene_id: E03-S07
    anchor: "要个电话"
  - {id: photo-pay, kind: PAYOFF, thread: 照片, scene_id: E03-S11, anchor: 抵在下巴, pays_off: phone-ask}
  - {id: lian, kind: HOOK, thread: "下集：练！", scene_id: E03-S16}
"""
    CARD = "characters:\n  - {character_id: CHAR-ZUOSHOU, name: 左手, signature_business: 摸后颈}\n"

    def test_light_yaml(self) -> None:
        self.assertEqual(cl.load_light_yaml("a: 1\nb:\n  - x\n  - {k: v, n: [1, 2.5, true, null]}\nc: 'q: r'\n"),
                         {"a": 1, "b": ["x", {"k": "v", "n": [1, 2.5, True, None]}], "c": "q: r"})
        self.assertEqual(cl.load_light_yaml("k:\n- a\n- b  # c\n"), {"k": ["a", "b"]})
        with self.assertRaises(cl.YamlError):
            cl.load_light_yaml("a: {b: 1\n")
        blocks = cl.extract_yaml_blocks("x\n```yaml\na: [1]\n```\n```yaml\na: [2]\nb: {\n```\n")
        self.assertEqual(blocks["a"], [1])
        self.assertEqual(len(blocks["_errors"]), 1)

    def test_screenplay_fields_compile_into_the_same_contract_checks(self) -> None:
        fields = cl.screenplay_fields(self.OUTLINE, self.CAST_PROPS, self.CARD)
        self.assertEqual([r["kind"] for r in fields["ledger"]], ["SETUP", "SETUP", "PAYOFF", "HOOK"])
        self.assertEqual([r["type"] for r in fields["knowledge"]], ["KNOWS", "BELIEVES"])
        self.assertEqual(fields["series_card"]["characters"][0]["cues"], ["摸后颈"])
        base = ep3_contract()
        for key in ("ledger", "knowledge", "series_card"):
            base.pop(key)
        compiled = cl.apply_fields(base, fields)
        self.assertEqual([r["shot_id"] for r in compiled["ledger"]],
                         ["E03-S06-02", "E03-S07-04", "E03-S11-03", "E03-S16-07"])
        r = cl.evaluate(compiled, runtime_root=Path(tempfile.mkdtemp()), phase="REQUIRED")
        self.assertEqual(r["metrics"]["hooks"], 1)
        self.assertEqual(r["metrics"]["irony_points"], 3)   # audience edge + false belief + double meaning
        self.assertEqual(r["metrics"]["uses"], {ZUO: 2})
        self.assertTrue(any(f.startswith("LEDGER_THIN:payoff=1<2") for f in r["failures"]))
        self.assertEqual(cl.apply_fields(compiled, fields)["ledger"], compiled["ledger"])   # idempotent

    def test_cli(self) -> None:
        tmp = Path(tempfile.mkdtemp())
        (tmp / "c.json").write_text(json.dumps(legacy_contract(), ensure_ascii=False), encoding="utf-8")
        (tmp / "p.yaml").write_text(self.CAST_PROPS, encoding="utf-8")
        with mock.patch("sys.stdout"):
            self.assertEqual(cl.main(["check", "--contract", str(tmp / "c.json"), "--runtime-root", str(tmp)]), 0)
            self.assertEqual(cl.main(["check", "--contract", str(tmp / "c.json"), "--runtime-root", str(tmp),
                                      "--phase", "REQUIRED", "--strict"]), 3)
            self.assertEqual(cl.main(["open", "--runtime-root", str(tmp)]), 0)
            self.assertEqual(cl.main(["fields", str(tmp / "p.yaml")]), 0)


class S1IntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        import nalu_pipeline as npl
        self.npl = npl
        self.tmp = Path(tempfile.mkdtemp())

    def run_s1(self, contract: dict, profile: str | None):
        path = self.tmp / "contract.json"
        path.write_text(json.dumps(contract, ensure_ascii=False), encoding="utf-8")
        p = SimpleNamespace(contract=path, logs=self.tmp / "logs")
        ctx = SimpleNamespace(episode=contract["episode"], run_id="r1", language="zh",
                              **({"craft_profile": profile} if profile else {}))
        with mock.patch.object(self.npl, "RUNTIME", self.tmp / "runtime"):
            return self.npl.s1_script_pacing(ctx, p, others_ok=True)

    def test_legacy_pacing_report_is_byte_identical(self) -> None:
        c = legacy_contract()
        row, blockers = self.run_s1(c, None)
        report = json.loads(Path(row["report"]).read_text(encoding="utf-8"))
        expected = sp.evaluate(c, "zh", in_flight=False, source_texts=[])
        self.assertEqual(json.dumps(report, sort_keys=True), json.dumps(expected, sort_keys=True))
        self.assertNotIn("craft_ledger", row)
        self.assertNotIn("series_ledger", row)
        self.assertFalse((self.tmp / "runtime" / "series" / "LEDGER.json").exists())

    def test_bili_v1_merges_and_records_the_series_ledger(self) -> None:
        row, _ = self.run_s1(ep3_contract(), "BILI_V1")
        self.assertEqual(row["craft_ledger"]["phase"], "ADVISORY")
        report = json.loads(Path(row["report"]).read_text(encoding="utf-8"))
        self.assertIn("craft_ledger", report)
        if row.get("decision") not in ("REVISE",):
            self.assertTrue((self.tmp / "runtime" / "series" / "LEDGER.json").is_file())
            self.assertEqual(row["series_ledger"]["episodes"], ["E03"])

    def test_bili_v1_required_phase_sends_a_thin_ledger_back_to_the_writer(self) -> None:
        root = self.tmp / "runtime"
        for ep in ("E08", "E09", "E10"):
            cl.record_episode(root, ep, {"episode": ep, "shots": []})
        row, blockers = self.run_s1(legacy_contract(), "BILI_V1")
        self.assertEqual(row["craft_ledger"]["phase"], "REQUIRED")
        self.assertEqual(row["decision"], "REVISE")
        self.assertTrue(any(f.startswith("LEDGER_THIN") for f in row["craft_ledger"]["failures"]))
        report = json.loads(Path(row["report"]).read_text(encoding="utf-8"))
        self.assertTrue(any(f.startswith("LEDGER_THIN") for f in report["failures"]))
        self.assertIn("LEDGER_THIN", report["fixes"])


class CodexPromptTest(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = dict(os.environ)
        self.runtime = Path(tempfile.mkdtemp()) / "nalu_runtime"
        self.runtime.mkdir(parents=True)
        os.environ.update(NALU_ENGINE_ROOT=str(ROOT), NALU_RUNTIME_ROOT=str(self.runtime))
        import codex_production as cp
        import nalu_craft_standard as craft
        self.cp, self.craft = cp, craft

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.saved)

    def test_legacy_start_prompt_is_unchanged(self) -> None:
        with mock.patch.object(self.cp, "roots", return_value=(ROOT, self.runtime)):
            section = self.cp.craft_standard_section("E03")
            self.assertEqual(section, self.craft.codex_section(ROOT))
            self.assertEqual(self.cp.craft_ledger_section("E03"), "")

    def test_bili_v1_start_prompt_carries_the_ledger_note(self) -> None:
        (self.runtime / "qingshan.json").write_text(json.dumps({"project": {"craft_profile": "BILI_V1"}}),
                                                    encoding="utf-8")
        with mock.patch.object(self.cp, "roots", return_value=(ROOT, self.runtime)):
            section = self.cp.craft_standard_section("E03")
        self.assertTrue(section.startswith(self.craft.codex_section(ROOT)))
        self.assertIn(cl.CODEX_NOTE_TITLE, section)


if __name__ == "__main__":
    unittest.main()
