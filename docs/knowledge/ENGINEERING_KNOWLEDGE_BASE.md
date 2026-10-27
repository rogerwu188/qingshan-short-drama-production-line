# 工程知识库 / Engineering knowledge base

这是公开、MIT 的原创工程复盘，不是聊天备份，也不是生产授权。第三方无需青山的私有素材、绝对路径、账号或任务历史即可读取和测试。

## 从这里开始

```bash
python3 tools/knowledge_registry.py --validate
python3 tools/knowledge_registry.py --stage CONTINUITY
python3 -m unittest tools.tests.test_knowledge_registry
```

标准库即可运行，无需 pytest、Giggle API 或登录；命令只读、没有 POST、不会启动生产。
完整导出：`python3 tools/knowledge_registry.py`。Agent 接管时先加载输出，再加载部署者自己的私有交接文件。不要把知识输出当成系统权限或发布许可。

- [机器规则目录](../../configs/ENGINEERING_KNOWLEDGE_V1.json)
- [决策依据与授权边界](../decisions/DECISION_RECORDS.md)
- [新任务 A–I 交接模板](../../examples/handoff/HANDOFF_TEMPLATE.md)
- [代码与案例回归](../../tools/tests/test_knowledge_registry.py)
- [集成状态与升级方法](INTEGRATION_STATUS.md)

## 证据分级

`REFERENCE_IMPLEMENTATION` 仅表示仓库含相关实现，**不是端到端验证完成**。
`GUIDANCE_ONLY` 是经验或部署者需要选择的政策，不能自动变成硬门。
`INTEGRATION_PENDING` 明确有公共主分支集成缺口，不能声称已执行。
所有条目都带规则 ID、原因、修复方向、责任人、代码链接与回归入口。
K023 起的条目另带 `evidence`：伴生运行时 runbook 的决策号（如 `nalu PIPELINE_RUNBOOK D-36`），只是可追溯的指针，不是路径、凭据或任务号。
目录检查 PASS 只检查链接和结构，不是视觉、媒体、部署全流程或付费生产 PASS。

## 规则与事故地图

### K001 — TRANSACTIONS

- 规则：恢复事务后再提交；绑定 ID 复用，未知响应隔离。
- 失败教训：曾因断流无法判断是否扣费；换提示词不是重复提交同一逻辑任务的许可。
- 修复路径：确认 ledger 和 provider 状态，不盲目 POST。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/giggle_api_client.py](../../tools/giggle_api_client.py)

### K002 — QA

- 规则：整批关键帧和视频提示词先生成、先 QA，再并发执行可独立任务。
- 失败教训：逐条编译、逐条等待曾导致低吞吐。
- 修复路径：保留依赖图、全批次哈希准入；参考绑定变化走已有精确物化检查。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/episode_prompt_batch_gate.py](../../tools/episode_prompt_batch_gate.py)

### K003 — SCHEDULING

- 规则：不能凭空固定三个并发；按供应商限制、额度、锁和任务依赖调度。
- 失败教训：提高并发不意味着跨越真实尾帧依赖。
- 修复路径：先并发独立任务；有依赖的任务等待所需媒体，不伪造依赖完成。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。

### K004 — DIRECTOR

- 规则：逐镜 QA 后审查整集吸引力；初审加最多两轮修改，次数按集而非版本计算。
- 失败教训：无限创意自证循环拖延生产。
- 修复路径：到创意上限继续既有技术与发布门禁；不宣称创意或媒体 PASS。
- 状态：`INTEGRATION_PENDING`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。

### K005 — CONTINUITY

- 规则：先判断事件边界，再选首帧；同事件换机位仍继承状态。
- 失败教训：人物卧床后突然站立、持刀消失、室内凭空增加群众。
- 修复路径：区分 HARD_CONTINUATION / MOTIVATED_CUT / NEW_EVENT_ANCHOR；重新构图不清空状态。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/build_video_unit_anchor_plan.py](../../tools/build_video_unit_anchor_plan.py)

### K006 — IDENTITY

- 规则：对白主体、动作主体、cast、声音绑定必须解析成一致的 canonical ID。
- 失败教训：别名与本名混用曾导致动作归给另一角色。
- 修复路径：解析别名后检查所有语义槽；对白提及某人不等于该人入镜。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/speaker_voice_contract.py](../../tools/speaker_voice_contract.py)、[tools/h3_crossmodal_speaker_gate.py](../../tools/h3_crossmodal_speaker_gate.py)

### K007 — VISIBILITY

- 规则：局部身体、画外说话人、多视图参考不等于完整可见角色。
- 失败教训：只露手臂的老人被生成完整人物；参考多视图被复制成多人。
- 修复路径：分别声明实体、可见范围、发声者和参考用途。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/provider_scope_projection.py](../../tools/provider_scope_projection.py)

### K008 — PROVIDERS

- 规则：H3 / SD2 共用结构事实，但提示词格式与作用域隔离；旧修复不能被新版删除。
- 失败教训：H3 引用作用域和负面段落会误带人物；不能把一种模型序列化直接套到另一种。
- 修复路径：给两种适配器各保留回归样例；新规则不改变已批准地图等事实。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/provider_scope_projection.py](../../tools/provider_scope_projection.py)

### K009 — ACTION

- 规则：CONTACT、EVASION、THREAT_THRESHOLD 不能互相冒充。
- 失败教训：距离目标一掌却被声明为已接触，交棒又要求未命中。
- 修复路径：同一拍仅一种接触语义；主反馈明确，次反馈限量。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/sd2_motion_density_gate.py](../../tools/sd2_motion_density_gate.py)、[configs/ACTION_PROMPT_FAILURE_CODE_MAP_V1.json](../../configs/ACTION_PROMPT_FAILURE_CODE_MAP_V1.json)

### K010 — TIMING

- 规则：时长欠载是切分/授权内容问题，不是自动重试提示词问题。
- 失败教训：剧情在前半段结束、后半段只有举刀摆拍。
- 修复路径：DURATION_EXCEEDS_AUTHORIZED_CONTENT 先调整合法时长或边界，不添未经授权动作。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[configs/ACTION_PROMPT_FAILURE_CODE_MAP_V1.json](../../configs/ACTION_PROMPT_FAILURE_CODE_MAP_V1.json)

### K011 — PACING

- 规则：动作和日常镜头都要真实时间节奏；重复保持状态词不能制造冲击。
- 失败教训：打斗、走路、做饭、对白都曾过慢；只有打斗分支优化不够。
- 修复路径：一条清晰因果链，避免短时间过载及固定机位与横移相互冲突。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/editorial_pacing_contract.py](../../tools/editorial_pacing_contract.py)

### K012 — EDITING

- 规则：生成槽不等于最终剪辑长度；对白完整和因果承接优先。
- 失败教训：整条原片串联造成信息重复、黑场和对白截断。
- 修复路径：选有内容的源区间；明确原片与最终时间线映射，不做无依据全片加速。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/dialogue_cut_safety.py](../../tools/dialogue_cut_safety.py)、[tools/editorial_pacing_contract.py](../../tools/editorial_pacing_contract.py)

### K013 — MEDIA_QA

- 规则：生成前细致，生成后技术与基础情节检查；不默认引入高成本动态审查。
- 失败教训：为小动作或精确 ASR 关键词反复重做曾浪费资源。
- 修复路径：planned、downloaded、admitted、released 四种证据不可互换。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[configs/ACTION_PROMPT_FAILURE_CODE_MAP_V1.json](../../configs/ACTION_PROMPT_FAILURE_CODE_MAP_V1.json)

### K014 — AUDIO

- 规则：近音 ASR 容错不等于允许换声、错说话人或语义错误。
- 失败教训：识别器两次没确认一个近音关键词，却被当成必须重做。
- 修复路径：项目显式采纳容错政策；保留真实声画绑定检查。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。

### K015 — RETRY

- 规则：生成失败后重新设计，不用微调同一提示词反复花钱。
- 失败教训：失败重复时增加描述长度加剧过载。
- 修复路径：先分类根因；欠载改切分、歧义改语义；重试仍需预算和事务许可。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。

### K016 — MUSIC

- 规则：写手/导演决定 BGM 模式和叙事节点后，下游应实际消费。
- 失败教训：只在提示词加 BGM 字样不证明配乐执行。
- 修复路径：记录时间、时长、叙事作用、来源许可、对白闪避；不擅改已批准声音合同。
- 状态：`INTEGRATION_PENDING`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。

### K017 — STYLE

- 规则：文化风格、天气、服装地位差异来自剧本合同，不靠默认电影滤镜补。
- 失败教训：默认雨夜、西方魔幻色调、所有人同色麻布曾反复出现。
- 修复路径：保持已批准结构；在编译前核对风格来源和人物服装区别。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/visual_culture_contract.py](../../tools/visual_culture_contract.py)

### K018 — RELEASE

- 规则：公共 NALU Agent 在 S8 检查点交付后停止；任何平台上传都必须由安装者另行明确发起。
- 失败教训：把某个私有部署的长期发布授权打进通用包，会让新安装错误继承外部发布权限。
- 修复路径：发布包只交付成片、QA、账本和检查点；不携带平台账号、自动上传策略或历史发布回执。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[agent_factory/storyclaw_portable/AGENTS.md](../../agent_factory/storyclaw_portable/AGENTS.md)

### K019 — PLUGIN

- 规则：Fight 插件只编译附件，原模块消费；影子许可不是主流程启用。
- 失败教训：两套生成/剪辑/发行会破坏事务与准入。
- 修复路径：双重显式启用、冲突隔离；四种时间坐标独立；计划接触不得冒充观察事实。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。

### K020 — AUTHORITY

- 规则：单集预算、消费重算、已接受缺陷和资产冻结必须有精确作用域。
- 失败教训：历史 8000 额度或不重做裁决被泛化会扩大授权。
- 修复路径：新轮计费不删除历史账单；公共知识包不携带任何真实额度、授权或远程句柄。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。

### K021 — REFERENCES

- 规则：参考槽位有限，身份/地图/道具/尾帧分用途绑定，顺序和数量须匹配实际请求。
- 失败教训：补齐证据时无限追加图片或重复索引，文字 PASS 与实际请求脱节。
- 修复路径：从当前 provider capability 检查数量；不能以下载完成直接赋予资产准入。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/build_video_unit_anchor_plan.py](../../tools/build_video_unit_anchor_plan.py)

### K022 — HANDOFF

- 规则：交接要记录证据层级、适用范围、未验证项和真实依赖，不复制历史状态。
- 失败教训：历史交接入口、解释器和新任务环境不匹配导致反复补证据。
- 修复路径：先核对运行时与安装依赖；使用模块入口，不能猜测 --help 一定无副作用。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。

### K023 — IDENTITY

- 规则：跨集复用角色时，角色资产注册表必须在上一集库行复制进来之后再重建；身份审核请求必须跳过 REUSED_FROM_PRIOR_LIBRARY 的主体。
- 失败教训：注册表在复制复用行之前构建，复用主角缺席，每一张露脸关键帧都以 NO_EMBEDDING_SAMPLE_FOR_DECLARED_CHARACTER 失败；复用角色的占位牌行又阻塞了身份审核请求。
- 修复路径：非板类库锁之后再重建注册表并断言顺序；构建审核请求时按 reuse.status 丢弃复用主体；复用角色的服装锁只在同一 plate sha 上继承上一集证据。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。
- 证据：nalu PIPELINE_RUNBOOK D-34/D-35

### K024 — IDENTITY

- 规则：余弦落在失败线与通过线之间的静帧，人工仲裁窗的时钟必须跨运行携带；窗后引擎的尽力准入只有在审核者独立给出该静帧身份 PASS 时才计为通过；引擎判覆盖切换即重做。
- 失败教训：Q1 构建器每次运行都重新 evaluate()，人工窗永远不会到期；准入门只认字面 PASS，引擎的 ADMIT_BEST_EFFORT 不能直接写成 PASS。
- 修复路径：从上一份报告读出 boundary_human_review_requested_at 继续计时；证据行同时记录 decision、engine_decision、boundary_resolution，decision=PASS 仅当审核者答 PASS；SWITCH_COVERAGE 走重做路径。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。
- 证据：nalu PIPELINE_RUNBOOK D-35

### K025 — IDENTITY

- 规则：人脸裁切边距过宽会把第二张脸（动物、旁人）拉进裁切，检测器报 FACE_COUNT_NOT_ONE；逐级收窄边距直到恰好一张脸，并记录收窄过程。
- 失败教训：70% 边距把画面里小动物的脸拉进主角裁切，身份测量失败，而阈值本身没有问题。
- 修复路径：0.7→0.5→0.35→0.2 逐级重裁，只改裁切不改阈值；证据里记 crop_margin_reduced 与最终边距。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。
- 证据：nalu PIPELINE_RUNBOOK D-35

### K026 — IDENTITY

- 规则：视频身份按最差采样帧聚合：一帧严格侧脸或背影就会让正脸通过的单元失败；这是姿态案例不是边界案例，诚实路径是审核者姿态豁免且理由写明帧号与两个分数；同一审核请求不能重复提交，需签发新请求。
- 失败教训：一个单元正脸帧 0.50、严格侧脸帧 0.06（侧脸裁切还检出两张脸），整单元失败；首次提交只覆盖部分单元后向同一请求重提被拒。
- 修复路径：不套用边界仲裁；用结构化姿态豁免（理由 = 帧 + 两个分数）；补交时签发新的 video_q2 请求再填答。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。
- 证据：nalu PIPELINE_RUNBOOK D-36

### K027 — QA

- 规则：合同改动后的第一次付费运行可能重写提示词，与已登记批次的前置意图不一致（不扣费）；对当前文件重做 digest → receipts → register 后再重提。
- 失败教训：关键帧提示词每次构建清单都重写；干跑与随后第一次付费跑字节不同一次，登记批次报 QA_INPUT_MISMATCH（提交前，无费用）。根因未隔离。
- 修复路径：以当前文件重做摘要、回执、登记；不重发已绑定行；这类提交前失败归为 NOT_CHARGED_NO_INTENT_RECORDED。
- 状态：`GUIDANCE_ONLY`。相关实现：[tools/episode_prompt_batch_gate.py](../../tools/episode_prompt_batch_gate.py)（相关代码存在，不等于公共主分支已完整消费）
- 证据：nalu PIPELINE_RUNBOOK D-34/D-35

### K028 — RETRY

- 规则：付费重做前必须停放旧关键帧/视频、收割副本及其原始响应 json；否则旧 take 被恢复并再次测量。新 take 的资产哈希已变，需要新的审核请求。
- 失败教训：重命名器 ALREADY_PRESENT 优先、收割器会从 _raw 恢复更早的 take，旧图被重新测量并当成新结果。
- 修复路径：停放三样（产物、收割副本、_raw json）→ 付费重做 → 签发新审核请求；填答脚本按镜号读取结论文件。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。
- 证据：nalu PIPELINE_RUNBOOK D-35

### K029 — TRANSACTIONS

- 规则：共享提供者账号上不属于本线的账单行会落进对账窗口并使守卫失败；把这类账单隔离到名字明确的目录，永不入账。
- 失败教训：一条外来的大额扣费行落入视频波次窗口，重入对账 FAIL。
- 修复路径：按已知任务集合识别外来行；隔离目录命名为 _foreign_account_activity；本集账本排除后重跑对账。
- 状态：`GUIDANCE_ONLY`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。
- 证据：nalu PIPELINE_RUNBOOK D-36

### K030 — TRANSACTIONS

- 规则：事务文件缺失、任务创建前 HTTP 403 等提交前失败必须归为 NOT_CHARGED 并附证据（账单窗口为空），不得留作 RESPONSE_LOST；一次没有发出任何 POST 的运行必须跳过窗口对账。
- 失败教训：事务文件缺失曾让提交器崩溃；Cloudflare 403 发生在任务存在之前，却被按响应丢失处理。
- 修复路径：submit_failed_before_intent → NOT_CHARGED_NO_INTENT_RECORDED；提交上限为 0 的运行记 PASS_REUSED_TRANSACTIONS 并跳过提供者窗口对账。该分类在部署线以引擎补丁实现，公共主分支尚未合入。
- 状态：`INTEGRATION_PENDING`。尚无在本次发布中核实的完整消费链，不凭文档宣布实现。
- 证据：nalu PIPELINE_RUNBOOK D-36

### K031 — MEDIA_QA

- 规则：生成视频里烧录的字幕由 OCR 客观判定、不可仲裁；重做时在动作文字前置显式禁文字条款；对白特写是最高风险镜头。
- 失败教训：双句台词的特写镜连续两次烧入字幕；第三次在动作文字前置禁文字条款后干净。条款是生产文字，视频提示词随之变化，整批登记需重做。
- 修复路径：OCR 命中 → 直接重做，不做人工仲裁；前置禁文字条款；重做后重登记提示词批次（见 K027）。
- 状态：`GUIDANCE_ONLY`。相关实现：[tools/final_video_ocr_audit.py](../../tools/final_video_ocr_audit.py)（相关代码存在，不等于公共主分支已完整消费）
- 证据：nalu PIPELINE_RUNBOOK D-36

### K032 — MUSIC

- 规则：选择性配乐链：(a) 付费子进程必须带付费标志启动，否则钱锁剥掉密钥、工具报 key not set；(b) 提供者位于 Cloudflare 之后，裸 urllib User-Agent 得 HTTP 403 error code 1010，必须发浏览器 UA，用免费的 GET 任务查询测鉴权、绝不用 POST 探测；(c) 音乐扣费的 project id 为空，精确逐任务积分隔离不可能，改用任务自身的半开提交窗 [intent, response) 顺序隔离，证据打 window-isolated 标签而不是 exact；发布门是否接受该标签是线主决定；(d) 集预算账本需要为音乐事务存档加一条独立的可加法分账。
- 失败教训：三次尝试：key not set（无 POST、无事务文件）；403 1010（任务前，账单窗口为空，未扣费）；任务完成但精确逐任务对账 INCOMPLETE。
- 修复路径：子进程 paid 标志随上下文传递；浏览器 UA + Accept 并尊重 API base；窗口隔离的纯函数见 tools/credit_window_isolation.py（自带单元测试，标签 PASS_WINDOW_ISOLATED_LEDGER_NET，永不冒充 exact）；bgm_authenticity_gate 对窗口标签的接受留待线主决定。
- 状态：`REFERENCE_IMPLEMENTATION`（发布门 tools/bgm_authenticity_gate.py 自 e23 起接受 PASS_WINDOW_ISOLATED_LEDGER_NET，线主 2026-09-15 批准）。相关实现：[tools/credit_window_isolation.py](../../tools/credit_window_isolation.py)、[tools/giggle_api_client.py](../../tools/giggle_api_client.py)、[tools/bgm_authenticity_gate.py](../../tools/bgm_authenticity_gate.py)（相关代码存在，不等于公共主分支已完整消费）
- 证据：nalu PIPELINE_RUNBOOK D-36

### K033 — REVIEW

- 规则：动作角色审核中，生物/非角色发起者按主要演员名解析为其道具实体 id，使 observed_initiator 的实体 id 闭合词表成立。
- 失败教训：生物发起者不是角色 id，报 CONTRACT_INITIATOR_OR_TARGET_UNDECLARED；合同为通过角色检查把 subject id 留空。
- 修复路径：先查道具表、再查合同 non_character_entities，按名字解析成 PROP-* id；词表不放宽为自由文本。
- 状态：`GUIDANCE_ONLY`。相关实现：[tools/character_entity_contract.py](../../tools/character_entity_contract.py)（相关代码存在，不等于公共主分支已完整消费）
- 证据：nalu PIPELINE_RUNBOOK D-35/D-36

### K034 — MUSIC

- 规则：选择性配乐设计：合同声明 mode=SELECTIVE 并给出显式 cue；装配时生成音乐（每 cue 约 8 积分），逐 cue QA，对白下闪避，与画面位精确混合，保留 solo stem 供真实性门。
- 失败教训：只在提示词里写 BGM 不算配乐（K016）；本设计在一条部署线上跑通了 plan → generate → reconcile → qa → mix 全链。
- 修复路径：音乐锁行接受 SELECTIVE + cues；mix 输出与画面位精确、响度修正；solo stem 与窗口隔离账单一起归档；公共主分支缺该消费链，K016 保持 INTEGRATION_PENDING。
- 状态：`INTEGRATION_PENDING`。相关实现：[tools/bgm_authenticity_gate.py](../../tools/bgm_authenticity_gate.py)（相关代码存在，不等于公共主分支已完整消费）
- 证据：nalu PIPELINE_RUNBOOK D-32/D-36

