# NALU 生产合同（Claude Code 执行，无人值守）

你在一台无 GPU 的 Linux miniPC 上无人值守地执行 NALU 短剧生产线的一集（下文 `<EP>`，如 E01）。
OpenClaw 编排代理已经替你完成：引擎克隆与依赖安装、运行时根目录初始化与模板修复、Giggle key 写入
`$NALU_ENGINE_ROOT/.env`、原著获取，以及这一集的叙事正典与生产简报。你负责其余全部：把叙事正典转成
可通过门禁的四层剧本，并执行 S1→S7。线主（项目负责人）不在终端前，只通过编排代理和你对话。

## 0. 环境与位置
- `NALU_ENGINE_ROOT`（默认 ~/nalu_engine）、`NALU_RUNTIME_ROOT`（默认 ~/nalu_runtime）、`NALU_WORK_ROOT=$NALU_ENGINE_ROOT/workflow/nalu`。
- 解释器 `$NALU_ENGINE_ROOT/.qingshan-venv/bin/python`（下文 `$P`）；线工具 `lines/nalu/runtime/tools`（下文 `$T`）；
  本 skill 脚本 `skills/nalu-claude-code/scripts`（下文 `$S`）。命令都在 `$NALU_ENGINE_ROOT` 下执行。
- 输入：`workflow/claude_writer_agent/scripts/<EP>_NARRATIVE_CANONICAL_v1.md`（叙事正典，事实与逐字台词的唯一来源）、
  `$NALU_RUNTIME_ROOT/briefs/<EP>_PRODUCTION_BRIEF.json`（人物外貌/年龄/性别/服装、地点、画风、目标时长、预算与线主原话）。
- 免费命令一律不带 key：`env -u GIGGLE_API_KEY $P $T/nalu_pipeline.py run --episode <EP> --until <Sx>`。
- 付费命令只用一个入口：`./lines/nalu/runtime/tools/paid_stage.sh <EP> <FROM> <UNTIL>`（它自己读 `.env`；你不要 `cat`/打印 `.env`）。

## 1. 绝对规则
- 不写假 PASS；审核必须实际看图/看帧后作答（用 Read 打开图片；视频先用 ffmpeg 抽帧拼成联系表再看）。
- 不替线主做决定、不编造线主原话。需要线主决定时立即结束本轮（见 §6 NALU_STATUS），由编排代理转达；
  编排代理会用线主的**原话**恢复你的会话，你再用仓库工具逐字记录。
- 不删事务文件和回执（`workflow/tasks/**`、`reviews/**`），作废的东西移到 `_superseded_<日期>_<原因>/`。
- 不发布、不上传任何平台；不 git push；不改门禁阈值。
- 同一镜第 2 次创意重做仍失败、预算将超上限、出现新的付费类别：停下问线主。

## 2. 四层剧本（免费）
写 `lines/nalu/runtime/tools/build_<ep小写>_layers.py`（作品文本，.gitignore 已拦，不入库），由叙事正典和简报生成
`<EP>_DIRECTING_SCRIPT_v1.md`、`<EP>_GENERATION_CONTRACT_v1.json`（qingshan.generation_contract.v3）、`<EP>_manifest_v1.json`，
以及 `$NALU_RUNTIME_ROOT/preproduction/<EP>/{asset_requirements_overlay.json,new_location_place_spec.json,view_reference_policy.json}`。
然后 `run --until S3`，直到 S1 PASS、S2 PASS、S3 DRY_PLANNED。必须满足（门禁源码在 `$T` 与 `tools/`，报错就读源码改剧本，不改门禁）：
- 对白镜时长 = 汉字数/4 + 0.5，向上取整到 0.5，最多再 +1；无对白镜 ≤ 5 s 且机位必须运动；单元（同场连续镜头）4–8 s 可切分。
- 每镜 `prompt_spec.camera_plan` 全字段（shot_scale/camera_height/camera_side/motion_family/motion_direction/lens_intent/axis_relation/start_framing/end_framing/motivation）；
  LOCKED 起止取景相同、运动镜不同；相邻单元首镜方向不能相同，5 个单元内同方向不超过 2 次。
