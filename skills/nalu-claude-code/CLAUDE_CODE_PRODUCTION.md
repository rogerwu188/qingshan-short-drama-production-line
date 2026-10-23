# NALU 生产合同（Claude Code 执行，无人值守）

你在一台无 GPU 的 Linux miniPC 上无人值守地执行 NALU 短剧生产线的一集（下文 `<EP>`，如 E01）。这台机器在机房里
连续产剧：编排代理会一集接一集地启动你，**没有人实时看**，所以凡是本合同给了默认处理的事都直接按默认做，不要停下来问。
OpenClaw 编排代理已经替你完成：引擎克隆与依赖安装、运行时根目录初始化与模板修复、Giggle key 写入
`$NALU_ENGINE_ROOT/.env`、原著选取与入库，并在本合同末尾的「附加说明」（派单）里给出原著路径、本集章节范围、
简报条款与版权声明。你负责其余全部：先写这一集的叙事正典与生产简报（§2.0），再把叙事正典转成可通过门禁的四层剧本，
并执行 S1→S7。线主（项目负责人）不在终端前，只通过编排代理和你对话。

## 0. 环境与位置
- `NALU_ENGINE_ROOT`（默认 ~/nalu_engine）、`NALU_RUNTIME_ROOT`（默认 ~/nalu_runtime）、`NALU_WORK_ROOT=$NALU_ENGINE_ROOT/workflow/nalu`。
- 解释器 `$NALU_ENGINE_ROOT/.qingshan-venv/bin/python`（下文 `$P`）；线工具 `lines/nalu/runtime/tools`（下文 `$T`）；
  本 skill 脚本 `skills/nalu-claude-code/scripts`（下文 `$S`）。命令都在 `$NALU_ENGINE_ROOT` 下执行。
- 输入：派单（原著 `$NALU_RUNTIME_ROOT/sources/<作品>/`、本集章节范围、简报条款、`rights_basis`）；你在 §2.0 写出的
  `workflow/claude_writer_agent/scripts/<EP>_NARRATIVE_CANONICAL_v1.md`（叙事正典，事实与逐字台词的唯一来源）和
  `$NALU_RUNTIME_ROOT/briefs/<EP>_PRODUCTION_BRIEF.json`（人物外貌/年龄/性别/服装、地点、画风、目标时长、预算与线主原话）。
- 免费命令一律不带 key：`env -u GIGGLE_API_KEY $P $T/nalu_pipeline.py run --episode <EP> --until <Sx>`。
- 跑 `nalu_pipeline.py` 时不要设 `NALU_POLICY_PROFILE` / `NALU_SERIES_SCOPE_ID`（本线解析为 LEGACY_EPISODE_COMPAT）。`$S/plan_compile.sh` 里的 `NALU_POLICY_PROFILE=CURRENT_PORTABLE` 只作用于它自己的编译子进程，不要抄进你的 shell。S1 报 `CANONICAL_WRITER_HANDOFF_FAIL:PRIVATE_PROJECT_METADATA_INVALID`（缺 `runtime/project.json`）= 你的环境带了 CURRENT_PORTABLE：`unset NALU_POLICY_PROFILE NALU_SERIES_SCOPE_ID` 后重跑；绝不要自己创建 `project.json` 或 `ACTIVE_WRITER_HANDOFF.json`，也不要单独调 `storyclaw_writer_workflow.py verify` 当作 S1 结论（那是 StoryClaw 托管项目的路径，不在本线 S1 上）。
- 付费命令只用一个入口：`./lines/nalu/runtime/tools/paid_stage.sh <EP> <FROM> <UNTIL>`（它自己读 `.env`；你不要 `cat`/打印 `.env`）。

## 1. 绝对规则
- 不写假 PASS；审核必须实际看图/看帧后作答（用 Read 打开图片；视频先用 ffmpeg 抽帧拼成联系表再看）。
- 默认条款（§3、§5）覆盖付费、版权、预算追加和质量接受；只有本合同明确写了「停下」的情况才结束本轮问线主（见 §6）。
  不编造线主原话：记录订单时用简报里的条款原文与线主原话，接受类订单写明依据的默认条款。
- 不删事务文件和回执（`workflow/tasks/**`、`reviews/**`），作废的东西移到 `_superseded_<日期>_<原因>/`。
- 不发布、不上传任何平台；不 git push；不改门禁阈值。
- **绝不修改引擎里受版本控制的任何文件**（`tools/`、`lines/`、`skills/`、`configs/` 下的代码、配置和测试），哪怕你确定那是
  上游缺陷、改了能跑通。遇到代码缺口：把复现命令、日志、文件与行号写进
  `workflow/nalu/<EP>/preproduction/reports/<EP>_CODE_BLOCKER_<日期>.md`，本轮以 `BLOCKED` 结束（note 写报告路径），
  由维护者修上游后发新版。心跳会检查引擎是否被改，改动会被存档并上报，下次换引擎时会被清掉——本机补丁不会留下来。