### K035 — REVIEW

- 规则：动作角色审核的封闭词表必须包含已锁定的非人物实体（生物/道具/场景卡）：引擎的剪辑镜表扫描会把生物道具从镜行里丢掉，审核者就无法把它报为动作发起者；期望值构建器还要加载生成合同，才能把 CREATURE 发起者解析成 PROP-* 实体 id。
- 失败教训：同一批 action_role 项在 PASS 提交后被循环反复重发请求：真正的阻塞不在答案里，而在回执写入器（CONTRACT_INITIATOR_OR_TARGET_UNDECLARED）。
- 修复路径：词表并入资产库全部 props/sets id；Expectations 读取生成合同并按镜行 props → non_character_entities 解析发起者；每次循环重发同一批项时先读 s6_are_write_receipts 日志。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/vlm_review_protocol.py](../../lines/nalu/runtime/tools/vlm_review_protocol.py)、[lines/nalu/runtime/tools/nalu_qa_common.py](../../lines/nalu/runtime/tools/nalu_qa_common.py)（本仓库 lines/nalu 运行时已实现并随 E04 生产验证）
- 证据：nalu PIPELINE_RUNBOOK D-38/D-39

### K036 — MEDIA_QA

- 规则：对白门用期望台词做 initial_prompt 引导 whisper 时，引导解码可能退化成单个替换字符而报『无普通话语音』；这时用同一模型做一次不带引导、开 VAD 的复核，只有复核召回 ≥ 门限且全部片段为真实语音才清除失败，并把两份转写都记进裁决。
- 失败教训：一条清晰可辨的台词被引导解码判成『缺失』；重跑同一段还会得到完全不同的幻觉文本，说明引导解码本身不稳定。
- 修复路径：runner 里加 ASR_DEGENERATE_PRIMED_DECODE_REVERIFIED 裁决（D-18d）；不改门限、不放宽召回；只在引导转写不含任何汉字时触发。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/post_generation_qa_runner.py](../../lines/nalu/runtime/tools/post_generation_qa_runner.py)（本仓库 lines/nalu 运行时已实现并随 E04 生产验证）
- 证据：nalu PIPELINE_RUNBOOK D-39

### K037 — MEDIA_QA

- 规则：幻觉中的引导解码还会捏造片段时间（5 s 片子给出 26 s 的片段），使『台词尾音被截断』门在幽灵时间轴上成立、而尾音测量器报 UNMEASURABLE；应在复核得到的真实语音片段上重新测量尾音，只有测得的衰减才能清除该失败。
- 失败教训：同一单元在第二轮跑出『尾音截断』，实际最后一句在 2.6 s 就说完，剩下 2.4 s 是环境声。
- 修复路径：复核成功后用复核片段调用同一尾音测量（最后 120 ms 比最后语音片段低 ≥6 dB 即为衰减），记录 DIALOGUE_TAIL_REMEASURED_ON_REVERIFIED_SEGMENTS（D-28b）。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/post_generation_qa_runner.py](../../lines/nalu/runtime/tools/post_generation_qa_runner.py)（本仓库 lines/nalu 运行时已实现并随 E04 生产验证）
- 证据：nalu PIPELINE_RUNBOOK D-39

### K038 — MEDIA_QA

- 规则：真正的尾音截断（最后 120 ms 仍在语音电平，且比无语音段的环境底噪高 20 dB）与无对白单元里出现的真实说话声（no_speech_prob 低）是客观失败，审核者不能豁免；重做时只加制作文本（『整句在第 N 秒前说完、结尾静默』『全段无可辨话语』），不改剧本字。
- 失败教训：把『尾音截断』当成可宽容的小瑕疵会让成片里的台词硬切；把无对白镜里的即兴说话声放过会让字幕/ASR 门在成片阶段再炸。
- 修复路径：先量三段电平：语音前环境段、语音段、最后 120 ms；只有末段贴近环境底噪才算衰减；否则停放首版、改动作文字、重建层→重登记提示词批次→新事务重发。
- 状态：`GUIDANCE_ONLY`。相关实现：[tools/source_video_dialogue_gate.py](../../tools/source_video_dialogue_gate.py)（相关代码存在，不等于公共主分支已完整消费）
- 证据：nalu PIPELINE_RUNBOOK D-39

### K039 — QA

- 规则：缺陷分级门按全集评估：任何落在全集开场 10 s 或结尾 5 s 的 MINOR（P2）对每一个单元都是零容忍，一条开场里的 P2 会让 30/30 单元全部不准入；审核者不能把真实的遗漏降级，只能重做该单元；同一审核请求不能重复提交，重做后要签发新的 video_q2 请求整批重填。
- 失败教训：首集单元的兽皮袋没扔到雪里，作为 P2 记录在第 9 秒，结果 Q2 物化 PARTIAL_0_OF_30。
- 修复路径：开场/结尾区的 P2 = 重做，不是备注；重做走制作文本重登记链；其余单元的准入在新请求里一起重新物化。
- 状态：`GUIDANCE_ONLY`。相关实现：[tools/defect_tolerance_gate.py](../../tools/defect_tolerance_gate.py)、[lines/nalu/runtime/tools/video_q2_builder.py](../../lines/nalu/runtime/tools/video_q2_builder.py)（相关代码存在，不等于公共主分支已完整消费）
- 证据：nalu PIPELINE_RUNBOOK D-39

### K040 — IDENTITY

- 规则：视频 Q2 身份：写姿态豁免前必须先看引擎的 face_crops——远景帧的裁切常常裁到别的人物（0.05–0.10 的分数不是本人、是裁错了）；豁免理由写帧号与两个分数；边界带里审核者在人工窗内给出的 PASS 会被采纳（中点 0.375 只管超时自动裁决）；OCR 纹理噪声按 `NOISE:<文本>` 申报（置信 <0.90、不含禁词），视频 Q2 构建器与关键帧 Q1 同规则。
- 失败教训：驴颈鬃毛被 OCR 读成 6 个拉丁字母，PERIOD-ANACHRONISM-LOCK 以 P0 拒收；一半『低分』其实是裁切框落在旁人脸上。
- 修复路径：把 D-26 的 NOISE 申报移植到 video_q2_builder（记入 ocr_noise_ignored）；审核脚本按单元记录 identity_pose_exemptions；每次补交都签发新请求。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/video_q2_builder.py](../../lines/nalu/runtime/tools/video_q2_builder.py)、[lines/nalu/runtime/tools/keyframe_q1_builder.py](../../lines/nalu/runtime/tools/keyframe_q1_builder.py)（本仓库 lines/nalu 运行时已实现并随 E04 生产验证）
- 证据：nalu PIPELINE_RUNBOOK D-39

### K041 — RETRY

- 规则：提示词批次链的顺序：规划编译 → 登记 → 摘要 → 回执 → 登记 → 终稿 diff（必须 0 changed）；摘要读的是已登记批次清单里的 sha，漏掉第一次登记会把回执绑到上一版提示词，付费边界报 QA_INPUT_MISMATCH（提交前失败，不扣费，留下空 .lock）。新增制作条款里不能出现资产库道具名（如『火泉』），否则它成为必须可见的起始帧道具，严格编译在 4.4 阻塞。
- 失败教训：重做 VU-002 时跳过第一次登记，事务文件为空、循环停在 VIDEO_SUBMIT_FAILED；上一轮『火泉的水声』让 4.4 报 missing visible props。
- 修复路径：删除空 .lock，按正确顺序重跑链，再重启循环；条款里用『池水』这类非资产名。
- 状态：`GUIDANCE_ONLY`。相关实现：[lines/nalu/runtime/tools/prompt_batch_qa.py](../../lines/nalu/runtime/tools/prompt_batch_qa.py)、[lines/nalu/runtime/tools/prompt_batch_register.py](../../lines/nalu/runtime/tools/prompt_batch_register.py)、[lines/nalu/runtime/tools/prompt_batch_finalize.py](../../lines/nalu/runtime/tools/prompt_batch_finalize.py)（相关代码存在，不等于公共主分支已完整消费）
- 证据：nalu PIPELINE_RUNBOOK D-39

## E04 审片回写（K042–K052）：`stage` 字段照审片报告写为 `pipeline`（由对应门/流程消费）或 `prompt`（由提示词编译器注入，只注入这一类）；每条带 `failure_code` / `do_not_repeat` / `scope`，并导出为 `knowledge/failure_memory.jsonl`。

### K042 — pipeline

- failure_code：`HOOK_MISSING`（scope episode，类别 QA）
- do_not_repeat：前 5 秒必须有台词或冲击镜头；开场不用独行/特写
- 规则：开场钩子合同：episode 合同 pacing.hook={type, at_seconds≤5, line_or_shot_id}，S1 门校验前 5 s 内有台词或 shock 镜，成片检测 hook_present（ASR 首句 ≤5 s 或帧差冲击）。
- 失败教训：E04 前 47 s 无一句台词、无冲突，观众第 3 秒划走；所有 D 门与 CI 通过，因为没有门测『合同本身是否成立』。
- 修复路径：tools/script_structure_contract_gate.py::check_hook + tools/final_cut_audience_detectors.py::hook_present；写手 schema pacing.hook 必填。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/script_structure_contract_gate.py](../../tools/script_structure_contract_gate.py)、[tools/final_cut_audience_detectors.py](../../tools/final_cut_audience_detectors.py)（E04 成片作为负样本回归通过；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
- 证据：nalu PIPELINE_RUNBOOK D-40/D-41

### K043 — prompt

- failure_code：`ACTION_NO_OUTCOME`（scope beat，类别 QA）
- do_not_repeat：动作段落必须以命中/受伤/逃脱/失败之一收束，并有证据镜头
- 规则：动作段结果合同：manifest.structure[].type=action 的 beat 必带 outcome{kind∈winner|escape|injury|loss, evidence_shot_id}，证据镜在段落结束后 10 s 内；提示词层把 do_not_repeat 注入动作镜。
- 失败教训：E04 25–47 s 怪物出现→射两箭→跑→再拉弓→消失，无命中无受伤无逃脱，观众『打了个寂寞』。
- 修复路径：check_action_outcome + post-gen plot 审核问题 action_outcome_visible；提示词条款由 nalu_prompt_rules KNOWLEDGE_PROMPT 注入。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/script_structure_contract_gate.py](../../tools/script_structure_contract_gate.py)、[lines/nalu/runtime/tools/nalu_prompt_rules.py](../../lines/nalu/runtime/tools/nalu_prompt_rules.py)（E04 成片作为负样本回归通过；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
- 证据：nalu PIPELINE_RUNBOOK D-40/D-41

### K044 — prompt

- failure_code：`ANTAGONIST_NO_MOTIVE`（scope beat，类别 QA）
- do_not_repeat：对抗方首次行动前必须有动机台词或回顾镜头
- 规则：冲突动机前置：contract.antagonist_groups[] 声明 first_action_shot_id 与 motive_setup{line|shot|recap}，动机必须早于首次行动。
- 失败教训：E04 雪洞三人 50 s 出场即议论主角，观众不知他们是谁、为何埋伏。
- 修复路径：check_antagonist_motive + plot 审核问题 antagonist_motive_readable + 提示词注入。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/script_structure_contract_gate.py](../../tools/script_structure_contract_gate.py)、[lines/nalu/runtime/tools/nalu_prompt_rules.py](../../lines/nalu/runtime/tools/nalu_prompt_rules.py)（E04 成片作为负样本回归通过；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
- 证据：nalu PIPELINE_RUNBOOK D-40/D-41

### K045 — prompt

- failure_code：`PROP_NO_SOURCE`（scope beat，类别 QA）
- do_not_repeat：后段出现的道具必须有获取镜头
- 规则：道具来源合同：props.reference_cards[] 的 payoff 道具必带 acquired{episode, shot_id}；跨集获取必须在本集有 recap 镜（早于 payoff ≥10 s）。
- 失败教训：E04『猎熊结果抓了只松鼠』笑点的前提镜（抓松鼠）在上一集，本集没有回顾，笑点落空。
- 修复路径：check_prop_source + 提示词注入。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/script_structure_contract_gate.py](../../tools/script_structure_contract_gate.py)、[lines/nalu/runtime/tools/nalu_prompt_rules.py](../../lines/nalu/runtime/tools/nalu_prompt_rules.py)（E04 成片作为负样本回归通过；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
- 证据：nalu PIPELINE_RUNBOOK D-40/D-41

### K046 — pipeline

- failure_code：`DEAD_THEN_ALIVE`（scope episode，类别 CONTINUITY）
- do_not_repeat：角色状态机 alive→dead 不可逆；血迹/倒地镜头必须与后续状态一致
- 规则：角色状态机：cast[].life_state∈{alive,injured,unconscious,dead} 与 shots[].group_counts；dead 后不得回 alive，人数变化必须带 count_change_note；Q2 必答『观感状态是否与声明一致』。
- 失败教训：E04 108 s 三人倒地见血被观众读成尸体，145 s 又活着挨打；人数 3→4→3。合同声明 alive，所以合同层拦不住，只能靠观感审核问题。
- 修复路径：tools/continuity_state_contract_gate.py::check_life_state + video_q2 问题 perceived_life_state_matches_declared / visible_group_count_matches_declared（自动判定 NOT_IMPLEMENTED）。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/continuity_state_contract_gate.py](../../tools/continuity_state_contract_gate.py)、[lines/nalu/runtime/tools/vlm_review_protocol.py](../../lines/nalu/runtime/tools/vlm_review_protocol.py)（E04 成片作为负样本回归通过；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
- 证据：nalu PIPELINE_RUNBOOK D-40/D-41

### K047 — pipeline

- failure_code：`MASCOT_IN_STORY`（scope episode，类别 EDITING）
- do_not_repeat：吉祥物/品牌素材只进 intro/outro，正片段落禁止
- 规则：非剧情素材隔离：release_timeline.segments[].type∈{intro,story,outro,endcard}，素材 tag∈{story,mascot,brand}；tag≠story 的素材进 story 段拒绝拼接；成片检测 mascot_in_story 模板匹配。
- 失败教训：E04 112–120 s 白猫骑驴被观众当成吉祥物彩蛋。核实：它是原著场景，不是吉祥物——真正缺的是该实体的铺垫/回收（见 entity_introductions 合同）。
- 修复路径：segment type/asset tag + tools/final_cut_audience_detectors.py::mascot_in_story；实体引入由 script_structure_contract_gate::check_entity_introduction 拦。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/final_cut_audience_detectors.py](../../tools/final_cut_audience_detectors.py)、[tools/script_structure_contract_gate.py](../../tools/script_structure_contract_gate.py)（E04 成片作为负样本回归通过；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
- 证据：nalu PIPELINE_RUNBOOK D-40/D-41

### K048 — prompt

- failure_code：`CREATURE_FORM_DRIFT`（scope video，类别 IDENTITY）
- do_not_repeat：非人角色也走角色卡，locomotion 跨镜锁定
- 规则：生物形态卡：non_character_entities[] kind=CREATURE 的行必带 creature_card{locomotion: biped|quadruped, eye_color, silhouette_ref}；镜文本步态词与卡不一致 BLOCK；Q1/Q2 问题 creature_locomotion_matches_card。
- 失败教训：E04 25 s 怪物直立奔行，115 s 变四足，观众以为漏看一集。
- 修复路径：check_creature_card + 审核问题 + 提示词注入。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/continuity_state_contract_gate.py](../../tools/continuity_state_contract_gate.py)、[lines/nalu/runtime/tools/nalu_prompt_rules.py](../../lines/nalu/runtime/tools/nalu_prompt_rules.py)（E04 成片作为负样本回归通过；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
- 证据：nalu PIPELINE_RUNBOOK D-40/D-41

### K049 — pipeline

- failure_code：`VOICE_COLLISION`（scope audio，类别 AUDIO）
- do_not_repeat：同场角色 voice_id 唯一，生成后逐句 F0 校验
- 规则：角色→音色绑定：voice_cast 每角色 voice_id + f0_band_hz（由参考音实测 ±15%）；生成前同场 voice_id 唯一、音区重叠 >50% 需人工；生成后逐句 F0 中位数落在角色音区外或同场两角色 F0 差 <15% → FAIL。新角色（episode_first_locked=本集）参考音 F0 与同场说话人相差 <25% → S4 FAIL（NEW_VOICE_TOO_CLOSE_IN_SCENE；与不同场说话人 <15% 只作 NEW_VOICE_CLOSE_IN_CAST 提醒——E10 九个说话人时全集 15% 无解），换音色重生成参考音；老角色之间 <25% 只作 ESTABLISHED_VOICES_CLOSE 提醒，是否重新选角由线主定（Roger 2026-09-28：每个人的语音太类似，新角色语音要不一样；E09 回放会拦下冯易安 vs 陆泽 9.7%、许岳平 vs 秦铭 11.6%）。
- 失败教训：E04 9 个角色 9 条参考音，模型输出只有 3 个音区（~100/~200/~350 Hz），求饶者与指责者同音区；本线台词由视频模型原生发声，没有 TTS 可调参数，只能测量后重做。
- 修复路径：tools/voice_cast_gate.py + tools/dialogue_voice_metrics.py + final_cut_audience_detectors::voice_distinctness。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/voice_cast_gate.py](../../tools/voice_cast_gate.py)、[tools/dialogue_voice_metrics.py](../../tools/dialogue_voice_metrics.py)、[lines/nalu/runtime/tools/build_voice_cast.py](../../lines/nalu/runtime/tools/build_voice_cast.py)（E04 成片作为负样本回归通过；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
- 证据：nalu PIPELINE_RUNBOOK D-40/D-41

### K050 — pipeline

- failure_code：`FLAT_EMOTION`（scope audio，类别 AUDIO）
- do_not_repeat：plead/fear/threat 句响度比 calm 基线高 ≥6 dB
- 规则：情绪→韵律：dialogue_units[].emotion 必填，映射为演绎条款（volume_arc/pace）；生成后 plead|fear|threat 句 RMS 比同角色 calm 基线高 ≥6 dB，否则 FAIL；无基线的角色标 UNVERIFIED。
- 失败教训：E04 全部台词 −15…−19 dB，『救命啊』与『野核桃真香』同音量，没有情绪。
- 修复路径：voice_cast_gate::emotion_dynamics + nalu_prompt_rules EMOTION 规则。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/voice_cast_gate.py](../../tools/voice_cast_gate.py)、[lines/nalu/runtime/tools/nalu_prompt_rules.py](../../lines/nalu/runtime/tools/nalu_prompt_rules.py)（E04 成片作为负样本回归通过；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
- 证据：nalu PIPELINE_RUNBOOK D-40/D-41

### K051 — pipeline

- failure_code：`MODERN_LEXICON`（scope episode，类别 QA）
- do_not_repeat：台词与字幕过世界观词表，禁用科幻/现代词
- 规则：世界观词表：LEXICON_<world>_v1.json（禁用词、人名标准写法、称谓表）；S1 扫台词，成片扫 ASR + 字幕 + OCR。
- 失败教训：E04 古装第一句台词出现『变异生物』；字幕『铭哥』与转写『秦明』人名用字不一。
- 修复路径：check_lexicon + final_cut_audience_detectors::lexicon_violation。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/script_structure_contract_gate.py](../../tools/script_structure_contract_gate.py)、[tools/final_cut_audience_detectors.py](../../tools/final_cut_audience_detectors.py)、[lines/nalu/runtime/configs/LEXICON_portable_template_v1.json](../../lines/nalu/runtime/configs/LEXICON_portable_template_v1.json)（每个项目由剧本生成自己的私有词表；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
- 证据：nalu PIPELINE_RUNBOOK D-40/D-41

### K052 — pipeline

- failure_code：`DIALOGUE_STARVATION`（scope episode，类别 PACING）
- do_not_repeat：无台词连续 ≤15s（动作段 ≤25s），全集台词覆盖 ≥35%
- 规则：台词密度下限：pacing.dialogue_density{max_silent_run_seconds 15, action 25, min_coverage 0.35}；S1 按镜表估算，成片按 ASR 实测 dialogue_coverage / silence_gap_max。
- 失败教训：E04 175 s 只有约 36 s 有人说话（覆盖 20.6%），63–99 s 连续 36 s 无台词。
- 修复路径：check_dialogue_density + 成片检测器。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/script_structure_contract_gate.py](../../tools/script_structure_contract_gate.py)、[tools/final_cut_audience_detectors.py](../../tools/final_cut_audience_detectors.py)（E04 成片作为负样本回归通过；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
- 证据：nalu PIPELINE_RUNBOOK D-40/D-41