- `state_delta_dimensions` 只能取 POSITION/POSTURE/CONTACT/POSSESSION/INTEGRITY/MOMENTUM，且 entry/exit 证据要不同；entry/completion 各 ≥ 6 字。
- 每个 scene_state：`ambient_life{grade A|B|C, motion_trend, first_frame_state, reaction_progression}` 和 `weather_provenance{source_type, source_ref, visibility_mode}`。
- 同场相邻镜头都写 `internal_transition_authoring`（transition_mode ∈ CONTINUOUS_ACTION/CAMERA_REFRAME/PAN_REVEAL/OCCLUSION_REVEAL/MOTIVATED_CUT/REACTION_CUT/MATCH_CUT）。
- 对白镜 `action.performance{emotion(词表 PERFORMANCE_EMOTION_LEXICON_v1), body_action(非琐碎), delivery}`；同场同情绪不连续 3 次；`writer_selfcheck_seq29.enforced: true`。
- 首帧可见角色默认必须露正脸；远小/背影在 `cast[].face_visibility` 写 `FAR_FIGURE_*` / `BACK_*`。入场文字里只写本镜 cast 里有的人。
- 道具名一旦出现在某镜文字里，该镜首帧就必须看得见。别设计「从怀里掏出来」这种首帧不可见的道具镜，尤其是承接上一单元尾帧的镜（会被派生起始帧审核卡死、重做也救不了）。
- 古装场景的灯写成「无罩敞口油盏」并把它声明为道具（`non_character_entities` + 镜头 props），否则图像模型画玻璃罩煤油灯，命中禁用词表。
- `runtime/nalu_entity_registry.json` 每个说话角色一行（`$S/apply_runtime_fixups.py --character 名=CHAR-ID:slug`，编排代理已跑过；新增角色时你补跑）。

## 3. 付费授权（等线主原话）
先检查付费凭据：`grep -qE '^GIGGLE_API_KEY=.+' .env`（只看有没有，绝不打印值）。为空时以
`OWNER_DECISION_REQUIRED` 结束本轮，`question` 请线主在对话里发 Giggle API key；编排代理写入 `.env` 后会用
「已配置 GIGGLE_API_KEY」恢复你（消息里不会出现 key 本身），你再复查一次。
S3 DRY_PLANNED 后结束本轮，`NALU_STATUS.state = OWNER_DECISION_REQUIRED`，`question` 里给出：剧本梗概、镜头/单元数、
预计积分（身份牌 11/张、配音 2/角色、关键帧 11/张、视频约 20/秒）、需要的授权原话与版权声明。收到线主原话后：
```bash
$P $T/record_paid_production_order.py --orders $NALU_RUNTIME_ROOT/runtime/SUPERVISOR_ORDERS.json --owner-id <简报里的 owner_id，缺省 owner> \
  --order "<线主原话，逐字>" --episode <EP> --stages S3,S4,S5,S6 --cap <上限> --rights-basis "<线主版权声明，逐字>" \
  --work "<剧名>" --recorded-by claude-code --authorizing-order-ref "<编排代理转达的出处>"
```
把它打印的授权坐标同时写进 `$NALU_RUNTIME_ROOT/qingshan.json` 的 `authorization` 和 `.env`
（`NALU_SUPERVISOR_ORDERS_PATH`、`NALU_PAID_ORDER_SEQ`、`NALU_LATEST_ORDER_SEQ`、`NALU_LINE_OWNER_ID`、`NALU_RUNTIME_ROOT`、`NALU_ENGINE_ROOT`），
设 `generation.paid_requests_enabled=true`、`budget_cap_credits_per_episode=<上限>`。**以后每记一条订单都要把两处的 latest_order_seq 改成最新**，否则全部订单失效。

## 4. S3→S7（每次 exit=4 = 有审核请求）
审核通用做法：`$NALU_RUNTIME_ROOT/runtime/reviews/<EP>/` 最新 `*_request.json` → `$P $T/vlm_review_protocol.py example-answers --request <req>` →
看媒体、逐题作答（每题枚举值、观察 ≥ 20 字、FAIL 必须带 defect）→ `submit --request <req> --answers <ans>` → 再跑同一阶段。
- **S3 身份牌**（`paid_stage.sh <EP> S3 S3`）：拼缩略图看全部 plates。年龄/外形不符判 FAIL；重做 = 改 `$NALU_RUNTIME_ROOT/preproduction/<EP>/prompts/` 中该角色 3 个 txt 的措辞（指纹=提示词 sha），把旧图、`_raw`、回执移到 `_rejected_*`，重跑。
- **S4 配音**：`$P tools/storyclaw_audio_provider.py speech-voices --out voices.json`（免费），给每个说话角色挑 voice_id 写 `runtime/voice_catalog.json`（键=拼音 slug）。同场两人参考音 F0 必须差 ≥ 25%（男女搭配最稳；男声挑「沉稳/醇厚」类）。换音色：旧 registry 行移到 `superseded_rows`，旧参考音目录和 `workflow/tasks/giggle_audio_transactions/**/speech/<slug>.json` 移到 `_superseded`。
- **S5 关键帧**：先过整批提示词门：`$S/prompt_batch_prepare.sh <EP>` → 通读 `workflow/nalu/<EP>/preproduction/planned_video_prompts/*.txt`、`prompts/keyframes/*.txt`、`reports/<EP>_PROMPT_BATCH_DIGEST.json` →
  写 `reports/<EP>_PROMPT_BATCH_ANSWERS.json`（`{"schema":"nalu.prompt_batch_answers.v1","reviewer":"claude-code","review_method":"CLAUDE_STRUCTURED_PROMPT_REVIEW","reviewed_at":…,"units":{"<UNIT>":{"verdict":"PASS","cross_unit_continuity_checked":true,"observation":"…"}}}`）→ `$S/prompt_batch_finish.sh <EP>`（必须 register PASS）→ `paid_stage.sh <EP> S5 S5`。
  之后有 keyframe Q1、start_frame 审核。改了剧本：重跑构建器 → `run --until S2` → prepare/finish → S5。被拒关键帧：把 `keyframes/<shot>-keyframe-v1.png` 和 `keyframe_harvest/_raw/<shot>*` 移走再跑。
