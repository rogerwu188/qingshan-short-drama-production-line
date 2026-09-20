# WIRING_NOTES.md — three standalone generalisation tools for the nalu line

Author: generalisation engineer. **`runtime/tools/nalu_pipeline.py` is owned by another
agent and is not edited by these tools or by this note.** Everything below is a
description of *where the orchestrator should call these tools and with what argv*.

All three are offline, make no HTTP request of any kind, never read `GIGGLE_API_KEY`,
and issue no POST. All three take absolute paths and are safe to run with
`cwd=$ENGINE_ROOT`.

```bash
export VENV=$ENGINE_ROOT/.qingshan-venv/bin/python      # never resolve() this symlink
export T=$RUNTIME_ROOT/runtime/tools
export SCRIPTS=$ENGINE_ROOT/workflow/claude_writer_agent/scripts
export PRE=$RUNTIME_ROOT/preproduction
```

> ⚠️ `.qingshan-venv/bin/python` is a **symlink** to `python3.12`. `Path(...).resolve()`
> on it silently leaves the virtualenv and PIL disappears. Both tools that shell out
> deliberately do *not* resolve the interpreter path. Do the same in the orchestrator.

---

## 1. `build_episode_asset_requirements.py` — stage **S2 pre-step / S3 input** (D-10)

Episode-agnostic replacement for `preproduction/E01/tools/build_asset_requirements.py`
and the prompt-writing half of `build_character_reference_image_manifest.py`, both of
which take no argv and bake in E01 paths.

### Call site
Runs **before S2 and before S3**, once per episode, as soon as the four script layers
pass S1. `build_nalu_preproduction.py` (S2) does not read `asset_requirements.json`,
but `bootstrap_identity_cards.py` (S3) requires both
`preproduction/<EP>/asset_requirements.json` and `preproduction/<EP>/prompts/`, and
`build_keyframe_manifest.py` (S5) reads the library compiled from those requirements.
Fingerprint it on the SHA of the four script layers plus the overlay, exactly like S1.

### Exact call
```bash
$VENV $T/build_episode_asset_requirements.py \
  --episode        E02 \
  --contract       $SCRIPTS/E02_GENERATION_CONTRACT_v1.json \
  --narrative      $SCRIPTS/E02_NARRATIVE_CANONICAL_v1.md \
  --manifest       $SCRIPTS/E02_manifest_v1.json \
  --prior-library  $RUNTIME_ROOT/runtime/asset_library.json \
  --out-dir        $PRE/E02/ \
  --overlay        $PRE/E02/asset_requirements_overlay.json \
  --gsm            $PRE/E02/global_space_map.json
```
Optional: `--directing` (default `$SCRIPTS/<EP>_DIRECTING_SCRIPT_v1.md`), `--charter`
(default the writer charter — the `series_bible_sha256` stand-in, stage-map blocker
R-1), `--prompts-only`, `--requirements-only`, `--dry-run`.

