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
| `SERIES_CARD.yaml` | L0 | premise, engine, `protagonist_ids`, `visual_culture_contract`, `characters[{id, name, want, fear, voice, verbal_habit, signature_business, signature_prop}]` (`voice` = diction + rhythm, `verbal_habit` = one habit only this character has; the script doctor reads both) |
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
@演 要=逼战雷当场交出妖皇 | 压=三天白等的火气 | 漏=令牌在指间停住 | 裂=到"做客"时笑意没了，眼皮一垂 | 做=下巴微抬；鼻里轻哼；指节压着令牌 | 收=目光钉在战雷脸上不放 | 听=战雷低头，喉结一滚
[麒麟 反应：离开柱子，右拳攥紧]
商余烬（OS，殿外）：找我何事？
麒麟冲上一步，抓住商余烬的袖子：带上我。
```

| Line | Meaning |
|---|---|
| `## Snn 地点 · 时间 · 光线` | a scene. The place is matched against `locations[].name` (or `@card location=LOC-…`) |
| `@see k=v \| …` | what the viewer must SEE in this scene (E27 脑补): `赌注` (stakes as visible evidence), `关系` (who stands where, who blocks whom), `环境` / `感官` (environment state, sensory specifics), and `<character name>=` that character's own business / behaviour this scene. No faces or looks |
| `（画面）…` | a concrete visual detail of the shot that follows (objects, positions, light, material, the body) |
| `@card k=v \| …` | the scene card. `goal[人]` (repeatable), `obstacle`, `turn`, `type`, `source` (`;`-separated source detail quotes), `source_lines`, `mirror_of`, `mood`, `music_stop` |
| `@arc 名字=入场状态→出场状态 \| …` | (E28 review) each character's emotional arc across this scene (protective layer failing a step at a time, never a jump); the first line of the character takes the entry, the curve chains each line's end into the next |
| `@演 要=… \| 压=… \| 漏=… \| 裂=… \| 做=… \| 收=… \| 听=…` | (E28 review) the writer's acting for the line directly above: 要 what the character wants from the other right now, 压 what they hold back, 漏 the physiological leak, 裂 where the protective layer cracks (by meaning; 「到"救他"时……」 is fine here, it never reaches H3 as a word), 做 concrete visible face / eyes / hands / breath, 收 the end state, 听 the in-frame listener's visible reaction |
| `名字（括号）：台词` | a dialogue line. The parenthetical gives the addressee (`对X`), off-screen (`OS`, `画外`, `殿外` …), delivery cues and an explicit `情绪=怒` |
| `名字<动作>：台词` | an action and the line in one row (the action is the speaker's) |
| `[X 反应：…]` | a reaction beat |
| `{道具 名 @人.手 描述}` | a prop declaration (or in CAST_PROPS `props`) |
| `（无声）…` | a silent shot: only a beat the viewer can read (see *Silent units* below) |
| other prose | an action line: who, which hand, what object, what changes |
| `#标签` at line end | `#揭示[:TYPE]` REVEAL, `#转折[:TYPE]` TURN (the scene's slow push), `#爽点:TYPE` PAYOFF, `#攻击` ATTACK, `#笑点` PUNCHLINE, `#结尾` ENDING, `#音乐` MUSIC_PASSAGE, `#静默` SILENCE, `#插入` INSERT, `#招牌` signature business, `#双关` double meaning, `#先物:PROP:名:TILT_UP` object-first entrance, `#交代` a report line, `#反应` a dedicated silent reaction close-up (`REACTION`, <= 3 per episode) |

`TYPE` is a `pacing.beat_sheet` type, for example `IDENTITY_REVEAL`, `REVERSAL` or `THREAT_ESCALATION`.

## Compilation

- **Shots.** One dialogue line becomes one shot (`beat_role: LINE` unless tagged). An action line attaches to the next line's shot. It attaches back to the previous shot when its subject just spoke and the next line belongs to someone else. A trailing action block, or a `（无声）` line, becomes its own silent 4 s shot.
- **Reactions.** A reaction becomes `listener_reaction` (+ `_en`) on the shot it follows. When nothing precedes it, or an action is still pending, it becomes `lead_in_reaction` on the next shot. WP3's director pass decides the final placement. The reacting characters are named in `listener_reaction_by` / `lead_in_reaction_by`. When a line's only action line belongs to someone else (商余烬 laughs, 白桃 asks 你笑什么), that character is the shot's action subject; the speaker keeps the lips.
- **Who is in frame.** The speaker (face), whoever the shot's actions name, the reaction owners, and the addressee as an over-the-shoulder listener (`BACK_AND_SHOULDERS_ONLY`). An OS line plays on the listener's face.
- **Props.** Props become `props.reference_cards` (owner, hand, description + `description_en`) and each shot's `props`, whenever the shot declares the prop or its action or reaction names it.
- **Scene cards.** A card becomes `pacing.scene_plan`:
  - `objective` / `conflict` / `physical_action` (= goal / obstacle / turn);
  - `source_detail_ids` and `source_lines` (WP1);
  - `scene_type`, `mirror_of`, `time_of_day`, `light`, `weather`, `set_pieces`, `turn_shot_id`, `turn_owner` (WP6);
  - `mood` and `music_stop` (WP5-C).
- **Writer-authored performance (E28 review 2026-11-26).** A line with an `@演` block gets `performance.authored` (+ `authored_en`, the `perf` rows of the same EN request; the crack's word anchor is stripped before translation) and a timeline built from it (`performance_timeline.build_authored`, `timeline.source: writer`): ENTRY = the character's previous exit in the scene, else the `@arc` entry, else what they hold back → CHANGE = leak, then crack → EXIT = 收.  The trigger word is the writer's stress note (the crack's quoted anchor, else the parenthetical's 落重 / 加重 / 压低 / 停顿 … note; `stress_word`), never the auto pick.  `听` becomes the listener reaction when the listener is in frame and no `[X 反应]` is given.  A line without `@演` keeps the lexicon timeline, marked `source: lexicon_fallback` (warning `PERFORMANCE_LEXICON_FALLBACK:<n>/<m>`; the lexicon also uses the paren's stress note when there is one).  The H3 V2 prompt (BILI_V1) prints the authored block as its own section between Action and Dialogue ("<Name>'s performance — …: - Starts / Wants right now / Holding back / What leaks out / Then the guard cracks / Visibly / Ends on"), untimed, every clause naming the line, a word, the voice or a time dropped (#352); `Delivery:` drops a defaulted lexicon emotion word.
- **Delivery is the voice only (lab A/B 2026-11-26).** The parenthetical's stress note keeps its words in the data (`performance.delivery`, the trigger, the directing script), but the text sent for the English twin is `performance_timeline.voice_only(cue, line)`: the words of the line it points at are dropped (「截住推想，先救他三个字落重」 → 「截住推想，落重」; also 后半句 / 药名 / quoted words).  The V2 renderer cuts any Delivery clause that still names or paraphrases the words (`_DELIVERY_POINTS_AT_WORDS`: "stresses saving him first", "on the Heavenly Ruler's title", "the last word"), for contracts compiled before.  Evidence (`~/nalu_lab/perf_lab/AB_REPORT.md`): E28 S01 lines burned as subtitles in 12 of 14 clips whose Delivery pointed at the words (origin/main 6 of 6), in 3 of 8 with a voice-only Delivery — a reduction, not a cure; the S6 burn check stays the safety net.
- **Clean scripts (E28 review).** Action lines, `@see` values and `（画面）` lines describe acting and visible business only.  Engine rules written into them (首帧 / 画面外 / 入画 / 镜头 / 机位 / 不让…进入 …, `RULE_TALK`) are dropped from the compiled text (`SCRIPT_RULE_TALK:<scene>:<clause>` warning); the director pass and the keyframe builder enforce first frames, framing and prop visibility.  One source of truth per shot: a character with their own action line in the shot (or the speaker's `做`) does not also get the scene-wide `@see` business there (`visual.business_superseded`).
- **One-time writer feedback (E28 review).** `report.craft_feedback` = `SCRIPT_CRAFT_REVISE:PERFORMANCE_UNAUTHORED:<n>/<m>` (more than a third of the on-screen lines have no `@演`), `SCRIPT_CRAFT_REVISE:RULE_TALK:<n>`, `SCRIPT_CRAFT_REVISE:SERIES_CARD_VOICE_MISSING:<names>` (a speaker with ≥ 2 lines whose series-card row lacks `voice` or `verbal_habit` — e.g. a series that switched engines mid-run; the writer backfills the card once, free).  Under BILI_V1 S1 sends them back ONCE through the bounded integrity loop (`nalu_pipeline.s1_craft_feedback`, like `RUNTIME_ESTIMATE_SHORT`); a revised script that still carries them is only recorded.  Never a hard stop, never a paid stage.  The series card's `voice` / `verbal_habit` reach `character_entities` as `voice_style` / `verbal_habit`.
- **Emotion.** The emotion is derived, never authored per shot. The source is, in order: the parenthetical's cue words and the speaker's own action (`configs/SCREENPLAY_LEXICON_V1.json` `emotion_cues`), then the scene type, then the punctuation. `（情绪=怒）` overrides. `performance.emotion_basis` records which one was used.
- **Shot sizes (vertical grammar, E27 2026-11-25).** The compiler's sizes are stamped `camera_plan.scale_source: screenplay_compile`; the BILI_V1 director pass (`director_pass._apply_scene_grammar`) then mixes them for 9:16 on those shots only: a line defaults to an MCU single, the scene's hardest line (`hardest_line`, else the `#转折` push, else the TURN, else the last REVEAL / PAYOFF / ATTACK) gets a CU single (MCU when the listener is named in the action), a line whose listener reacts in frame is a front/back two-shot, the DP9 floor (>= 2 two-person shots per multi-character scene) is met with OTS listeners (the scene's first line as an OTS MEDIUM for geography), no more than 2 consecutive units share size + framing, and OTS MCUs widen to MEDIUM while CU+MCU > 80 % (DP9 ceiling). Each decision is recorded in `prompt_spec.director.shot_grammar`.
- **Micro-performance (E27 2026-11-25).** Every on-screen line gets `performance.timeline` (`performance_timeline.py`, data in `configs/PERFORMANCE_EMOTION_LEXICON_v1.json` `micro_performance`): ENTRY (the character's previous exit state in this scene, or the emotion's entry) -> CHANGE on the line's hardest word (a name, a hard word, else the last clause's last two characters) -> EXIT end frame; jumps across more than one stage of the protective ladder are softened and warned (`EMOTION_CURVE_JUMP`). A disfluency is picked by psychology (parenthetical cue first) on the hardest word, at most 2 per scene, written as body, never as added words. The H3 renderers print it untimed, face and body only (`bili_carry.performance_timeline_line`: "<who>'s face and body change visibly ...: at first ...; then ...; at the end ...") -- never seconds, the trigger word, "the word / the line / the syllable", voice cues or FACS codes (E28 2026-11-26, device 1101: the time-coded version read like a subtitle track and H3 burned the spoken line as on-screen text in 12 of 31 speaking units); the timing and trigger stay in the data and in the directing script's `表演分拍`.
- **Silent units (E27 2026-11-25).** 1101 E27 S01 opened on 9 units, 4 of them silent 2.5–3 s procedure inserts (sword caught, rope cut, rope falls, collapse) nobody could read. `apply_silent_policy` runs on each scene's shots before compiling: a silent shot is readable when it carries a beat tag (`#揭示 #爽点 #笑点 #结尾 #钩子 #攻击 #音乐 #静默 #插入 #反应 #先物`) or is an entrance / exit (`entrance_words_zh`); any other silent shot (also one tagged only `#转折` / `#招牌`) folds into the adjacent on-screen dialogue shot — the subject's own line first, else the line it leads into, else the line it follows — while that shot keeps <= 2 action sentences and <= 72 characters of action (`SILENT_FOLDED`, `action.folded_silent`; the H3 prompt says the folded action plays during the line, because S7 cuts a dialogue unit to its words). Its reactions become the target's listener reactions (no lead-in second is added). Two silent shots in a row merge when they fit (`SILENT_MERGED`). What is left is a warning only: `SILENT_PROCEDURE_KEPT`, `SILENT_RUN`, `SILENT_UNITS_OVER:<scene>:<n>` (> 1 per scene; the music passage and reaction close-ups are exempt). The director pass reports the same on any contract (`silent_policy_advisories`). `report.silent_policy` records before / after per scene.
- **Opening (E27).** The first ~10 s must make who / where / what's at stake visible: the scene's `@see 赌注` / `关系` play in its first shot (`prompt_spec.visual.stakes`), and whoever they name is put in frame. Warnings only: `OPENING_CAST_UNSEEN:<cid>` (a first-scene character not on screen in the first ~10 s), `OPENING_STAKES_UNDECLARED`, `OPENING_SILENT_HEAVY`; `report.opening` lists the window.
- **Visual expansion / 脑补 (E27).** `prompt_spec.visual` = `{stakes, detail, environment, business: {cid}}` with English twins (`*_en`, the `visual` rows of the same EN request; an unanswered row is simply left out of the prompt, never a stall). The H3 renderers (V1 and V2, BILI_V1 only) print `What the viewer must see in this frame: …`, `Visible detail: …`, `<Name>'s own way of moving here: …` and `Around them: …` (the environment once per unit), at most 900 characters per beat, appearance clauses dropped (identity comes from the reference images); the keyframe prompt takes the static ones (`看得见的处境`, `环境细节`, optional lines dropped on an extend-word). The directing script shows them. A scene without `@see` gets `SEE_MISSING` (warning).
- **Runtime budget after folding (E27).** Folding removes units, and S7 trims every unit (a line to its words, a silent unit to 2–3 s), so the nominal `target_seconds` sum over-states the cut. `cut_runtime_estimate` (derived line seconds + 3 s per silent unit, 2 s per reaction close-up / music shot; calibrated on 1101 E27: 109 s estimated for the 107.1 s shipped) is reported as `report.runtime_estimate` and in S1's `script_length` (`cut_estimate_seconds`, `cut_estimate_ratio`). Folding is runtime-aware (`fold_budget`): a dry run finds the foldable silent shots, and they are granted only while the post-fold estimate stays >= 0.92 × target — the opening scene first, then the least readable step (untagged, then `#招牌`, then `#转折`), each costing 3 s; the rest stay silent (`SILENT_KEPT_FOR_RUNTIME`, plus their SILENT_* advisory; `report.silent_policy.runtime_budget`). Below 0.95 × the brief target (default 110 s) the compile warns `RUNTIME_ESTIMATE_SHORT` with the fix: deepen the existing scenes with more exchanges and a developed conflict, never silent inserts or new plot events (the release holds below 0.85 ×). Under BILI_V1, before any paid stage, S1 sends it back to the writer ONCE through the bounded integrity loop (`s1_runtime_feedback`: the first failing script that carries it is a `SCRIPT_INTEGRITY_REVISE` round; a revised script that is still short is only recorded, and exhaustion admits it as usual — never a hard stop).
- **Durations.** A dialogue shot gets the seq29 rule-5a duration (line seconds + 0.5, at least the 4 s H3 floor). A silent shot gets 4 s.
- **English twins.** Every zh field the H3 prompt needs has an English twin (WP4 `EN_TWIN_MISSING`): `action.business_en` (= `action_en`, the whole primary action), `performance.business_en` (the speaker's own action), `delivery_en`, `listener_reaction_en`, `lead_in_reaction_en` and `description_en`. Authored rows are looked up in `<EP>_SCREENPLAY_EN.json` by `sha256(field + zh)[:16]`; missing rows are written to `<EP>_SCREENPLAY_EN_REQUEST.json` (exactly the missing ones) and the compile exits 3. The writer always answers the request in the same run and recompiles. A compiler fallback (a line with no action, a line with no delivery cue) gets the compiler's own English, marked `fallback` in `field_sources`, and is never sent to the translator.
- **Translation request at S1.** An unanswered request stops S1 with `SCREENPLAY_EN_TRANSLATION_REQUIRED:<key>:<n>` before any gate runs. It is not an integrity round. The Codex tick resumes the writer up to 3 times per request key, at least 30 min apart (`codex_production.translation_request_pending` / `translation_step`). If the request is still unanswered, the tick writes `<EP>_SCREENPLAY_EN_FALLBACK.json` (the request key) and resumes the writer once more to rerun S1. S1 then fills the missing twins with compiler English (marked `fallback` in `field_sources`) and proceeds, recording `SCREENPLAY_EN_FALLBACK_USED:<n>` in the S1 details, the CHECKPOINT and the fleet note (`series/STATUS.md`). Without a tick, S1 does the same once it has seen the same request 4 times over at least 90 min. Owner rule: never stall the line.
- **Fallbacks.** A field the screenplay does not give is filled from the line itself and recorded in `prompt_spec.action.field_sources` as `fallback`. `action.source` is `screenplay` or `fallback`. WP7 reports the share.
- **WP6 fields.** `ledger` (CAST_PROPS), `knowledge` (OUTLINE) and the series card go through `craft_ledger.screenplay_fields` / `apply_fields`, which resolve `scene_id` + `anchor` to a shot. Without the module, they are copied as written.
- **Stamps.** The contract is stamped `craft_profile: BILI_V1`, `writer_format: SCREENPLAY_V1`, `camera_grammar_policy: CAMERA_GRAMMAR_V1` and `h3_prompt_style: DIRECTOR_PROMPT_V2`. It also carries a `screenplay_v1` block (scenes, lines, props) that the checks read.

## S1

- `nalu_pipeline.s1_screenplay_compile` runs first in `stage_s1`, before the layers are hashed. It recompiles only when a screenplay input is newer than the contract, and keeps the previous layers once as `*.pre_compile`. An episode past a paid stage is never recompiled.
- The five input files are part of `fp_s1` and the S1 layer hashes, so an S1 PASS cannot survive a screenplay edit.
- Compile errors and a `build_<ep>_layers.py` generator are S1 integrity blockers. They go through the bounded writer loop, then the script is admitted and the gap recorded. The line never stalls.

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