- **S6 视频**（`paid_stage.sh <EP> S6 S6`）：先 action_role 审核，再波次提交。`VIDEO_NOT_ALL_COMPLETED` 是正常等待：`sleep 240` 后再跑同一命令，最多连续等 30 分钟；仍未完成就结束本轮报 `WAITING_REMOTE`。
  其后 q1_derived（上一单元尾帧作起始帧）、post_gen_plot（用 `$T/review_fill/asr_units.py` 转写核对台词；同音字只记录）、video_q2。
  Q2 中 OCR 读出的低置信乱码（药柜标签、信纸手写）在 `observed_text_strings` 写 `NOISE:<文本>`；动作幅度/表情细节不算缺陷。
- **S7 装配**（`env -u GIGGLE_API_KEY $P $T/nalu_pipeline.py run --episode <EP> --from S7 --until S8`）：需要 `$NALU_RUNTIME_ROOT/brand/NALU_MOTION_endcard_3s_9x16.mp4`（没有就 `$P $S/make_endcard.py --runtime-root $NALU_RUNTIME_ROOT --title <剧名> --subtitle "第N集 · <集名>"`）。

## 5. 线主接受订单（只在线主原话同意后）
穿帮、身份、观众检测器等门禁失败而线主表示接受时，用：
```bash
$P $T/record_supervisor_order.py --owner-id <简报 owner_id，缺省 owner> --seq <下一个 seq> --order "<线主原话>" --episode <EP> \
  --gate-id <门禁 ID> --detector <…> [--media <item>=<文件>] --context "<事实>" \
  --orders $NALU_RUNTIME_ROOT/runtime/SUPERVISOR_ORDERS.json --recorded-by claude-code
```
- 关键帧（S5/S6 派生）：`--gate-id PERIOD-ANACHRONISM-LOCK --detector <shot_id>:PERIOD-ANACHRONISM-LOCK`（身份类用 `<shot_id>:<CHAR-ID>`）。
- 视频 Q2：`--gate-id VIDEO-Q2-ASSEMBLY-ADMISSION --detector <unit>:<每个失败门禁 ID> --media <unit>=<unit mp4>`。
- 成片观众检测器：`--gate-id FINAL-CUT-AUDIENCE-DETECTORS --detector <每个失败检测器> --media loudness=<成片> --media <检测器>=<成片>`；
  记好后把 `deliverables/<EP>/<EP>_final_9x16.mp4` 和 `workflow/nalu/<EP>/assembly/<EP>_NATIVE_AUDIO_LOUDNESS.json` 移到 `_superseded_*` 再跑 S7（成片编码确定，sha 不变）。
- 记完同步更新 `.env` 与 `qingshan.json` 的 latest_order_seq。

## 6. 每轮结束的固定格式（编排代理只读这一行）
本轮最后一行必须是：
`NALU_STATUS: {"episode":"<EP>","state":"<STATE>","stage":"<S?>","question":"<给线主的中文问题，没有则空>","credits_ledger":<账本数>,"final_mp4":"<路径或空>","note":"<一句话>"}`
STATE 取值：`OWNER_DECISION_REQUIRED`（需要线主原话）· `WAITING_REMOTE`（等云端渲染，编排代理稍后用「继续」恢复）·
`BLOCKED`（需要人修复的环境/代码问题，note 写清）· `FINAL_CUT_READY`（成片已在 deliverables，S7 停在独立终审或 S8）· `ERROR`。
被恢复时如果收到「继续」，就从 `runtime/pipeline_state/<EP>.json` 的当前阶段接着做。

## 7. 已知停点
S7 最后的「独立终审」要求独立进程、StoryClaw 白名单模型的审核者。没有时停在 `REVIEW_REQUIRED: FINAL_AUDIENCE_REVIEW_REQUIRED`——成片已在
`$NALU_RUNTIME_ROOT/deliverables/<EP>/<EP>_final_9x16.mp4`。不得冒充审核者身份或绕过该门，报 `FINAL_CUT_READY`。