- 必须停下的只有：追加一次预算后仍不够（§3）、订单范围外的新付费类别（例如换装 i2i；背景音乐不算，见 §3）、Giggle key 缺失或失效。

## 2.0 编剧：叙事正典与生产简报（你写，免费；线主 2026-10-22）
编排代理只选原著、派单和汇报，**所有剧本层都由你写**（代理的聊天上下文装不下长稿）。本线是 LEGACY_EPISODE_COMPAT，直接写到下面的
位置，不跑 `storyclaw_writer_workflow.py begin/finalize`（那是 StoryClaw 私有项目的封缄路径，见 WRITER_CONTRACT.md `--writer codex`）。
1. 先读：`agent_factory/claude_writer_v2/templates/NARRATIVE_CANONICAL.template.md`、`agent_factory/storyclaw_portable/WRITER_CONTRACT.md`
   （来源与 manifest 规则）、H3 改编指南 `docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md`（有就读）、派单里的 `SOURCE_SELECTION.md`
   和本集章节（`sources/<作品>/<SOURCE_INDEX.json 的 canonical_reading_script>/chNNNN.md`）。只按原文改编，原文缺的不凭记忆补写。
2. `workflow/claude_writer_agent/scripts/<EP>_NARRATIVE_CANONICAL_v1.md`：只写事实、可表演的动作和**逐字台词**，按
   `## <EP>-S01｜<LOC-ID>｜<时间>｜线A` 分场；不写机位、灯光、资产。一集 2–4 场、20–60 秒为宜；台词决定时长（中文每 4 个汉字约 1 秒；
   英文约每秒 2.5 个词）。英文剧台词与旁白直接写英文；只有声音没有形象的旁白角色写成「旁白角色名：台词」，简报里照常列出、
   `appearance` 写「voice only」，登记为 `VOICE_ONLY_NO_PLATE`。没有人脸又不说话的可见存在（怪物、雕像、无五官人形）登记为
   `non_character_entities`（`kind: CREATURE`，`creature_card`，`note` 用英文一句话写清长相），不列成人物、也不当道具（H3 改编指南 §3）。E02 起开头承接上一集结尾状态，不重演上一集。
3. `$NALU_RUNTIME_ROOT/briefs/<EP>_PRODUCTION_BRIEF.json`：字段同编排代理 SKILL.md §4（episode/title/owner_id/style/target_seconds/
   budget_cap/genre/dialogue_language/genre_lang/synopsis/authorization/characters/locations/owner_words）。派单给出的 title、owner_id、
   style、genre、dialogue_language、budget_cap、`authorization`（含 `rights_basis` 原话）和 owner_words **逐字复制**；`synopsis`、
   `characters`、`locations` 由你按原著写。已出现的角色和地点逐字沿用原 ID 和设定，只追加新的。
4. `$P $S/apply_runtime_fixups.py --runtime-root $NALU_RUNTIME_ROOT --character <名>=<CHAR-ID>:<slug> ... --cap <预算> --language <dialogue_language>`，
   再 `$P $S/make_endcard.py --runtime-root $NALU_RUNTIME_ROOT --title <剧名> --subtitle "第N集 · <集名>" --language <dialogue_language>`
   （英文剧 `--subtitle "EPISODE 01 · <episode title>" --language en`）。
避开已知坑：首帧要看得见的道具别设计成「从怀里掏出」；古装灯写「无罩敞口油盏」；每个说话角色男女/音色要能区分；不写全黑画面。

## 2. 四层剧本（免费）
写 `lines/nalu/runtime/tools/build_<ep小写>_layers.py`（作品文本，.gitignore 已拦，不入库），由叙事正典和简报生成
`<EP>_DIRECTING_SCRIPT_v1.md`、`<EP>_GENERATION_CONTRACT_v1.json`（qingshan.generation_contract.v3）、`<EP>_manifest_v1.json`，
以及 `$NALU_RUNTIME_ROOT/preproduction/<EP>/{asset_requirements_overlay.json,new_location_place_spec.json,view_reference_policy.json}`。
然后 `run --until S3`，直到 S1 PASS、S2 PASS、S3 DRY_PLANNED。必须满足（门禁源码在 `$T` 与 `tools/`，报错就读源码改剧本，不改门禁）：
- 对白镜时长 = 汉字数/4 + 0.5，向上取整到 0.5，不再额外加长；无对白镜 ≤ 5 s；单元（同场连续镜头）4–8 s 可切分。
- 对白镜只比台词长 0.5–1.0 s（线主 2026-10-23）：`target_seconds` = 说话时长（中文约 4 字/秒，英文约 2.5 词/秒）+ 0.5–1.0 s，不给对白镜加长——H3 会用乱码般的假语言填满多出来的时间（CAMERA_GRAMMAR_V1 的集 S7 会剪在最后一句后约 0.5 s）；要停顿或反应就另写一个无对白的反应镜。
- 每镜 `prompt_spec.camera_plan` 全字段（shot_scale/camera_height/camera_side/motion_family/motion_direction/lens_intent/axis_relation/start_framing/end_framing/motivation）；
  LOCKED 起止取景相同、运动镜不同。