Auxiliary mode, run **once per authored episode**, to lift the overlay out of a
hand-authored requirements file (this is how `E01`'s overlay was produced):
```bash
$VENV $T/build_episode_asset_requirements.py --episode E01 \
  --extract-overlay-from $PRE/E01/asset_requirements.json \
  --overlay-out          $PRE/E01/asset_requirements_overlay.json
```

### Inputs
| input | why |
|---|---|
| `--contract` | `character_entities` (`canonical_name`/`aliases`/`appearance_ch1`), `non_character_entities` (`name`/`note`), `scene_states`, `shots`, `audio_contract`, `visual_culture_contract` |
| `--narrative` | `canonical_sha256` + every `authority_refs` narrative SHA |
| `--manifest` | `distinct_locations` (scene order), `episode_global_space_map_id`, `global_space_map_refs[0]`, `source_binding` |
| `--directing` | wardrobe/prop `authority_refs`, and `directing_script_mentions` counts when the overlay supplies `mention_terms` instead of a literal |
| `--gsm` | the place/room a location belongs to — needed for the `所属空间图 … / 房间 …` line of every location prompt, and as the derivation source for `spatial_topology` / `key_fixed_elements` when the overlay does not author them |
| `--prior-library` | cross-episode reuse authority; also the fallback source for wardrobe/voice/accent prose of a **returning** character |
| `--overlay` | the authored prose no script layer carries (see below) |

### Outputs
* `<out-dir>/asset_requirements.json` — `ai_drama.production_asset_requirements.v1`,
  ten categories in E01's order: characters, wardrobe, scenes, props, voices, accents,
  music, ambience, sfx, reference_materials.
* `<out-dir>/prompts/<EP>-{CHAR,LOC,PROP}-<suffix>.txt` — one per NEW image subject.
  `SET-*` ids are written as `<EP>-PROP-*` because
  `bootstrap_identity_cards.prompt_path_for` looks for exactly that name.
* `<out-dir>/asset_requirements_build_report.json` — per-subject NEW/REUSED decision,
  prior artifact SHA for every reused subject, prompt inventory, and every
  `AUTHORING_REQUIRED_*` sentinel emitted.

### Derived vs authored
Derived from the sealed layers: all ids, contract-entity labels, `appearance_ch1`,
prop `physical_function`, per-scene `scene_states` + `lighting_variants_required`,
ambience beds, dialogue line counts, the NO-BGM music row, all three
reference_materials rows, and every `authority_refs` SHA.

Genuinely authored (no script layer carries it) → `--overlay`, schema
`nalu.episode_asset_requirement_overlay.v1`: character priority / apparent age / sex,
wardrobe state descriptions, per-location `label` + `spatial_topology` +
`key_fixed_elements`, the props only the directing script names, voice timbre briefs,
the accent profile, the SFX table. Resolution order per field:
**overlay → prior asset library (a returning subject keeps its locked prose) →
`AUTHORING_REQUIRED_<FIELD>` sentinel**. It never invents prose.

### Reuse marking
A subject `status` `LOCKED*` **and** `qa.status == PASS` in `--prior-library` gets a
`reuse` block (`prior_status`, `prior_version`, `prior_artifact_sha256`,
`prior_requirement_sha256`, library path), keeps the prior `first_use_episode`, has
this episode appended to `required_in_episodes`, and **gets no prompt**. NEW subjects
get **no** `reuse` key at all, which is what makes an all-new episode byte-reproducible.

### Failure modes
| symptom | meaning | action |
|---|---|---|
| exit **2** `--contract not found` etc. | a required input is missing | fix the path; `--directing` and `--charter` default into the engine clone |
| exit **3**, `status: AUTHORING_REQUIRED` | one or more `AUTHORING_REQUIRED_*` sentinels landed in the output | **treat as a blocking stop.** The file is written so the gaps are inspectable, but a sentinel would be baked into a paid prompt. Author `--overlay` and re-run |
| `SystemExit: <LOC> is in manifest.distinct_locations but has no scene_states` | the writer layers disagree | S1 problem, not this tool |
| `PROMPT_SKIPPED_NO_GLOBAL_SPACE_MAP_ENTRY` in `authoring_gaps` | a location has no place map | run tool 2 first, then re-run this one |
| `--overlay is for episode Ex` | wrong overlay | pass the episode's own overlay |

---

## 2. `extend_global_space_map.py` — stage **S2 pre-step** (D-10, GSM half)

Episode-agnostic replacement for `preproduction/E01/tools/build_global_space_map.py`.
Must run **before** `build_nalu_preproduction.py`, because S2's documented fallback of
reusing E01's GSM is wrong for any episode that visits a new location, and because
`build_nalu_preproduction.SpaceIndex` hard-fails on a `scene_id` the GSM does not map.

### Exact call
```bash
$VENV $T/extend_global_space_map.py \
  --episode   E02 \
  --contract  $SCRIPTS/E02_GENERATION_CONTRACT_v1.json \
  --manifest  $SCRIPTS/E02_manifest_v1.json \
  --base-gsm  $PRE/E01/global_space_map.json \
  --out       $PRE/E02/global_space_map.json \
  --asset-requirements $PRE/E02/asset_requirements.json   # optional, authored key_fixed_elements
  # --place-spec $PRE/E02/new_location_place_spec.json     # optional, authored siting
  # --asset-dir  $PRE/E02/space_map_assets                 # default <out dir>/space_map_assets
  # --reports-dir $PRE/E02/reports                         # default <out dir>/reports
  # --engine-root $ENGINE_ROOT  --python $VENV
  # --skip-render --skip-gate                              # diagnostics only
```
Chicken-and-egg note: `--asset-requirements` is only used for a new location's
`key_fixed_elements`, and tool 1's `--gsm` is only used for location prompts and
derived topology. For an episode with new locations run **tool 2 first without
`--asset-requirements`**, then tool 1, then (optionally) tool 2 again to pick up the
authored elements. For an episode with no new locations the order does not matter.

### What it does
1. Deep-copies `--base-gsm`. Every existing `global_space_map_id`, `room_id`,
   `zone_id`, `angle_id`, `axis_id`, `element_id`, `entrance_id` and all existing
   geometry is carried through unchanged; derived ids for a new place are checked
   against the base id set and a collision is a hard error.
2. New `location_id`s (from `scene_states` / `manifest.distinct_locations`) get a place
   map: one room bound to the `location_id`, a three-band zone split with real
   polygons in the series coordinate system, fixed elements, an entrance, a
   north-bound axis, and **one camera position per shot** whose `name` declares the
   shot id — `"远景／固定机位（E02-S11-01）"`. That annotation is the contract
   `build_nalu_preproduction.SpaceIndex.angle_shot_hints` reads
   (`re.findall(r"S\d+-\d+", camera["name"])`, matched against the shot-id suffix in
   `choose_angle`), exactly as E01 writes `"固定高机位俯瞰全村（E01-S01-01）"`.
3. Reused locations get this episode's `scene_mappings` appended and their existing
   camera positions **re-annotated with this episode's shot ids**, with other
   episodes' shot-id annotations stripped. Only `name` changes — `angle_id` and
   geometry do not — so the rendered place-map PNGs stay bit-identical. This is not
   cosmetic: without it E02's `S01-01` suffix aliases onto E01's camera annotation and
   `choose_angle` picks a camera by dict insertion order.
4. Recomputes `topology_sha256` via the engine's own
   `global_space_layout_gate.content_sha256`; sets `inheritance.mode` to
   `INHERITED_EXACT` (with all seven required source fields) when the topology did not
   move, `COMPOSED` otherwise.
5. Shells out to `tools/render_global_space_map_assets.py` (deterministic, PIL only)
   to render the episode sheet + every place map and bind real SHA256 + `qa_status:
   PASS`, then to `tools/global_space_layout_gate.py` with a generated
   authority-only config to prove `status: PASS`.

### Outputs
`--out` (the locked authority), `<out>.template.json` (the pre-render template),
`<reports-dir>/gsm_shot_plan_empty_<EP>.json`,
`…/gsm_shot_plan_rendered_<EP>.json`,
`…/global_space_map_render_receipt_<EP>.json`,
`…/gsm_gate_config_<EP>.json`,
`…/global_space_layout_gate_<EP>.json` ← **this is a real PASS `SCENE-AUTHORITY-LOCK`
report and belongs in the episode's `machine_gate_reports`**, and
`…/global_space_map_extension_<EP>.json` (the extension report: new locations, new
place maps with their angle ids and names, every camera-name rewrite, every appended
scene mapping, auto-siting notes, both subprocess argvs).

### Failure modes
| symptom | meaning | action |
|---|---|---|
| exit **2** `--base-gsm is not a qingshan.episode_global_space_map.v1 authority` | wrong file | point at E01's `global_space_map.json`, not the `.template.json` |
| exit **4** `RENDER_FAILED` + `ModuleNotFoundError: No module named 'PIL'` | `--python` was resolved through the venv symlink, or a non-venv interpreter was passed | pass `.qingshan-venv/bin/python` **unresolved** |
| exit **4** `GATE_FAILED` | read `gate_failures` in the report. `authority_status not_locked` / `*_map_image file_missing` means the render did not run or the asset dir moved | re-run without `--skip-render`; keep `--asset-dir` stable per episode |
| `SystemExit: <LOC>: derived ids collide with the base map` | a new location's derived id already exists | rename the location, or author it in `--place-spec` |
| `auto_sited: [... AUTO_SITED_REQUIRES_SPATIAL_REVIEW]` | the geometry is valid and gate-clean but *where* the place sits relative to the village was chosen by the tool | a human should confirm or author `--place-spec`; this is a directorial call, not a machine one |

### Identity property (relied on by resume logic)
`--episode` equal to the base GSM's own `episode` is the identity operation: no camera
name is rewritten, no scene mapping is appended, no manifest field overrides an
authored elaboration of it, and because the renderer is bit-deterministic the emitted
authority is **byte-identical** to `--base-gsm`. Re-running is therefore free and safe.
Point `--asset-dir` at that episode's existing `space_map_assets` for this to hold.

---

## 3. `materialize_paid_authorization.py` — stages **S3 / S5 / S6, immediately before each paid submit** (D-11)

Turns a deployment-private, source-receipted line-owner order into the authority
fields the submitters demand, and produces the `GIGGLE-REROLL-COST-GUARD` report
bound to the manifest's exact SHA. There is no built-in owner, sequence or public
repository fallback. Without it, `--precheck-only` is green and the paid run dies in
`validate_submission_authority` — `--precheck-only` **skips** that check.

The deployment must set these values under `qingshan.json.authorization` or the
equivalent environment variables:

```json
{
  "authorization": {
    "supervisor_orders_path": "/private/runtime/SUPERVISOR_ORDERS.json",
    "paid_order_seq": 1,
    "latest_order_seq": 1,
    "line_owner_id": "owner-id-from-the-line-owner-interface"
  }
}
```

Environment overrides are `NALU_SUPERVISOR_ORDERS_PATH`, `NALU_PAID_ORDER_SEQ`,
`NALU_LATEST_ORDER_SEQ`, and `NALU_LINE_OWNER_ID`. The orders and receipt paths must
be absolute and outside the public engine checkout. Producers mount this inbox
read-only and never create an order themselves.

### Call site
Between the budget check and the paid submit, in all three paid stages. Feed the
submitter the **materialised copy**, not the original:

* **S3** — after `bootstrap_identity_cards.py`, on `identity/character_asset_plan.json`,
  then `submit_giggle_character_asset_plan.py --plan <…_PAID_AUTHORIZED.json>`
* **S5** — after `build_keyframe_manifest.py` + `keyframe_entry_state_gate.py`, on the
  keyframe image manifest, then `submit_giggle_image_manifest.py --manifest <…_PAID_AUTHORIZED.json>`
* **S6** — after `production_efficiency_contract.py`, on
  `<EP>_VIDEO_TRANSACTION_MANIFEST_V1.json`, then `submit_giggle_video_manifest_v2.py`

Re-run it after **any** edit to the manifest: the gate report binds the manifest's byte
SHA, so an edited manifest invalidates it. It is idempotent — re-running replaces the
guard report and rebinds the new SHA, and it never duplicates the registered entry.

### Exact call
```bash
$VENV $T/materialize_paid_authorization.py \
  --episode E01 --stage S3 \
  --orders /private/runtime/SUPERVISOR_ORDERS.json \
  --order-seq 1 --expected-latest-seq 1 --line-owner-id owner-1 \
  --plan     $ENGINE_ROOT/workflow/nalu/E01/identity/character_asset_plan.json \
  --manifest $RUNTIME_ROOT/preproduction/E01/E01_KEYFRAME_IMAGE_MANIFEST_SUBSET_V1.json \
  --ledger   $RUNTIME_ROOT/runtime/budget/ledger.json \
  --report   $RUNTIME_ROOT/runtime/reports/E01_paid_authorization.json
```
Optional: `--out-dir`, `--suffix` (default `_PAID_AUTHORIZED`), `--in-place`,
`--task-key K` (repeatable — price and authorise only those tasks, matching
`submit_giggle_image_manifest.py --task-key`), `--cap 8000`, `--image-credits 11`,
`--video-credits-per-second 20`, `--policy`, `--engine-root`, `--python`,
`--allow-image-model`.

The selected active order must use decision kind
`PAID_PRODUCTION_AUTHORIZATION`, set `paid_requests_allowed: true`, list the
authorized subset of `S3`–`S6` in `paid_stages`, list exact
episode ids in `episode_scope`, name the cap and `seedance-2.0-pro`, and carry a
line-owner rights declaration. Its `source_receipt` binds an absolute private JSON
file by SHA-256. That receipt uses schema
`qingshan.line_owner_order_source_receipt.v1`, status `CONFIRMED`, and repeats the
same issuer, order seq/id and verbatim text. The inbox uses
`_schema: supervisor_orders_v1`; all seq values are unique and its
`latest_order_seq` must equal both the highest row and the caller's observed latest
sequence.

### What it sets
Manifest level: `provider_post_allowed: true`, `maximum_new_submissions = len(selected
tasks)`, `authorization_ref = <order id>`, plus a `paid_authorization` provenance block
recording the order seq/id and the orders-file SHA. Per selected task: `status:
READY_TO_SUBMIT`, `provider_post_allowed: true`, `maximum_new_submissions: 1`,
`authorization_ref`, and `blocking_note` removed. Plan level: the same plus
`READY_TO_SUBMIT` on every `new_asset_groups` row. Then it registers **exactly one**
`GIGGLE-REROLL-COST-GUARD` report in `machine_gate_reports` (replacing its own prior
entry, never duplicating it).

### The cost-guard report
`tools/reroll_cost_guard.py` is **actually run** against
`configs/reroll_cost_guard_policy_v1_20260716.json` and the live nalu ledger, and its
verbatim result plus the exact argv are embedded as evidence. The guard's own output
carries no `gate_id`, no `reviewed_manifest_sha256`, and its pass status is
`PASS_AUTO_REROLL_ALLOWED`, not `PASS` — so the wrapper supplies **only** those three
binding fields that `validate_submission_authority` / `validate_gate` require. Ordering
matters: the manifest is written **first** (with the gate path already registered), its
SHA is then computed, and the report is written afterwards to a separate file, so
binding the SHA cannot invalidate it.

`guard_semantics` states in the report that the guard was run as a
`COST_ENVELOPE_PROBE_NOT_AN_ACTUAL_REROLL` (`reroll_number=1`, `failure_tier=BLOCK`,
`rerolls_consumed: 0`) — it proves the policy would still permit one paid reroll after
this batch. It is not a claim that a reroll happened.

### Refusals (exit **5**, nothing written but a refusal report)
| refusal | trigger |
|---|---|
| `SUPERVISOR_ORDERS_*` | wrong schema, duplicate/stale latest sequence, or inbox under the public engine root |
| `ORDER_SEQ_<n>_DOES_NOT_EXIST` | `--order-seq` is not in `SUPERVISOR_ORDERS.json` |
| `ORDER_SOURCE_RECEIPT_*` | source receipt is absent, unconfirmed, private-path-invalid, byte-mismatched or disagrees with the order |
| `ORDER_NOT_ACTIVE` / `ORDER_ISSUER_MISMATCH` / `ORDER_VERBATIM_MISSING` | status, configured owner or exact instruction is invalid |
| `ORDER_PAID_DECISION_KIND_INVALID` / `ORDER_DOES_NOT_EXPLICITLY_AUTHORIZE_PAID_REQUESTS` | the order is not an explicit paid-production authorization |
| `ORDER_MISSING_REQUIRED_CONDITIONS` | the order lacks model, paid-request or rights conditions |
| `ORDER_CAP_MISMATCH` | `--cap` is not the cap the order's own condition text declares |
| `ORDER_SD2_CONDITION_DOES_NOT_NAME_seedance-2.0-pro` | the SD2 condition was reworded |
| `EPISODE_OUT_OF_ORDER_SCOPE` | `--episode` is not in the order's explicit episode list |
| `MODEL_FORBIDDEN_BY_ORDER_CONDITION_1` | any `seedance-2.0-fast/mini/bare` or `MiniMax-H3` anywhere in the manifest |
| `VIDEO_MODEL_IS_NOT_seedance-2.0-pro` | a video task's model is not SD2 |
| `IMAGE_MODEL_IS_NOT_gpt-image-2-pro` | an image task uses another model (override only with `--allow-image-model` **and** a named authorisation) |
| `PLANNED_CREDITS_EXCEED_CAP` | images `n×11`, video `seconds×20` over the cap |
| `NALU_BUDGET_LEDGER_CHECK_NOT_PASS` | `nalu_budget_ledger.py --check` did not return PASS |
| `MANIFEST_HAS_ZERO_TASKS` / `UNKNOWN_TASK_KEYS` | bad selection |

Exit **6** `MATERIALISED_BUT_VALIDATOR_REFUSES` means the files were written but the
submitter's own validator still refuses — read `self_verification.reason` in the
report. Exit **0** means the tool re-imported
`submit_giggle_image_manifest.validate_submission_authority` (a pure function, no
network, no POST) and it raised nothing.

### Money-safety boundary
`provider_post_allowed: true` in a file is still only **one** of the pipeline's locks.
`qingshan.json` `generation.paid_requests_enabled` and the orchestrator's `--paid` flag
remain independently required, and the materialised file says so in
`paid_authorization.second_lock_still_required`. Note that
`nalu_budget_ledger.py --check` **appends an entry to the ledger on every run**, which
is correct for a real pre-submit gate — pass a scratch `--ledger` when rehearsing.

---

## Suggested orchestrator stage order per episode

```
S1  script gates                                   (unchanged)
S1b extend_global_space_map.py                     → preproduction/<EP>/global_space_map.json  + PASS SCENE-AUTHORITY-LOCK report
S1c build_episode_asset_requirements.py            → asset_requirements.json + prompts/
S2  build_nalu_preproduction.py --gsm <S1b output>
S3  bootstrap_identity_cards.py
    nalu_budget_ledger.py --check --planned-credits <identity credits>
    materialize_paid_authorization.py --plan <character_asset_plan.json>
    submit_giggle_character_asset_plan.py --plan <…_PAID_AUTHORIZED.json>          💰
S4  voices                                         (unchanged)
S5  build_keyframe_manifest.py ; keyframe_entry_state_gate.py
    nalu_budget_ledger.py --check --planned-credits <keyframe credits>
    materialize_paid_authorization.py --manifest <keyframe manifest>
    submit_giggle_image_manifest.py --manifest <…_PAID_AUTHORIZED.json>            💰
S6  S2 re-run with --keyframe-dir ; production_efficiency_contract.py
    nalu_budget_ledger.py --check --planned-credits <video credits>
    materialize_paid_authorization.py --manifest <video transaction manifest>
    submit_giggle_video_manifest_v2.py --manifest <…_PAID_AUTHORIZED.json>         💰
```

Fingerprints: S1b on `base-gsm` SHA + contract SHA + manifest SHA; S1c on the four
layer SHAs + overlay SHA; the materialiser on the input manifest SHA + orders-file SHA
(it is cheap and idempotent, so re-running it unconditionally before each paid step is
the safer default).

## Newly found engine gap, not previously in the D-list

`submit_giggle_video_manifest_v2.py --project-root $RUNTIME_ROOT` — the
argv the runbook prescribes for S6 — sets `ROOT` to the runtime and then
`authoritative_pipeline_tools_dir()` looks for
`$RUNTIME_ROOT/tools/production_video_submission_gate.py`, which does not
exist, so the submitter dies with *"Production video gate is unavailable"* **before any
manifest validation at all**. The gate does exist at
`$ENGINE_ROOT/tools/production_video_submission_gate.py`. S6 must therefore also
export `BACKLOT_PIPELINE_TOOLS_DIR=$ENGINE_ROOT/tools` (or drop
`--project-root`). With that set, the video precheck's blocking reason becomes
`CURRENT_PROMPT_FILE_MISSING` (the stage-4.4 prompt-compilation chain, D-4/D-5) — and
it is **identical before and after** materialisation, which is the demonstration that
authority is no longer the blocker. Note also that
`production_video_submission_gate.py` contains **no** authority-field checks at all:
for video, `authorization_ref` / `provider_post_allowed` / `maximum_new_submissions`
are set by this tool for auditability and reroll-guard purposes, not because the
video submitter enforces them.
