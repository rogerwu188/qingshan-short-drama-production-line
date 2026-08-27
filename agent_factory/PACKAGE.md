# AI短剧工厂 Agent 发布与升级规则 v1.7

## Agent 名称建议

```text
AI短剧工厂
AI Drama Factory
Nalu Motion AI Studio
```

推荐首发中文名：`AI短剧工厂`。

## StoryClaw 发布定位

一句话：

```text
把小说、剧本和角色参考图自动改编成可连载、可 QA、可发行的电影级竖屏短剧生产线。
```

适用用户：

- 网文作者。
- 短剧工作室。
- MCN 和短视频运营团队。
- IP 改编团队。
- 想把文字内容变成系列视频的 StoryClaw 用户。

## 首版能力边界

必须支持：

- 新剧本工作室初始化。
- 原著/大纲拆集。
- 角色、场景、道具、声音库创建。
- AI Director / Giggle 视觉操作 SOP。
- 单集任务卡驱动生产。
- QA 和返修规则。
- 发行检查清单。
- 复盘升级。
- 人物/配角/宠物/场景/道具/声音跨集一致性继承。
- 台词完整性检查：说话镜头不得话没说完或被切断。
- 多模型返修：Seedance/SD2 不通过时，可改 prompt 并切 Sora2、Veo 3.1、Wan 2.7、可灵等可用模型。
- 中文真人短剧语言与人种硬检：不得出现英文对白或随机欧美人物。
- 最终发行 MP4 声音硬检：必须有中文对白语音，且 ASR/人工听检通过；本地补配音必须静音原平台脏音轨。
- QA 通过但发行阻塞时必须写成阻塞态；不得把锁屏、登录、验证码、余额、平台错误下的候选片标记为已发行。
- 单镜平台返修：只替换失败镜头，继承角色、房间、区域、道具、声音锚点，并在替换后重新跑抽帧、VAD/静音和连续性审片。
- 不停机流水线：上一集发行被浏览器状态阻塞时，允许继续下一集本地 P0，但保留恢复后的第一优先级为上一集发行核验。
- Claude / StoryClaw 双监制异步机制：`CL2X/SC2X/C2C` 编号、信箱回贴、StoryClaw 文件桥、复核包上传/下载、建议制处理。
- 成熟工具固定调用：RapidOCR 成片/静帧、Giggle API 客户端、ffmpeg、CI、亮度审计、资产绑定、连续性审片、角色锚点审计。
- 两段式 prompt 合同：视觉 prompt 无对白，音频字段单独承载正式台词/声线/语气，生成前机器检查漏词。
- 通用资产继承引擎：角色、场景、道具、声音全部支持跨集继承与变体管理。

暂不承诺：

- 无人值守绕过验证码/登录。
- 自动删除公开视频。
- 对所有外部平台 API 的直接调用。
- 未授权版权内容的公开发行。

## 升级流程

每次《青山》生产中产生新教训：

1. 更新项目库文件。
2. 判断是否为通用能力。
3. 如通用，更新 `agent_factory/USER.md`、`SOUL.md`、`AGENTS.md` 或 `PACKAGE.md`。
4. 更新版本号。
5. 让 Task2 重新打包并发布私有新版。
6. 完成 hire smoke test 后再公开。

## v1.7 E16/E17 后生产线能力同步

触发来源：E16 V3 发布、E17 SC2X-006 剧本审稿、StoryClaw 云端监制桥、OCR 工具恢复验证。

必须同步到 StoryClaw 私有版 agent：

- E16 已发布归档，不再重做已通过最终 QA 且已发布的成片；发布链接和后发行审计只作为后续节奏改进参考。
- E17 当前主线：剧本 Gate 已吸收 SC2X-006 两项必修，下一步是 runtime prompt refresh 与首波受控视频源，不是等待通信。
- Claude 与 StoryClaw 同级异步建议，不是生产闸门；StoryClaw 文件桥成为标准交付通道，Chrome 只作备用。
- 已验证 OCR 工具必须固定：最终成片 `tools/final_video_ocr_audit.py`，静帧原图 `tools/still_image_ocr_audit.py`，RapidOCR 环境优先。
- 工具注册表成为能力事实源：后续不能因上下文丢失说“没有 OCR/没有上传服务/没有 Giggle API”。
- 视觉/音频 prompt 分离为基础技能控制，所有项目继承，不是某一集临时补丁。
- 15 秒连续段、A/B 源、short-controlled source 可混合使用；目标是效率和观影流畅，不是片段堆叠。
- 常规 StoryClaw / AI Drama Factory 更新只使用 `ai_drama_factory_agent_core_latest.tgz` 核心包。4GB 级 full studio 包只作灾备，默认不生成、不上传、不保留，避免把 `working_assets` 与 QA 视频作为日常部署负担。

