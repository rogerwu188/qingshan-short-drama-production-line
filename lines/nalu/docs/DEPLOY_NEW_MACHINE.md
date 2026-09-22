# 新机器部署 nalu 生产线（从克隆到成片）

目标：第三方在一台新机器上，用本仓库 + 自己的素材与密钥，跑出与原部署同等的能力。全文按顺序执行；
带 💰 的步骤会花提供者积分，其余免费。凡标 **MANUAL_REQUIRED** 的环节需要一个能看图、能改文本的代理
（人或 Claude/Codex 之类的代码代理）坐在审核位上——仓库替代不了这一环。

## 0. 你不会从仓库拿到什么

- 提供者凭据（Giggle API key）、任何付费额度；
- 剧作原文、角色照片、音色选择、品牌片尾（都是线主的素材，永不入库）；
- 私有运行时里的原著、角色素材、事务、账本与审核回执；
- 审核位上的代理：五类审核都是「实际看图 → 逐条填结构化答案」，由代理完成。

## 1. 引擎与虚拟环境

```bash
git clone https://github.com/rogerwu188/qingshan-short-drama-production-line.git nalu_engine
cd nalu_engine && export NALU_ENGINE_ROOT="$PWD"
python3 -m venv .qingshan-venv && .qingshan-venv/bin/pip install -r requirements-core.txt -r requirements-media.txt
.qingshan-venv/bin/pip install -e .
# S4 语音与 S6 选择性配乐使用仓库内 tools/storyclaw_audio_provider.py；无需私有 AgentCut。
```

需要 `ffmpeg`/`ffprobe` 在 PATH；容器也可显式设置 `QINGSHAN_FFMPEG` / `QINGSHAN_FFPROBE`
或 `NALU_FFMPEG` / `NALU_FFPROBE`。字幕烧录需要真实 CJK 字体（Linux 推荐
`fonts-noto-cjk`），自定义文件用 `QINGSHAN_CJK_FONT` 或 `NALU_CJK_FONT`。显式路径无效或
依赖缺失时流水线会写明 `BLOCKED_MEDIA_TOOL` / `BLOCKED_CJK_FONT`，不会把未测量结果记成 PASS。
除 requirements 外还要装 `insightface onnxruntime rapidocr-onnxruntime faster-whisper opencc`
（身份余弦、OCR、ASR、繁简转换；Python 3.12）。

## 2. 两把钱锁

```bash
cp .env.example .env            # 填 GIGGLE_API_KEY、GIGGLE_API_BASE；其余留空即可
cp configs/pipeline.example.json "$NALU_RUNTIME_ROOT/qingshan.json"   # 锁文件在运行时根（nalu_pipeline CONFIG_PATH），不在引擎目录
```

`$NALU_RUNTIME_ROOT/qingshan.json` 里 `generation.paid_requests_enabled` 默认 `false`。付费阶段必须同时满足：
命令行 `--paid` **且** 该字段为 `true`；免费子进程会被剥掉 API key，物理上碰不到付费端点。

## 3. 运行时根目录（状态与素材，放在仓库之外）

```bash
export NALU_RUNTIME_ROOT="$HOME/nalu_runtime"
python3 lines/nalu/runtime/tools/bootstrap_runtime_root.py --runtime-root "$NALU_RUNTIME_ROOT" --line-id my-line --work "作品名"
python3 lines/nalu/runtime/tools/nalu_paths.py        # 打印解析出的 ENGINE_ROOT / RUNTIME_ROOT / VENV_PYTHON
```

工具从仓库的 `lines/nalu/runtime/tools/` 运行；三个根由环境变量决定（`NALU_ENGINE_ROOT`、
`NALU_RUNTIME_ROOT`、可选 `NALU_VENV_PYTHON`），未设置时按 `nalu_paths.py` 顶部说明自动探测。
把这三个 `export` 写进 shell 配置，心跳/循环脚本也依赖它们。

## 4. 线主素材接入（免费）