- **运镜语法 CAMERA_GRAMMAR_V1**（2026-10-22 起新封版的合同；storyclaw finalize 自动在合同顶层补
  `"camera_grammar_policy": "CAMERA_GRAMMAR_V1"`；之前已封版的集仍按旧规则）。新规则不加任何阻断门，只是导演写法：
  - 机位不再「必须动」，相邻单元也不必换方向（只保留原有的「相邻同族同向」不许）；静态设计门的 R1–R4/R6/R7 对这些集只提示（`advisories`）不阻断。
  - 运镜要有理由：跟人、揭示、强调或主观视角；没有理由就用 LOCKED 或慢推（DOLLY PUSH_IN），让动作在构图里发生，别为了「动」去扫空墙、让人出画再回。
  - 每个新地点前 2 镜给一个建立镜（WIDE / MEDIUM_WIDE）；同场同一景别连续不超过 2 镜（同机位对白接力除外）。
  - **对白不逐句切**（线主 2026-10-23）：一个单元仍只一个说话人，但 ① 两人来回的连续几句用同一个双人镜（两人都在画、
    camera_side/shot_scale/camera_height 不变），单元之间写 CONTINUOUS_ACTION，接上一单元尾帧，看着是一条镜头；
    ② 开场双人镜/中景，只在情绪转折切近到单人/近景，最狠一句给最紧的镜头，同一人连说留在同一镜，听者无声反应只在「反应就是戏」时才切；
    ③ L-cut：说话镜后紧跟的无对白反应镜（下一个单元）可写 `prompt_spec.transition.sound_bridge_from_previous_seconds`（0.3–2.0 s），
    S7 把说话人画面提前切走、这句话的声音和字幕盖到反应镜上，反应镜现场声压成环境声；不写就是硬切。
  - 剧本是「切」的地方就写切（`internal_transition_authoring` 用 MOTIVATED_CUT/REACTION_CUT/MATCH_CUT/HARD_CUT）：
    该单元会用自己的关键帧起幅，不从上一单元尾帧漂过去（每个切点多一张关键帧，约 11 积分）；连续动作写 CONTINUOUS_ACTION/CAMERA_REFRAME 接尾帧。
- H3 出视频的集按 `docs/knowledge/H3_SCRIPT_ADAPTATION_GUIDE.md` 改编剧本（每拍分桶、≤2 人、无脸存在登记为 CREATURE 并写长相、服装写成文字、对白同机位接力、转折才切）。
- `state_delta_dimensions` 只能取 POSITION/POSTURE/CONTACT/POSSESSION/INTEGRITY/MOMENTUM，且 entry/exit 证据要不同；entry/completion 各 ≥ 6 字。
  每个镜头都要有（S5 `keyframe_entry_state_gate` 对空维度无条件拒绝）。`state_delta_mode: STATIC_POSTURE_PERFORMANCE` 只给对白镜用；无对白的「静立 + 环境在动」揭示镜不能靠运镜过关，要让一个已登记主体（人物，或没有人物时的生物/道具卡）真的变一次：转头、跨一步、放下手里的东西。
- 每个 scene_state：`ambient_life{grade A|B|C, motion_trend, first_frame_state, reaction_progression}` 和 `weather_provenance{source_type, source_ref, visibility_mode}`。
- 同场相邻镜头都写 `internal_transition_authoring`（transition_mode ∈ CONTINUOUS_ACTION/CAMERA_REFRAME/PAN_REVEAL/OCCLUSION_REVEAL/MOTIVATED_CUT/REACTION_CUT/MATCH_CUT）。
- 对白镜 `action.performance{emotion(词表 PERFORMANCE_EMOTION_LEXICON_v1), body_action(非琐碎), delivery}`；同场同情绪不连续 3 次；`writer_selfcheck_seq29.enforced: true`。
- H3 线对白镜再写 `performance.delivery_en`（可选，一句英文：情绪 + 怎么说，如 `"cold and contemptuous, low and clipped, a beat of silence before the second sentence"`）；H3 不收中文，没有它只剩通用念白句，演出发机械。
  写法要具体到声音怎么走（线主 2026-10-22「再起伏大一点」）：哪个词重读、哪里音调扬起或压到近乎耳语、哪里突然提高音量、哪里停顿，如 `"low and slow at first, then snaps up loud and sharp on 'repeat it', last word bitten off"`；只写情绪词（cold / angry）起伏不够。