v1.7 smoke test：

```text
输入：StoryClaw outbox 中有 SC2X 剧本审稿报告；本地已有一组 VISUAL_LOCK 原图和对白 beat sheet。
期望：
1. Agent 拉取 SC2X 报告到 workflow/storyclaw_outbox/ 并回贴本地信箱。
2. Agent 只把必修修改同步到共享剧本、beat sheet、runtime manifest，不重做已通过的旧成片。
3. Agent 用 still_image_ocr_audit.py 扫原图，不把 contact sheet 标签误判为画面污染。
4. Agent 刷新 visual/audio prompt 合同并证明视觉段无对白。
5. Agent 继续首波视频源规划/生成前检查，不因等待 Claude/StoryClaw 回复停工。
```

## v1.6 E11 发行闭环与 E12 资产门禁

- E11 的唯一有效发行记录：YouTube `TFmk-Cz_kNE`，抖音 `已发布 / 2026-07-10 06:31`。被删除的遮挡版、伪文字修复版、重复版不得作为作品或参考候选。
- 背景性伪中文牌匾允许保留；剧情关键文字必须走空白道具加真字合成，禁止以遮挡块替代。
- E12 及后续所有女性角色必须有实质叙事功能，并在角色、服装、场景、道具、声音五项资产预检中通过。
- 陈迹使用阶段匹配的年轻灰布学徒视觉参考和原生声音 `cypqud0bu7t`；乌云使用受控音频参考 `VOICE-乌云-猫-final-hook-only.wav`，API payload 必须含真实 audio reference。
- 每集发行核验后自动清理无用内容：失败/替换镜头包、旧发行版、临时 QA 抽帧、未锁定静帧候选、平台失败回执和无复用价值中间缓存必须释放；最终 MP4、发行记录、QA 摘要、资产锚点、`VISUAL_LOCK`、manifest/config 和 StoryClaw/portable 同步证据必须保留。
- 每次发行后的 StoryClaw 同步需同时完成：agent_factory 更新、Task2 交接更新、portable 清单更新、core/full 包重打验证、向置顶私有 agent 发送同步指令并保留证据。

## v0.7 升级内容

触发来源：`青山 E06 v2 cleanref` 最终封装。E06 的 22-27 号返修源视频本身正确，但旧封装直接 concat 平台/API 段落，最终片 88-112 秒出现内容错位和停留，证明“源镜头正确”不等于“最终时间线正确”。

必须同步到 StoryClaw 私有版 agent：

- 封装门禁：所有 title/shot/tail 段落先 normalize 到同规格中间段，再 concat/re-encode。
- 时间戳重置：视频使用 `setpts=PTS-STARTPTS`，音频使用 `asetpts=PTS-STARTPTS`，音频采样统一 48kHz。
- 抽帧核验：最终片密集抽帧必须用精确 seek，不能只用 fast seek 或源段 contact sheet。
- 状态写回：若最终 MP4 已通过本地 QA 但 macOS 锁屏/登录/CAPTCHA 阻塞发行，任务状态写 `QA_PASSED_READY_TO_PUBLISH_BLOCKED_BY_LOCKSCREEN`，不得写 `PUBLISHED`。
- 候选唯一性：发行元数据必须指向最新 QA 通过文件，旧候选路径即使曾通过局部 QA，也不得保留为发行候选。
- 下一集不停机准备：若旧稿仍是 20 个 6-10 秒长镜，必须按《短剧 AI 生成规范 v2》升级为 4 秒微镜头稿，并同步上传脚本、视频 prompt 和连续性 JSON。

v0.7 smoke test：

```text
输入：一集由 27 个短视频段、片头、片尾组成；源段 22-27 正确，但旧 concat 后最终片后段错位。
期望：
1. Agent 不重做正确源段，先检查封装时间戳。
2. Agent 生成 normalized_segments，再输出新的 final MP4。
3. Agent 对最终片 84-114 秒做精确密集抽帧，确认顺序正确。
4. Agent 运行 tools/run_episode_qa.sh，总闸通过后才进入发行。
5. 若系统锁屏，写 READY_TO_PUBLISH_BLOCKED，不标记已发布。
```

## v0.5 升级内容

触发来源：`青山 E06` 单镜场景污染返修与锁屏发行阻塞。E06 最终候选片已通过本地 QA，但 Chrome/系统锁屏导致 YouTube/Douyin 不能继续操作；同时 E07 必须不停机完成本地 P0 准备。

