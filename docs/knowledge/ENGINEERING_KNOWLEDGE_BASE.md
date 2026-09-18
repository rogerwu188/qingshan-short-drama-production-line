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
- 规则：角色→音色绑定：voice_cast 每角色 voice_id + f0_band_hz（由参考音实测 ±15%）；生成前同场 voice_id 唯一、音区重叠 >50% 需人工；生成后逐句 F0 中位数落在角色音区外或同场两角色 F0 差 <15% → FAIL。
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
- 状态：`REFERENCE_IMPLEMENTATION`。相关实现：[tools/script_structure_contract_gate.py](../../tools/script_structure_contract_gate.py)、[tools/final_cut_audience_detectors.py](../../tools/final_cut_audience_detectors.py)、[lines/nalu/runtime/configs/LEXICON_yewujiang_v1.json](../../lines/nalu/runtime/configs/LEXICON_yewujiang_v1.json)（E04 成片作为负样本回归通过；自动判定做不到的项在检测器里标 NOT_IMPLEMENTED）
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

## 引用和许可

以上文字为项目经验的原创概括，随本仓库 MIT LICENSE 发布。未复制外部社区文章、教程全文、他人视频/图片或私人聊天。
若以后导入社区打斗模板，必须记录原作者、URL、许可和可再分发范围；MIT 不覆盖第三方素材。
“重建推断”训练样本必须标为 INFERRED_RECONSTRUCTED_NOT_ORIGINAL，不能冒充原始镜头提示词，也不能推断未采集的音频。