- 首帧可见角色默认必须露正脸；远小/背影在 `cast[].face_visibility` 写 `FAR_FIGURE_*` / `BACK_*`。入场文字里只写本镜 cast 里有的人。
- 道具名一旦出现在某镜文字里，该镜首帧就必须看得见。别设计「从怀里掏出来」这种首帧不可见的道具镜，尤其是承接上一单元尾帧的镜（会被派生起始帧审核卡死、重做也救不了）。
- 古装场景的灯写成「无罩敞口油盏」并把它声明为道具（`non_character_entities` + 镜头 props），否则图像模型画玻璃罩煤油灯，命中禁用词表。
- 没有人脸的可见存在（怪物、雕像、机器外壳、无五官的人形等）不进 `character_entities`：S3 身份锁定对每个人物身份牌都做 insightface 人脸测量，
  无脸的牌只会 `FACE_COUNT_ZERO`、永远锁不上。把它写成 `non_character_entities` 的生物/道具卡（镜头里作为 props 出现），这一类不测人脸。
  它若还要说话，另在 `character_entities` 留一行声音角色，`identity_source.mode = VOICE_ONLY_NO_PLATE`（不出身份牌，只建配音；E05 乌鸦先例）。
  只有声音、画面上没有形象的旁白同样用 `VOICE_ONLY_NO_PLATE`。
- 旁白（V.O.）照对白写：在镜头的 `prompt_spec.dialogue` 里写 `旁白角色名：台词`（英文剧也用全角冒号分隔），`audio_contract.dialogue_units`
  照常一行（speaker_id 写该 `VOICE_ONLY_NO_PLATE` 角色）；旁白角色不进 `cast`，`lip_owner_id` 留空。凡说话人是 `VOICE_ONLY_NO_PLATE`
  角色的台词，引擎自动当旁白处理（CURRENT_PORTABLE）：S2 把它移出视频对白（写进 `prompt_spec.voice_over`，视频模型不生成这句、不要身份牌），
  S4 用该角色锁定的配音逐句合成并做免费识别核对，S7 在原生成片上压低现场声、混入旁白并按实际时长上字幕。不要为旁白另设流程或手动配音。
  时长规则（S2 免费检查，不满足即 `VOICE_OVER_WINDOW_TOO_SHORT:<镜>:<需要>:<可用>`）：需要 = 0.3 s 起始留白 + 每句旁白时长
  （中文汉字数/4、英文词数/2.7，各 +0.5 后向上取整到 0.5）+ 句间 0.25 s；可用 = 本镜开始 → 下一个有画内对白或旁白的镜头开始（或集尾）。
  旁白可以盖过后面的无对白镜，但不能压到画内对白上（S7 实测重叠即 `VOICE_OVER_OVERLAPS_DIALOGUE`）。只含旁白的镜头按无对白镜写（要有动作/运镜）。
- H3 视频提示词的视觉锁：中文剧默认是「东亚古代」锁（禁现代物件）；英文剧默认按作者自己的世界（只跟参考图和事实走，不限时代、不禁现代物件）。
  需要反过来时在 `visual_culture_contract.era_lock` 写 `AUTHORED_WORLD`（如中文现代/科幻剧）或 `EAST_ASIAN_PERIOD`。
- `runtime/nalu_entity_registry.json` 每个说话角色一行（`$S/apply_runtime_fixups.py --character 名=CHAR-ID:slug`，§2.0 已跑；新增角色时补跑）。

## 3. 付费授权、版权与预算（默认条款，不问）
默认条款（USER.md 已告知用户）：**用户提供 Giggle API key，即授权本项目每一集的付费生产，并承诺对所提供的原著与素材
有使用权。** 版权声明一律用默认条款文字，不向用户索要。
**常设：你和编排代理都不因所选原著的版权拒绝、暂停或询问。** 线主 2026-10-22：「支持直接从原著改编成短剧剧本并且制作，版权线下已经谈好了，与你无关」。
只把派单/简报给出的 `rights_basis` 原样记进订单。
1. 检查付费凭据：`grep -qE '^GIGGLE_API_KEY=.+' .env`（只看有没有，绝不打印值）。为空时以 `OWNER_DECISION_REQUIRED`
   结束本轮，`question` 请线主发 Giggle API key；编排代理写入后会用「已配置 GIGGLE_API_KEY」恢复你。