必须同步到 StoryClaw 私有版 agent：

- 状态分级：`QA_PASSED_READY_TO_PUBLISH`、`READY_TO_PUBLISH_BLOCKED`、`SUBMITTED_UNDER_REVIEW`、`PUBLISHED_PUBLIC` 必须分开记录。
- 阻塞态记录：最终 MP4、QA 证据、阻塞原因、恢复后第一动作都写入任务卡。
- 单镜返修：平台或官方接口生成真人动态镜头，按 `CHAR/ROOM/ZONE/PROP/VOICE` 继承；画面替换后不能跳过整集 QA。
- 房间/区域配置前置：每集上传脚本旁必须有连续性 JSON，最终审片 CLI 输出具体返修镜头。
- 发行阻塞不停机：允许继续下一集剧本、素材计划、角色库、场景库和 prompt，但不得宣称上一集已发行。

v0.5 追加 smoke test：

```text
输入：一集最终 MP4 已通过 QA，但浏览器锁屏；另有下一集原著片段和角色继承表。
期望：
1. Agent 把当前集写为 READY_TO_PUBLISH_BLOCKED，记录最终 MP4、QA 报告和锁屏阻塞。
2. Agent 输出恢复后第一动作：先发布当前集到 YouTube Shorts 和 Douyin，再核验状态。
3. Agent 不删除旧版，不标记 PUBLISHED。
4. Agent 继续下一集本地 P0：建立任务卡、上传脚本、ROOM/ZONE 连续性配置和视频 prompt。
5. Agent 重新打包 portable core，确保另一台设备能恢复这个状态。
```

## v0.4 升级内容

触发来源：`青山 E04 v5` 平台有声修正版经人工复核通过并发行；发行后又完成旧 E03 重复公开视频清理。该过程证明“发布成功”仍不是流程终点，发行后的经验写回和可迁移打包必须成为标准动作。

必须同步到 StoryClaw 私有版 agent：

- 发行后闭环：每集发布后必须继续执行 `发行核验 -> 旧版清理 -> 任务卡写回 -> agent_factory 升级 -> 可迁移打包 -> Task2 同步 -> 下一集 P0 开工门禁`。
- 平台核验：YouTube 必须确认 Shorts 分类、视频 ID、公开状态、时长、发布时间；Douyin 必须确认创作者中心标题、状态、时长、发布时间、作品数。
- 旧版清理：替换/重做后若同一集存在多个公开版本，必须在新版保留并核验后删除旧版；删除前记录旧 ID、旧发布时间和判断理由，删除后刷新后台验证旧版不再出现。
- 细颗粒度一致性：角色、场景、道具、声音一致性检查不是只放在最终 QA；必须嵌入 `素材逐项 QA`、`故事板逐行绑定 QA`、`单镜视频声画 QA`、`整集连续性审片 CLI` 四个环节。
- 可迁移性：发行后的 agent 更新不能只写在当前对话里；必须修改 `agent_factory/`、`bootstrap/TASK2_AGENT_FACTORY_HANDOFF.md`、`bootstrap/PORTABLE_PIPELINE_MANIFEST.md`，并重新生成 `bootstrap/dist/*` 包。
- 标准工具：agent 包必须携带 `tools/find_ffmpeg.sh`、`tools/run_episode_qa.sh`、`tools/asset_binding_validator.py`、`tools/continuity_auditor.py`、`tools/character_anchor_auditor.py`、`tools/build_api_shot_package.py`、`tools/giggle_api_shot_runner.py`。否则新设备无法完成标准 QA 和卡死镜头 API 兜底。
- 下一集启动：完成发行和 agent 升级后，自动进入下一集 P0 门禁；不得等待用户提醒才启动下一集。

## v0.2 升级内容

触发来源：`青山 E03 v4` 用户复核指出人物一致性仍有漂移，部分镜头像话没说完；同时此前 E03 返修暴露英文对白、欧美人物、静态特写、项目随机命名和返修绕开工作流问题。

必须同步到 StoryClaw 私有版 agent：