1. 角色照片：每角色一张正脸放进 `$NALU_RUNTIME_ROOT/runtime/character_sources/`，用仓库根的
   `tools/intake_character_sources.py --folder <目录> --map $NALU_RUNTIME_ROOT/runtime/character_source_map.json`
   登记 sha、角色绑定、授权备注（肖像与改编授权是线主线下声明，仓库不校验也不替你声明）。
2. 原文：`tools/intake_source_text.py --input <文本文件> --work <作品名> --out $NALU_RUNTIME_ROOT/sources --authorization "<授权说明>"`
   分章登记；线专用的分章读取脚本由 `NALU_SOURCE_TXT` 指向你的文本文件。
3. 音色：`.qingshan-venv/bin/python tools/storyclaw_audio_provider.py speech-voices` 列表 → 代理按角色气质挑选 → 写入
   `runtime/voice_catalog.json`（模板已装好，每个说话角色一行）。**MANUAL_REQUIRED**
4. 品牌片尾：9:16 的 3 s 片尾放进 `$NALU_RUNTIME_ROOT/brand/`。**MANUAL_REQUIRED**
5. 实体注册：`runtime/nalu_entity_registry.json` 按角色补 `entity_aliases`（加法式）。

## 5. 一集的剧本层（免费，MANUAL_REQUIRED）

每集四层：叙事正典（手写）、导演脚本、生成合同（JSON）、manifest。逐集构建器 `build_e0N_layers.py` 是作品专用文件（内含该集镜头表与逐字台词，属于作品文本，不入库）；仓库提供的是它依赖的规则与校验：`nalu_prompt_rules.py`（提示词规则）、`static_design_gate.py`（机位运动 R1–R8）、`nalu_qa_common.py`。新作品的构建器按这个骨架自写：SCENES（场次：地点/时间/秒数/信息条数）→ CAMERA_PLANS（每镜景别/机位/运动族/起止取景）→ SHOTS（每镜 3–6 s：动作主体/对白/entry_state/completion_state/状态维度/参考指代）→ 校验（单场可切 4–8 s 单元、无对白 ≤4 s、LOCKED ≤30%、远景后露脸镜 identity_reanchor、道具在 action 就必须在 entry/exit、姿态词不进 entry/exit 文本）→ 写 directing script / generation contract（qingshan.generation_contract.v3）/ manifest（beat_disposition 逐拍申报）。新地点还要写
`preproduction/<EP>/new_location_place_spec.json`（作者命名与坐标）。

## 6. S1 → S8

```bash
P=$NALU_ENGINE_ROOT/.qingshan-venv/bin/python; T=$NALU_ENGINE_ROOT/lines/nalu/runtime/tools
$P $T/nalu_pipeline.py run --episode E01                 # 免费阶段先干跑：S1 S2 通过、S3 在 DRY_RUN 停下
$P $T/nalu_pipeline.py run --episode E01 --paid          # 💰 S3 起付费；每次卡在 REVIEW_REQUIRED（exit 4）时按下表填答后重跑
$P $T/nalu_pipeline.py status --episode E01
```

| 阶段 | 内容 | 审核（代理实际看图后填答） | 填答脚本（`tools/review_fill/`，按集复制改名） |
|---|---|---|---|
| S1 | 四层 + gate10 + 角色实体合同 | — | — |
| S2 | 预制作（分单元、空间图、提示词） | — | — |
| S3 💰 | 身份牌三视图、道具/构筑物卡 | 身份审：缩略总表 + InsightFace 余弦 | `e0N_fill_identity_answers.py` |
| S4 💰 | 每个说话角色一次配音参考 | — | — |
| 整批提示词门 | 关键帧提示词登记 | 通读摘要写逐行答案 → receipts → register | `prompt_batch_qa.py digest/receipts`、`prompt_batch_register.py` |
| S5 💰 | 关键帧 + Q1 admission | Q1：缩略总表看图填答；REJECT → 改镜头文字 → 停放旧图/旧提示词 → 重登记 → 重跑 | `e0N_fill_keyframe_answers.py`、`contact_sheet.py` |
| S6 💰 | 视频波次 + 选择性 BGM 源生成（每个不同提示词约 8 积分）+ post-gen QA + Q2 | 动作角色审、剧情审、Q2（5 帧 + 身份仲裁 `identity_pose_exemptions`） | `e0N_fill_action_role_answers.py`、`e0N_fill_post_gen_plot.py`、`e0N_fill_video_q2.py`、`video_sheets.py`、`asr_units.py` |
| S7 | 装配、字幕、片尾、BGM 时间线规划/事务核验/账单对账/QA/混音、响度；**零 provider POST** | — | 配乐对账见 K032（提供者音乐账单无 project_id → 按提交窗口隔离） |
| S8 | 写 CHECKPOINT，等线主 `approve` | 线主看片 | `nalu_pipeline.py approve --episode E01` |

