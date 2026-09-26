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

## Engineering knowledge / 经验继承

[工程知识库（59 条规则与事故教训）](docs/knowledge/ENGINEERING_KNOWLEDGE_BASE.md) ·
[决策依据](docs/decisions/DECISION_RECORDS.md) ·
[A–I 交接模板](examples/handoff/HANDOFF_TEMPLATE.md) ·
[集成状态与待完成项](docs/knowledge/INTEGRATION_STATUS.md)。

Run `python3 -m qingshan_engine.cli knowledge --validate` to check the portable
catalog; omit `--validate` to export context for a new agent.
This is read-only, requires no paid provider, and never grants production
authorization. Guidance and pending integration are explicitly distinguished
from referenced implementations. Private episode decisions are not defaults.

## Engine contents

Deployment verification: [installation guide](docs/DEPLOYMENT.md) ·
[0.3.1 reliability and production-parity audit](docs/PIPELINE_INTEGRITY_AUDIT_2026-09-05.md).
Run `python3 tools/deployment_code_integrity.py` after downloading a release to
verify the reusable engine inventory. Private runtime data is intentionally separate.

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

H3 transports each canonical voice through its public HTTPS reference URL. SD2 transports the provider-registered audio asset ID. A dialogue unit is rejected before a paid request when its speaker is missing, the model-specific transport is unavailable, two speakers share an implicit slot, or the prompt omits the binding. H3 resolves `character_id → SUBJECT_N → @ImageN → SPEAKER_N → @AudioN` explicitly and treats every speaker change as a generation-task boundary; it never assumes that independently numbered image and audio lists have matching ordinals. Release additionally requires machine evidence for speaker diarization, canonical-voice similarity, and visible lip ownership; ASR text correctness alone cannot pass. See [`docs/H3_CROSSMODAL_SPEAKER_BINDING.md`](docs/H3_CROSSMODAL_SPEAKER_BINDING.md).

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

Post-generation dialogue QA follows `configs/BASIC_DIALOGUE_QA_POLICY.json` for both SD2 and H3: homophones, similar-sounding words and ASR-only transcription differences are recorded, not rejected or regenerated. Do not run repeated transcription to resolve minor spelling differences. Keep the authored dialogue unchanged in prompts and canonical subtitles. Missing/inaudible dialogue, obvious wrong speakers, clipped sentences and decoding failures still require basic checks; ASR alone does not prove those failures or certify voice identity. This does not change model prompt formats, map/weather/camera contracts or voice bindings.

SD2 and H3 keep the dialogue, ambience, foley, action sounds, and timing generated by each admitted multimodal task. The postproduction line does not redub or replace that content, but it now measures every native-audio unit before assembly, assigns a dialogue/action/ambience loudness role, applies bounded static gain with true-peak limiting, and rejects units that remain inaudible or create an excessive loudness jump at the next media boundary. These unit targets are explicitly premaster staging targets; the assembled release is then normalized and independently gated for integrated loudness, loudness range, and true peak. A release cannot pass merely because it contains an AAC stream or lacks long digital silence.

## Tail-ad slot (optional, per-episode opt-in)

An episode may optionally carry a short (4–6s) ad after the final frame and before the studio end-card, with zero effect on episodes that don't opt in: `manifest.ad_slot` absent means `final_9x16.mp4` is byte-identical to a line with the feature disabled. The orchestrator asks once, via a file-based Q&A poll (`ads/prompts/<EP>_AD_PROMPT.json` / `_AD_ANSWER.json`, 60s wall-clock, no `input()`), right after the writer layers are sealed and before S1; a late answer arriving before S7 starts is still honoured. Two input modes feed the same slot: dropping a finished clip in `ads/inbox/<sku>.mp4` (Mode A, may already carry its own burned-in badge/CTA — declare it via an optional `<sku>.meta.json` sidecar so the OCR-clean check allow-lists it), or a brief in `ads/briefs/<sku>.json` routed through `tools/adforge_adapter.py` to an external AdForge deployment (Mode B, `ADAPTER_REQUIRED` when `ADFORGE_ROOT` is unset — the line produces its normal ad-free cut). Both modes pass through `tools/ad_tail_package.py` (format/duration/loudness/badge/OCR/spoken-content checks, all fail-closed) and `tools/ad_tail_insert.py` (splices `content | ad | endcard`, verifying the packaged ad's SHA-256 before touching the output), producing `<EP>_final_9x16_AD.mp4` alongside — never overwriting — the original. The ad never gates the episode's own creative QA: six diagnostics surface under the existing `FINAL-AUDIT-COMPLETENESS` evidence bundle as optional/informational only. Slot contract (position, duration bounds, format, loudness target, spoken-char cap) lives in `configs/AD_SLOT_CONTRACT_V1.json`, parameterized per deployment.

## 从素材到成片（一条真实走通的路径）

