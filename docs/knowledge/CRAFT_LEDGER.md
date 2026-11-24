# Craft ledger (BILI_V1, CHANGE_SPEC WP6)

Owner decision 2026-11-23, from the Bilibili ep3 benchmark (`~/Desktop/B站对标分析/第三集分析.md`). Ep3 beat ep2 on structure: a misunderstanding chain the audience can see through, at least 7 setup → payoff threads (2 of them calling back to ep2, plus a hook for ep4), a hero whose turn is played in silence, recurring business, mirrored compositions, and props shown before faces.

All of this is **BILI_V1 only** (`docs/knowledge/CRAFT_PROFILE.md`). A LEGACY series gets the same S1 pacing report and the same Codex start prompt as before, byte for byte.

- Code: `lines/nalu/runtime/tools/craft_ledger.py`
- Tests: `tools/tests/test_ledger_and_irony.py`

## Contract fields

All fields are additive in `generation_contract.schema.json`.

| Field | Shape |
|---|---|
| `ledger` | `[{id, kind: SETUP\|PAYOFF\|CALLBACK\|HOOK, thread, shot_id, pays_off, from_episode, prop?}]`. A row may give `scene_id` + `anchor` instead of `shot_id`; the anchor is a fragment of the line or action text. |
| `knowledge` | `[{scene_id, who, knows\|believes\|unaware: fact}]`, or `{scene_id, who, type, fact, hidden_from}`. `who: AUDIENCE` with `hidden_from` means the audience knows something those characters don't. |
| `series_card` | `{characters: [{character_id, name, signature_business, signature_prop, cues[], main}]}`. If the contract has no card, it is looked up in runtime `qingshan.json` `series_card` (or `project.series_card`), then in `SERIES_CARD.yaml\|json` next to the scripts or the series ledger. |
| `pacing.scene_plan[]` | `mirror_of`, `time_of_day`, `light` / `weather`, `set_pieces`, `turn_shot_id`, `turn_owner` |
| shot `prompt_spec` | `beat_role` (adds `REVEAL TURN ATTACK PUNCHLINE ENDING MUSIC_PASSAGE SILENCE INSERT`), `object_first {subject: HANDS\|FEET\|PROP\|WHEELS\|VEHICLE\|SCREEN, of, then: INSERT\|TILT_UP\|PUSH_IN\|PAN\|RACK_FOCUS}`, `signature_business` (a character id or a list of ids), `double_meaning: true` |

### Using these fields with SCREENPLAY_V1 (WP2)

The writer puts the same fields in YAML:

- `ledger:` goes in `<EP>_CAST_PROPS.yaml`.
- `knowledge:` goes in a fenced ```` ```yaml ```` block in `<EP>_OUTLINE.md`.
- The card goes in `SERIES_CARD.yaml`. A top-level `characters:` is accepted.

The compiler calls `craft_ledger.screenplay_fields(outline_md, cast_props_yaml, series_card_yaml)` and then `craft_ledger.apply_fields(contract, fields)`. That step resolves `scene_id` + `anchor` to a `shot_id`. After that, both paths run the same checks over the compiled contract.

`craft_ledger.load_light_yaml` is a stdlib YAML subset. It handles block mappings and sequences, flow `{}` / `[]`, scalars and comments, and also accepts a full-width `：`. Quote a flow value if it contains an ASCII comma.

The zh aliases 伏笔/埋 (SETUP), 回收 (PAYOFF), 回扣 (CALLBACK) and 钩子 (HOOK) are accepted, as are 知道/以为/不知道.

## Checks

| Code | Rule | Tier |
|---|---|---|
| `LEDGER_THIN` | ≥2 SETUP, ≥2 PAYOFF, ≥1 CALLBACK to an earlier episode (only once the series ledger has an earlier episode), and 1 HOOK on a shot ending in the last 10 s | graduated |
| `LEDGER_PAYOFF_UNRESOLVED` | `pays_off` names a SETUP/HOOK in this episode or the series ledger (`E02:<id>` for older ones) | graduated |
| `LEDGER_SHOT_UNKNOWN` | a row points at no shot | graduated |
| `SIGNATURE_CARD_MISSING` / `SIGNATURE_BUSINESS_UNUSED` / `_OVERUSED` | each main character on screen uses their business 1–3 times. This is counted from the explicit tag or the cues in the action text; zh cues match with ≤2 chars between, so 捂嘴 matches 捂住嘴 | graduated |
| `INSERT_OVER` | ≤3 dedicated insert units. These are `beat_role: INSERT`, object-first `then: INSERT`, or silent measured INSERT shots | taste |
| `INSERT_WITHOUT_LEDGER_PROP` | an insert shows a prop from the ledger: a row's `prop`, or the props of a SETUP/PAYOFF shot | taste |
| `NO_IRONY` | ≥1 `believes` / `unaware` row, an AUDIENCE row with `hidden_from`, or a `double_meaning` line | advisory |
| `TURN_TALKED` | the owner of the scene's turn has ≤2 lines in that scene, and the turn shot has an action or reaction | advisory |
| `NO_TIME_PLACE` | each scene has a time of day, light or weather, and ≥1 set piece | advisory |
| `MIRROR_UNRESOLVED` / `MIRROR_SETUP_DIFFERS` | `mirror_of` names an earlier scene; it reuses that scene's scale, height and side | advisory |
| `OBJECT_FIRST_NONE` / `OBJECT_FIRST_FACE_SHOWN` | ≥1 object-first entrance. A `then: INSERT` shot is faceless: every cast member is `HANDS_ONLY` / `FEET_ONLY` …, which the H3 renderer already honours. A tilt or push needs a `start_framing` on the detail | advisory |

Each tier is handled differently:

- **Graduated** codes are warnings for the first `ADVISORY_EPISODES = 3` episodes the series ledger records. After that they become failures in the SHORT_DRAMA_PACING_V1 revision loop: at most 2 rounds, then the script is admitted with the gaps recorded. The line never stalls.
- **Taste** codes are failures from the first BILI_V1 episode on, because they control cost.
- **Advisory** codes are never failures.

## Series ledger

The ledger lives at `<runtime>/sources/<series>/LEDGER.json`. `<series>` is the contract's `series_id` / `series` / `work`, or else the folder of the first `sources/*/SOURCE_INDEX.json`. Without either, it goes to `<runtime>/series/LEDGER.json`.

S1 appends the episode's rows when it admits the script, at the same point as `SOURCE_COVERAGE.json`. Re-recording an episode replaces its rows.

- `python3 lines/nalu/runtime/tools/craft_ledger.py open` lists the setups and hooks nobody has paid off yet.
- Under BILI_V1, the Codex start prompt carries the rules and those open threads (`codex_production.craft_ledger_section`).

## L4 hooks (WP3 director pass)

`craft_ledger.director_hints(contract)` is pure; nothing is applied at S1. It returns:

- the object-first entrances; a tilt or push counts as the scene's one move;
- the camera setup fields of each in-episode mirrored scene (`SETUP_FIELDS`);
- the zero-cost insert alternative: "foreground hands / object in sharp focus, the face soft behind".

## Cost

The checks cost 0 credits. Each dedicated insert unit is one H3 unit of about 4 s, roughly 4.4 credits. The cap is 3 per episode, so at most about +13 credits, and only if the writer uses them.