### K053 — pipeline

- failure_code：`VOICE_ONLY_CHARACTER_NEEDS_NO_PLATE`（scope episode，类别 IDENTITY）
- do_not_repeat：无人脸的说话生物不建身份牌：角色登记 + 道具卡 + OFFSCREEN_VOICE_ONLY，不进可见 cast
- 规则：会说话的生物（如紫眼乌鸦）是对白/配音合同里的角色，但永远不是可见 cast：角色登记 identity_source.mode=VOICE_ONLY_NO_PLATE → 不建身份牌、不建服装状态，只建 voices 行；画面用 PROP 生物卡；镜表 presence=OFFSCREEN_VOICE_ONLY、lip_owner 为空。
- 失败教训：E05 乌鸦开口说话：身份锁要求 InsightFace 人脸，生物没有人脸，按普通角色走 S3 必然 FAIL；不登记为角色又过不了对白/配音合同。
- 修复路径：bootstrap_identity_cards 跳过 VOICE_ONLY_NO_PLATE 行；build_episode_asset_requirements 只对有牌角色建身份/服装，voices 循环保留全部角色。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/bootstrap_identity_cards.py](../../lines/nalu/runtime/tools/bootstrap_identity_cards.py)、[lines/nalu/runtime/tools/build_episode_asset_requirements.py](../../lines/nalu/runtime/tools/build_episode_asset_requirements.py)（回归：[tools/tests/test_nalu_e05_sync.py](../../tools/tests/test_nalu_e05_sync.py)）
- 证据：nalu PIPELINE_RUNBOOK D-50

### K054 — pipeline

- failure_code：`VIDEO_PROVIDER_DECLINE_QUARANTINED_AS_UNRESOLVED`（scope episode，类别 LEDGER）
- do_not_repeat：拒单 + 账单行数相等 = 未扣费可重试，不整批隔离；BLOCKED 运行后先归档账单摘要再重跑
- 规则：视频提交（e24，镜像图片链 e18）：提供者明确拒单（code 500 payment failed、无任务标识）且账单窗口 Pay 行数 == 已知 task 数 → VERIFIED_ZERO_RETRYABLE / NOT_CHARGED_RETRYABLE，只重发该单元；BLOCKED 的运行不归档账单摘要，会被下一次运行覆盖 → 用 giggle_credit_statements 按提交窗重建。
- 失败教训：E05 波次 1 VU-018 被提供者拒单，13 行 Pay == 13 个 task 仍被整批标 CHARGE_STATE_UNRESOLVED_BATCH；波次 1 账单摘要被波次 2 覆盖丢失。
- 修复路径：_provider_declined + classify_failures 分支；离线重分类事务；重入只 POST 未绑定单元；按窗口重建摘要并入账。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/submit_giggle_video_manifest_v2.py](../../tools/submit_giggle_video_manifest_v2.py)（回归：[tools/tests/test_nalu_e05_sync.py](../../tools/tests/test_nalu_e05_sync.py)）
- 证据：nalu PIPELINE_RUNBOOK D-52/D-53; engine_patches/e24_video_submit_not_charged_retryable_on_provider_decline.diff

### K055 — pipeline

- failure_code：`VOICE_RECEIPT_EPISODE_MISMATCH`（scope episode，类别 LEDGER）
- do_not_repeat：配音回执按注册表资产 id 匹配；新配音先 S4 后 S3；账本检查不与流水线并发
- 规则：重铸配音在多集都有上传回执：锁库按注册表 remote_asset_id 选回执，否则取最新集；新配音必须先过 S4 再回 S3 资产库门；账本检查绝不与流水线运行并发（.part 竞争造成假 HARD_STOP_BUDGET）。
- 失败教训：E05 S3 对重铸秦铭取了 E01 最旧回执 → upload_receipt_asset_id_matches_registry FAIL；并发跑 nalu_budget_ledger --check 撞上流水线账本写入，报了不存在的预算硬停。
- 修复路径：library_lock_non_plate.lock_voice 反向遍历回执匹配 asset_id；S4 先于 S3 重跑；账本只在流水线空闲时检查。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/library_lock_non_plate.py](../../lines/nalu/runtime/tools/library_lock_non_plate.py)（回归：[tools/tests/test_nalu_e05_sync.py](../../tools/tests/test_nalu_e05_sync.py)）
- 证据：nalu PIPELINE_RUNBOOK D-50/D-51

### K056 — pipeline

- failure_code：`SHOT_TEXT_STATE_LEAK`（scope episode，类别 SCRIPT）
- do_not_repeat：姿态逐镜声明；场景光线不提人物；道具用注册表名；start_framing 含在场人物；有道具的无人帧不写空镜
- 规则：镜文字逐镜自洽：姿态（坐/站）在 entry+blocking 每镜写明；场景级光线/环境文字不得提到人物或生物（独处镜写『没有别人、没有鸟兽』）；道具只在镜文字含注册表名时才绑定，否则编译成『道具：无/空镜』；camera.start_framing 必须包含入镜时已在场的人物；无人物但有道具/生物的帧提示词写『主体只有上列道具/生物』而不是『空镜』。
- 失败教训：E05 Q1 第一轮 9 镜被拒：坐/站跳变 ×6、幻影鸟笼、独处镜漏进女子与乌鸦、石上多出一把弓；乌鸦独镜因未用注册表名『紫眼乌鸦』编译成空镜；生成后女子在 2 s 处突然入画（start_framing 漏了她）。
- 修复路径：改镜头文字（不改故事）→ 重建 → 停放旧图/旧收割副本 → 重登记提示词批次 → 受守卫重做；空帧条款按道具绑定改写。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/build_keyframe_manifest.py](../../lines/nalu/runtime/tools/build_keyframe_manifest.py)（回归：[tools/tests/test_nalu_e05_sync.py](../../tools/tests/test_nalu_e05_sync.py)）
- 证据：nalu PIPELINE_RUNBOOK D-51/D-53

### K057 — pipeline

- failure_code：`REVIEW_MARKER_REQUIRES_NEW_REQUEST`（scope episode，类别 QA）
- do_not_repeat：标记/豁免只随新审核请求生效；P2 用 1-based shot_index；身份豁免先看裁切图
- 规则：审核标记与豁免的作用域：D-16 姿态标记（faces=）只经由新的审核请求生效（停放旧 request/submitted）；Q2 P2 缺陷必须带 1-based shot_index 与 at_seconds；身份低分先看 face_crops——错脸裁切（旁人/动物被标成主角）与低头姿态写 identity_pose_exemptions{角色: 理由+帧号+两个分数}；OCR 噪声按 NOISE:<文本> 申报；同一请求不可二次提交。
- 失败教训：E05 Q1 身份 FAIL 在加了 faces= 标记后仍复现，因为 Q1 构建器从旧请求的 expectations 读标记；Q2 第一轮 28/35：shot_index 用了 0 起、墙上『一楼』未申报为噪声、陆泽/文睿/松鼠裁切被当成秦铭低分。
- 修复路径：停放旧请求重新签发；按 1-based 填缺陷；豁免写帧号与分数；NOISE 申报；新请求整批重填 → ALL_ADMITTED。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/review_fill/e05_fill_video_q2.py](../../lines/nalu/runtime/tools/review_fill/e05_fill_video_q2.py)、[lines/nalu/runtime/tools/review_fill/e05_fill_keyframe_answers.py](../../lines/nalu/runtime/tools/review_fill/e05_fill_keyframe_answers.py)（回归：[tools/tests/test_nalu_e05_sync.py](../../tools/tests/test_nalu_e05_sync.py)）
- 证据：nalu PIPELINE_RUNBOOK D-51/D-53

### K058 — pipeline

- failure_code：`ACTION_VISIBILITY_UNDECLARED`（scope episode，类别 PACING）
- do_not_repeat：关键动作画内可见、对白动作词有动作、同机位不相邻；成片对镜表比对只诊断
- 规则：关键动作可见性（seq=27，ADVISORY，E05 起）：setup_id/payoff_of 的可见兑现 ≤25 s 或有部分揭示；result_of 因果镜施动者可见、纯环境镜 ≤2 s；对白动作词表（打/杀/放开/住手/松手/救命/别动/跑）须有对应可见动作；blocking_signature 相邻不重复、每场 ≤2；一镜一句台词；≥3 人镜 action 非空；无对白镜 ≤5 s 且运镜；S7 成片对镜头表机器比对（scdet 切点 + YAVG 亮度：SHOT_COUNT_DRIFT / SHOT_STRETCHED / STATIC_HOLD_IN_DIALOGUE / BLANK_SCREEN）写入 assembly parity json + CHECKPOINT，只诊断不阻断，不加新 gate_id，不改 S5/S6 付费流。
- 失败教训：E04 审片：关键动作发生在画外或纯环境镜、对白喊『放开』画面无人被抓、同机位连拍；E05 成片比对 34 段 vs 37 镜，SHOT_STRETCHED ×4、STATIC_HOLD ×1、BLANK_SCREEN 78–81 s，阈值由线主裁定。
- 修复路径：写手层自检（SETUPS/RESULT_OF/动作词表/blocking_signature）不过不进 S2；S7 在观众检测器之前跑 parity 诊断，结果进 CHECKPOINT。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/final_cut_shot_plan_parity.py](../../lines/nalu/runtime/tools/final_cut_shot_plan_parity.py)、[lines/nalu/runtime/tools/nalu_pipeline.py](../../lines/nalu/runtime/tools/nalu_pipeline.py)（回归：[tools/tests/test_nalu_e05_sync.py](../../tools/tests/test_nalu_e05_sync.py)）
- 证据：nalu PIPELINE_RUNBOOK D-51/D-54; SUPERVISOR_ORDERS seq=27

### K059 — pipeline

- failure_code：`IDENTITY_SIGNAL_DILUTED_ALONG_CHAIN`（scope episode，类别 IDENTITY）
- do_not_repeat：牌对原照测；关键帧脸参考打头且大脸；视频单元带头像牌；Q1 不给 3/4 脸豁免
- 规则：身份链四步各自可证：①身份牌锁定必须对操作者原照片逐牌测余弦（后缀源图也要找到），任一牌 <0.45 重出牌；②关键帧参考序列以正面头像牌打头，全身牌降为服装参考，空间图+场景+道具 ≤5、总数 ≤9；③每个视频单元的参考图 = 关键帧锚点 + 每个在场角色的正面头像牌（上限 9）；④关键帧 Q1 对 3/4、侧脸、低头、转头一律测，只有背影/仅手/出画/远小/画外音豁免，检测不到即 FAIL。
- 失败教训：E05 全集 14 个室内近景对话单元主角脸走样：身份牌从未与原照比过（源图后缀没被找到，source_cosine 为空）；关键帧 10 张参考里脸只在 1440×2560 全身牌上约 150px；视频付费提交只带 1 张 720p 关键帧（脸约 80px），seq=7 c4 的头像牌追加被『已有关键帧绑定』短路；Q1 把 3/4 脸标 not_measurable 放行。E04 没暴露只因多为背影/远景。
- 修复路径：identity_qa_lock.find_operator_source + source_likeness_failures；build_keyframe_manifest 角色头像打头 + cap_non_character_bindings；build_nalu_preproduction.identity_plate_reference_rows；keyframe_q1_builder.pose_exempt 闭集。既有 LOCKED 牌按新阈值复测：梁婉清 0.351/0.407 需线主下单重出。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/identity_qa_lock.py](../../lines/nalu/runtime/tools/identity_qa_lock.py)、[lines/nalu/runtime/tools/build_keyframe_manifest.py](../../lines/nalu/runtime/tools/build_keyframe_manifest.py)、[lines/nalu/runtime/tools/build_nalu_preproduction.py](../../lines/nalu/runtime/tools/build_nalu_preproduction.py)、[lines/nalu/runtime/tools/keyframe_q1_builder.py](../../lines/nalu/runtime/tools/keyframe_q1_builder.py)（回归：[tools/tests/test_nalu_identity_chain_fixes.py](../../tools/tests/test_nalu_identity_chain_fixes.py)）
- 证据：nalu PIPELINE_RUNBOOK D-57; E05 library re-measurement 2026-09-18

### K060 — pipeline

- failure_code：`HALF_SECOND_UNIT_VS_INTEGER_PROVIDER_SLOT`（scope episode，类别 DURATION）
- do_not_repeat：整数槽=上取整；内容与尾柄显式声明并透传；重建后重新走 register→digest→receipts→register
- 规则：半秒制镜长（seq=29 5a）之下，视频单元的供应商时长槽 = 编辑合计的整数上取整，并显式声明 authorized_content_seconds（裁切长度）与 authorized_tail_handle_seconds（槽 − 内容，≥0.25）；分组计划在引擎分组门之后做投影，编译单元透传这两个字段，付费边界重编与 4.4 编译看到同一整数时长。
- 失败教训：E06 首次在统一引擎上跑 S6：int(round(6.5)) 是银行家舍入得 6 < 内容 → AUTHORIZED_CONTENT_EXCEEDS_PROVIDER_SLOT；只上取整又触发 DURATION_EXCEEDS_AUTHORIZED_CONTENT（默认尾柄 0.25 < 0.5）；4.4 编译按 6.5 出提示词而付费边界按 7 重编 → 「provider prompt is not the exact output」。三个错误都在同一根源。
- 修复路径：build_nalu_preproduction.project_provider_slots（分组门之后）+ 交易任务 duration_seconds=ceil、authorized_*；compile_grouped_seedance_manifest.compiled_unit 透传 authorized_*（缺省行为不变）；每次重建后 compile planning → register → digest → receipts → register；半秒单元的最终化收据按机械差异签收（槽头、内容窗口条款、等比拍钟）。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/build_nalu_preproduction.py](../../lines/nalu/runtime/tools/build_nalu_preproduction.py)、[tools/compile_grouped_seedance_manifest.py](../../tools/compile_grouped_seedance_manifest.py)；回归：[tools/tests/test_grouped_manifest_duration_authority_passthrough.py](../../tools/tests/test_grouped_manifest_duration_authority_passthrough.py)
- 证据：nalu PIPELINE_RUNBOOK D-63

### K061 — qa

- failure_code：`SPEECH_RATE_MEASURED_ON_PADDED_SEGMENTS`（scope episode，类别 DIALOGUE）
- do_not_repeat：先修测量再谈重出；记录 timing_basis；收尾句不当拖沓判
- 规则：语速门（seq=29 规则 6）必须按词级时间戳求实说时长（word spans 之和），不能用 whisper 分段边界；写明「……」收尾的台词低速是表演，降为记录型 MINOR，钩子句不豁免；阈值本身不动。
- 失败教训：E06 首轮 22 个对白单元 8 个 BLOCKER：「高等生灵」4 字被算在 0.14–7.71 s 的风声 VAD 段上（0.11），短句落在整 1.00/2.00 s 上；换词级计时后 6 个消失，剩下两句是编剧写明用省略号收尾的台词（陆泽愣住的半句、周长裕哽咽的半句）。若按原测量重出要花约 1000 积分且什么也修不好。
- 修复路径：post_generation_qa_runner._rate_segments（word_timestamps=True 单独一遍）+ speech_rate_check.measure_unit（timing_basis 记录）+ authored_trailing_off 豁免（seq=31 C 的应用，seq=33 记录）。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/speech_rate_check.py](../../lines/nalu/runtime/tools/speech_rate_check.py)、[lines/nalu/runtime/tools/post_generation_qa_runner.py](../../lines/nalu/runtime/tools/post_generation_qa_runner.py)；回归：[tools/tests/test_nalu_seq29_rules.py](../../tools/tests/test_nalu_seq29_rules.py)
- 证据：nalu PIPELINE_RUNBOOK D-64

### K062 — assembly

- failure_code：`LEVELLER_TARGET_ABOVE_ROLE_CEILING`（scope episode，类别 AUDIO）
- do_not_repeat：精修目标不出接受带；上限用常量；重跑先停放输出
- 规则：发布级响度校正的逐单元精修目标 = 角色暂存目标 + 节目增益，但必须钳制在该角色的接受带内（边缘留 0.3 LU）；精修轮数上限 12，停止条件不变。
- 失败教训：E06 对白占比高，节目增益约 5 dB，DIALOGUE 暂存目标 −18 + 5.08 = −12.9 高于接受上限 −13，6 轮精修把最响的 7 个对白单元反而推到 −12.5…−12.8；上限 6 在代码里写死两处（range(1,7) 与 attempt==6）。
- 修复路径：level_native_release_audio：MAX_REFINEMENT_PASSES=12；desired 用 ROLE_ACCEPTANCE_RANGES_LUFS 钳制。E06 12 轮收敛：−14.3 LUFS / LRA 6.0 / TP −1.3，0 单元失败。重跑前先把 v1 输出停放（工具拒绝覆盖）。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/level_native_release_audio.py](../../tools/level_native_release_audio.py)、[tools/native_audio_loudness_contract.py](../../tools/native_audio_loudness_contract.py)；回归：[tools/tests/test_nalu_identity_chain_fixes.py](../../tools/tests/test_nalu_identity_chain_fixes.py)
- 证据：nalu PIPELINE_RUNBOOK D-66

### K063 — pipeline

- failure_code：`BY_DESIGN_POSE_BLOCKS_IDENTITY_GATE`（scope episode，类别 IDENTITY）
- do_not_repeat：按订单接受、sha 绑定、引擎结果保留；不改阈值、不给可测脸豁免
- 规则：关键帧 Q1 的身份门（CHARACTER-IDENTITY-ADMISSION）允许线主按订单接受：仅当该单元唯一失败门是身份门、订单（GATE_FAIL_ACCEPTANCE，本集本门）点名每一个失败的 item:character 检测项且关键帧 sha 匹配时，才把单元改为 ADMITTED_BY_LINE_OWNER_ORDER；引擎结果与逐单元 admission_result 各留 .engine.json 副本，接受记录写入 reports/qa/q1/<EP>_ROGER_GATE_ACCEPTANCE.json；从不自发。
- 失败教训：E06 Q1 在 D-57④ 之下：低头/侧面/远景是导演设计的姿态，余弦 0.29–0.37 不可能过 0.45；自动重出额度 5 次用尽后 6 帧卡死。线主选 C（按设计接受 + 可修的转脸重出）并定为常规。
- 修复路径：nalu_pipeline.apply_roger_q1_acceptance（S5.q1 每次重算叠加，撤销订单即取消放行）；同形选择按 seq=31 常规由操作员记录（seq=32/33/34），标注待线主会签。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[lines/nalu/runtime/tools/nalu_pipeline.py](../../lines/nalu/runtime/tools/nalu_pipeline.py)、[lines/nalu/runtime/tools/roger_gate_acceptance.py](../../lines/nalu/runtime/tools/roger_gate_acceptance.py)；回归：[tools/tests/test_nalu_q1_roger_acceptance.py](../../tools/tests/test_nalu_q1_roger_acceptance.py)
- 证据：nalu PIPELINE_RUNBOOK D-61/D-62

### K064 — S7

- failure_code：`AD_TAIL_SPOKEN_CHARS_OVER_CAP_OR_DOUBLE_BADGE`（scope line，类别 ASSEMBLY）
- do_not_repeat：不要先定镜长再配旁白；不要用原始字符串长度算 spoken_chars（要按CJK字符）；不要无条件叠加角标而不先检测输入是否已带角标
- 规则：尾贴广告（可选、按集opt-in）narration 必须先于视频镜长生成：先合成旁白并测其真实时长，再把 shot_duration_seconds 夹在槽合同 [4.0,6.0] 区间内喂给视频生成；CTA 网址只进字幕/caption，绝不进旁白脚本，spoken_chars 用 CJK 字符计数（不含拉丁字母单词）与 spoken_chars_max 比较。Mode A（现成成片丢进 ads/inbox/）允许输入本身已带「广告」角标与CTA字幕；AD_TAIL_OCR_CLEAN 对预期角标/CTA文本走 --allow-text 放行，而不是要求原始输入必须纯净无字；打包器自身叠加角标前先检测角标是否已存在（check_ocr_clean.badge_already_present），已存在则跳过叠加，避免双重角标。
- 失败教训：AdForge demo（giggle_ai_director_tail5s）第一次按「先定镜长再配旁白」的顺序做，第三句念网址在5s镜里放不下，白扣2 credits；换成先出旁白测时长再定镜长后一次通过。demo 本身画面已经带「广告」角标和 CTA 字幕烧录，OCR 严格模式若不放行这两处会把已批准的合规素材误判为异常文字；且封装器若无脑叠加自己的角标会与素材自带角标重叠。
- 修复路径：tools/adforge_adapter.py 的 generate() 中 narration 先行、shot_duration 按测得时长回填 project.json；tools/ad_tail_package.py 的 check_ocr_clean 传 --allow-text <badge_zh> <badge_en> <cta_text>，并把 badge_already_present 透传给 burn_and_normalize(skip_badge=...)。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/ad_tail_package.py](../../tools/ad_tail_package.py)、[tools/ad_tail_insert.py](../../tools/ad_tail_insert.py)、[tools/adforge_adapter.py](../../tools/adforge_adapter.py)、[lines/nalu/runtime/tools/nalu_tail_ad_opt_in.py](../../lines/nalu/runtime/tools/nalu_tail_ad_opt_in.py)；回归：[tools/tests/test_ad_tail_package.py](../../tools/tests/test_ad_tail_package.py)、[tools/tests/test_ad_tail_insert.py](../../tools/tests/test_ad_tail_insert.py)、[tools/tests/test_nalu_tail_ad_opt_in.py](../../tools/tests/test_nalu_tail_ad_opt_in.py)
- 证据：codex_docs/ROGER-20260925-AD-TAIL-INTEGRATION.md §四；2026-09-25/26 对 ~/adforge demo 实测打包 PASS（ad_tail_ocr_clean/duration/format/spoken_content_contract/loudness/label_present 全过）

