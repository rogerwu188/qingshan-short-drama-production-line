# Craft profile switch (`craft_profile`)

Owner decision 2026-11-23 (Bilibili benchmark ep2 + ep3, CHANGE_SPEC WP0). Every behaviour change of the script and craft redesign (WP1–WP7) sits behind one per-series profile. The default is `LEGACY`, so merging a WP changes no running series. The owner turns `BILI_V1` on per series.

Code: `lines/nalu/runtime/tools/craft_profile.py`. A re-export for engine `tools.*` modules lives at `tools/craft_profile.py`. Tests: `tools/tests/test_craft_profile.py`.

## Keys

| Key | Values | Default | Used by |
|---|---|---|---|
| `craft_profile` | `LEGACY` \| `BILI_V1` | `LEGACY` | all WPs |
| `bgm_mood_cues` | bool | `false` | WP5-C mood cues |
| `writer_format` | `CONTRACT_JSON` \| `SCREENPLAY_V1` | `CONTRACT_JSON` | WP2 screenplay compile |

- The two sub-switches only take effect under `BILI_V1`. Under `LEGACY`, `bgm_mood_cues` is always false and `writer_format` is always `CONTRACT_JSON`, whatever is declared.
- An unknown value is ignored. Resolution falls through to the next source and ends at the default.

## Where a series declares it

Each key is resolved on its own. The first hit wins, in this order:

1. The generation contract: a top-level key (also on a compiled unit), or the same key inside a `craft` block.
2. The episode brief `briefs/<EP>_PRODUCTION_BRIEF.json`, same keys.
3. Runtime `qingshan.json` → `project.craft_profile` / `project.bgm_mood_cues` / `project.writer_format`. This is the normal series-wide switch.
4. The defaults above.

To turn a series on, set this in the runtime `qingshan.json`:

```json
{"project": {"craft_profile": "BILI_V1", "bgm_mood_cues": true, "writer_format": "SCREENPLAY_V1"}}
```

## API for WP code

Import it the same way under the runtime-tools root and the engine-tools root:

```python
try:
    from tools import craft_profile as _cp
except ModuleNotFoundError:  # runtime tools dir only
    import craft_profile as _cp
```

- `_cp.is_bili_v1(x)`, `_cp.is_legacy(x)`, `_cp.writer_format(x)`, `_cp.bgm_mood_cues(x)`, `_cp.enabled(name, x)` and `_cp.profile_of(x)` all accept `x` as any of:
  - a pipeline `Ctx`;
  - a contract or unit dict;
  - a runtime root `Path` (plus `episode=`);
  - a profile string;
  - `None` with `episode=` / `runtime_root=` / `brief=` / `config=`.
- A dict alone is read as a contract only and never reads the runtime. Pass `episode=` or `runtime_root=` to add the brief and `qingshan.json`.
- `enabled()` accepts a profile name (`"BILI_V1"`), a writer format (`"SCREENPLAY_V1"`) or `"bgm_mood_cues"`. An unknown name is false.
- Low level:
  - `resolve(contract, brief, config) -> str`;
  - `settings(contract, brief, config) -> dict`;
  - `resolve_runtime(episode, contract=, runtime_root=)`;
  - `settings_runtime(...)`.
- In the pipeline (`nalu_pipeline.py`):
  - `ctx.craft_settings` (dict) and `ctx.craft_profile` (str) are resolved once per run and cached after S1 writes the contract;
  - `ctx_craft_profile(ctx)` returns `"LEGACY"` for stage test doubles;
  - `resolve_craft_settings(contract, config, episode)` is also available.

## Rules for every WP

- A LEGACY series must stay byte-identical. Branch only when `is_bili_v1(...)` is true, and keep the historical text and code path untouched otherwise.
- Read the profile only through this module. Do not add another key or lookup path.

## What BILI_V1 changes so far

- **WP1 adaptation and episode allocation** (`lines/nalu/runtime/tools/bili_adaptation_check.py`, called from `script_pacing_check.evaluate`):
  - 1 main + ≤1 secondary plot event (`ADAPTATION_TOO_DENSE`); `ADAPTATION_TOO_THIN` and `SINGLE_CHAPTER_EPISODE` are off; the TOO_FEW_TURNS and SCRIPT_TOO_SHORT fixes say "deepen the scenes, do not add plot events";
  - ≥2 `pacing.scene_plan[].source_detail_ids` per scene, each found in the source (`SOURCE_DETAIL_MISSING`, `SOURCE_DETAIL_NOT_IN_SOURCE`); report-style lines ≤20 % (`REPORT_LINES_OVER`, lexicon `configs/REPORT_LINE_PATTERNS_V1.json`); slogans without a source anchor (`SLOGAN_LINE`, `configs/SLOGAN_PATTERNS_V1.json`; advisory on the first evaluation) -- taste codes, admitted after the pacing revision rounds;
  - `REVEAL_NAME_NOT_IN_SOURCE` -- integrity: back to the writer inside the S1 integrity loop, admitted and recorded after `S1_INTEGRITY_MAX_ROUNDS`;
  - the dialogue register gate reads every declared chapter of any work (`--source` repeated / `--source-text-file`), is active from E01 and allows ≤2 listed short source lines per scene (`source_lines`);
  - gate10 counts a scene with `source_detail_ids` as sourced and never blocks; `adaptation_plan.source_chapters` is the authoritative chapter list (structure gate `--craft-profile BILI_V1`).

## WP4 / WP7 under BILI_V1

- **WP4 carry-through** (`tools/bili_carry.py`):
  - the grouped compiler stamps `craft_profile: BILI_V1` on the H3 units and defaults them to DIRECTOR_PROMPT_V2;
  - S1 integrity `EN_TWIN_MISSING:<shot>:<field>` (script_structure_contract_gate `--craft-profile BILI_V1`);
  - both H3 renderers state the authored `lead_in_reaction_en` first and `listener_reaction_en`, and the declared props in hand;
  - V2 states the authored micro-expression / body-sync / contact instead of omitting it (receipt `authored_fact_ids_kept`);
  - Codex gets `codex_compressed_zh_bili_v1`;
  - `tools/check_l3_to_h3_carry.py` reports the noun carry (target ≥ 95 %).
- **WP7 craft metrics** (`tools/craft_metrics.py`, report only):
  - S7 writes `assembly/<EP>_CRAFT_METRICS.json` + `.md` (copied into CHECKPOINT.md), `craft_metrics` in the final QA report, and one `series/STATUS.md` line.
  - It runs on every BILI_V1 episode. `NALU_CRAFT_METRICS=on` measures any series; `=off` measures none.
