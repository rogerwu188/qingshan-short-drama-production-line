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

- 规则：内置浏览器三次失败后使用已连接外部浏览器；先查重再上传。
- 失败教训：浏览器操作失败被误称为等待额外内容审核。
- 修复路径：复用平台策略；登录/安全权限是真边界；自动发布权限来自本部署操作者。
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[configs/PLATFORM_RELEASE_AUTOMATION_POLICY_V1.json](../../configs/PLATFORM_RELEASE_AUTOMATION_POLICY_V1.json)

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

## 引用和许可

以上文字为项目经验的原创概括，随本仓库 MIT LICENSE 发布。未复制外部社区文章、教程全文、他人视频/图片或私人聊天。
若以后导入社区打斗模板，必须记录原作者、URL、许可和可再分发范围；MIT 不覆盖第三方素材。
“重建推断”训练样本必须标为 INFERRED_RECONSTRUCTED_NOT_ORIGINAL，不能冒充原始镜头提示词，也不能推断未采集的音频。