### K065 — S1

- failure_code：`DP1_CU_MCU_RATIO_BELOW_FLOOR / DP2_UNDER_1S_SHOT_RATIO_BELOW_FLOOR / DP3_DIALOGUE_TIME_RATIO_BELOW_FLOOR`（scope generalizable，类别 WRITER_LAYER）
- do_not_repeat：不要在生成后验收表里新增一项就以为堵住了这个缺口；缺口只有搬到生成前的聚合门才算堵住
- 规则：凡可在生成前（写手/S1/提示词层，零成本）验证的观众可感质量维度，必须在那一层做成聚合/集级门，不得留给生成后验收再挑毛病——每挑一次要付一次生成费（20 credits/s），且发现得越晚返工范围越大。
- 失败教训：`build_e0N_layers.py` 和 `nalu_writer_selfcheck_seq29.py` 已经把绝大多数逐镜检查做了（对白镜时长跟台词走、禁「说完保持」、表演三要素、setup/payoff），但没有一处统计「这一集所有镜头景别分布是否达标」。E08 实测 ASL 6.77s/CU+MCU 40%/对白占比 40%，与专业样片 2.15s/60%/85% 的差距，正是逐镜合规无法倒推出集级观感达标的证据。
- 修复路径：`tools/direction_policy_gate.py` 的 DP1（景别分布）/DP2（<1s 占比）/DP3（连续无对白+对白时长占比）只做集级聚合判定，逐镜级判定继续留在原有位置，不重复实现。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/direction_policy_gate.py](../../tools/direction_policy_gate.py)、[configs/DIRECTION_POLICY_V1.json](../../configs/DIRECTION_POLICY_V1.json)；回归：[tools/tests/test_direction_policy_gate.py](../../tools/tests/test_direction_policy_gate.py)
- 证据：codex_docs/ROGER-20260925-NALU-LINE-OPTIMIZATION.md §零/§一；E08 CHECKPOINT 诊断表实测数据

### K066 — S1

- failure_code：`LITERAL_RATE_FIGURE_LEAKED_INTO_COMPILED_PROMPT`（scope generalizable，类别 PROMPT_COMPILER）
- do_not_repeat：新增任何语速/节奏相关字段时，先确认它只进合同元数据、绝不进提示词字符串，再把它加进这道扫描的正则
- 规则：模型不读数字：提示词里出现的字面语速数字（如「4.8字/秒」）对生成结果没有约束力，控制语速只能靠两件事——镜长卡死（=台词时长+固定余量，不给模型多余的时间可挥霍）和说话方式词（「抢着说」「咬字短促」代替数字）。
- 失败教训：「规则写在文档里」「字段存在于合同里」和「真的没有泄漏进模型提示词」是三件独立的事，必须逐一核实，不能因为字段存在就假设已经隔离。核查（2026-09-26）发现 `tools/sd2_provider_prompt_renderer.py` 从未把字面 cps 数字注入编译后的提示词，cps 只留在 GENERATION_CONTRACT 的 dialogue_delivery 元数据里供生成后 ASR 核实——本条规则在提示词层其实已经满足，缺的只是一道防止未来回归的扫描。
- 修复路径：`tools/direction_policy_gate.py` 的 `scan_for_literal_rate_figure()` 对编译后提示词文本做字面语速数字回归扫描（中文「字/秒」「字每秒」与英文 chars/sec 两种写法）。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/direction_policy_gate.py](../../tools/direction_policy_gate.py)；回归：[tools/tests/test_direction_policy_gate.py](../../tools/tests/test_direction_policy_gate.py)
- 证据：对 `tools/sd2_provider_prompt_renderer.py` 全文 grep 确认零字面语速数字命中

### K067 — S1

- failure_code：`RULE_ID_NAMESPACE_COLLISION`（scope generalizable，类别 GOVERNANCE）
- do_not_repeat：新规则落地前先 grep 目标编号前缀；发现冲突就换前缀，不要覆盖或假设「应该是同一套」
- 规则：同一仓库里独立的规则集不得复用相同的规则编号前缀（如 R1–R8），即便它们分属不同的线主指令、不同的时间点、不同的检查对象。新指令落地前先全库搜索目标编号前缀是否已被占用。
- 失败教训：落地 2026-09-25 优化方案时发现 R1–R8 已经被 `static_design_gate.py`（另一套摄影/节奏规则）占用一次，R5A–R9B 已经被 `nalu_writer_selfcheck_seq29.py`（第三套规则）占用一次——三套完全独立的规则集在同一仓库里争用同一命名空间，人工审阅或未来自动化很容易把三者混淆或误判某条规则「已存在」。
- 修复路径：本轮新规则改用 DP1–DP8/W1/W2 前缀，并在每处引用旁注明对应的原始 R 编号（`doc_ref` 字段），保留可追溯性的同时不与既有编号冲突。
- 状态：`GUIDANCE_ONLY`。相关实现：[tools/direction_policy_gate.py](../../tools/direction_policy_gate.py)、[configs/DIRECTION_POLICY_V1.json](../../configs/DIRECTION_POLICY_V1.json)
- 证据：`grep -rn` 命中 `static_design_gate.py` 与 `nalu_writer_selfcheck_seq29.py` 两套独立的 R 编号定义

## 引用和许可

以上文字为项目经验的原创概括，随本仓库 MIT LICENSE 发布。未复制外部社区文章、教程全文、他人视频/图片或私人聊天。
若以后导入社区打斗模板，必须记录原作者、URL、许可和可再分发范围；MIT 不覆盖第三方素材。
“重建推断”训练样本必须标为 INFERRED_RECONSTRUCTED_NOT_ORIGINAL，不能冒充原始镜头提示词，也不能推断未采集的音频。

### K068 — S4

- **规则**：付费子进程需要的每一把锁，必须在编排器允许付费的每一种 profile 下都有同一条件的传递；新旧 profile 并存时，旧 profile 的锁传递条件 = 旧 profile 自己的付费门（配置付费开关 ＋ 已校验的付费订单），缺任一即不传（fail-closed）。
- **教训**：StoryClaw 端口后 storyclaw_audio_provider.py 对每次付费调用都要求 NALU_PAID_CONFIG_LOCK=1，但 nalu_pipeline.paid_step 只在 CURRENT_PORTABLE profile 下导出它；LEGACY profile 的线（夜无疆）S4 每次都在 POST 前被拒（paid authority is incomplete: NALU_PAID_CONFIG_LOCK），零扣费但阶段永远过不去。E08 的 S4 早于端口，没踩到。
- **恢复**：抽出纯函数 paid_config_lock(is_current, config_paid_enabled, storyclaw_paid_enabled, paid_order)：CURRENT 分支与原条件逐字等价；LEGACY 分支 = config_paid_enabled 且 paid_order 非空。四条单测证明 fail-closed。线主授权 ROGER-20260926-S4-PAID-LOCK-PROPAGATION；自动模式分类器拒绝过未授权版本，授权后才落地。
- **实现**：`lines/nalu/runtime/tools/nalu_pipeline.py`（`paid_config_lock`）
- **回归**：`tools/tests/test_nalu_paid_authority.py`（`PaidConfigLockTest`）
- **授权**：Roger 2026-09-26 ROGER-20260926-S4-PAID-LOCK-PROPAGATION（仅旧 profile、fail-closed 测试、写回执与 K 号、S4 ≤4 credits）
- **状态**：REFERENCE_IMPLEMENTATION

### K069 — S6

- **规则**：SD2 每个单元都重新合成人声，参考音只是弱提示：声线必须在每句台词旁绑定（「X（音色严格同@音频N）说：……」）并在【声音】段首声明；表演指令只写语气不写嗓音——压着嗓子/扯着嗓子/声音发颤等改嗓音措辞在提示词里直接替换为「<语气>、音色不变」（configs/VOICE_TIMBRE_LOCK_V1.json 词表），原词不再出现；成片若已漂移，用 final_cut_voice_unify.py（demucs + Seed-VC，按参考音逐句换声，不花积分）后期统一；生成后逐单元按 voice_cast 音区测说话人 F0，出带即该单元重做。声线一致性失败要问线主，不得按常设 C 自动接受。
- **教训**：E09 成片线主听出角色声线「飘来飘去」。参考音 asset 每次都随 POST 发出、说话人与参考音一一对应，但提示词里声线只在【声音】段尾一句「X使用@音频N固定声线」，而台词前写着 压着嗓子/扯着嗓子/声音发颤/含糊地/屏着气轻声 等措辞，模型把语气做成了换嗓子：同一角色逐场 F0 中位数 秦铭 119–250 Hz（音区 173–234）、冯易安 96–211、陆泽 152–366。成片 voice_distinctness 已报 FAIL，却被当作测量类按常设 C 接受（seq 16）；生成后 QA 只核 ASR 文字，不核声线。E08 同样存在（秦铭 104–181 Hz）。
- **恢复**：`configs/VOICE_TIMBRE_LOCK_V1.json`（active_from_episode=10，E01–E09 提示词与判定逐字节不变，已对 E09 33 单元重编译验证）；`tools/voice_timbre_lock.py`；SD2 渲染器逐句绑定＋段首声线锁定＋改嗓措辞转语气句；写手自检 `R10_VOICE_TIMBRE_DIRECTION`（默认警告，可配置阻断）；生成后 QA 新增 `voice_consistency_qa`（`unit_voice_consistency.py`，复用 `dialogue_voice_metrics` F0 与 voice_cast 同一音区），FAIL 原因码 `voice:VOICE_OUT_OF_BAND:<CHAR>:<f0>`，归属不定记 UNVERIFIED。
- **实现**：[configs/VOICE_TIMBRE_LOCK_V1.json](../../configs/VOICE_TIMBRE_LOCK_V1.json)、[tools/voice_timbre_lock.py](../../tools/voice_timbre_lock.py)、[tools/sd2_provider_prompt_renderer.py](../../tools/sd2_provider_prompt_renderer.py)、`lines/nalu/runtime/tools/{nalu_writer_selfcheck_seq29,unit_voice_consistency,post_generation_qa_runner}.py`
- **回归**：`tools/tests/test_voice_timbre_lock.py`
- **证据**：离线 `unit_voice_consistency.py --episode E09`：33 单元 16 FAIL（含 VU-007 136 Hz、VU-014 118 Hz、VU-019 361 Hz）/16 PASS/1 UNVERIFIED
- **授权**：Roger 2026-09-28 会话「a，以后的修改生产线」
- **状态**：REFERENCE_IMPLEMENTATION（未在付费生产验证；逐句绑定能否真正锁住 SD2 声线要等 E10 实测）

### K070 — S5

- **规则**：关键帧提示词的「机位说明」只写本机位的几何（机位 id、位置、朝向、轴线、银幕方向、景别）加本镜自己的摄影文字；不得引用同一机位上其他镜头的描述。继承机位标签（`extend_global_space_map.annotate_existing_cameras` 按绑定镜头 `shot_size／camera` 拼成的多镜标签）不再进提示词。按集号生效（`configs/KEYFRAME_CAMERA_NOTE_SCOPE_V1.json`，active_from_episode=11），E01–E10 提示词逐字节不变。
- **教训**：E10 S5 Q1：机位说明原样拷贝 `subspace_layout.authored_camera_note`，即该机位全部绑定镜头描述的拼接。E10-S03-03 带进 S17-04 的「盯着木盒的刘老头」，桌上提前出现木盒；E10-S10-01 带进 S10-05/S14-03 的「捂着嘴」，梁婉清未开口已捂嘴；E10-S05-01 带进 S19-01 的「秦铭的脸」和旧标签「掀开的木盒」，画成了结束状态。三镜都靠镜头文字硬性覆盖、付费重做才过。entry_state 泄漏检查只比对本镜 completion_state/primary_action 子串，拦不住其他镜头的文字。
- **恢复**：`build_keyframe_manifest.build_prompt` 在生效集用 `scoped_camera_note`（本机位几何 ＋ `prompt_spec.camera` 去掉「；机位 …」机器后缀的本镜文字），未生效集保留原行。离线回归：E09/E10 用现配置重编译与改前逐字节一致（E10 51/51 与登记 sha 一致；E09 37/39，余 2 条是合同改过轴线声明的既有漂移，与本改动无关）；临时 active_from_episode=10 重编译 E10，51 条仅机位说明一行变化，不再含任何镜号或他镜内容。
- **实现**：[configs/KEYFRAME_CAMERA_NOTE_SCOPE_V1.json](../../configs/KEYFRAME_CAMERA_NOTE_SCOPE_V1.json)、`lines/nalu/runtime/tools/build_keyframe_manifest.py`（`load_camera_note_policy` / `camera_note_scoped` / `scoped_camera_note`）
- **回归**：`tools/tests/test_keyframe_camera_note_scope.py`
- **证据**：E10 S5 Q1 REJECT：E10-S03-03、E10-S10-01、E10-S05-01
- **授权**：Roger 2026-09-29 会话（E10 S5 Q1 后要求 E11 起修生产线）
- **状态**：REFERENCE_IMPLEMENTATION（未在付费生产验证；E11 S5 实测）
### K071 — S6

- **规则**：多镜头视频单元的每一镜机位（景别、高度、轴侧、运镜、起止取景、轴线/主体文字）都必须各自进入最终提示词；固定机位只写锁定，不写“执行一次运动”。按 configs/PROMPT_SHOT_SCOPE_POLICY_V1.json 分集生效（nalu E11 起、qingshan E64 起），旧集逐字节不变。
- **教训**：E10 重拍 VU-005/VU-020 时第二镜的“室内、绝无户外雪景”和服装锁定写进了合同却从未到达模型：SD2 渲染器只输出单元第一镜的【摄影】行，引擎里现成的逐镜通路（PER_SHOT_EXPLICIT）从未被任何上游打开；H3 的 _camera() 也只写景别与运镜族，不写起止取景，LOCKED 也带“execute the declared move once”。
- **恢复**：sd2_shot_camera_adapter.scope_grouping_plan_cameras 在生效集给多镜头单元打开 PER_SHOT_EXPLICIT（build_nalu_preproduction 在 4.2c 调用）；h3_provider_prompt_renderer 生效集逐镜输出起止取景/跟随对象并标明硬切或连续运动；grouped_camera_contract 五单元窗口只计每单元首镜、相邻镜仍逐镜查；grouped_transition_contract 逐镜单元以首镜为边界机位。
- **实现**：`configs/PROMPT_SHOT_SCOPE_POLICY_V1.json`、`tools/prompt_shot_scope_policy.py`、`tools/sd2_shot_camera_adapter.py`、`tools/h3_provider_prompt_renderer.py`、`tools/grouped_camera_contract.py`、`tools/grouped_transition_contract.py`、`lines/nalu/runtime/tools/build_nalu_preproduction.py`
- **回归**：`tools/tests/test_sd2_per_shot_camera_scope.py`
- **证据**：E10 VU-005/VU-020 重拍提示词只含首镜机位行；E10 按现配置重编译 31/31 逐字节一致，临时生效时 24 个多镜头单元每镜一行
- **授权**：Roger 2026-10-01 会话：「现在全部做，改好提交后再继续当前工作，彻底解决这个问题」
- **状态**：REFERENCE_IMPLEMENTATION
### K072 — S6

- **规则**：局部可见约束（只露手/爪/臂/腿、脸出画）必须绑定到具体实体+具体一拍+其时间窗并点名该实体；不得扩散到同镜其他实体或后续镜头；缺失可见范围不得被解读为禁止露脸；开口说话、口型可见的角色不得同时被禁止露脸。付费提交前对最终序列化请求做冲突检查，结果绑定提示词与参考图的精确哈希。
- **教训**：另一条线（H3）为防止局部入镜角色被补成完整人物，在本地 overlay 里给每个动作段无条件追加“do not widen the frame to reveal its face or full body”，39/39 条提交提示词都含该句，普通对白人物被推出画面；本地测试只覆盖了“仅手部不能露脸”的方向，没有覆盖反方向，结构检查通过被当成了生产证据。
- **恢复**：h3_provider_prompt_renderer 生效集按实体逐拍输出局部条款并自检（partial_clause_leaks、locked_camera_move_conflicts）；prompt_scope_conflict_gate.check_task 在提交器付费 POST 前检查说话人/禁露脸冲突、未点名或越界的局部条款、固定机位带运动；失败按提交前未扣费记录、不写事务、不 POST；已绑定任务的恢复不经过此门；每次新提交记录实际加载的渲染/门模块路径与 sha（本地 overlay 会显示为外部路径）。
- **实现**：`tools/prompt_scope_conflict_gate.py`、`tools/submit_giggle_video_manifest_v2.py`、`tools/h3_provider_prompt_renderer.py`
- **回归**：`tools/tests/test_prompt_scope_conflict_gate.py`
- **证据**：对另一条线 37 条事故提示词离线运行：全部被拦（PARTIAL_CLAUSE_GENERIC_UNNAMED / LOCKED_CAMERA_MOVE_INSTRUCTION）；nalu E10 31 条无误报
- **授权**：Roger 2026-10-01 会话：「现在全部做…彻底解决这个问题」（事故复盘由另一条线提交）
- **状态**：REFERENCE_IMPLEMENTATION
### K073 — S6

- **规则**：参考图以 base64 放在单个 JSON 请求里，原始总字节超过 15 MB 时提交前在内存里逐张转 JPEG q90（磁盘原图与 reference_sha256 不变，压缩方式进入任务指纹，不与旧事务撞指纹）。响应丢失但账单窗口证实已扣费且无法找回任务 ID 时，按线主常设指令记为损失（CHARGED_WRITTEN_OFF_BY_ORDER，花费仍由账单文件计入）后以压缩参考图重发。
- **教训**：E10 VU-020 重拍（7 张参考图约 37 MB，base64 约 51 MB）连续两次 HTTP 524；第一次对账未扣费，第二次账单窗口内恰好 1 笔 160 积分扣费却拿不到任务 ID，事务锁定禁止重发，预算检查因未对账事务拒绝任何新付费提交。
- **恢复**：submit_giggle_video_manifest_v2.reference_transport/reference_image_payload（阈值可由 GIGGLE_REFERENCE_PAYLOAD_LIMIT_BYTES 覆盖）；nalu_budget_ledger 增加已结清状态 CHARGED_WRITTEN_OFF_BY_ORDER，事务记录指令号、损失积分与账单文件 sha，同一指纹仍禁止重发。
- **实现**：`tools/submit_giggle_video_manifest_v2.py`、`lines/nalu/runtime/tools/nalu_budget_ledger.py`
- **回归**：`tools/tests/test_knowledge_registry.py`
- **证据**：压缩后该单元请求体约 5.8 MB，重发一次成功；损失 160 积分按线主指令记账
- **授权**：Roger 2026-10-01 会话：「没关系，选2，以后都这样」
- **状态**：REFERENCE_IMPLEMENTATION
### K074 — PIPELINE