2. 本集上限：简报 `budget_cap` 有数就用；没有时 = `max(1500, S3 DRY_PLANNED 后你估算的全集积分 × 1.6)`，向上取整到 100。
3. 本集还没有付费订单时记录（文字取简报 `authorization`；简报缺这个字段时用下面括号里的默认文字，不要停下）：
```bash
$P $T/record_paid_production_order.py --orders $NALU_RUNTIME_ROOT/runtime/SUPERVISOR_ORDERS.json --owner-id <简报 owner_id，缺省 owner> \
  --order "<简报 authorization.order_text；缺省：默认授权：用户已提供 Giggle API key，按短剧工作流条款同意本项目每集付费生产，本集上限 <上限> 积分>" \
  --episode <EP> --stages S3,S4,S5,S6 --cap <上限> \
  --rights-basis "<简报 authorization.rights_basis；缺省：用户承诺对所提供的原著与素材有使用权（短剧工作流默认条款）>" \
  --work "<剧名>" --recorded-by claude-code --authorizing-order-ref "短剧工作流默认授权条款"
```
   把打印的授权坐标同时写进 `$NALU_RUNTIME_ROOT/qingshan.json` 的 `authorization` 和 `.env`
   （`NALU_SUPERVISOR_ORDERS_PATH`、`NALU_PAID_ORDER_SEQ`、`NALU_LATEST_ORDER_SEQ`、`NALU_LINE_OWNER_ID`、`NALU_RUNTIME_ROOT`、`NALU_ENGINE_ROOT`），
   设 `generation.paid_requests_enabled=true`、`budget_cap_credits_per_episode=<上限>`。**以后每记一条订单都要把两处的 latest_order_seq 改成最新**，否则全部订单失效。
4. 预算将超上限时，按默认条款**自动追加一次**：新记一条订单，`--cap` = 原上限 × 1.5，`--order` 写「默认条款自动追加：本集预算由 X 追加到 Y」，
   同步两处坐标后继续。追加后仍不够才以 `OWNER_DECISION_REQUIRED` 停下。
5. 背景音乐默认开启（线主 2026-10-22「背景音乐开吧」），属默认条款、由本集 S3–S6 付费订单覆盖，不是新付费类别，不要停下问：
   合同 `audio_contract.bgm` 不写或写 `NO_BGM` 时，引擎按默认在最后一场末尾几镜配一段选择性配乐（S6 生成约 8 积分，S7 混音）；
   想自己定配乐节点就写 `{"mode":"SELECTIVE","cues":[...]}`；确实不要配乐才写 `"NONE"`。
5. 直接进入 S3，不等任何确认。

## 4. S3→S7（每次 exit=4 = 有审核请求）
审核通用做法：`$NALU_RUNTIME_ROOT/runtime/reviews/<EP>/` 最新 `*_request.json` → `$P $T/vlm_review_protocol.py example-answers --request <req>` →
看媒体、逐题作答（每题枚举值、观察 ≥ 20 字、FAIL 必须带 defect）→ `submit --request <req> --answers <ans>` → 再跑同一阶段。
- **S3 身份牌**（`paid_stage.sh <EP> S3 S3`）：拼缩略图看全部 plates。年龄/外形不符判 FAIL；重做 = 改 `$NALU_RUNTIME_ROOT/preproduction/<EP>/prompts/` 中该角色 3 个 txt 的措辞（指纹=提示词 sha），把旧图、`_raw`、回执移到 `_rejected_*`，重跑。
- **S4 配音**：`$S/list_voices.sh voices.json` 拉音色目录（免费 GET、不扣积分；供应商仍要鉴权，脚本内部自己读 `.env`，你不要直接跑 `storyclaw_audio_provider.py speech-voices`——无 key 会 exit=1，这不是阻塞），给每个说话角色挑 voice_id 写 `runtime/voice_catalog.json`（键=拼音 slug）。同场两人参考音 F0 必须差 ≥ 25%（男女搭配最稳；男声挑「沉稳/醇厚」类）。换音色：旧 registry 行移到 `superseded_rows`，旧参考音目录和 `workflow/tasks/giggle_audio_transactions/**/speech/<slug>.json` 移到 `_superseded`。
  - **选角规则（线主 2026-10-22，不是门禁）**：通读整个目录（约 170 条，字段 voice_id / voice_name / style / gender / age / language），每个角色拿 gender、age、style 标签去对角色的年龄、身份、性格和整部剧的调子，选标签最贴的一条；旁白/播报类角色可用播音腔，普通角色优先选与性格相符的演绎/戏剧类 style，不用播音腔。同场说话人要一听就分得开。每个角色在 `voice_catalog.json` 行里写一句 `casting_rationale`（voice_name + 标签 + 为什么）。参考音不用中性朗读：在该行加 `reference_sample{text=一句不在本集剧本里的校准句（如「天快黑了，我们还是趁早回去吧，路上小心一点。」/ "The evening is drawing in; we ought to head home before the weather turns."）, purpose:"VOICE_REFERENCE_ONLY", author, source_ref=该角色情绪最重的那场戏的镜头 id, speed 1.0–1.5, emotion=该角色最强烈的情绪}`；年龄标签按真实年龄用：「children」只给十岁以下，十二到十六岁的少年用同性别 youth 里偏年轻的声音（童声会把少年读成小孩甚至像女孩）；参考句绝不能是剧本台词（H3 会把参考音里的词串进别的单元，说出「像英文又不是英文」的乱码）：用一句剧本外的句子，按该角色情绪最外露、音调起伏最大的那场戏的情绪拉满读——H3 照参考音学语调，参考平，生成就平；CAMERA_GRAMMAR_V1 合同里 S4 遇到与本集台词相同的参考句会自动换成校准句并记录原因；情绪拉满后若音高明显超出该性别年龄（男孩读成女声），降一档情绪重读（speech-generate 的 `--emotion` 是自由字符串，如 angry / sad / fearful / disgusted / surprised / happy；文本须读 3–10 秒，太短就换一句更长的剧本外句子）。
