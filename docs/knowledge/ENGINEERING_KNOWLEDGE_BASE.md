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


## 引用和许可

以上文字为项目经验的原创概括，随本仓库 MIT LICENSE 发布。未复制外部社区文章、教程全文、他人视频/图片或私人聊天。
若以后导入社区打斗模板，必须记录原作者、URL、许可和可再分发范围；MIT 不覆盖第三方素材。
“重建推断”训练样本必须标为 INFERRED_RECONSTRUCTED_NOT_ORIGINAL，不能冒充原始镜头提示词，也不能推断未采集的音频。