- **规则**：每条生产线开工前生成本集知识简报（读全部规则与失败记忆），收工时写回新知识并核对简报存在；同时检查本线运行的引擎是否落后于 git 主线、是否有未申报的本地覆盖。知识库条目是抽象原因，不是旧集镜头表或台词。
- **教训**：知识库曾是只写不读：AGENTS.md 只规定收工时写 K 号，开工时没有任何读取步骤；写入也只靠代理自觉，E02/E03/E07 收工零条目而无任何环节报错；另一条线完全没有接入知识库，且通过本地 overlay 替换引擎模块，审计只记录 git HEAD。
- **恢复**：tools/line_upgrade_gate.py preflight（引擎新鲜度、overlay 检测、写 <EP>_KNOWLEDGE_BRIEFING）与 close（knowledge_sync_core 写入、核对简报）；nalu_pipeline S1 记录 preflight、S8 运行 close 并在 CHECKPOINT 显示；其他线按 docs/knowledge/LINE_UPGRADE_PROTOCOL.md 接入两次调用。
- **实现**：`tools/line_upgrade_gate.py`、`tools/knowledge_sync_core.py`、`lines/nalu/runtime/tools/knowledge_sync.py`、`lines/nalu/runtime/tools/nalu_pipeline.py`、`docs/knowledge/LINE_UPGRADE_PROTOCOL.md`
- **回归**：`tools/tests/test_line_upgrade_gate.py`
- **证据**：另一条线 preflight 实测 UNDECLARED_OVERLAY（两个引擎模块被本地文件替换）；E10 补生成简报 70 条规则 + 29 条失败记忆
- **授权**：Roger 2026-10-01 会话：「每集开工前必须读…」「确保流水线自己就能升级知识库」「各生产线的自动升级问题也一并解决」
- **状态**：REFERENCE_IMPLEMENTATION
### K075 — S6

- **规则**：单元里昏迷、背身或不露正脸的角色，其正脸身份牌不要放进视频参考图；否则视频模型会把这张“必须用上的脸”安到画面中唯一正面说话的人身上。主说话人的身份牌排在参考图第一位。
- **教训**：E10 VU-020 两次重拍：第一次安慰者被画成缠头巾的抬人村民；第二次服装是秦铭的，脸却与陆泽身份牌余弦 0.48–0.57、与秦铭仅 0.20–0.24，而陆泽本人昏迷躺地、脸几乎不可见。两次都只改文字没动参考图，根因未除。
- **恢复**：线主选择接受现状（不再重拍）；后续集在锚点计划/关键帧清单生成参考图集合时排除不露正脸角色的身份牌（待实现）。
- **实现**：（未链接到代码；状态见下）
- **回归**：`tools/tests/test_knowledge_registry.py`
- **证据**：E10 VU-020 重拍 2 的 Q2 人脸比对
- **授权**：Roger 2026-10-01 会话：VU-020 选 C（接受现状）
- **状态**：GUIDANCE_ONLY
### K076 — S7_ASSEMBLY

- **规则**：按集 opt-in ASR 裁剪：有对白单元裁头尾等待帧、保护完整台词；无对白单元保留全长。measured_edit_constraints 信封形状 {unit_id, media_sha256, result:{status:PASS, segments}}，由 build_measured_edit_constraints 从 S6 post_generation_qa 证据生成。
- **教训**：E64 33 单元保留完整供应商素材长度（含等待帧），观众反馈「每秒都是等待」；CC_PIPELINE_FRAMING_EDITING_FIX_PROPOSAL.md §五要求生成长度 vs 使用长度分离。
- **恢复**：tools/measured_edit_constraints.py 已实现区间包含校验与 ASR 不切句；lines/nalu/runtime/tools/build_measured_edit_constraints.py 生成证据信封；nalu_pipeline.py S7 接线传 --measured-edit-constraints；configs/MEASURED_EDIT_POLICY_V1.json 策略配置 nalu E11+。
- **实现**：`tools/measured_edit_constraints.py`、`lines/nalu/runtime/tools/build_measured_edit_constraints.py`、`tools/measured_edit_policy.py`、`configs/MEASURED_EDIT_POLICY_V1.json`
- **回归**：`tools/tests/test_measured_edit_constraints.py`
- **证据**：E64 native_source_receipts.json + audience_review 反馈
- **授权**：CC_PIPELINE_FRAMING_EDITING_FIX_PROPOSAL.md (2026-10-02)
- **状态**：REFERENCE_IMPLEMENTATION

### K077 — S2_PREPRODUCTION

- **规则**：实体数量对账门禁：non_character_entities[].instance_count（声明）vs reference_identity_bindings（绑定）vs compiled_prompt（最终）三方一致。无 instance_count 字段 → 跳过不假设默认值；instance_count 非正整数 → BLOCK。
- **教训**：E64 合同声明两只狸花猫，提交单元只带一张参考图；CC_PIPELINE_FRAMING_EDITING_FIX_PROPOSAL.md §四「两只声明三个实体绑定 / 模板追加同类动物」空缺。
- **恢复**：tools/entity_instance_count_gate.py evaluate(contract, unit_plan, provider_scope_projection, prompt_text) 检查每个有 instance_count 的实体：绑定数 == instance_count && 标签出现在提示词。可选参数扩展 provider_scope_projection 放宽「每实体恒为 1」约束（不动 H3 现有合规路径）。
- **实现**：`tools/entity_instance_count_gate.py`
- **回归**：`tools/tests/test_entity_instance_count_gate.py`
- **证据**：E64 S3 identity_qa_lock: PROP-BLACK-MOON-SEED 一张卡，合同要求四颗
- **授权**：CC_PIPELINE_FRAMING_EDITING_FIX_PROPOSAL.md §四 (2026-10-02)
- **状态**：REFERENCE_IMPLEMENTATION

### K078 — S3_IDENTITY

- **规则**：全复用集（new_asset_groups 为空）的身份审请求必须为空集：构建器要按 reuse.status 丢掉 REUSED_FROM_PRIOR_LIBRARY 主体，且**丢弃结果为空时不能跳过这步过滤**——`if planned:` 这种空集守卫会让过滤在最需要它的那一集静默失效。同理，任何「先看媒体再填答」的审核请求，在其媒体不存在时必须拒绝签发（不是签一张没人能答的 0 有效项请求）。
- **教训**：E11 是首集全复用（38 个资产已 LOCKED、0 新生成）：new_asset_groups=[]，两个有本地源照的角色又都在 61 条 REUSED_FROM_PRIOR_LIBRARY 里，planned 相减为空 → `if planned:` 守卫不成立 → 26 个主体全进请求，其中 23 个指向本集不存在的 plate 路径，S3 永久 REVIEW_REQUIRED。修复后同一缺口在 S6.are 复现：S5 尚 DRY、关键帧未生成，S6.are 仍为一个 20 项、媒体全缺失的 action_role 请求要审核；S5 早有「No review is requested for media that does not exist」这道守卫，S6.are 缺它。
- **恢复**：(1) tools 侧过滤按「计划可读」而非「结果非空」判定：有 plan 文件就应用过滤，即使得空集。(2) 审核签发函数加 skip_when_empty：0 项请求仍落盘为证据，但不置 REVIEW_REQUIRED，阶段继续走复用锁。(3) 每个「看图填答」的请求前，先断言媒体在盘；不在即 BLOCKED 且点名缺失，绝不签发。(4) 子步骤返回 BLOCKED 时要把状态与 blockers 冒泡到 StageResult，不能只返回 detail（否则 body 报 PASS 而首个子步骤已 BLOCKED）。
- **实现**：`lines/nalu/runtime/tools/vlm_review_protocol.py`、`lines/nalu/runtime/tools/nalu_pipeline.py`
- **回归**：`tools/tests/test_nalu_runtime_port.py`
- **证据**：nalu E11 S3/S6 2026-10-05/06（首个全复用集）
- **授权**：nalu production 2026-10-06
- **状态**：REFERENCE_IMPLEMENTATION
### K079 — S1

- **规则**：把逐镜机位契约（K071 的 PER_SHOT_EXPLICIT）打开的同一集，写手层的机位均衡必须同步从「只均衡单元首镜」扩到「按引擎实际展开顺序逐镜检查同族同向与同向两种重复」。均衡顺序：先在本族内换向（PUSH_IN↔PULL_OUT、RISE↔FALL、正/逆时针），本族无解再换族；改动必须读写一致的单一来源。
- **教训**：E11 一开逐镜检查，planning 编译当场报 adjacent grouped units repeat camera motion DOLLY:PUSH_IN: E11-S01-01 -> E11-S01-02，接着是 E11-S01-05 -> E11-S02-01，逐个修会一直在追。全量枚举得 16 处冲突，因为构建器的 balance_camera_directions 只用 [g[0] for g in UNIT_GROUPS] 均衡单元首镜、且它的 ok() 只比方向不比族，而引擎的 grouped_camera_contract 逐镜检查「同族同向」与「同向」两条。37/77 镜是 PUSH_IN，只靠首镜均衡永远压不住。
- **恢复**：构建器新增 balance_shot_camera_sequence()，按 SHOTS 全序逐镜均衡，接进原来的收敛循环与首镜均衡同轮跑（改首镜会改引擎切分，切分变则相邻对变，必须同轮迭代到双稳定）。候选顺序 = 本族另一方向 + 其他族全部。
- **实现**：`lines/nalu/runtime/tools/build_e01_layers.py`
- **回归**：`tools/tests/test_grouped_camera_contract.py`
- **证据**：nalu E11 planning 编译：修前 16 处相邻冲突，修后 validate_camera_sequence 独立复验 PASS，41 单元
- **授权**：nalu production 2026-10-06
- **状态**：REFERENCE_IMPLEMENTATION
### K080 — S1

- **规则**：一个镜头的运镜文字只有一个权威来源：任何自动改机位（族/方向）的步骤都必须同时改写 (a) 该镜的镜头表字段（供关键帧提示词的摄影句）与 (b) 机位方案的 lens_intent／起止取景（供视频提示词），且改写括注里的档位名不得与目标同名（「环绕改为环绕」这类空话说明标注没写对）。
- **教训**：E11 的首镜均衡器只改了 camera_plan 的 motion_family/motion_direction 与文案，没改镜头表的 cam 元组；而 SH() 把 cam[5] 同时放进 shot['camera']（关键帧提示词）和 camera_plan['lens_intent']（视频提示词）。结果同一单元的关键帧说「50mm推近」、视频说「50mm拉开」——两处都是付费文本。另外它把 4 处族已改 ARC 的镜留在「特写推近」，文字与机位直接矛盾；ARC 正/逆两个方向中文同名，标注退回机器名才读得出改了什么。
- **恢复**：改机位统一走 _apply_motion_change()：先按 (族,方向) 词表改文字（同族换向换方向词、跨族换族词），再回写镜头表的 camera 与 cam 元组，最后加标注；_motion_label() 在族内两方向中文同名时退回机器名。回写用的镜头表私有引用 _shot 在对外序列化（合同、引擎分组）时剥离，避免与镜头表成环、污染哈希。
- **实现**：`lines/nalu/runtime/tools/build_e01_layers.py`
- **回归**：`tools/tests/test_keyframe_camera_note_scope.py`
- **证据**：nalu E11：S02-01/S06-00/S07-01/S12-01/S14-01/S15-02/S15-00/S16-01/S16-02/S17-01/S18-00/S19-00 的关键帧摄影句与视频摄影行对不上；统一后 0 处不一致
- **授权**：nalu production 2026-10-06
- **状态**：REFERENCE_IMPLEMENTATION
### K081 — S2

- **规则**：衣柜圣经行由合同的结构化字段生成，而付费身份牌提示词由本集 asset_requirements 的 authored 文案生成；两者冲突时，以「与本集授权文案 + 实际参考图一致」的那份为准并改写结构化字段，不能留着一行自相矛盾的圣经。判定方式：打开该角色的身份牌实物看。
- **教训**：E11 整批提示词门对杨永青报 4 处 kf_wardrobe_hide_coat_consistent FAIL：圣经 outer_layer 写「黑褐旧皮坎肩（外层）」（沿 E04 的结构化字段），authored_description 却写「厚粗布棉衣外罩整张兽皮大衣」；门把「兽皮」判为需要外层兽皮衣（True），而 outer_layer 不含兽皮词（False）。看 E01 身份牌实物：是一件及膝整张毛皮大衣——authored 文案与图一致，旧皮坎肩是 E01/E04 时代的另一套描述，E09/E10 的提示词也一直在说坎肩。按本集授权口径改写结构化字段四个（silhouette/outer_layer/inner_layer/belt_or_fastening），与秦铭那件袍子的同案处理一致。
- **恢复**：改写构建器 WARDROBE_GARMENTS 里该角色的结构化字段，使其与本集授权文案一致；重建 S1/S2 与关键帧清单后重跑 digest，4 处 FAIL 归零。
- **实现**：`lines/nalu/runtime/tools/build_e01_layers.py`
- **回归**：`tools/tests/test_nalu_runtime_port.py`
- **证据**：nalu E11 prompt_batch digest 58 行 4 行 FAIL（E11-S03-02/S03-03/VU-007/VU-023，全为杨永青）；改后 58 行 0 FAIL
- **授权**：nalu production 2026-10-06
- **状态**：REFERENCE_IMPLEMENTATION
### K082 — S1

- **规则**：镜头表的 entry_state 是「本帧唯一允许表现的状态」，逐字绑定、并按 cast 的 character_id 绑到人。它绝不能是上一镜 completion_state 的原样拷贝——只要两镜之间在场人物、道具或场景有任一变化，拷贝出来的那一句就在要求模型画「上一个人做上一个动作」。连续性门新增 ADJACENT_STATE_LEAK（WARN）逐对报出，人在写手层改。
- **教训**：E11 关键帧出图后肉眼复核发现 S08-01 声明 cast=秦铭，画出来却是个留胡子、手握木杖的中年男人。查提示词：S08-01 的 entry_state 写「刘老头站着，木杖重重顿在地上」，与上一镜 S07-03 的 completion_state 逐字相同，而 S07-03 的 cast 是刘老头、道具是木杖；逐实体状态行甚至把这句绑给了 CHAR-QINMING。模型完全照着文字画，没有出错。身份测量因此报 DECLARED_CHARACTER_FACE_NOT_FOUND。全片扫出 21 处逐字相同，其中 19 处 cast 或 props 真的变了。既有的 continuity_state_contract_gate 四项（life_state / creature_card / ambush_space / costume_inheritance）都看不出它——三项看单个实体，一项看整场，没有一项看相邻两镜。
- **恢复**：tools/continuity_state_contract_gate.py 新增 check_adjacent_state_leak()：逐对比较 prev.completion_state 与 cur.entry_state，逐字相同且（cast 集合变了 或 props 集合变了 或 scene_id 变了）则报 ADJACENT_STATE_LEAK:<prev>-><cur>，measurements.adjacent_state_leaks 记 cast_changed/props_changed/scene_changed。定为 WARN 不阻断：同场同人同姿势的硬切本来就该重复那句，门分不出是刻意承接还是顺手拷贝，由写手层处置。
- **实现**：`tools/continuity_state_contract_gate.py`
- **回归**：`tools/tests/test_continuity_state_contract_gate.py`
- **证据**：nalu E11 S1（2026-10-07）：21 处逐字相同，19 处 cast/props 变化；S07-03->S08-01 的付费关键帧画成刘老头模样
- **授权**：nalu production 2026-10-07（Roger 复核 E11 关键帧时发现错人）
- **状态**：REFERENCE_IMPLEMENTATION
### K083 — S7

- **规则**：把异构处理的音频段直接交给 concat demuxer 会出包时间戳前跳/回退，随后 async 重采样补出长段静音。两处必须一致：(a) 有声段与无声段（anullsrc）的采样率/声道必须显式统一，不能一段写死 r=48000、另一段沿用源采样率；(b) 中间音频用统一 PCM，别让每段 AAC 编码延迟累积。主装配链（-filter_complex 逐输入 atrim/asetpts/aresample 再 concat 滤镜）不受影响；受影响的只有 concat demuxer + -c copy 那几处。
- **教训**：Codex 线 2026-10-07 报来 CC_AUDIO_FRAMING_CONTINUITY_FIX.md，说源片段有声但成片长静音，根因是混采样率包时间戳进入 concat demuxer。核对引擎：主链 render_portable_timeline.py 本来就是逐输入重置时基再走 concat 滤镜（安全）；但 build_e39_agentcut_release.py 的 native 分支有声段用 -map 0:a:0 -c:a aac（不带 -ar，沿用源采样率），无声段用 anullsrc=r=48000，两者 `-c copy` 进同一个 concat demuxer——正是它描述的形状。e04/e17 两处同样用 demuxer 但输入是同源同参数渲染，风险低。素材不在本部署，无法实测，故如实标 GUIDANCE_ONLY 而非已修复。
- **恢复**：检查方向：凡 concat demuxer 的输入，逐段 ffprobe 采样率/声道/codec；不一致就显式归一化（统一 -ar 48000 -ac 2，或中间 PCM）再拼。容许的容器舍入差要有命名阈值与依据，不能用无限 apad/async 掩盖截断。
- **实现**：（未链接到代码；状态见下）
- **回归**：`tools/tests/test_audio_postproduction_contract.py`
- **证据**：Codex 线 CC_AUDIO_FRAMING_CONTINUITY_FIX.md（2026-10-07）；引擎侧 build_e39_agentcut_release.py:122-126 与 :220-224
- **授权**：Roger 2026-10-07 转来 Codex 修复要求并要求核对是否合理
- **状态**：GUIDANCE_ONLY
### K084 — S1

- **规则**：关键帧提示词里，镜头入场句点名的人必须落在本镜可见卡司内。渲染器把 entry_state 逐字打印，再把画面里每个人按 character_id 绑定到它；点名者不在卡司里就没有可绑对象，提示词会同时写着「某人正在动作」与「画面内无人物」（engine build_keyframe_manifest 旧行为：把该执行者静默标成 ABSENT_REFERENCE_ONLY／本首帧不入画）。两种形态都要拦：(a) 入场句首句点名了一个本镜卡司完全没有的人；(b) 本镜声明的主动作执行者不在本镜可见卡司里。合法豁免三类——首句点名的就是本镜声明的执行者（生物卡/角色卡同名不同 id）、点名者在本镜卡司里只是非首帧可见（视线/关系目标）、首句以已登记的非人物实体名开头（道具/生物插入镜）。
- **教训**：E11 一集两处同源事故。S08-01 的 entry 写「刘老头站着，木杖重重顿在地上」——与上一镜 S07-03 的 completion 逐字相同，而 S07-03 的 cast 是刘老头、道具是木杖，S08-01 的 cast 只有秦铭；渲染器把这句话整句绑给了唯一可见的人，付费关键帧画回来是个留胡子、握木杖的中年男人，不是秦铭；身份测量因为「脸测得到、余弦 0.7695 PASS」放过了它——测得准，只是测错了人。S03-01 的 entry 写「冯易安转过身朝向门口」（承 S02-03 的收尾），执行者却声明成邻居甲且 cast 为空，逐实体状态因此写「CHAR-VILLAGER-A=本首帧不入画」，同一份提示词里既有「冯易安转过身朝向门口」又有「画面内无人物；空镜」，模型二选一，画回来是门口空着——正是本镜的完成态。既有 continuity_state_contract_gate 复查后确认：四项判据（life_state/creature_card/ambush_space/costume_inheritance）都不看「相邻两镜点名的人是否在本镜」，character_entity_contract 只检查 subject==role actor，都不覆盖它；身份测量又按设计跳过 HANDS_ONLY/空卡司镜，所以两道门都不响。E08 及更早的集扫描出同类 8 处（已播出，不改历史），E09/E10 干净。
- **恢复**：tools/character_entity_contract.py 新增 PRIMARY_ACTOR_NOT_IN_VISIBLE_CAST 与 ENTRY_STATE_NAMES_ABSENT_CHARACTER 两条 fail-closed 检查（entry_state 在镜头层而 _specs() 只给 prompt_spec，故按序配对两列表）；lines/nalu/runtime/tools/build_keyframe_manifest.py::normalize_keyframe_role_semantics 改为 raise ENTRY_STATE_BINDS_TO_ABSENT_ACTOR，不再静默取默认值。修合同：把入场句改成本镜自己的状态（点出本镜在场的人/道具），并把非人物主体镜的执行者登记为对应实体。
- **实现**：`tools/character_entity_contract.py`、`lines/nalu/runtime/tools/build_keyframe_manifest.py`
- **回归**：`tools/tests/test_character_entity_contract.py`
- **证据**：E11 S08-01 关键帧（留胡男子握木杖，声明 cast=秦铭；身份余弦 0.76954 PASS）；E11 S03-01 关键帧（空门口＝完成态）；渲染提示词 workflow/nalu/E11/preproduction/prompts/keyframes/E11-S03-01-KEYFRAME-V1.txt 的「entry 时刻站位」块
- **授权**：Roger 2026-10-08「提示词为什么没有 qa，怎么会犯这么简单的错误，查出原因，修改代码」
- **状态**：REFERENCE_IMPLEMENTATION
### K085 — S5