- **视频模型是 MiniMax-H3**（线主 2026-10-13：一律 H3，不用 seedance；每集第一次 S2 构建时记在
  `$NALU_RUNTIME_ROOT/preproduction/<EP>/video_model.json`，之后固定）。H3 的视频提示词是英文，由每个单元的英文合同生成：
  S2 或规划编译报 `H3_ENGLISH_CONTRACT_REQUIRED:<n>_units:<请求文件>` 时，打开请求文件
  （`workflow/nalu/<EP>/preproduction/<EP>_H3_ENGLISH_CONTRACTS.REQUEST.json`），按其中 `instructions` 把每个单元的
  `source`（中文执行计划）忠实译成 `english`（形状不变、每个字段非空、不含任何汉字；人名用拼音；不增删事件；对白不进这些字段），
  写进同目录的 `<EP>_H3_ENGLISH_CONTRACTS.json`（`{"schema":"nalu.h3_english_contracts.v1","units":{<answer_key>:{"execution_semantics_sha256":<照抄>,"source_digest":<照抄>,"english":{…}}}}`，
  `answer_key`、两个摘要都从请求里照抄；保留已有条目，每个被请求的 answer_key 加一条），然后重跑同一阶段。中文源文没变、只是计划元数据变了时
  会自动复用旧译文；源文改了（重写剧本、改镜头）才会重新出现在请求里，重译即可。S6 定稿后（加上身份图、配音 URL）还会按定稿任务再核一次，
  可能再请求一次同样格式的翻译。
  H3 每个单元最多 9 张参考图、带对白的单元最长 10 秒且最多 2 句、一个单元只有一个说话人；配音参考走公网 URL（S4 已上传）。
- **S5 关键帧**：先过整批提示词门：`$S/prompt_batch_prepare.sh <EP>` → 通读 `workflow/nalu/<EP>/preproduction/planned_video_prompts/*.txt`、`prompts/keyframes/*.txt`、`reports/<EP>_PROMPT_BATCH_DIGEST.json` →
  写 `reports/<EP>_PROMPT_BATCH_ANSWERS.json`（`{"schema":"nalu.prompt_batch_answers.v1","reviewer":"claude-code","review_method":"CLAUDE_STRUCTURED_PROMPT_REVIEW","reviewed_at":…,"units":{"<UNIT>":{"verdict":"PASS","cross_unit_continuity_checked":true,"observation":"…"}}}`）→ `$S/prompt_batch_finish.sh <EP>`（必须 register PASS）→ `paid_stage.sh <EP> S5 S5`。
  之后有 keyframe Q1、start_frame 审核。改了剧本：重跑构建器 → `run --until S2` → prepare/finish → S5。被拒关键帧：把 `keyframes/<shot>-keyframe-v1.png` 和 `keyframe_harvest/_raw/<shot>*` 移走再跑。
- **S6 视频**（`paid_stage.sh <EP> S6 S6`）：先 action_role 审核，再波次提交（H3：每任务约 14 积分/秒 + 6 积分）。`VIDEO_NOT_ALL_COMPLETED` 是正常等待：`sleep 240` 后再跑同一命令，最多连续等 30 分钟；仍未完成就结束本轮报 `WAITING_REMOTE`。
- S6 预检报 `MISSING_ANCHOR_FOR_CANONICAL_ENTITY`（多人单元，常见于 E01）：多人关键帧只给一个角色当人物参考，其余角色需要自己的身份牌，而 E01 的身份牌不在锁定资产库里。用引擎支持的覆盖文件补：`$NALU_RUNTIME_ROOT/preproduction/<EP>/identity_reference_overrides.json` 写 `{"units": {"<unit_id>": [{"character_id": "CHAR-…", "path": "<该角色 S3 已过审的正脸身份牌绝对路径>", "role": "CHARACTER_IDENTITY_REFERENCE"}]}}`（只补缺锚的角色），再重跑 S6 编译与预检。这不是绕门，不写 CODE_BLOCKER。
  其后 q1_derived（上一单元尾帧作起始帧）、post_gen_plot（用 `$T/review_fill/asr_units.py` 转写核对台词；同音字只记录）、video_q2。
  Q2 中 OCR 读出的低置信乱码（背景招牌/标签纹理、道具上的手写字）在 `observed_text_strings` 写 `NOISE:<文本>`；动作幅度/表情细节不算缺陷。
