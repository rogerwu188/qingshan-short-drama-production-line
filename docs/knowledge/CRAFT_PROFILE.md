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
