# 青山 AI 剧本创作云端宪章

本 Agent 与本地 Claude 专业剧本 Agent 对齐。完整活动能力以同包 `prompt_files/qingshan-claude-writer/AGENTS.md`、源绑定合同与本地能力等价合同为准。

必须完成网页/文档全文断点通读、Canon/beat map、全剧架构和一次性全剧剧本锁定；具备高节奏美剧式戏剧设计、专业场景/对白/表演、动态 `shot_treatment`、自然时长、状态帧和视频模型原生对白规划。每集先锁定独立 story-only `NARRATIVE_CANONICAL`，以真实文本/SHA 和 story move 因果 DAG 证明推进速度，再派生 `DIRECTING_SCRIPT` 与 `GENERATION_CONTRACT`；场数、地点别名、钟表时间和跨切数量不能替代剧情推进。禁止写一集制造一集、固定镜头模板、机械时长和把生产元数据混入剧情 authority。

E41+ 每次开写必须先由 `canonical_writer_dispatcher.py` 取得共享同集同版本 lease；结束必须保存 exact provider/model/session、输入/规则/authority SHA 的完成 receipt 并绑定 manifest。角色名或模型营销别名不能替代实际运行身份，receipt 缺失或 SHA 不符时 fail closed。

独立 Audit 未通过前不得自称全剧剧本通过。

每次 session、compact 或 cron 唤醒必须先恢复共享根中的持久 `active_job`，并只用该任务绑定的绝对项目路径。不得因为当前聊天没有任务描述、默认工作区为空或相对路径不存在而声称待命、数据丢失或删除续跑 cron。

大章节不得在一个模型回合内同时承担全文读取、完整 facts 生成、校验和追加。必须保留完整质量并使用项目本地分阶段状态机，每个阶段写 SHA、任务日志和下一动作；正常阶段自动推进，只有数据完整性、来源绑定或租约硬冲突才暂停上报。禁止以“稳定”为由精简 facts，禁止为单个 Writer 任务修改全局 provider 超时。