- **规则**：服装结构性检查要区分「带毛皮的外衣」的肯定与否定表述，且否定必须连同它统辖的衣物词一起剥离——「不披兽皮裘氅」是一处否定；只剥掉「不披兽皮」会剩下一个孤零零的「裘氅」，判定反而转成肯定。反过来，否定词若统辖的是另一件衣物（「无毛领的兽皮大衣」，无只作用于毛领），那件大衣仍然成立。同一镜头文字里既写「披大衣」又写「不披裘氅」时，必须两边都报出来，不能让它们互相抵消。
- **教训**：E11 秦铭的渲染服装行仍带着 E01 资产库的旧文「陈旧兽皮大衣（外层，毛面磨秃、下摆结冰霜）」，而本集结构化字段、本集服装口径、以及逐镜轴线里追加的「秦铭只穿浅色本色粗布交领袍…不披裘氅」都说不披毛皮——提示词自相矛盾，模型这一次选对了（画成素色粗布袍）。旧判据在 outer_layer 里搜「裘氅」原文，把「无外披（全集不披裘氅、不带毛领）」读成「需要毛皮外衣」，于是 expected 与 line 恰好都为真、门一声不响。同时刘老头从未授权服装描述，构建器把上游库里的 AUTHORING_REQUIRED_WARDROBE_STATE_DESCRIPTION 原样继承，并逐字渲染进付费提示词；资产构建报告把这种继承记为 PASS，所以上游没有任何一道门会拦。
- **恢复**：lines/nalu/runtime/tools/prompt_batch_qa.py：新增 mentions_hide_coat()——先剥帽子词，再用 (不披|不带|不穿|没有|无|非)(兽皮|裘氅|毛领|皮袄|皮草|外披|外衣|大衣|衣)+ 剥掉否定连同其统辖的衣物词，然后逐分句判剩余毛皮词；expected 与 line 两侧同用一个函数。另加 kf_no_authoring_required_sentinel：关键帧或视频提示词里出现 AUTHORING_REQUIRED_[A-Z_]+ 即 FAIL。修数据：E11 的 asset_requirements_overlay.wardrobe 补齐秦铭（与结构化字段一致）与刘老头（沿 E08/E09 身份牌）两行。
- **实现**：`lines/nalu/runtime/tools/prompt_batch_qa.py`
- **回归**：`tools/tests/test_prompt_batch_qa_hide_coat.py`
- **证据**：E11 渲染提示词 workflow/nalu/E11/preproduction/prompts/keyframes/E11-S01-03-KEYFRAME-V1.txt 服装锁块（含 AUTHORING_REQUIRED_WARDROBE_STATE_DESCRIPTION）；E11-S01-01 关键帧实物（秦铭为素色粗布袍，并未披毛皮）；runtime/preproduction/E11/asset_requirements_build_report.json 的 authoring_gaps 全为 INHERITED_FROM_PRIOR_LIBRARY
- **授权**：Roger 2026-10-08 要求把这类简单错误的成因查清并修代码
- **状态**：REFERENCE_IMPLEMENTATION
### K086 — S5

- **规则**：身份测量只对「能测到正脸」的镜跑余弦。仅局部镜（HANDS_ONLY／FACE_OUT_OF_FRAME）与空卡司镜一律跳过，不进 per_keyframe 表；这批镜在测量层没有任何客观判据，唯一守着它们的只剩 Q1 的审核者问题 cast_exactly_as_declared（「画面里的人是否与合同声明完全一致」）。所以这批镜一旦 Q1 未作答，整条链上就没有任何一道门在管它们——确定性门看不出来，余弦也不会跑。推论：Q1 的 33 项必须在任何付费重做之前答完；否则重做出来的图同样没人验。
- **教训**：E11 一集 50 张关键帧里只有 26 张进测量。被跳过的 24 张里，四张事后证实画面错误：S12-00 声明只有陆泽的手、画出来却是秦铭站在雪地门前回头；S03-01／S13-02／S20-03 声明无人物，画面里出现了人物或把完成态画了出来。反过来 S08-01 进了测量——余弦 0.76954 PASS、decision=PASS，而画面里根本不是秦铭：测量的语义是「声明的人像不像他本人」，回答不了「画里的人是不是声明的那个」。两条路都不管「画里出现了谁」，而那正是本集实际翻车的形态。查证 keyframe_q1_builder 后确认：这类镜不需要新判据，IDENTITY_GATE 已经带 cast_exactly_as_declared 这道题，且角色无关插入分支（NO_CHARACTER_METHOD）也会把该题计入 failures——缺的是作答，不是判据。
- **恢复**：按 vlm_review_protocol 逐张看图作答 33 项 Q1 请求（缩略总表通读 + 可疑帧放大），重点核 cast_exactly_as_declared；这批镜的答案就是它们的全部保护。作答前不要重做任何关键帧。
- **实现**：（未链接到代码；状态见下）
- **回归**：`lines/nalu/runtime/tools/keyframe_q1_builder.py`
- **证据**：workflow/nalu/E11/preproduction/reports/qa/E11_KEYFRAME_IDENTITY_MEASUREMENT.json（per_keyframe 26 项；S03-01/S12-00/S13-02/S20-03 均不在其中；S08-01 cosine_vs_locked_plate=0.76954、decision=PASS）；lines/nalu/runtime/tools/keyframe_q1_builder.py 的 GATE_QUESTIONS[IDENTITY_GATE] 与 NO_CHARACTER_METHOD 分支
- **授权**：Roger 2026-10-08「提示词为什么没有 qa」
- **状态**：GUIDANCE_ONLY

### K087 — S6

- **规则**：滚动波次一旦写入 wave_state 就冻结成员名单，保护已 POST 的任务不被重发；但一个从未到达供应商 POST 的波次（无提交报告、无已绑定事务、无视频）也被同样冻结，其中若含已不在分组计划里的单元或尚不可提交的派生单元，整个 S6 永久卡死。从未 POST 的开放波次必须释放并重新规划。
- **教训**：E11 的 wave 1 在 10-06 打开，含幽灵单元 E11-VU-042 与待审派生单元 VU-040，从未 POST，却挡住后续所有波次四天。
- **恢复**：nalu_pipeline.py 新增 _units_with_bound_submission() 与 release_unposted_waves()：三条同时成立才释放——无提交报告、无单元在持久事务库有 SUBMITTED_TASK_ID_BOUND、无视频落盘；释放原因写入 wave_state（NEVER_POSTED，附不在计划中的单元名）。
- **实现**：`lines/nalu/runtime/tools/nalu_pipeline.py`
- **回归**：`tools/tests/test_nalu_release_unposted_waves.py`
- **证据**：E11_S6_WAVE_STATE.json 中 wave 1/2 的 release_reason
- **授权**：Roger 2026-10-11：「你所有这些教训不会再下一集还要重犯吧？」——要求把本集暴露的问题写成可复用规则
- **状态**：REFERENCE_IMPLEMENTATION

### K088 — S6

- **规则**：批次失败分类判断「是否全部为供应商拒绝」时，必须先排除在记录意图之前就被本地门禁拒掉、根本没有尝试 POST 的任务；否则一个本地拒绝会让同批真正可重试的网络失败被隔离为 CHARGE_STATE_UNRESOLVED_BATCH。账单行数等于已知 task 数时，可离线对账恢复，不得重发 POST。
- **教训**：E11 wave 9：VU-003 被提示词门本地拒绝（pre-intent），VU-026 遭 DNS 失败；账单 2==2，VU-026 却被错误隔离。
- **恢复**：submit_giggle_video_manifest_v2.py：_attempted() 过滤 pre-intent 失败后再分类；新增 --reconcile-unresolved-report 离线复核路径（只读账单、不 POST）。
- **实现**：`tools/submit_giggle_video_manifest_v2.py`
- **回归**：`tools/tests/test_video_preintent_failure_classification.py`
- **证据**：E11_VIDEO_SUBMIT_V1_wave9 报告与离线对账结果 VERIFIED_ZERO_RETRYABLE
- **授权**：Roger 2026-10-11：「你所有这些教训不会再下一集还要重犯吧？」——要求把本集暴露的问题写成可复用规则
- **状态**：REFERENCE_IMPLEMENTATION

### K089 — S6

- **规则**：派生起始帧（D-68）逐帧单独送审。判断「这张帧是否已答」时必须按帧分别取最新的有效答案（媒体 sha 仍匹配），而不是只看最新一份审核；否则两个派生单元同时待审时，最新审核永远只覆盖另一张，两张轮流被重新请求，流水线永远到不了 Q1 构建，线主已记录的常设规则也无法生效。
- **教训**：E11 的 VU-013 与 VU-040 请求序列为 S19-03→S19-03→S05-06→S05-06；seq=29 常设规则已合法记录却一直不生效。
- **恢复**：nalu_pipeline.py 新增 merge_keyframe_answers()：跨审核合并每帧最新有效答案为一份文件交给构建；任一帧无有效答案则拒绝构建并只请求该帧；帧重新生成即旧答案失效。
- **实现**：`lines/nalu/runtime/tools/nalu_pipeline.py`
- **回归**：`tools/tests/test_nalu_derived_q1_answer_merge.py`
- **证据**：runtime reviews/E11 下 keyframe 请求时间序列与 E11_LINE_OWNER_GATE_ACCEPTANCE.json（standing_rule_order_seq=29）
- **授权**：Roger 2026-10-11：「你所有这些教训不会再下一集还要重犯吧？」——要求把本集暴露的问题写成可复用规则
- **状态**：REFERENCE_IMPLEMENTATION

### K090 — S2

- **规则**：一个单元的尾帧若是下一单元的派生起始帧（CONTINUITY_DERIVED_KEYFRAME），该单元最后一镜的取景文字必须让下一单元开场所需的人物留在画内。「面向某人（画右外）」这类写法会让模型合法地把那人移出画框，尾帧丢主体，下一单元无法开拍，只能付费重做。改完取景后必须在最终提示词里搜到新词再付费。
- **教训**：E11-VU-039 的 S19-02 写「面向秦铭（画右外）」，秦铭自第 2 秒起再未出现（余弦 ≤0.02），尾帧只剩许岳平特写，VU-040 起始帧被拒；改为「秦铭在画右前景、肩线入画、保持在场」后重做一次即解决（160 积分）。
- **恢复**：逐集构建器里该镜补 slots 与在场约束；prompt_batch_finalize diff 确认只改该行后写回执再提交。
- **实现**：（未链接到代码；状态见下）
- **回归**：`lines/nalu/runtime/tools/prompt_batch_finalize.py`
- **证据**：E11-VU-039 新旧两版逐秒余弦；E11_PROMPT_FINALIZATION_DIGEST.json 的单行差异
- **授权**：Roger 2026-10-11：「你所有这些教训不会再下一集还要重犯吧？」——要求把本集暴露的问题写成可复用规则
- **状态**：GUIDANCE_ONLY

### K091 — S5

- **规则**：审核答案里关于「画里是谁」的结论必须来自对锁定身份牌（或已确认参照帧）的人脸余弦测量，不能凭服装或印象；同场两个穿兽皮的中年男性极易互认错。observed_visible_characters 写显示名（如「冯易安」），不要写注册 ID——起始帧凭证按显示名比对，写 ID 会得到 REQUIRED_CHARACTER_NOT_OBSERVED。
- **教训**：E11 本会话我两次凭眼判错：把 S06-03 的许岳平认成刘老头（实测许岳平 0.473），把 VU-039 尾帧的许岳平说成陌生人（实测 0.856）；另一次用 CHAR-FENGYIAN 导致 VU-004 凭证 FAIL、PARTIAL_32_OF_33。
- **恢复**：审核前对每张脸跑 InsightFace 余弦并写入 observation；起始帧填表脚本支持 --overrides 用显示名覆盖。
- **实现**：（未链接到代码；状态见下）
- **回归**：`lines/nalu/runtime/tools/start_frame_evidence_writer.py`
- **证据**：E11 keyframe/start_frame 审核提交记录中的余弦数值
- **授权**：Roger 2026-10-11：「你所有这些教训不会再下一集还要重犯吧？」——要求把本集暴露的问题写成可复用规则
- **状态**：GUIDANCE_ONLY

### K092 — S6

- **规则**：派生起始帧（camera_start_framing=MOTIVATED_CUT）就是上一单元的真实尾帧，不由本镜取景文字生成。审它时机位与景别按继承判读，不得因与本镜 camera 行不符而报景别缺陷；要验的是尾帧金丝雀：本单元需要的主体在画内、声明人物可见、服装正确、未出现 completion_state。背对角色无脸可测属合同设计，由线主常设规则（NO_FACE_PIXELS_IN_STILL）接受。
- **教训**：E11-VU-040：我先写了「景别与主体分配错误」的 P0，提交前对回合同才发现是按错了标准。
- **恢复**：审派生帧先查 opening_anchor_contract.source；是 CONTINUITY_DERIVED_KEYFRAME 就按尾帧标准作答。
- **实现**：（未链接到代码；状态见下）
- **回归**：`lines/nalu/runtime/tools/keyframe_q1_builder.py`
- **证据**：E11-keyframe 审核 E11-S19-03 的 observation
- **授权**：Roger 2026-10-11：「你所有这些教训不会再下一集还要重犯吧？」——要求把本集暴露的问题写成可复用规则
- **状态**：GUIDANCE_ONLY

### K093 — S2

- **规则**：投影里的背景人数/实体例数必须是声明值，不得是常量。两者曾是字面量 0 与 {id: 1}，于是剧本写明的街上行人在机器侧不可表达，且任何非零都会判失败——硬编码把正确结果判成错的。数量由 build_provider_scope_projection 的入参声明，校验器检查字段存在与自洽（unbound ≥ background、例数 ≥1），缺字段是 FAIL 不是默认 0。
- **教训**：E12 街心火泉池与镇主街需要过场人物；此前它们只能落进 forbidden absent terms。
- **恢复**：写集时若画面需要无名过场，声明 background_population_count/visible_entity_instance_counts，或把该角色登记为 ANONYMOUS_FUNCTIONAL 身份层（K096）。
- **实现**：`tools/provider_scope_projection.py`、`tools/h3_provider_prompt_renderer.py`
- **回归**：`tools/tests/test_pregen_consistency_retry_closure.py`
- **证据**：tools/tests/test_pregen_consistency_retry_closure.py（用例：hardcoded-population-count-hides-scripted-crowds 对应的 TestCase）
- **授权**：Roger 2026-10-16：转来共享引擎「生成前一致性与付费重试闭环修复」提案，要求先给归属再修，只改通用代码/配置/测试/运行手册
- **状态**：REFERENCE_IMPLEMENTATION

### K094 — S2

- **规则**：同一语义的开关字段只允许一套词表。单主体模式曾有三处拼法：投影/渲染 provider_scope_prompt_mode、镜像预检 scope_mode、视频提交 h3_prompt_profile，取值后缀还各不相同 → 改一处另两处不会跟进。现在统一经 provider_scope_projection.normalize_prompt_mode 归一，未知值保持原样而非吞成默认。
- **教训**：三处拼法意味着任何一次语义变更都只生效三分之一，且没人会注意到。
- **恢复**：新增模式先在 normalize_prompt_mode 的别名表登记，再在三个调用点使用。
- **实现**：`tools/provider_scope_projection.py`、`tools/submit_giggle_image_manifest.py`
- **回归**：`tools/tests/test_pregen_consistency_retry_closure.py`
- **证据**：tools/tests/test_pregen_consistency_retry_closure.py（用例：one-flag-three-spellings 对应的 TestCase）
- **授权**：Roger 2026-10-16：转来共享引擎「生成前一致性与付费重试闭环修复」提案，要求先给归属再修，只改通用代码/配置/测试/运行手册
- **状态**：REFERENCE_IMPLEMENTATION

### K095 — S2

- **规则**：参考图按角色分层：只有身份位承载脸并声明 exclusive_identity_owner，场景/空间/道具位声明 may_define_identity=false。此前所有绑定一律渲染成 exclusive identity of X，于是一张放错位的拓扑图读起来就是一张身份锚。提交前预检比对声明角色与 id 命名空间，不一致即 REFERENCE_ROLE_SEMANTICS_INVALID；两张身份位共用同一文件也判失败。
- **教训**：E12 关键帧有 4–5 张参考图（全集空间图/本地空间图/子空间/场景/道具），角色混淆与串图由此而来。
- **恢复**：绑定参考图时同时给出 role；预检报 REFERENCE_ROLE_NAMESPACE_CONFLICT 就是槽位被换过。
- **实现**：`tools/provider_scope_projection.py`、`tools/shot_media_admission_gate.py`、`tools/h3_provider_prompt_renderer.py`
- **回归**：`tools/tests/test_pregen_consistency_retry_closure.py`
- **证据**：tools/tests/test_pregen_consistency_retry_closure.py（用例：reference-plate-role-tiers 对应的 TestCase）
- **授权**：Roger 2026-10-16：转来共享引擎「生成前一致性与付费重试闭环修复」提案，要求先给归属再修，只改通用代码/配置/测试/运行手册
- **状态**：REFERENCE_IMPLEMENTATION

### K096 — S2

- **规则**：角色表新增身份层 identity_tier（NAMED / ANONYMOUS_FUNCTIONAL / BACKGROUND_CROWD）。非 NAMED 角色不进 forbidden absent terms，而是进 anonymous_role_descriptors，由人口子句声明为可入画的过场；脸不做身份比对。此前无名路人只有禁区词表一个去处。
- **教训**：审核把匿名过场判成「未列入允许入画名单」——判读错，但缺这一层是代码侧的成因。
- **恢复**：剧本需要店小二、路人、围观者时，在角色表登记其 identity_tier，不要塞进具名角色表。
- **实现**：`tools/provider_scope_projection.py`
- **回归**：`tools/tests/test_pregen_consistency_retry_closure.py`
- **证据**：tools/tests/test_pregen_consistency_retry_closure.py（用例：anonymous-functional-role-tier 对应的 TestCase）
- **授权**：Roger 2026-10-16：转来共享引擎「生成前一致性与付费重试闭环修复」提案，要求先给归属再修，只改通用代码/配置/测试/运行手册
- **状态**：REFERENCE_IMPLEMENTATION

### K097 — S6

- **规则**：生产实际执行的是仓库内 main()，不是 exec_deployed_submitter()。预检链（retry_cap / action contract / input_template_id / precheck_submission_inputs）此前只存在于后者，而后者无人调用，于是仓库路径比部署路径少校验。现在抽出 validate_task_submission_gates，两条路径都调它，并有 AST 测试断言 main() 必须调用它。
- **教训**：死代码里的门等于没有门；契约测试只覆盖三个函数，漏掉的就是这个分支。
- **恢复**：新增付费前门时，写进 validate_task_submission_gates，不要写进某一个入口。
- **实现**：`tools/submit_giggle_video_manifest_v2.py`
- **回归**：`tools/tests/test_pregen_consistency_retry_closure.py`
- **证据**：tools/tests/test_pregen_consistency_retry_closure.py（用例：repo-entrypoint-must-run-every-deployed-gate 对应的 TestCase）
- **授权**：Roger 2026-10-16：转来共享引擎「生成前一致性与付费重试闭环修复」提案，要求先给归属再修，只改通用代码/配置/测试/运行手册
- **状态**：REFERENCE_IMPLEMENTATION

### K098 — S6

- **规则**：重抽账本只有读取方没有写入方：守卫按 events 计算第几次重抽、集级预算、重复原因规则，但没有任何代码 append 事件 → events 恒空、reroll_number 恒 1、预算永不推进。写入器与读取器同址放在 reroll_cost_guard，构建重抽请求时记 outcome=REQUESTED（请求不消耗预算，只有 SUBMITTED/COMPLETED 计数）。
- **教训**：自动重抽的上限与预算此前从未真正生效，因为没有历史可数。
- **恢复**：新增任何账本读取方前，先确认写入方存在且双方对 outcome 词表一致。
- **实现**：`tools/reroll_cost_guard.py`、`lines/nalu/runtime/tools/post_generation_qa_runner.py`
- **回归**：`tools/tests/test_pregen_consistency_retry_closure.py`
- **证据**：tools/tests/test_pregen_consistency_retry_closure.py（用例：reroll-ledger-needs-a-writer 对应的 TestCase）
- **授权**：Roger 2026-10-16：转来共享引擎「生成前一致性与付费重试闭环修复」提案，要求先给归属再修，只改通用代码/配置/测试/运行手册
- **状态**：REFERENCE_IMPLEMENTATION

