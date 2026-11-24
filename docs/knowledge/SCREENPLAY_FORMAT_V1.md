# Screenplay format (SCREENPLAY_V1)

Owner decision 2026-11-23, from the Bilibili benchmark (`~/Desktop/B站对标分析/剧本反推.md`, CHANGE_SPEC WP2). Under `craft_profile: BILI_V1` with `writer_format: SCREENPLAY_V1` (`docs/knowledge/CRAFT_PROFILE.md`), the writer writes a Chinese prose screenplay plus light YAML. S1 compiles them into the four legacy layers, so S2–S8 keep working unchanged.

- Compiler: `lines/nalu/runtime/tools/screenplay_compile.py`
- Checks: `lines/nalu/runtime/tools/screenplay_checks.py` (called from `script_pacing_check.evaluate`)
- Lexicon: `lines/nalu/runtime/configs/SCREENPLAY_LEXICON_V1.json`
- Worked example (E25 妖皇宫, ch.226): `tools/tests/fixtures/screenplay_e25/`
- Tests: `tools/tests/test_screenplay_compile.py`, `tools/tests/test_anti_template_v2.py`

## Files

All under `workflow/claude_writer_agent/scripts/` (next to the contract).

| File | Layer | Content |
|---|---|---|
| `SERIES_CARD.yaml` | L0 | premise, engine, `protagonist_ids`, `visual_culture_contract`, `characters[{id, name, want, fear, voice, signature_business, signature_prop}]` |
| `<EP>_OUTLINE.md` | L1 | prose, plus one fenced `yaml` block: `title`, `source_chapters`, `plot_events[{event, chapter, role: MAIN\|SECONDARY}]`, `cut`, `hook`, `end_hook.open_question`, `carry_in`, `knowledge` |
| `<EP>_SCREENPLAY.md` | L2 + L3 | scene cards and the prose screenplay; **the compile input** |
| `<EP>_CAST_PROPS.yaml` | — | `cast`, `props`, `locations`, `source`, `ledger` |
| `<EP>_SCREENPLAY_EN.json` | — | English twins, `{schema: nalu.screenplay_en.v1, rows: {key: english}}` |

The light YAML is a stdlib subset: block mappings and lists, flow `[...]` / `{...}`, quoted and plain scalars, `|` / `>` blocks and comments. WP6's `craft_ledger.load_light_yaml` is used when the engine ships it. JSON is accepted too.

## Screenplay grammar

```
## S01 妖皇宫正殿 · 日 · 殿门逆光
@card goal[白桃]=拿一句臣服交差 | obstacle=妖皇不在 | turn=正主进门一口答应，狠话落空 | type=争吵→喜剧落空 | source=翘着二郎腿;拱了拱手 | mirror_of=- | mood=comic_bounce | music_stop=S01-12
{道具 战神令 @白桃.右手 金色令牌}
（无声）妖皇宝座上，白桃帝姬翘着二郎腿，右手指尖转着战神令。 #招牌
白桃（不抬眼，悠悠，对战雷）：三天到了。你们的妖皇呢？
白桃停下令牌，"嗒"地磕在宝座扶手上。
白桃（冷笑）：三天变五天，你当我是来做客的？ #爽点:THREAT_ESCALATION
[麒麟 反应：离开柱子，右拳攥紧]
商余烬（OS，殿外）：找我何事？
麒麟冲上一步，抓住商余烬的袖子：带上我。
```