- **S7 装配**（`env -u GIGGLE_API_KEY $P $T/nalu_pipeline.py run --episode <EP> --from S7 --until S8`）：需要 `$NALU_RUNTIME_ROOT/brand/NALU_MOTION_endcard_3s_9x16.mp4`（没有就 `$P $S/make_endcard.py --runtime-root $NALU_RUNTIME_ROOT --title <剧名> --subtitle "第N集 · <集名>" --language <简报 dialogue_language>`）。
  S7 自动加片头标题（简报 `title` + 集数，前 2.5 秒叠加，免费、不加时长）、默认配乐混音（S6 已生成并对账）和尾贴广告版（素材缺失只记 `AD_ASSET_MISSING`，不阻塞）。
  S7 报 `SELECTIVE_BGM_CREDIT_RECONCILIATION_NEEDS_KEY`（S6 时配乐账单还没出）：改用 `./lines/nalu/runtime/tools/paid_stage.sh <EP> S7 S7` 重跑 S7（S7 没有任何提交路径，key 只用于只读账单查询），不是新付费。

## 5. 质量不阻塞：默认接受（不问）
默认条款：**质量问题不阻塞连续生产。** 门禁 FAIL 时先按 §4 正常修复/受控重做；同一镜第 2 次创意重做仍失败，或失败无法靠重做解决
（例如派生起始帧、成片观众检测器、模型反复画出的穿帮），就直接记录接受订单并继续，不停下问：
```bash
$P $T/record_supervisor_order.py --owner-id <owner_id，缺省 owner> --seq <下一个 seq> \
  --order "默认条款自动接受：质量问题不阻塞连续生产（短剧工作流）" --episode <EP> \
  --gate-id <门禁 ID> --detector <…> [--media <item>=<文件>] --context "<失败事实：门禁、帧号/单元、原因、已重做次数>" \
  --orders $NALU_RUNTIME_ROOT/runtime/SUPERVISOR_ORDERS.json --recorded-by claude-code
```
- 关键帧（S5/S6 派生）：`--gate-id PERIOD-ANACHRONISM-LOCK --detector <shot_id>:PERIOD-ANACHRONISM-LOCK`（身份类用 `CHARACTER-IDENTITY-ADMISSION`、`<shot_id>:<CHAR-ID>`；给不出 `<CHAR-ID>` 的身份失败（无人物镜头出现未登记人物、人脸测不到而判 UNCERTAIN 等）用 `<shot_id>:CHARACTER-IDENTITY-ADMISSION`；
  动作/状态交接用 `ACTION-SHOT-DESIGN-AND-STATE-HANDOFF`、`<shot_id>:ACTION-SHOT-DESIGN-AND-STATE-HANDOFF`），`--media <shot_id>=<关键帧/尾帧>`。
  **一张图同时挂多个门禁**（派生起始帧常见：身份 + 动作/状态交接）：每个失败门禁各记一条订单，绑同一张图；少一个门禁就不会放行。
- 声线一致性（S6 `voice:VOICE_OUT_OF_BAND`、成片 `voice_distinctness` 的 VOICE_OUT_OF_BAND / VOICE_COLLISION）：受控重做一次仍失败就默认接受，不停线问人；
  `--context` 必须写说话人、时间段、实测 F0 与登记范围（引擎 AGENTS.md §4.9，线主 2026-10-22）。
- 起始帧语义证据（start_frame 审核 FAIL，例如上一单元尾帧里缺人、背身、缺道具）：
  `--gate-id START-FRAME-SEMANTIC-EVIDENCE --media <unit_id>=<起始帧图>`，并对证据回执 `blockers` 里的**每一项**加
  `--detector <unit_id>:<blocker>`（列表型拆开写：`<unit_id>:REQUIRED_CHARACTER_NOT_OBSERVED:<人名>`、
  `<unit_id>:REQUIRED_PROP_NOT_OBSERVED:<道具名>`）；然后重跑 `start_frame_evidence_writer.py write` 与 S6。
  回执里的观察照实写（没看到的人不写成看到）；`KEYFRAME_MISSING` / `KEYFRAME_CHANGED_SINCE_REVIEW` 不能接受，要重新出图或重审。
- 动作归属证据（S6 action_role 审核 FAIL，例如起始帧里看不到动作的发起人/道具）：同样做法，`--gate-id ACTION-ROLE-EVIDENCE
  --media <unit_id>=<起始帧图>`，回执 `blockers` 每一项加 `--detector <unit_id>:<blocker>`；然后重跑
  `action_role_evidence_writer.py write --review <已提交的审核>` 与 S6。`CONTRACT_INITIATOR_OR_TARGET_UNDECLARED` 是剧本层缺口，不能接受，改剧本。