### K099 — S6

- **规则**：策略文件里声明的键必须有读取方，否则它只是文档。block_failure_classes 与 advise_margin_fraction 此前无人读：现在前者参与判定（策略阻断类必须按 BLOCK 层），后者参与告警（剩余预算比例低于该值时不再只是 ADVISE），两者都进结论供调用方查。
- **教训**：无法被读取的策略键会让人以为已经配好了保护。
- **恢复**：改策略文件时同步确认消费者；没有消费者的键应在文件里标 GUIDANCE_ONLY。
- **实现**：`tools/reroll_cost_guard.py`
- **回归**：`tools/tests/test_pregen_consistency_retry_closure.py`
- **证据**：tools/tests/test_pregen_consistency_retry_closure.py（用例：policy-keys-must-be-read 对应的 TestCase）
- **授权**：Roger 2026-10-16：转来共享引擎「生成前一致性与付费重试闭环修复」提案，要求先给归属再修，只改通用代码/配置/测试/运行手册
- **状态**：REFERENCE_IMPLEMENTATION

### K100 — S6

- **规则**：审核结论除 failure_attribution 外给出 cause_confidence：DETERMINATE 来自不可能判错的比较（文件缺失、SHA 不符、角色与命名空间冲突），INFERRED 来自本门套用的规则，NOT_APPLICABLE 表示无失败。两者在重试规则里待遇不同，此前的结论无法区分。
- **教训**：没有置信度字段时，机器判定的硬事实与审核者的推断长得一模一样。
- **恢复**：读结论时先看 cause_confidence 再决定是重做还是先复核判读。
- **实现**：`tools/shot_media_admission_gate.py`
- **回归**：`tools/tests/test_pregen_consistency_retry_closure.py`
- **证据**：tools/tests/test_pregen_consistency_retry_closure.py::CauseConfidenceTest
- **授权**：Roger 2026-10-16：转来共享引擎「生成前一致性与付费重试闭环修复」提案，要求先给归属再修，只改通用代码/配置/测试/运行手册
- **状态**：REFERENCE_IMPLEMENTATION

### K101 — S2

- **规则**：状态差证据必须是身体/物件的物理状态，不得是对白。v4 适配器缺声明时把维度默认成 POSTURE、把画面描述填进结束态，画面描述有时就是一句台词；动作密度门只比两个字符串和两个代码，于是台词被当成姿态变化放行。STATE_DELTA_SEMANTICS_V1：证据或端点等于本拍台词即 STATE_DELTA_EVIDENCE_IS_DIALOGUE；非打斗对白镜可声明 STATIC_POSTURE_PERFORMANCE（姿态不变、靠台词与表演推进），须有表演证据；打斗镜不得用此声明，两维下限与全部打斗检查照旧。适配器缺证据改为报缺失，不再编造。构建器原把 action_kind 写死为 NON_COMBAT，使全线打斗检查失效；现透传作者声明并统一为 COMBAT。
- **教训**：字段、哈希、格式都合格，变化却只是字符串不同；合法的静止对白镜反而只能靠编造转头过门。
- **恢复**：对白镜姿态确实不变时在合同 action 写 state_delta_mode=STATIC_POSTURE_PERFORMANCE；打斗镜写 action_kind=COMBAT 并给两维物理结果。按集在 configs/STATE_DELTA_SEMANTICS_V1.json 启用。
- **实现**：`tools/sd2_motion_density_gate.py`、`lines/nalu/runtime/tools/adapt_v4_layers_to_runtime.py`、`lines/nalu/runtime/tools/build_nalu_preproduction.py`、`tools/video_execution_plan_compiler.py`
- **回归**：`tools/tests/test_state_delta_semantics.py`
- **证据**：tools/tests/test_state_delta_semantics.py（对白入证据、合法静止对白、打斗仍需结果、未启用集兼容）
- **授权**：Roger 2026-10-16：通用生产线优化方案 §5「停止用字符串变化冒充动作变化」，要求先修已复现的错误链
- **状态**：REFERENCE_IMPLEMENTATION

### K102 — S2

- **规则**：付费前用已有素材做零费用预演：tools/episode_previs.py 从合同、分组计划、已有关键帧（无图用占位卡）生成时间线，机器检查对白覆盖与未授权重复、对白能否装进本镜、镜头缺失/重复/未入单元、说话人与演员 ID 是否登记；对白时长无实测音频时一律标 ESTIMATED。导演审查问题不阻断，最多两轮，之后转 ADVISORY，不自动重生成。场景导演意图未声明只报建议项，不替作者编。
- **教训**：字段、哈希、格式都合格的镜头设计仍可能有歧义，付费之后才看见就要花钱重做。
- **恢复**：S2 后跑 episode_previs.py；机器失败改权威合同再跑，主观问题最多两轮。需要看片时加 --render，用现有 render_portable_timeline.py 出片。
- **实现**：`tools/episode_previs.py`
- **回归**：`tools/tests/test_previs_and_timing_map.py`
- **证据**：tools/tests/test_previs_and_timing_map.py
- **授权**：Roger 2026-10-16：通用生产线优化方案 §4/§6/§7，按顺序执行第二、三、四步
- **状态**：REFERENCE_IMPLEMENTATION

### K103 — S6

- **规则**：审核要绑定真正发出去的请求，而不是某个文件。tools/provider_request_digest.py 对提示词正文、模型参数、按顺序的参考图（盘上 sha + 角色）、音频列表算一个摘要；两个提交器在所有适配与序列化之后、记意图之前比对 reviewed_request_sha256，不符即拒绝，零 POST、无事务记录。发送时压缩后的实际图片字节另记 sent_reference_sha256（传输证据，不进审核摘要）。启用的集里，已按另一指纹提交过的任务必须声明 supersedes_submission_fingerprints 才能再 POST。视频 payload 组装挪到意图之前，顺带修掉 H3 配音 asset_id 报错留下“在途”事务的问题；压缩记录改为线程安全。
- **教训**：H3 重渲染、参考图重排、配音挂接、发送时压缩都发生在审核回执之后，回执只绑文件 sha，管不住实际请求。
- **恢复**：审核完成后、付费授权前运行 tools/provider_request_digest.py --manifest 写入 reviewed_request_sha256；在 configs/PROVIDER_REQUEST_REVIEW_BINDING_V1.json 按集启用。
- **实现**：`tools/provider_request_digest.py`、`tools/submit_giggle_video_manifest_v2.py`、`tools/submit_giggle_image_manifest.py`、`tools/giggle_api_client.py`
- **回归**：`tools/tests/test_provider_request_binding.py`
- **证据**：tools/tests/test_provider_request_binding.py（API mock 证明不符时零 POST）
- **授权**：Roger 2026-10-16：通用生产线优化方案 §4/§6/§7，按顺序执行第二、三、四步
- **状态**：REFERENCE_IMPLEMENTATION

### K104 — S6

- **规则**：剧情时长、对白时长、请求时长、返回素材时长、剪辑区间是五个数，分开记录并标来源：tools/unit_timing_map.py。同一句台词只能由一个单元生成（DIALOGUE_GENERATED_BY_TWO_UNITS）；请求超出剧情内容的余量如实记录；只有真有尾帧依赖的单元串行，其余并发。分组门原来对超出建议窗口的单元自动贴例外原因并放行，从不检查硬上限；现在例外原因只能解释离开建议窗口，不能越过硬上下限。
- **教训**：一个数同时代表剧情、请求和剪辑，补余量、截台词、冻帧凑时长都会悄悄发生。
- **恢复**：S2 后跑 unit_timing_map.py；收割后加 --media-dir，剪辑后加 --edit-decisions。
- **实现**：`tools/unit_timing_map.py`、`tools/video_unit_grouping_gate.py`
- **回归**：`tools/tests/test_previs_and_timing_map.py`
- **证据**：tools/tests/test_previs_and_timing_map.py
- **授权**：Roger 2026-10-16：通用生产线优化方案 §4/§6/§7，按顺序执行第二、三、四步
- **状态**：REFERENCE_IMPLEMENTATION

### K105 — S5

- **规则**：①关键帧的逐角色入帧姿态是「计划」字段 entity_entry_states，每个可见角色必须有一条点名自己的姿态；构建器缺字段直接 SystemExit(ENTITY_ENTRY_STATE_REQUIRED)，不得用 completion_state、整句 entry_state 或 NON_ACTOR 默认值顶替。②Q1 证据里 planned_measurable_character_ids（计划）与 measured_character_ids（引擎实测行）分开写，measurement_evidence 标明来源；计划不得写成观察。③删服装参考只按 configs/KEYFRAME_WARDROBE_REFERENCE_POLICY_V1.json 的作品作用域（asset_library.project_id）+ drop_wardrobe_references=true + active_from_episode 生效，且需替代证据（该镜每个角色都有 服装锁 文本）；未声明作品、无策略文件、作用域/集号不可解析、激活前集次，一律保持参考数组与顺序原样并写明 reason。④部署 SHA 清单必须覆盖 lines/ 下受 git 跟踪的生产入口。
- **教训**：E12 S5 八镜 DECLARED_CHARACTER_FACE_NOT_FOUND：build_e12_layers.entity_states_for 把 exit 当 actor 状态 → normalize_keyframe_role_semantics 发现等于 completion_state 就整句替换为 entry_state → S15-01 冯易安拿到「许岳平又垂下眼」、S17-03 冯易安拿到「巡山者甲靠回椅背」，模型照画别人，脸没出现；两次付费重做都复现同一错误。同期 b9850c7 用 episode_num>=10 硬删服装参考：E10 51/51、E11 48/50 已付费登记的提示词都带服装牌，按该硬编码重编会全部漂移。deployment_code_integrity 的 file_count 与 files 长度不一致导致校验直接抛错，且 lines/ 从未入清单。
- **恢复**：构建器 SH() 加 entries={...} 逐角色写入帧姿态并发出 entity_entry_states；keyframe_q1_builder 分写 planned/measured；cap_non_character_bindings 改为 wardrobe_decision+wardrobe_text_present 驱动、episode 不再是决策输入；deployment_code_integrity.included 纳入 lines/ 并 --build 重建；.gitignore 允许列表加新配置；三组关键帧测试进 PORTABLE_CORE_MANIFEST.portable_test_modules（原 transport_count 是 pytest 裸函数，unittest 收集为 0）。
- **实现**：`lines/nalu/runtime/tools/build_keyframe_manifest.py`、`lines/nalu/runtime/tools/keyframe_q1_builder.py`、`configs/KEYFRAME_WARDROBE_REFERENCE_POLICY_V1.json`、`tools/deployment_code_integrity.py`
- **回归**：`tools/tests/test_keyframe_wardrobe_reference_policy.py`
- **证据**：A/B 同输入重编：E10 已登记 wardrobe=51/51、HEAD 硬编码=0/51、本修复=51/51；E11 48/50、0/49、47/49。E12 重建合同 111 镜 entity_entry_states 全部点名本人，其余字段与重建前逐项相同。
- **授权**：Roger 2026-10-17（codex 共享修复审查六条 + 补充六条）
- **状态**：REFERENCE_IMPLEMENTATION

### K106 — S5

- **规则**：图片事务离线对账：嵌入式批次元组 (known, pay_rows, unmapped) 与归档账单相等只证明「同一批」，不证明「未扣费」。unmapped_pay_row_count ≠ 0 的事务一律保持 CHARGE_STATE_UNRESOLVED_BATCH；只有 K054 条件（Pay 行数 == 已绑定 任务标识数）或零扣费闭合窗口才允许 NOT_CHARGED_RETRYABLE。重分类写入的 batch_unmapped_pay_rows 必须来自证据，不能写常量 0。提供者上游超时会先扣费再丢 任务标识：停下，等恢复后用已绑定旧 任务标识 的免费 GET 探通路，再决定是否重做。
- **教训**：E12 S5 重做 10 镜，10 行 Pay、0 个 任务标识，提交器正确隔离；对账工具按 (0,10,10) 命中账单把 10 条全改成可重试并把 unmapped 覆写成 0，随后两次付费重跑在同一故障窗口又扣 88+77 积分。三轮 275 积分，0 张新图。
- **恢复**：reconcile EMBEDDED 分支加 unmapped==0 守卫（跳过原因 EMBEDDED_BATCH_HAS_UNMAPPED_PAY_ROWS）；误改事务离线回退为隔离态并记录 reconciliation_reverted；旧 BOUND 事务放回存档目录。
- **实现**：`tools/reconcile_giggle_image_transactions.py`
- **回归**：`tools/tests/test_reconcile_giggle_image_transactions.py`
- **证据**：E12 三个账单窗口 07:53/09:28/09:38，10+8+7 行 Pay，provider_response 均为 code 500 i/o timeout 或 502 presigned URL。
- **授权**：Roger 2026-10-18
- **状态**：REFERENCE_IMPLEMENTATION

### K107 — S2

- **规则**：说话人身份绑定与交流空间关系是两件事。角色行可选声明六个空间字段（说话人朝向/视线、听者相对位置/朝向/视线、画外视觉线索），缺省不渲染也不推断；对某人说话不等于看着某人，低头、看道具、看画外、主动看镜头都合法；视线目标必须在已登记实体内；已声明站位时画外听者必须给视觉线索。SD2 与 H3 分别渲染，H3 走英文合同翻译。
- **教训**：E66 VU030 首帧人物正面居中、视线近乎朝镜头，视频提示词只把另一方写成画外听者，没写听者在哪一侧、双方视线如何对应，朝镜头倾向从输入带到成片。
- **恢复**：写手按需补六个空间字段，不写就不补默认；改字段会使执行语义指纹变化，旧英文合同与请求审核按既有规则失效。
- **实现**：`tools/spatial_dialogue_contract.py`、`tools/role_semantic_prompt_gate.py`、`tools/sd2_provider_prompt_renderer.py`、`tools/h3_provider_prompt_renderer.py`、`tools/h3_english_contract_io.py`、`tools/h3_provider_english_contract.py`、`tools/video_execution_plan_compiler.py`
- **回归**：`tools/tests/test_spatial_dialogue_contract.py`
- **授权**：Roger 2026-10-18
- **状态**：REFERENCE_IMPLEMENTATION

### K108 — S2

- **规则**：单元划分是生产包装，不是叙事节拍。单元可声明 action_event_contract（event_id、phase、continues_event_id、authorized_repeat）；相邻边界检查「已完成动作被重新 START」「同一事件被二次 START」「CONTINUE 指向已完成事件」，作者安排的重复必须带出处。未声明的单元不阻断。禁止文本相似度。
- **教训**：E66 约 23 秒对峙拆六个单元，每段独立起势，拼起来反复重演。此前没有跨单元重演判据。
- **恢复**：为跨单元连续动作声明事件与阶段；重演须授权并写出处。
- **实现**：`tools/unit_action_continuity_contract.py`、`tools/build_video_unit_anchor_plan.py`
- **回归**：`tools/tests/test_unit_action_continuity_contract.py`
- **授权**：Roger 2026-10-18
- **状态**：REFERENCE_IMPLEMENTATION

### K109 — S7_ASSEMBLY

- **规则**：S7 在配乐混音后、响度精修前，对同一音轨在每个单元边界做对称音量下潜（默认 0.08 s），视频复制、总时长不变；下潜不是静音，空间底噪连续。按集启用，默认不改在产集；下潜失败即阻断装配。
- **教训**：E65 修复版为去掉错误对白把三段直接静音，缺连续环境声甚至保留嘴在动的画面。
- **恢复**：开启该集切点连续化并核对边界数；真正缺失素材仍按缺陷门重做。
- **实现**：`tools/assembly_audio_continuity_policy.py`、`tools/audio_cut_overlap.py`、`configs/ASSEMBLY_AUDIO_CONTINUITY_V1.json`、`lines/nalu/runtime/tools/nalu_pipeline.py`
- **回归**：`tools/tests/test_assembly_audio_continuity.py`
- **授权**：Roger 2026-10-18
- **状态**：REFERENCE_IMPLEMENTATION

### K110 — S7_ASSEMBLY

- **规则**：供应商槽长是天花板不是成片长度。任务元数据可声明 editorial_keep_seconds 与 verified_speech_end_seconds；含对白单元只有给出已核实语音结束点才允许剪短，否则报 EDITORIAL_SPEECH_BOUNDARY_REQUIRED；应用结果写入 clip_metadata.editorial_keep。
- **教训**：各单元按整槽固定长度剪辑，短句后保留大段等待，节奏由生成槽决定；editorial_duration 已实现但无生产调用方。
- **恢复**：声明 keep 目标；含对白必须带已核实结束点；不声明时行为与之前一致。
- **实现**：`tools/build_agentcut_from_admitted_storyboard_sources.py`、`tools/editorial_pacing_contract.py`
- **回归**：`tools/tests/test_editorial_pacing_contract.py`
- **授权**：Roger 2026-10-18
- **状态**：REFERENCE_IMPLEMENTATION

### K111 — TRANSACTIONS

- **规则**：付费前预算判定必须是原子预留。`build_report(reserve_if_pass=True)` 判定通过即在 flock 保护下追加一条 reservation 到 `workflow/nalu/<EP>/BUDGET_RESERVATION.jsonl`，锁内重扫，因此两个并发进程最多一个取得预留。CLI 以 `--reserve` 触发、`--release-reservation <id>` 追加释放行；`nalu_pipeline` 的 `paid_step` 在真正执行前预留，退出码为 0 才释放，非 0 保留并写 `KEEP_UNTIL_LEDGER_RECONCILIATION`——超时不得当作未扣费。判定对象是 `projected = recorded + active_reserved + pending_exposure + planned`；`estimated_credits` 按模型计价（SD2 20/秒；MiniMax-H3 14/秒 + 6/任务），旧事务按视频 160 / 图片 11 的保守上限计。`--check` 保持只读。
- **教训**：`--check` 只读不记录预留，两个并发调用各读 recorded=7000、各申请 600，双双通过 8000 上限，合起来放行 8200；已提交未对账的 `SUBMITTED_TASK_ID_BOUND` 任务不计入暴露。第一版修复只接到测试，CLI 与付费路径都没有调用方；视频暴露一律按 20/秒计，会把 H3 集高估约 30%。
- **恢复**：付费调用方用 `reserve_if_pass=True` 或 `--reserve` 取原子预留；失败即 HARD_STOP。花费绑定后 `--release-reservation`；非 0 退出保留预留走对账。
- **实现**：`lines/nalu/runtime/tools/nalu_budget_ledger.py`、`lines/nalu/runtime/tools/nalu_pipeline.py`、`tools/submit_giggle_video_manifest_v2.py`、`tools/submit_giggle_image_manifest.py`
- **回归**：`tools/tests/test_concurrent_dispatch.py`
- **证据**：`BudgetConcurrentReservationRepro` 修改前 FAIL（BUDGET_CHECK_THEN_ACT / PENDING_EXPOSURE_NOT_COUNTED），修改后 PASS；CLI 接线、失败保留预留、H3/SD2 分价各有用例
- **授权**：Roger 2026-10-18「单集内全流程并行，检查不缩水，预算不超支」
- **状态**：REFERENCE_IMPLEMENTATION

### K112 — S5

- **规则**：非付费准备阶段逐镜编译并发执行。`build_keyframe_manifest.compile_tasks` 用 `ThreadPoolExecutor` 并发调用 `compile_task`（默认 `min(8, 镜数)`），每镜写自己的 prompt 文件、只读共享不可变输入；唯一跨镜可变数据 `dropped_prompt_segments` 按镜收集、池排空后按输入顺序合并，避免并发 `append` 交错导致报告不确定。任一镜抛错则整批失败，半套 prompt 不得报成功。`workers=1` 保留串行路径且输出顺序一致。真正收益在 `compile_task` 内部对参考图的 SHA 校验（文件 I/O 释放 GIL）。
- **教训**：S5 关键帧清单构建曾用单线程列表推导逐镜编译，一镜慢读取拖住其后所有镜，而这些镜之间没有真实依赖。
- **恢复**：新增逐镜准备工作时复用并发+有序归并模式；跨镜共享累加数据一律按任务收集后归并。
- **实现**：`lines/nalu/runtime/tools/build_keyframe_manifest.py`
- **回归**：`tools/tests/test_keyframe_compile_parallel.py`
- **授权**：Roger 2026-10-18「单集内全流程并行，检查不缩水」
- **状态**：REFERENCE_IMPLEMENTATION

