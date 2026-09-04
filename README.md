# Qingshan Short Drama Engine（青山 AI 短剧引擎）

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Portable Core](https://github.com/rogerwu188/qingshan-short-drama-production-line/actions/workflows/portable-core.yml/badge.svg)](https://github.com/rogerwu188/qingshan-short-drama-production-line/actions/workflows/portable-core.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](pyproject.toml)

An MIT-licensed, end-to-end open-source engine for people who want to build a
real, commercially usable AI film or short-drama production line—not just a
prompt demo. It covers source-grounded script generation, shot and continuity
planning, keyframes, SD2/H3 video compilation, durable generation, editing,
technical QA, and ordered YouTube/Douyin release.

青山是一个面向普通创作者和小型制片团队的、真正从剧本到发行的开源 AI
影视生产引擎。代码可以自由使用、修改、部署和商业化；你的故事原文、媒体、
账号凭据和平台回执始终留在自己的私有运行目录中。

## What is included

| Stage | Engine capability |
| --- | --- |
| Script | Writer Agent v2, source provenance, canonical activation and dramatic gates |
| Pre-production | event boundaries, complete maps, character/wardrobe/prop/weather/state continuity |
| Images | keyframe contracts, reference binding, image preflight and durable task submission |
| Video | shared semantic IR with independent SD2 and MiniMax-H3 prompt renderers |
| Post | Portable FFmpeg timeline (optional AgentCut), safe cuts, native-audio loudness, subtitles and final encoding |
| QA | registered fail-closed gates, basic post-generation plot checks and release lock |
| Release | YouTube → Douyin ordering, authenticated browser/API adapters and signed receipts |

## Quick start

```bash
git clone https://github.com/rogerwu188/qingshan-short-drama-production-line.git
cd qingshan-short-drama-production-line
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install --upgrade pip
python3 -m pip install -e .
qingshan init --workspace ../my-short-drama
qingshan doctor --profile core --config ../my-short-drama/qingshan.json
qingshan test
```

Install media/ASR/cloud integrations with:

```bash
python3 -m pip install -e '.[media,asr,cloud]'
qingshan doctor --profile all --config ../my-short-drama/qingshan.json
```

The sample configuration keeps paid generation disabled. Installation,
initialization, doctor, tests and preflight never spend credits or publish.
See [Deployment](docs/DEPLOYMENT.md), [Architecture](docs/ARCHITECTURE.md), and
the [portability audit](docs/PORTABILITY_AUDIT.md).

Tracked scope:

- `qingshan_engine/`: stable public CLI and clean-clone deployment surface.
- `tools/`: production orchestration, generation, QA, transaction, assembly, continuity and release tooling.
- `agent_factory/claude_writer_v2/`: portable Writer Agent v2 runtime, gates, schemas and tests.
- `configs/PORTABLE_CORE_MANIFEST.json`: authoritative reusable-engine inventory and CI scope.
- `examples/` and `configs/pipeline.example.json`: public, credential-free starting points.

The local canonical manifests, media assets, QA evidence, credit transactions, receipts, runtime logs, and credentials are intentionally excluded. They remain authoritative in the production workspace and must never be reconstructed from this repository.

Files named for a historical episode are retained as production migration and
replay evidence. They are not stable public APIs and may refer to excluded
episode assets. The portable core is explicitly tested separately so a clean
clone cannot produce a false red build merely because private media is absent.

## Bootstrap Writer Agent v2

From a clean clone:

```bash
qingshan writer-doctor
python3 agent_factory/claude_writer_v2/runtime/canonical_writer_dispatcher.py --help
```

See [`agent_factory/claude_writer_v2/README.md`](agent_factory/claude_writer_v2/README.md)
for the source-provenance, runtime-state and scheduled execution contract. The
older `claude_writer/` folder remains only as a v1 migration path.

The production line supports two explicitly selected video models: Giggle `seedance-2.0-pro` (SD2 standard, provider-native 720p 9:16 in the current production contract) and Giggle `MiniMax-H3` (provider-native 768p 9:16). SD2 keeps its established complete prompt grammar unchanged. H3 uses a separate native audiovisual compiler with structured reference definitions, stable speaker IDs, `<d>`-isolated literal dialogue, separated soundscape/music fields, and a no-unprompted-speech gate. `seedance-2.0-fast`, `seedance-2.0-mini`, and an unversioned bare `seedance-2.0` remain prohibited. Any higher-resolution delivery derived from H3 must be labeled as an upscale; synthetic `2K` must never be represented as native generation. E40 remains abandoned and private.

Long-form episodes are compiled with media-safe segmentation: dialogue must finish before a safety pad and a 0.6–1.5 second bridge handle, every outgoing tail keeps residual breathing/clothing/environment motion instead of a freeze, and every adjacent pair receives real-media frame/audio evidence. Release is fail-closed until plot, identity/wardrobe, pose/blocking, complete-map axis, props, sound, and transition motivation all pass the boundary acceptance report. Character wardrobe is role/status-driven and same-tier characters must remain visually distinguishable by silhouette, palette, material, fastening, or accessories.

Install the official H3 prompt/API skill on an execution host before starting E45:

```bash
npx skills add https://github.com/giggle-official/skills --skill giggle-minimax-h3-gen
```

The durable project submitter remains the only paid-POST entrypoint. The installed skill supplies the official H3 capability and prompt contract; it does not bypass transaction recording, task-id binding, credit reconciliation, complete-map gates, or pre-submit continuity QA.

### Provider scope isolation

From E56 onward, the engine separates the episode-global entity graph from the
provider-facing prompt. Each keyframe, SD2 or H3 request must carry an auditable current-unit
allowlist and one-to-one reference identity bindings. H3 prompts are checked in full,
including negative clauses, because naming an absent concrete entity can cause H3 to
render it. SD2 retains its existing prompt grammar and negative-prompt behavior. See
[`docs/PROVIDER_SCOPE_ISOLATION.md`](docs/PROVIDER_SCOPE_ISOLATION.md).

## Canonical speaker/voice binding

Dialogue generation for both MiniMax-H3 and SD2 is fail-closed. Every distinct speaker must be bound to a stable entity, a registered canonical voice, a dedicated audio slot, and the visible lip owner. Configure the runtime registry with `QINGSHAN_VOICE_REGISTRY`; its schema is shown in [`configs/VOICE_REFERENCE_REGISTRY.example.json`](configs/VOICE_REFERENCE_REGISTRY.example.json). The real registry and voice media stay outside Git.

H3 transports each canonical voice through its public HTTPS reference URL. SD2 transports the provider-registered audio asset ID. A dialogue unit is rejected before a paid request when its speaker is missing, the model-specific transport is unavailable, two speakers share an implicit slot, or the prompt omits the binding. Release additionally requires machine evidence for speaker diarization, canonical-voice similarity, and visible lip ownership; ASR text correctness alone cannot pass.

## Grouped-video continuity gate

Every boundary between editorial beats packed into one provider video task must carry an authored `internal_transition_contract`. The compiler and submitter fail closed unless that contract is bound to both beats' exact:

- visible cast and dialogue speaker;
- global map, location, and shot subspace;
- prop set and ownership/handoff;
- ambience, foley, and action sound;
- previous action terminal state and successor initial state;
- camera transition and axis strategy; and
- reference-image entity mapping.

Different characters may not reuse the same mapped screen slot as an implicit identity transformation. That handoff must be split or expressed as an authored cut, reveal, or reframe. The compiled model prompt contains the full `【节拍内连续性硬合同】`; the same contract is fingerprinted and revalidated immediately before any paid provider POST.

Creative continuity is a pre-submission gate. Post-generation rejection is limited to technical integrity and basic plot/identity correctness; action taste, choreography preference, and micro-expression precision do not consume regeneration attempts after a technically usable result exists.

## Cultural visual-language contract

Image and video generation share one immutable cultural design contract. For
Qingshan E54 and later, the Writer/Director selects and records the profile in
the generation contract from the story world, period, region, and visual bible.
Downstream keyframe and video compilers may only inherit and validate that
decision; they never insert a default profile. The final provider prompt must
carry the exact Writer-owned decision. The profile fixes Chinese architecture, dress, armor
lineage, palette, motivated lighting and material language, while explicitly
excluding European plate armor, Gothic/knight silhouettes, black-gold Western
fantasy posters and teal-orange grading. Fully concealed identities are treated
as complete appearance authorities—not face references—and must carry an
admitted cultural profile. A missing or diluted contract fails before any paid
provider request.

## Canonical character identity contract

E54 and later use `character_id` as the sole identity key across the Writer
contract, cast, action subject/patient, dialogue speaker/listener, visible lip
owner, appearance references, and voice bindings. Display names and story
aliases (for example, a title and a personal name) resolve to one registered
entity and can never create two people. `voice_entity_id` identifies a voice
asset; it is deliberately separate from `character_id`. The Writer seal and
provider compiler both fail closed on alias collisions, unregistered cast,
name/ID mismatch, an absent visible speaker, a speaking character marked
silent, a wrong lip owner, an action-subject mismatch, or a voice binding owned
by another character.

## Physics-first action generation

Action units are compiled through [`configs/ACTION_VIDEO_GENERATION_METHOD_V2.json`](configs/ACTION_VIDEO_GENERATION_METHOD_V2.json) and the source-faithful combat library. The shared Action IR locks initiator/target roles, weapon ownership, force origin, exactly one of contact/evasion/threat-threshold, one primary feedback, at most one secondary feedback, and an observable irreversible terminal state before either model compiler runs. Canonical failure names and pre/post-generation ownership are defined in [`configs/ACTION_PROMPT_FAILURE_CODE_MAP_V1.json`](configs/ACTION_PROMPT_FAILURE_CODE_MAP_V1.json). SD2 retains its existing provider-facing grammar. H3 additionally requires the first explosive action within 0.5 seconds, an explicit `feet → hips → shoulders → elbow/wrist` power path, both sides of the exchange, causally synchronized sound anchors, and rejection of handshake-like contact, slow push-hands, static tableaux, pose slideshows, loops, and reverse-force outcomes.

Omni reference images are treated as semantic state anchors, not guaranteed frame interpolation. After a reviewable video-content failure, wording-only or negative-prompt-only tuning is prohibited: the next attempt must recompile the complete provider execution prompt from a materially redesigned Action IR, receive a new candidate ID and prompt SHA, and register the failed SHA as `do_not_repeat`. Canonical story, identity, wardrobe, map, weather, shot type, camera type, axis, prop ownership, voice binding, and native-audio intent remain immutable. Pre-generation QA remains comprehensive; post-generation QA remains basic technical plus basic plot/outcome presence. Optical flow, motion-energy scoring, action-velocity analysis, dynamic-causality scoring, and other detailed action review are not run after generation.

## E47+ production-efficiency contract

`tools/production_efficiency_contract.py` turns the next-episode speed policy into a fail-closed preflight instead of an informal convention. It preserves every identity, map, wardrobe, prop, sound, transition, transaction, and real-media boundary gate while removing repeat work:

- character cards, map anchors, wardrobe cards, and scene anchors are reused by exact SHA across episodes; a new keyframe is generated only for semantic novelty such as a new identity, subspace, wardrobe state, non-interpolable physical state, or transition-critical terminal state;
- MiniMax-H3 dialogue units default to 6–10 seconds and no more than two lines, while silent or continuous-action units may run up to 15 seconds; an authored, named exception is required to exceed the dialogue limits;
- generation runs in rolling waves of at most six units, with completed handles harvested and technically checked immediately instead of waiting for a whole batch;
- exact model/prompt/reference hashes form the generation cache key, so a completed identical request is reused and never posted twice; and
- local release encoding prefers Apple VideoToolbox H.264, caches normalized segments by content hash, and performs one final subtitle/outro/upscale composite. Software `libx264` remains the deterministic fallback.

The optimization changes scheduling and reuse only. It does not lower prompt QA, paid-task durability, post-generation technical/basic-plot checks, or publication gates.

## Automatic BGM profile binding

The writer/director keeps creative authority over music through the generation contract's `audio_contract.bgm` declaration. AgentCut does not choose a postproduction audio mode independently. `tools/audio_profile_binding.py` deterministically compiles that declaration into exactly one registered profile:

- no-BGM declarations → `NATIVE_MULTIMODAL_NO_EXTERNAL_BGM`;
- explicitly limited narrative windows → `NATIVE_MULTIMODAL_SELECTIVE_BGM`; and
- an explicit whole-episode/layered requirement → `LAYERED_POST_WITH_BGM`.

Every new AgentCut assembly requires `--generation-contract`. The resolved profile, creative declaration, contract path, and both contract/declaration SHA-256 values are embedded in the project and admission receipt. Manual profile overrides, later contract mutation, episode mismatch, unknown prose, forbidden BGM tracks, or a missing required BGM track fail closed before release.

## Native-audio loudness contract

SD2 and H3 keep the dialogue, ambience, foley, action sounds, and timing generated by each admitted multimodal task. The postproduction line does not redub or replace that content, but it now measures every native-audio unit before assembly, assigns a dialogue/action/ambience loudness role, applies bounded static gain with true-peak limiting, and rejects units that remain inaudible or create an excessive loudness jump at the next media boundary. These unit targets are explicitly premaster staging targets; the assembled release is then normalized and independently gated for integrated loudness, loudness range, and true peak. A release cannot pass merely because it contains an AAC stream or lacks long digital silence.

## License

The source code in this repository is released under the [MIT License](LICENSE). You may use, copy, modify, merge, publish, distribute, sublicense, and sell copies subject to the license notice. Generated media, source novels/scripts, credentials, third-party models, provider services, and other separately supplied assets are not automatically relicensed by this repository.