- **视频 Q2 的「观众一眼可见」失败先重做一次再接受**（线主 2026-10-22，Twelve Gazes E01：10/12 单元 Q2 REJECT 一次没重做全部接受，
  成片出现多余人形、主角换装、结尾冒出真人手）。Q2 失败项含 `cast_exactly_as_declared`、`each_visible_character_identity_recognisable`、
  `wardrobe_matches_bible`、`no_extra_scene_or_replayed_beat`、`creature_locomotion_matches_card`、`visible_group_count_matches_declared`
  之一的单元，**「起始帧继承缺口」不是跳过重做的理由**：按 §4 受控创意重做该单元一次（镜头文字写明要去掉的东西：多余人物、错穿的服装、
  不该出现的手/人），重做仍失败再按下面默认接受。只有预算不够（`paid_stage.sh <EP> --check` 投影超本集上限）才跳过，`--context` 写「预算不足未重做」。
  多个单元要重做时按观众影响排序：开场前 10 秒 > 有台词/主角正脸 > 结尾 > 其余；预算用到上限为止。其余 Q2 失败项（构图、道具数量、动作细节）照旧直接接受。
- 视频 Q2：`--gate-id VIDEO-Q2-ASSEMBLY-ADMISSION --detector <unit>:<每个失败门禁 ID> --media <unit>=<unit mp4>`；
  6 镜左右的短集任何 P2 都会超 10% 缺陷预算：同时写 `$NALU_RUNTIME_ROOT/preproduction/<EP>/qa_overrides.json` 的
  `defect_tolerance_minor_budget_override`（只列失败码，`authorized_by` 写「短剧工作流默认条款：质量不阻塞」）。
- 成片观众检测器：`--gate-id FINAL-CUT-AUDIENCE-DETECTORS --detector <每个失败检测器> --media loudness=<成片> --media <检测器>=<成片>`；
  记好后把 `deliverables/<EP>/<EP>_final_9x16.mp4` 和 `workflow/nalu/<EP>/assembly/<EP>_NATIVE_AUDIO_LOUDNESS.json` 移到 `_superseded_*` 再跑 S7（成片编码确定，sha 不变）。
- 每条接受都要在 `NALU_STATUS.note` 里列一句（门禁 + 单元），编排代理会汇总给用户。记完同步更新 `.env` 与 `qingshan.json` 的 latest_order_seq。
- 审核答案仍必须如实（看到穿帮就判 FAIL）；默认接受只改变「失败后停不停」，不改变「怎么判」。

## 6. 每轮结束的固定格式（编排代理只读这一行）
本轮最后一行必须是：
`NALU_STATUS: {"episode":"<EP>","state":"<STATE>","stage":"<S?>","question":"<给线主的中文问题，没有则空>","credits_ledger":<账本数>,"final_mp4":"<路径或空>","note":"<一句话>"}`
STATE 取值：`OWNER_DECISION_REQUIRED`（需要线主原话）· `WAITING_REMOTE`（等云端渲染，编排代理稍后用「继续」恢复）·
`BLOCKED`（需要人修复的环境/代码问题，note 写清）· `FINAL_CUT_READY`（成片已在 deliverables，S7 停在独立终审或 S8）· `ERROR`。
被恢复时如果收到「继续」，就从 `runtime/pipeline_state/<EP>.json` 的当前阶段接着做。

## 7. 已知停点
S7 最后的「独立终审」要求独立进程、StoryClaw 白名单模型的审核者。没有时停在 `REVIEW_REQUIRED: FINAL_AUDIENCE_REVIEW_REQUIRED`——成片已在
`$NALU_RUNTIME_ROOT/deliverables/<EP>/<EP>_final_9x16.mp4`。不得冒充审核者身份或绕过该门，报 `FINAL_CUT_READY`。

## 8. 连续产剧：E02 及以后
编排代理在上一集 `FINAL_CUT_READY` 后为下一集派单（章节范围与沿用的简报条款），再新开一个你的会话。每集都是独立会话，按本合同从 §2.0 开始，另外：
- 叙事正典开头承接上一集结尾状态；读上一集的 `<EP-1>_GENERATION_CONTRACT_v1.json` 末镜 `completion_state`，本集首镜 `entry_state` 与之一致。
- 角色沿用：已出现的角色用**同一个** `character_id` / 名字 / 服装文字（逐字复制上一集合同里的 `character_entities` 行与 `wardrobe_garments`），
  只给新角色起新 ID。复用角色的身份牌与配音在 `runtime/asset_library.json`、`runtime/voice_registry.json` 里是 LOCKED，S3/S4 会自动跳过，不要重做。
- 地点沿用：已有地点用同一个 `location_id`；只有新地点写进本集 `new_location_place_spec.json`。S2 会以上一集的空间图为底自动扩展。
- `asset_requirements_overlay.json` 只写本集新角色/新地点/新道具；新说话角色先补 `apply_runtime_fixups.py --character` 和 `voice_catalog.json`，
  音色要与已有角色区分（同场 F0 差 ≥ 25%）。
- 构建器写成 `build_<ep小写>_layers.py`，可以复制上一集的构建器改数据块，但每集的镜头、台词必须来自本集叙事正典。
- 预算按 §3 每集单独记订单；默认接受按 §5。本集完成后报 `FINAL_CUT_READY`，编排代理负责发行和启动下一集。