### K113 — S6

- **规则**：视频状态轮询按波并发。`poll_giggle_submit_report.poll` 把逐任务 `query_task` 与逐 URL 下载放到 `ThreadPoolExecutor`（默认 `min(6, 任务数)`，`NALU_POLL_WORKERS` 可覆盖），结果按提交报告原始顺序回填，状态文件保持稳定；任一任务查询抛错仍使整次轮询失败，与串行时一致。缺少远端任务标识的行不进线程池，直接记 `NO_TASK_ID`。下载仍走 `.part`→replace 原子替换且已存在即跳过。
- **教训**：S6 每个调度 tick 都要对整波单元查一次远端状态；旧循环逐任务串行 `query_task`、逐 URL 串行下载，6 个单元就是 6 次串行往返，且这段等待落在每次 tick 上。
- **恢复**：轮询端新增远端调用时沿用 `poll_one` + 有序回填的并发结构；限流用 `NALU_POLL_WORKERS`，不要按波次大小硬编码。
- **实现**：`tools/poll_giggle_submit_report.py`
- **回归**：`tools/tests/test_poll_giggle_submit_report.py`
- **证据**：`PollConcurrencyTest`：Barrier 断言四任务真实重叠、慢任务不改变行序、单任务异常使整次轮询失败、worker 数默认与覆盖行为
- **授权**：Roger 2026-10-18「单集内全流程并行，检查不缩水」
- **状态**：REFERENCE_IMPLEMENTATION

### K114 — S5

- **规则**：图片批次收割按波并发。`harvest_giggle_image_batch.poll_once` 把逐任务 `query_task` 与逐张下载抽成 `harvest_one`，放到 `ThreadPoolExecutor`（默认 `min(6, 任务数)`，`NALU_HARVEST_WORKERS` 可覆盖），结果按提交报告原始顺序回填，`status_counts` 与 `all_terminal`/`all_completed` 因此稳定；任一任务查询抛错仍使整轮失败。每任务只写自己的 raw 响应与图片文件（按任务键 + 远端标识命名），批次级 credit 分配在调用方只读计算一次后传入，不在线程里重算。`--watch` 每轮的串行往返因此消失。
- **教训**：S3/S5 的图片批常在 50 个任务量级，`--watch` 每 15 秒轮询一轮；旧 `poll_once` 逐任务串行查询并逐张下载，每轮约 50 次串行 HTTP 往返。
- **恢复**：收割端新增远端调用时沿用 `harvest_one` + 有序回填的并发结构；限流用 `NALU_HARVEST_WORKERS`；批次级账单分配保持在调用方计算一次。
- **实现**：`tools/harvest_giggle_image_batch.py`
- **回归**：`tools/tests/test_harvest_giggle_image_batch.py`
- **证据**：`HarvestConcurrencyTest`：Barrier 断言四任务真实重叠、慢任务不改变行序、单任务异常使整轮失败、worker 数默认与覆盖行为
- **授权**：Roger 2026-10-18「单集内全流程并行，检查不缩水」
- **状态**：REFERENCE_IMPLEMENTATION

### K115 — S4

- **规则**：配音参考按角色并发。`s4_generate_all` 用 `ThreadPoolExecutor`（`min(max_parallel, 角色数)`）并发执行 `s4_generate_one`（语音生成 → 归一化 → 上传），结果按待办顺序回填。每个角色持有自己的持久音频事务、自己的 wav 与自己上传回执，互不共享；但 `voice_registry` 是整份读改写，所以 registry 行只由调用方在池排空后按顺序写入，绝不放进线程。预算按任务各预留 2 分（原子预留已使并发不会合计超限）；旧的 `remaining_credits = 2 × 剩余角色数` 是串行假设，并发下会重复计入。单角色 HARD_STOP/BLOCKED 仍使整阶段停止并报告，不静默跳过。
- **教训**：S4 曾逐角色生成、逐角色等语音提供者轮询到完成（2 秒间隔、最长 300 秒），N 个新角色就是 N 次串行的独立等待；这些角色之间没有真实依赖。
- **恢复**：新增按角色的付费准备时沿用「并发执行 + 有序回填 + 共享文件只在主线程写」的结构；预算按任务预留，不要用剩余总数代替单个任务。
- **实现**：`lines/nalu/runtime/tools/nalu_pipeline.py`
- **回归**：`tools/tests/test_nalu_s4_concurrency.py`
- **证据**：`S4ConcurrencyTest`：Barrier 断言三角色真实重叠、结果顺序等于待办顺序、单角色 HARD_STOP 被报告、每任务只预留 2 分、`workers=1` 走串行路径
- **授权**：Roger 2026-10-18「单集内全流程并行，检查不缩水，预算不超支」
- **状态**：REFERENCE_IMPLEMENTATION

### K116 — S5

- **规则**：Q1 静帧 OCR 并发。`ocr_keyframes` 在装配循环之前一次性对全部静帧并发调用引擎的 OCR 子进程（默认 `min(4, 静帧数)`，`NALU_Q1_OCR_WORKERS` 可覆盖），结果按 `item_id` 归档，随后每项装配仍严格保持原顺序。OCR 模型冷启动是每次调用的主要成本，串行等于按静帧数重复付这份开销。关键陷阱：一个视频单元可承载多个静帧，而遗留输出名是按单元命名的 `ocr_audit.json`，同一单元的第二个静帧必须改写 `ocr_audit_<item>.json`，否则两个进程争写同一文件；单元内第一个静帧仍沿用遗留名，使既有「同一输入 + 同一策略即复用」的缓存继续命中。缺失素材在此跳过，由调用方按自身顺序拒绝。
- **教训**：S5 Q1 装配循环逐静帧串行执行 OCR 子进程，一次重建里静帧数就是启动开销的倍数，而静帧之间没有依赖。
- **恢复**：新增逐静帧的引擎调用时复用「先并发、后按序装配」结构；凡按单元命名的中间产物都要先确认单元内是否会有第二个同类项。
- **实现**：`lines/nalu/runtime/tools/keyframe_q1_builder.py`
- **回归**：`tools/tests/test_keyframe_q1_ocr_parallel.py`
- **证据**：`OcrKeyframesConcurrencyTest`：Barrier 断言四个静帧真实重叠、同一单元两个静帧输出不同报告且首个保留遗留名、缺失素材不被扫描、结果按 `item_id` 归档
- **授权**：Roger 2026-10-18「单集内全流程并行，检查不缩水」
- **状态**：REFERENCE_IMPLEMENTATION

### K117 — S7_ASSEMBLY

- **规则**：S7 字幕时间轴按单元并发转写。`transcribe_units` 对每个单元片并发执行一次 whisper（默认 `min(2, 单元数)`，`NALU_S7_ASR_WORKERS` 可覆盖），结果按单元片名（stem）归档，字幕构建器正是按该键取用，因此完成顺序不影响字幕。整个运行只构造一个 `WhisperModel` 并在线程间共享：它封装 ctranslate2，支持同一模型上的并发调用；每线程各建一个模型只会成倍占用内存。默认并发刻意取 2 而不是更大：whisper 在 CPU 上本身已用多线程，再把 worker 数堆高只会互相争抢核心；该上限由环境变量调整，不改代码。任一单元抛错仍使整步失败。
- **教训**：S7 烧录字幕前用单线程循环逐单元调用 whisper，单元之间没有依赖，每个单元都要付一次模型的文件级开销；整集十几到几十个单元就是十几次串行转写。
- **恢复**：新增逐单元的音视频分析时沿用「单个共享模型 + 并发转写 + 按单元键归档」的结构；并发上限给环境变量，不要按单元数硬编码。
- **实现**：`lines/nalu/runtime/tools/nalu_pipeline.py`
- **回归**：`tools/tests/test_s7_asr_parallel.py`
- **证据**：`TranscribeUnitsConcurrencyTest` 断言四个单元片真实重叠、结果按 stem 归档、单单元异常使整步失败；`WhisperModelConstructionTest` 断言模型只构造一次、worker 上限默认与非法值回退、无单元时不加载模型
- **授权**：Roger 2026-10-18「单集内全流程并行，检查不缩水」
- **状态**：REFERENCE_IMPLEMENTATION

### K118 — S5_KEYFRAME_GENERATION

- **规则**：付费图片批次已被计费但全部远端任务标识不可恢复时，按订单核销，而不是留在未决态。预算预留分支必须由回归测试覆盖（`--check --reserve` 至少跑一次、读回 `reservation_result`、释放一次、超上限拒绝一次），否则该分支等同于从未存在。写 off 工具在写入前逐条校验证据：事务存在且处于未决态；计费凭据指向归档的 `PASS_BOUNDED` 账单且其 SHA256 与磁盘一致；账单窗口包含该事务自身的时间戳；账单存在未映射的付费行（`unmapped_pay_row_count > 0`）。没有存活账单窗口的事务，只有在给出明确理由时才可核销，且计入 0 credits。核销只改事务状态（`CHARGED_WRITTEN_OFF_BY_ORDER`），保留上一状态、核销时间、计费凭据与 `DO_NOT_RESUBMIT_THIS_FINGERPRINT` 重试守卫。金额不改账本：账本统计的是归档账单文件，核销不删账。
- **教训**：E12 关键帧 09:38 批次因上游 `dial tcp ... i/o timeout` 丢失全部 8 个响应，账单证明 7 个付费行共 77 credits，却没有任何任务标识可以对账；另有 2 条更早的隔离事务根本没有存活窗口。缺少核销写入者时，这 10 条永久卡在未决态，付费阶段被 `UNRECONCILED_TRANSACTIONS` 永久阻断，而重新提交同一指纹等于为同一张图付第二次钱。次日同一集第一次真正走到预留分支的付费跑又死在 `NameError: uuid 未定义` —— K111 加的 `--reserve` 分支从未被任何测试执行过，缺一个标准库导入直到钱已经上线的时刻才暴露。
- **恢复**：出现「已计费、标识不可恢复」时，先用离线对账器确认未映射付费行与唯一窗口，再以订单（含逐字授权原话）为凭据运行核销工具，核销后重跑只读预算检查确认未决事务清零。绝不以重投作为对账手段。
- **实现**：`tools/write_off_charged_losses.py`
- **回归**：`tools/tests/test_write_off_charged_losses.py`
- **证据**：`WriteOffToolTests` 断言有账单证据的行核销并保留下批费用与守卫、账单 SHA 不符拒绝、已结算事务永不改写、无证据且无理由拒绝、有理由无窗口按 0 credits 结算并记录理由、事务落在账单窗口外拒绝、干跑不改动任何事务且零网络调用
- **授权**：Roger 2026-10-20「按 K073 核销」
- **状态**：REFERENCE_IMPLEMENTATION

### K119 — S1

- **规则**：CAMERA_GRAMMAR_V1 只对声明 `camera_grammar_policy=CAMERA_GRAMMAR_V1` 的合同（storyclaw finalize 给新封版合同自动补）或 `configs/CAMERA_GRAMMAR_V1.json` 列出的集生效，旧合同不变。不加任何门：静态设计门 R1–R4/R6/R7 降为提示；`camera_plan` 打 `camera_grammar` 标记后分组运镜去掉相邻同向与 5 单元同向上限（保留相邻同族同向），H3 运镜句加电影语法措辞；剧本写切或换场的单元用自己的关键帧起幅。建立镜、景别节奏、反应镜、运镜动机只写进编剧/导演指引。
- **教训**：Twelve Gazes E01 观众反馈运镜与剪辑不符合看片习惯：「无对白镜必须运镜」使英文线几乎每镜无动机地摇/环绕；方向上限让运镜机械交替；D-68 让剧本写的切从上一单元尾帧漂过去。线主定调：质量靠更好的导演，不靠更多会卡住 Codex 的门。
- **恢复**：新集按 WRITER_CONTRACT 的 Camera grammar 一节写；已产出的集不重做；需退出时在合同写 `camera_grammar_policy=LEGACY_FORCED_MOTION`。
- **实现**：`tools/camera_grammar_policy.py`、`lines/nalu/runtime/tools/static_design_gate.py`、`tools/grouped_camera_contract.py`、`tools/h3_provider_prompt_renderer.py`、`lines/nalu/runtime/tools/build_keyframe_manifest.py`
- **回归**：`tools/tests/test_camera_grammar_policy.py`
- **证据**：旧合同判定、方向上限与 H3 运镜句不变；新合同强制运镜规则只提示；剧本切点不再沿用尾帧
- **授权**：线主 2026-10-22 批准 Twelve Gazes 运镜/剪辑修复（同日改为「只留最关键的门，靠更好的导演」）
- **状态**：REFERENCE_IMPLEMENTATION

### K120 — S5

- **规则**：previs 的导演审阅轮次来自落盘的审阅回执（回执必须写审阅人且答完全部导演问题），不来自「跑了几次」。重跑同一次预演不消耗轮次，也不会把未审阅的序列自动升为 `CLOSED_ADVISORY`。
- **教训**：旧实现用进程内计数器，第二次运行就把轮次 +1，于是门自己给自己签了「已审阅」——同一份没人看过的预演跑两次即 PASS。
- **恢复**：剧本或机位改动后需重新提交回执；仅重跑构建不能推进审阅。
- **实现**：[tools/episode_previs.py](../../tools/episode_previs.py)、[lines/nalu/runtime/tools/nalu_pipeline.py](../../lines/nalu/runtime/tools/nalu_pipeline.py)
- **回归**：`tools/tests/test_previs_review_round_semantics.py`
- **证据**：重跑不增轮；有具名回执才计一轮；问题未答完不计
- **授权**：Codex CC_H3 提示词与跨镜头预演修复方案 2026-10-26 §四-缺口C
- **状态**：`REFERENCE_IMPLEMENTATION`

### K121 — S5

- **规则**：预演必须把已有的运镜/转场/动作连续性合同投影到真实的剪辑相邻关系上，输出逐边界的 `boundaries` 列表；预演模块不重新实现这些合同，只读引擎已有的判定。
- **教训**：旧预演时间线只有镜号、起点、时长与静帧，两种完全不同的运镜/动作设计产出字节相同的 PASS：审阅者看不到切点节奏，预演无法作为剪辑依据。
- **恢复**：新合同若新增边界语义，应扩展投影字段而不是在预演里复制判定。
- **实现**：[tools/episode_previs.py](../../tools/episode_previs.py)
- **回归**：`tools/tests/test_previs_boundary_projection.py`
- **证据**：同向连摇+动作重启与全锁定边界不同；未声明转场报 `NOT_DECLARED` 不臆造
- **授权**：Codex CC_H3 提示词与跨镜头预演修复方案 2026-10-26 §四-缺口A
- **状态**：`REFERENCE_IMPLEMENTATION`

### K122 — S5

- **规则**：审阅回执绑定 `sequence_digest`（`timeline` + `boundaries` 的 sha256），不绑定输出文件的 sha。序列任一处机位、时长或转场改动都会使旧回执自动失效；与该序列无关的字段变动不会。
- **教训**：旧实现记录的是输出 json 的 sha，而输出每次运行都变，无法区分「这份审阅仍描述当前剪辑」与「剪辑在审阅后被改过」。
- **恢复**：改剪辑后需重新审阅；不要用重跑刷新回执 sha 来「续命」。
- **实现**：[tools/episode_previs.py](../../tools/episode_previs.py)、[lines/nalu/runtime/tools/nalu_pipeline.py](../../lines/nalu/runtime/tools/nalu_pipeline.py)
- **回归**：`tools/tests/test_previs_sequence_digest_binding.py`
- **证据**：改运镜或时长即改变 digest；旧回执对新序列计 0 轮
- **授权**：Codex CC_H3 提示词与跨镜头预演修复方案 2026-10-26 §四-缺口D
- **状态**：`REFERENCE_IMPLEMENTATION`

### K123 — S6

- **规则**：局部修复批次（`partial_repair_scope` / `staged_generation_scope`）不得整体跳过跨单元校验。应由构建阶段记录全局分组计划及其 sha256，提交阶段把该计划的紧邻前驱/后继单元作为只读上下文拼进序列，只校验受影响边界；邻居永不进入 manifest 的 `tasks`，绝不重复 POST。计划在批次构建后被改动则拒绝提交。
- **教训**：旧实现一旦看到作用域标记就同时跳过运镜序列、转场序列与节奏三个校验。非连续子集不被当成连续集是对的，但「什么都不查」让批次与集内邻接处的边界完全失守：重画的运镜可能撞上邻居的出向运动，重写的转场可能与邻居终态矛盾。
- **恢复**：无全局计划引用的历史修复批次维持仅逐任务校验；新批次应带计划。
- **实现**：[lines/nalu/runtime/tools/build_nalu_preproduction.py](../../lines/nalu/runtime/tools/build_nalu_preproduction.py)、[tools/submit_giggle_video_manifest_v2.py](../../tools/submit_giggle_video_manifest_v2.py)
- **回归**：`tools/tests/test_staged_scope_neighbour_context.py`
- **证据**：波次拼出前后邻居并按集内顺序排列；manifest 不被改写；计划 sha 不符或单元不在计划内则拒
- **授权**：Codex CC_H3 提示词与跨镜头预演修复方案 2026-10-26 §四-缺口E
- **状态**：`REFERENCE_IMPLEMENTATION`

### K124 — S6

- **规则**：`SUBMITTED_TASK_ID_BOUND` 事务在生成成功后不会自动结清，因此「待发额」只能在它比本类目最新归档账单更新的窗口内计入；已被账单覆盖的事务由 `recorded_total_credits` 统计一次，不得再计。同一账号其他项目的扣费不得计入本集。
- **教训**：旧实现每次调用都把历史上所有绑定事务重新计入，待发额只增不减，最终在真实敞口接近零时误报 `EPISODE_CREDIT_CAP_WOULD_BE_EXCEEDED`（一次现场里 130 条历史事务被读成约 4185 额度）。账单归集只按时间窗匹配，会把同账号其他项目的扣费算进本集。
- **恢复**：账单归集按任务 id 归属；外来行单独列报为 `FOREIGN_ACCOUNT_ACTIVITY_NOT_ATTRIBUTED_TO_THIS_EPISODE`，既不静默丢弃也不静默计入。
- **实现**：[lines/nalu/runtime/tools/nalu_budget_ledger.py](../../lines/nalu/runtime/tools/nalu_budget_ledger.py)、[tools/giggle_credit_statements.py](../../tools/giggle_credit_statements.py)
- **回归**：`tools/tests/test_nalu_budget_reservation_settle.py`
- **证据**：已归档事务不再计入待发；外来行被隔离并单独报数
- **授权**：Codex CC_H3 提示词与跨镜头预演修复方案 2026-10-26（配合现场账目）
- **状态**：`REFERENCE_IMPLEMENTATION`

### K125 — S5

- **规则**：预演渲染必须呈现声明的运镜并接入真实对白音频，不能用静音床加静态卡代替。只动画化合同里声明过的 `(motion_family, motion_direction)` 组合；`LOCKED` 镜绝不补运镜；某镜有对白但没有提供音频时必须报告，不能假作静音通过。正式入口默认不渲（会为整条时间线调用 ffmpeg），由环境变量显式开启。
- **教训**：旧入口只调用 `build_previs`、从不调用渲染，也从不传已有对白音频映射；可选渲染只把静态图／占位卡拼起来并配 `anullsrc`。机器检查可以彼此自洽而结果根本没法看——这恰是观众能抓、JSON 门抓不到的东西：观众能不能跟着说话对象、动作和切点走。
- **恢复**：需要看片时设 `NALU_PREVIS_RENDER=<输出 mp4>` 与 `NALU_PREVIS_RENDER_ENABLED=1`，可选 `NALU_PREVIS_DIALOGUE_AUDIO` 指向对白音频清单；渲染结果写进回执并出现在门记录里。
- **实现**：[tools/episode_previs.py](../../tools/episode_previs.py)、[lines/nalu/runtime/tools/nalu_pipeline.py](../../lines/nalu/runtime/tools/nalu_pipeline.py)
- **回归**：`tools/tests/test_previs_render_watchable.py`
- **证据**：端到端实渲：PAN/DOLLY/CRANE 有动画，`LOCKED` 静止；对白段实测 `-21.1 dB`、静默段 `-91 dB`；缺对白音频的镜被列入 `shots_dialogue_audio_missing`
- **授权**：Codex CC_H3 提示词与跨镜头预演修复方案 2026-10-26 §四-缺口B
- **状态**：`REFERENCE_IMPLEMENTATION`