波次循环：`tools/review_fill/nalu_e03_s6_loop.sh <EP>`（每 3 分钟 `run --from S6 --paid`，直到不再是
VIDEO_NOT_ALL_COMPLETED；其他阻塞会停下等人）。心跳模式：定时检查状态/日志，REVIEW_REQUIRED 就看图填答，
API 错误就从断点续跑，付费 POST 靠 `workflow/tasks/*_transactions/` 的指纹不会重复。

预算：每集 8000 积分硬上限由 `nalu_budget_ledger.py` 守；付费前估算，超限即停。回执：
`$NALU_RUNTIME_ROOT/runtime/reports/`、`preproduction/<EP>/reports/`、`deliverables/<EP>/CHECKPOINT.md`。
当前可移植策略把配乐事务存到
`workflow/tasks/giggle_bgm_transactions/<series_scope>/<episode>/`，预算门显式读取同一目录；不同系列即使都用
`E01` 也不会互相复用或计费。旧的 `giggle_bgm_transactions/<episode>/` 位置只供历史回放。

## 7. 已知未接入（INTEGRATION_PENDING）

- 整批提示词门仍是手动 5 步，未并入 S5；
- 地图素材 → 空间图无自动接入；
- D-9/D-12 两个最终 QA 证据键无生产者（S7 以 BLOCKED 结束，S8 单独 `run --from S8`）；
- `bgm_authenticity_gate` 是否接受窗口隔离账单标签，由线主决定（K032）；
- 原部署实例仍从自己的运行时副本运行，切换到仓库副本后再删除该副本。

## seq=19 additions (2026-09-16, after the E04 audience review)
- S1 now also runs `tools/script_structure_contract_gate.py` (hook, dialogue density, action outcomes, antagonist
  motive, prop sources, entity introductions, lexicon) and `tools/continuity_state_contract_gate.py` (life states,
  group counts, creature cards, ambush space, costume inheritance) — both blocking.  The writer schema
  (`agent_factory/claude_writer_v2/schemas/*.json`) documents the new optional contract fields; an episode builder
  must declare them or S1 stops.  Lexicon: `lines/nalu/runtime/configs/LEXICON_<world>_v1.json`.
- S4 ends with `build_voice_cast.py`: measures each reference clip's F0, writes `runtime/voice_cast.json`, and a
  co-presence precheck (band overlap > 50 % → REQUIRES_HUMAN, the line owner decides).
- S7 runs `tools/final_cut_audience_detectors.py` on the levelled final (hook, coverage, silent runs, voice
  distinctness, emotion dynamics, lexicon via ASR+subtitles+OCR, mascot-in-story, loudness −14 LUFS / TP −1) and
  the registered wrapper gate `FINAL-CUT-AUDIENCE-DETECTORS`; FAIL blocks the deliverable, UNVERIFIED /
  NOT_IMPLEMENTED items are listed in the report and never count as PASS.
- Review questionnaires carry the new perceived-state / group-count / creature-gait (Q2, Q1) and action-outcome /
  antagonist-motive / new-entity-purpose (plot) questions; fill scripts must answer them from the media.
- `knowledge/failure_memory.jsonl` is generated from the K registry; only `stage == "prompt"` rows are injected into
  prompts (`nalu_prompt_rules.apply`, ctx["failure_memory"]).