| Line | Meaning |
|---|---|
| `## Snn 地点 · 时间 · 光线` | a scene. The place is matched against `locations[].name` (or `@card location=LOC-…`) |
| `@card k=v \| …` | the scene card. `goal[人]` (repeatable), `obstacle`, `turn`, `type`, `source` (`;`-separated source detail quotes), `source_lines`, `mirror_of`, `mood`, `music_stop` |
| `名字（括号）：台词` | a dialogue line. The parenthetical gives the addressee (`对X`), off-screen (`OS`, `画外`, `殿外` …), delivery cues and an explicit `情绪=怒` |
| `名字<动作>：台词` | an action and the line in one row (the action is the speaker's) |
| `[X 反应：…]` | a reaction beat |
| `{道具 名 @人.手 描述}` | a prop declaration (or in CAST_PROPS `props`) |
| `（无声）…` | a silent shot |
| other prose | an action line: who, which hand, what object, what changes |
| `#标签` at line end | `#揭示[:TYPE]` REVEAL, `#转折[:TYPE]` TURN (the scene's slow push), `#爽点:TYPE` PAYOFF, `#攻击` ATTACK, `#笑点` PUNCHLINE, `#结尾` ENDING, `#音乐` MUSIC_PASSAGE, `#静默` SILENCE, `#插入` INSERT, `#招牌` signature business, `#双关` double meaning, `#先物:PROP:名:TILT_UP` object-first entrance, `#交代` a report line |

`TYPE` is a `pacing.beat_sheet` type, for example `IDENTITY_REVEAL`, `REVERSAL` or `THREAT_ESCALATION`.

## Compilation

- **Shots.** One dialogue line becomes one shot (`beat_role: LINE` unless tagged). An action line attaches to the next line's shot. It attaches back to the previous shot when its subject just spoke and the next line belongs to someone else. A trailing action block, or a `（无声）` line, becomes its own silent 4 s shot.
- **Reactions.** A reaction becomes `listener_reaction` (+ `_en`) on the shot it follows. When nothing precedes it, or an action is still pending, it becomes `lead_in_reaction` on the next shot. WP3's director pass decides the final placement.
- **Who is in frame.** The speaker (face), whoever the shot's actions name, the reaction owners, and the addressee as an over-the-shoulder listener (`BACK_AND_SHOULDERS_ONLY`). An OS line plays on the listener's face.
- **Props.** Props become `props.reference_cards` (owner, hand, description + `description_en`) and each shot's `props`, whenever the shot declares the prop or its action or reaction names it.
- **Scene cards.** A card becomes `pacing.scene_plan`:
  - `objective` / `conflict` / `physical_action` (= goal / obstacle / turn);
  - `source_detail_ids` and `source_lines` (WP1);
  - `scene_type`, `mirror_of`, `time_of_day`, `light`, `weather`, `set_pieces`, `turn_shot_id`, `turn_owner` (WP6);
  - `mood` and `music_stop` (WP5-C).
- **Emotion.** The emotion is derived, never authored per shot. The source is, in order: the parenthetical's cue words and the speaker's own action (`configs/SCREENPLAY_LEXICON_V1.json` `emotion_cues`), then the scene type, then the punctuation. `（情绪=怒）` overrides. `performance.emotion_basis` records which one was used.
- **Durations.** A dialogue shot gets the seq29 rule-5a duration (line seconds + 0.5, at least the 4 s H3 floor). A silent shot gets 4 s.
- **English twins.** `business_en`, `action_en`, `delivery_en`, `listener_reaction_en`, `lead_in_reaction_en` and `description_en` are looked up in `<EP>_SCREENPLAY_EN.json` by `sha256(field + zh)[:16]`. Missing rows are written to `<EP>_SCREENPLAY_EN_REQUEST.json`. The compile then exits 3, and S1 reports `SCRIPT_INTEGRITY_FAIL:SCREENPLAY_EN_TWIN_MISSING`.
- **Fallbacks.** A field the screenplay does not give is filled from the line itself and recorded in `prompt_spec.action.field_sources` as `fallback`. `action.source` is `screenplay` or `fallback`. WP7 reports the share.
- **WP6 fields.** `ledger` (CAST_PROPS), `knowledge` (OUTLINE) and the series card go through `craft_ledger.screenplay_fields` / `apply_fields`, which resolve `scene_id` + `anchor` to a shot. Without the module, they are copied as written.
- **Stamps.** The contract is stamped `craft_profile: BILI_V1`, `writer_format: SCREENPLAY_V1`, `camera_grammar_policy: CAMERA_GRAMMAR_V1` and `h3_prompt_style: DIRECTOR_PROMPT_V2`. It also carries a `screenplay_v1` block (scenes, lines, props) that the checks read.

## S1

- `nalu_pipeline.s1_screenplay_compile` runs first in `stage_s1`, before the layers are hashed. It recompiles only when a screenplay input is newer than the contract, and keeps the previous layers once as `*.pre_compile`. An episode past a paid stage is never recompiled.
- The five input files are part of `fp_s1` and the S1 layer hashes, so an S1 PASS cannot survive a screenplay edit.
- Compile errors, missing English twins and a `build_<ep>_layers.py` generator are S1 integrity blockers. They go through the bounded writer loop, then the script is admitted and the gap recorded. The line never stalls.

## Anti-template checks (replace the blacklists)

| Code | Rule | SCREENPLAY_V1 | BILI_V1 contract JSON |
|---|---|---|---|
| `SCENE_CARD_REPEATED:<field>:<a>,<b>` | goal / obstacle / turn pairwise distinct (names and scene numbers masked, char-trigram Jaccard ≥ 0.6) | integrity | taste |
| `EMOTION_PERIODIC:<p>:<score>` | the per-line emotion sequence is periodic: lag 3–6 autocorrelation ≥ 0.8, or one 3–6 word cycle covering ≥ 60 % of the lines (E11) | integrity | taste |
| `ACTION_TEXT_TEMPLATE:<a>,<b>` | two shots' authored `primary_action` ≥ 0.6 similar (names and the line masked; fallback rows skipped) | integrity | taste |
| `GENERATOR_SCRIPT_PRESENT:<file>` | `lines/nalu/runtime/tools/build_<ep>_layers.py` exists | integrity | — |
| `ACTION_LINES_THIN:<scene>` | ≥ 1 action line per 3 dialogue lines | taste | — |
| `NO_TOUCH_IN_TWO_PERSON_SCENE:<scene>` | a scene with ≥ 2 people has a contact / handover verb naming both | taste | — |
| `PROP_UNDECLARED:<noun>` / `PROP_UNUSED:<id>` | prop nouns in action lines are declared; declared props are used | advisory | — |

- Under SCREENPLAY_V1, the phrase blacklists (`KNOWN_BOILERPLATE_PHRASES`, `placeholder_acting`) are superseded. The seq29 per-shot emotion requirement (R7B emotion field, R7C three-in-a-row) is dropped, because the compiler guarantees lexicon members.
- LEGACY runs none of this.

## Cost

The format costs 0 H3 credits. Codex writes prose instead of a generator, so token use is about the same.