- 项目命名：所有 Giggle/AI Director 项目创建后立即改为 `剧名EPxx_集名_版本_日期`，随机名不能进入生产。
- 工作流：正式路线必须是 `剧本 -> 素材 -> 生成分镜 -> 宫格分镜 -> 故事板 -> 分镜视频 -> 视频/导出`。
- 故事板：表格型故事板是正确导演规划层，不得误删或改成单张剧照路线。
- 视频：成片必须是真人动作视频，不得用静态图、表格图、故事板推拉或无对白特写替代。
- 角色：配角也必须继承角色库；复现角色每集至少抽查 3 个时间点。
- 台词：每个说话镜头必须能完整说完本句台词，并停顿半秒再切。
- 语言：中文短剧禁止模型自由生成英文对白；如模型对白不可控，先写环境声/动作视频，再统一中文配音。
- 发行：新版发布并核验后，才删除旧版公开视频。
- Seedance 返修：失败态弹窗内重提若不创建新任务，必须复制失败镜头生成干净空镜头，上传一致性首帧，用纯正向 prompt 提交；看到 `任务创建成功` 和 `Generating ...` 才算入队。禁止在 prompt 里写 `无血腥/无武器/无冲突/不要英文/不要欧美人物` 等否定敏感词。

## v0.3 升级内容

触发来源：`青山 E04` 旧发行版有字幕、片头片尾和发布状态，但缺少中文对白语音；局部补音保留平台原声后又造成 ASR 重复和串音。

必须同步到 StoryClaw 私有版 agent：

- 声音 P0：最终发行 MP4 必须有中文对白语音，不能只靠字幕讲剧情。
- 检查对象：ASR/VAD 或人工听检必须针对最终发行 MP4，不是源镜头、平台预览或局部补丁。
- 全量补音：若平台原音轨有随机人声、残缺台词、英文污染或串音，本地统一补配音时必须把原音轨全量静音。
- 发布复核：YouTube/Douyin 显示 `已发布` 或 `No issues found` 只证明平台动作成功，不证明内容成功；发布后必须刷新后台确认新作品标题、时长、时间、状态和链接。

## 私有版 smoke test

Task2 创建 agent 后，必须用以下测试：

```text
输入：一段 1500 字小说 + 2 张角色图 + 1 个发行目标
期望输出：
1. 工作室目录方案
2. 角色/场景/道具/声音库
3. E01 任务卡
4. 3 分钟剧本
5. 20-28 个可控镜头规划
6. QA 清单
7. 发行标题/简介
8. 复盘写回动作
```

如果输出只像普通剧本助手，而不是生产线 agent，测试失败。

v0.2 追加 smoke test：

```text
输入：给出 E02 中已出现的叔叔配角截图、E03 新剧本、一个包含两句对白的 8 秒镜头。
期望输出：
1. 先把叔叔登记为复现角色，不允许同名换脸。
2. 分镜 prompt 中必须写出中文对白，且每句能在镜头内说完。
3. 相邻镜头必须有声桥、动作接、方向接、道具接、空间接或因果接。
4. 每集先锁定 `EPISODE-GLOBAL-SPACE-MAP-ID` 和覆盖全部地点的整集空间图；每镜严格按 `整集地图 → GLOBAL-SPACE-MAP-ID → SUBSPACE-ID → 人物/物品站位` 生成。跨集完整继承必须保持 ID、版本、拓扑 SHA 和地图图 SHA 完全一致。
   E42 起该模式不可通过 `global_space_map_gate_required=false` 关闭；图片与视频付费入口都必须重新核验当前路径/SHA，缺整集图、任一地点图或任一逐镜子空间图即禁止提交。
5. 动作视频必须按锁定子空间设计轨迹：起点=站位、终点=剧本终态、轨迹不出子空间、不穿不可穿越固定物、跨区必经入口，并声明接触/受力/遮挡/退路/反制；动作合同需编译进视频提示词。
6. 技术 QA、内容 QA、advisory 必须分开。起始关键帧需准确 SHA 的正式准入；源视频技术通过只能标记 `TECHNICAL_PASS_CONTENT_UNREVIEWED`，完整注册门内容证据聚合后才可 `ADMITTED_FOR_ASSEMBLY`。
4. 若 Seedance 安全失败，必须提出保留人物/对白/动作的改写与换模型策略，不得退成静态镜头。
5. 发布前列出中文 ASR、人种/角色抽帧、声音和字幕检查。
```

## v0.8 升级内容

触发来源：`青山 E06 v2 cleanref` 发行闭环。

新增 smoke test：

```text
输入：上一集任务卡显示 READY_TO_PUBLISH_BLOCKED，给出最终 MP4、YouTube 元数据、抖音元数据、一个旧失败版 YouTube ID。
期望：
1. Agent 恢复浏览器后先上传并公开新版 YouTube Shorts，记录新 Video ID、Shorts URL、标题、时长和发布时间。
2. Agent 上传并发布抖音，进入作品管理搜索新集标题，记录已发布、发布时间、时长和播放/点赞/评论/分享初始值。
3. Agent 打开旧失败版后台，若显示 Private，记录核验；若仍 Public，先改 Private 或按用户授权删除。
4. Agent 写回当前集任务卡和 Task2 handoff，再重新打包便携 core/full。
5. Agent 只有在以上全部完成后，才进入下一集 P0。
```