本节来自一条真实跑通 E01–E03 的部署（2026-09-09 → 09-15）。逐步操作、停下来问人的点、
失败分类和尚未自动化的步骤见根目录 [AGENTS.md](AGENTS.md)。这条线的编排器与全部线专属工具已随仓库发布在
`lines/nalu/runtime/tools/`（路径参数化，离线测试 `tools/tests/test_nalu_runtime_port.py`）；新机器从零部署按
[lines/nalu/docs/DEPLOY_NEW_MACHINE.md](lines/nalu/docs/DEPLOY_NEW_MACHINE.md) 走，它也如实列出仓库给不了的东西
（凭据、作品素材、AgentCut、审核位上的代理）。

### 启动话术（正式版，用户把它发给一个全新代理）

```
你是这条短剧生产线的编排代理。先读仓库根目录 README.md 与 AGENTS.md，再按 AGENTS.md §1 部署。
作品：<作品名>；源文本：<文件路径>（我提供文件，不要上网抓正文）；改编与肖像授权：<我的声明原话>。
要求：竖屏 9:16、每集约 <N> 秒、视频模型 <model>、每集积分上限 <cap>、画风 <…>、节奏 <…>。
素材：人物照片目录 <路径>（角色→照片的对应由你提议，我确认）；场景/地图图片 <路径或无>；片尾/品牌 <路径或无>。
规则：付费步骤先给我计划与费用，我说“开始”再跑；每集成片给我看；发布不在你的权限内。
先把 E01 推进到第一道付费门前（S1/S2 通过、S3 DRY_PLANNED），把计划、费用与需要我决定的事一次列给我。
```

### 四类素材：格式 / 位置 / 最低要求

| 素材 | 格式 | 位置（`$RUNTIME_ROOT` 相对） | 最低要求 |
|---|---|---|---|
| 短剧要求 + 集数预算 | 用户原话 | `$ENGINE_ROOT/workflow/claude_writer_agent/SUPERVISOR_ORDERS.json`（代理记成带 seq 的指令） | 画风、时长、模型、上限、停下来问的点 |
| 小说 / 剧本 | 单个文本文件（GB18030 或 UTF-8，繁/简皆可） | `sources/<作品>/{zh-Hant,zh-CN}/chNNNN.md` + `SOURCE_INDEX.json` | 章节标题可被识别（`第N章`）；`python3 tools/intake_source_text.py --input <file> --work <名> --out $RUNTIME_ROOT/sources` |
| 图片：人物照 | 每角色一张正脸（PNG/JPG） | `runtime/character_sources/<CHAR-ID>__SOURCE_V2_TANG.png`，原图与裁切 `runtime/character_sources_hold/`（不入库） | 授权声明写进 `runtime/character_source_map.json`；`python3 tools/intake_character_sources.py --folder <目录> --map …` |
| 图片：场景 / 历史地图 | 可选 | `runtime/reference_images/` | 只作提示词参考；空间图仍由代理按合同手写/自动扩展（INTEGRATION_PENDING） |
| 其它（片尾、品牌、音色偏好） | 9:16 PNG / 文本 | `brand/`、`runtime/voice_catalog.json` | 手放；音色从 `agentcut speech-voices` 挑 |

### 端到端最短路径（走过的那条）

```bash
# 0. 部署（AGENTS.md §1）：clone → venv → qingshan init/doctor/test → 伴生运行时 runtime/ → .env → qingshan.json
# 1. 素材接入：intake_source_text → episode_source_map（OBSERVED）→ intake_character_sources → voice_catalog
# 2. 写手：E01_NARRATIVE_CANONICAL_v1.md（手写）→ build_e01_layers.py → 四层
# 3. 免费阶段：run --episode E01 --until S3      # S1 三门 + S2 预制作 PASS，S3 DRY_PLANNED 并打印付费计划与费用
# 4. 线主说“开始”：run --from S3 --until S3 --paid → 身份审（看图填答）→ S4 → S5 干跑 → 整批提示词门（编译/登记/摘要/答案/回执/登记）
# 5. run --from S5 --until S5 --paid → Q1（看图填答；REJECT 走重做小循环）→ S6 波次循环 → post-gen/Q2 → S7（选择性配乐：付费子进程带 paid 标志；配乐账单按提交窗隔离）→ S8（线主看片）→ S7-SYNC（仓库收工）
```

每一步的输入、产出、门、人工点、费用与停止条件见 AGENTS.md §3；能自动的都在编排器里，标 MANUAL_REQUIRED 的必须由代理或线主亲手做。

E03 之后操作者要多知道的三件事（详见 AGENTS.md §5 与知识库 K029–K032）：

- 配乐提供者位于 Cloudflare 之后：裸 urllib User-Agent 会得到 HTTP 403 `error code: 1010`；发浏览器 UA，用免费的 GET 任务查询测鉴权，绝不用 POST 探测。
- 音乐扣费没有精确的逐任务 id：`tools/credit_window_isolation.py` 按任务自身的半开提交窗 [intent, response) 隔离，证据标签是 `PASS_WINDOW_ISOLATED_LEDGER_NET`（不是 exact）；发布门是否接受该标签由线主决定。
- 共享账号上不属于本线的账单行要隔离、永不入账。

## License

The source code in this repository is released under the [MIT License](LICENSE). You may use, copy, modify, merge, publish, distribute, sublicense, and sell copies subject to the license notice. Generated media, source novels/scripts, credentials, third-party models, provider services, and other separately supplied assets are not automatically relicensed by this repository.