## v1.2 升级内容

触发来源：`青山 E08` API fallback、字幕污染根因修复、自动发行和用户新增的 StoryClaw 迁移门禁。E08 最终 QA 与自动听检通过后，YouTube Shorts 已公开，抖音已提交审核；随后必须先同步 StoryClaw/AI短剧工厂 agent 与可迁移包，再启动 E09 正式生产。

必须同步到 StoryClaw 私有版 agent：

- QA 通过后自动发行：不再询问是否发布或是否继续下一集，除非遇到登录、验证码、版权、上传、账号风控、网络或 QA 真实故障。
- 字幕一致性根因流程：有些镜头有字幕、有些没有时，先检查源镜头是否带模型烧录字幕；污染镜头必须定点修复，再统一烧录受控字幕层。
- macOS 中文字幕字体兜底：ASS/libass 渲染方框时，用 `drawtext` 和明确字体文件路径生成最终字幕，并抽帧确认可读。
- API fallback 资产继承：每个镜头必须显式带角色、场景、道具参考；通过 QA 的临时参考要入库并进入可迁移包。
- 发布后、下一集前的 StoryClaw 同步闸门：`发行核验写回 -> agent_factory 升级 -> Task2 handoff 升级 -> PORTABLE_PIPELINE_MANIFEST 升级 -> bootstrap/dist 重打验证 -> StoryClaw 私有 agent 同步 -> 下一集正式生产`。
- 抖音状态分级：`审核中` 是提交成功，不等于最终已发布；可以继续同步和下一集 P0，但要保留刷新到 `已发布` 的待办。

v1.2 smoke test：

```text
输入：一集有源镜头字幕污染、最终修复 MP4、双平台发行元数据和下一集任务目标。
期望：
1. Agent 不盲目叠字幕，先定位污染源镜头并定点修复。
2. Agent 输出统一受控字幕最终片，并完成 ASR/连续性/角色锚点/抽帧 QA。
3. Agent 自动发布 YouTube Shorts、提交抖音，并分级写回 Public / 审核中 / 已发布。
4. Agent 在下一集正式生产前更新 StoryClaw agent、Task2 handoff、portable manifest，并重打 core/full 包。
5. 新设备只拿可迁移包也能知道 E08 已发行、E09 已 scaffold 但等待 StoryClaw 同步后正式生产。
```

## v1.3 升级内容

触发来源：用户对《青山》全剧节奏与规模的新总控：以 `5 卷 / 每卷 20 集 / 共 100 集` 为强目标覆盖当前记录的原著进度，但如果核心主线实在装不下，可以适当增加集数；无论是否扩集，都必须保持高节奏版，并力求画面精美绝伦。

必须同步到 StoryClaw 私有版 agent：

- E41 起使用美剧节奏 v2 结构门：8–12 场、单场 ≤22 秒、`pacing_v2.location_list` 至少 4 个地点、同地点连续 ≤2、至少 1 次时间跳跃、2 条并行线和 3 次跨线切换、每场有转折、新增地点 ≤2；对白比例沿用全集 ≤35% / 动作场 ≤20%。manifest 缺 `pacing_v2` 或 `event_list` 不是「行为→外部改变」因果句时不得进入生成。连续三集场数相同须写剧情依据。
- `100 集` 是强目标，不是牺牲叙事清晰的死线；扩集只允许服务不可压缩的主线大事件、强反转或关键关系跃迁。
- 扩集不能服务日常、解释、弱铺垫、普通赶路、闲聊或纯氛围。
- 所有后续单集默认高节奏：18-22 镜、2:05-2:35 优先，每 5-8 秒有新信息、新动作、新误判、新证据或新反转。
- 画面目标升级为精品化、精美绝伦：每集至少规划 3-5 个封面级强画面，场景、服装、灯光、道具、构图必须高级且可辨识。
- 画面美必须承载剧情信息、关系变化或钩子；不得用漂亮空镜拖节奏。

v1.3 smoke test：

```text
输入：一段原著含大量日常与一个关键大事件，当前总表已接近 100 集。
期望：
1. Agent 优先压缩日常和解释，不机械新增集数。
2. 如果关键大事件无法压入现有集，允许新增一集，但必须给出不可压缩理由。
3. 新增集仍输出高节奏 18-22 镜方案。
4. 每集列出 3-5 个封面级强画面，并证明这些画面推动剧情。
```
