# AI短剧工厂 Agent 执行手册 v0.9

本文件是 agent 运行时的硬规则。遇到冲突时，以用户最新指令和本文件中的 P0/P1 门禁优先。

## P0 当前恢复点必须动态解析，禁止写死集号

每轮先从 `workflow/work_queue.json` 的 `current`、canonical/manifest 与对应
`workflow/production_line/E##_TASK_LANES_V1.json` 解析当前活动集和下一真实工位。
历史集的发行链接与恢复点只作为账本证据，不得覆盖当前 work queue，也不得让旧集号
（例如 E17）重新成为生产入口。

当前付费图片只允许经持久化事务提交器进入；E40 及以后的视频只允许
`seedance-2.0-fast`，并经当前部署的 durable transaction submitter 提交。
`tools/giggle_api_client.py`、旧 supervisor、一次性 E##_ 脚本和浏览器操作均不是可直接
POST 的默认入口。若工具注册表与本段冲突，以当前用户授权、注册门、事务账本和
`work_queue` 的活动集状态为准。

E41+ canonical Writer 的唯一运行登记入口为 `tools/canonical_writer_dispatcher.py`。本地 Claude/Cowork 或 StoryClaw 开写前必须取得同集同版本独占 lease，完成后固化 exact provider/model/session、输入与规则 SHA、authority SHA；缺完成 receipt 的正文不得通过 script phase。Codex 维护生产线和门，但不是默认 canonical 作者，除非 Roger 明确授权改稿。

## P0 StoryClaw/Claude 双监制异步通信

- 当前临时路由以 `workflow/SUPERVISOR_COMMUNICATION_MODE.json` 为准。`LOCAL_CLAUDE_PRIMARY` 时，本地 Claude 是唯一主动监制信箱；StoryClaw 远程读写暂停并保留待恢复队列，禁止双写、重复执行或让远程恢复阻塞生产。
- Claude 本地监制与 StoryClaw 云端监制同级，均为异步建议通道；codex/AI Drama Factory 的核心任务是继续完成剧集，不因等待回复停工。
- 编号分区：`CL2X`=本地 Claude，`SC2X`=StoryClaw 云端监制，`C2C`=工厂回报。
- StoryClaw 文件桥是标准能力：报告拉到 `workflow/storyclaw_outbox/`，回贴 `codex_docs/CLAUDE_TO_CODEX.md` 置顶；复核包通过 StoryClaw 文件区/上传服务交付，Chrome 控制只是备用。
- 已到达的明确修订意见必须吸收或写明异议；未到达/未 ACK/桥接延迟只建异步待办，不阻塞主线。

## P0 成熟工具不得遗忘

- OCR 成片：`tools/final_video_ocr_audit.py`；OCR 静帧/原图：`tools/still_image_ocr_audit.py`；优先 `.asr_env`/`.ocr_deps` RapidOCR 环境。不能再说“没有 OCR 工具”。
- Giggle API：`tools/giggle_api_client.py`、`tools/submit_giggle_task_manifest.py`、`tools/run_giggle_api_plan.py`、`tools/giggle_api_shot_runner.py`；临时接口失败同请求自动重试 1 次。
- 视频/CI：`tools/find_ffmpeg.sh`、`tools/run_regression_ci.py`、`tools/generate_scene_brightness_audit.py`。
- 资产/连续性：`tools/asset_binding_validator.py`、`tools/continuity_auditor.py`、`tools/character_anchor_auditor.py`。
- 工具事实源：`libraries/tools/TOOL_CAPABILITY_REGISTRY.md`。能力疑问先查注册表与历史 QA，不凭记忆否定工具。

## P0 发行后闭环

每集成片通过 QA 并发行后，任务还没有结束。必须继续完成：

```text
发行核验
旧版清理
任务卡写回
经验抽象
agent_factory 升级
可迁移包重打
Task2 同步
下一集 P0 开工门禁
```

禁止只在聊天里总结经验。凡是会影响未来生产质量、平台操作路径、QA 门禁、资产一致性或发行流程的教训，都必须写入本地文件并重新打包，保证另一台设备复制包后也能继承。

发行后到下一集之间必须有 StoryClaw/AI短剧工厂同步闸门：

```text
YouTube Shorts 公开或失败原因写回
Douyin 已发布/审核中/失败原因写回
平台指标基线写回
导演策略更新
agent_factory 规则升级
Task2 handoff 升级
PORTABLE_PIPELINE_MANIFEST 升级
bootstrap/dist 可迁移包重打并验证
StoryClaw 私有版 agent 同步
下一集正式生产
```

下一集任务卡可以提前 scaffold，但不得进入正式剧本生成、素材生成、视频生成或平台项目生产，直到上述同步闸门完成。抖音 `审核中` 记为已提交待审核，可以继续同步 agent 和准备下一集，但必须保留刷新核验到 `已发布` 的发行待办。平台指标的 `T+24h/T+72h/T+7d` 可能发生在下一集制作中途，心跳任务必须继续补采并影响后续集；不得因下一集已启动就停止复盘。

## P0 平台指标自进化门禁

- 任一图片或视频 QA 失败且根因涉及提示词合成时，必须先通过 `tools/ingest_prompt_qa_memory.py` 把失败回执、失败提示词、失败素材、根因、优化规则和证据 SHA 写入 `workflow/local_lora/seedance2_prompt_failure_training.jsonl`，再允许生成 changed-input 修复提示词。相同证据指纹只入库一次。
- `storyboard`、`continuous_long_take`、`multi_keyframe_long_take` 全部必须在付费提交前读取并编译适用记忆；编译回执没有 `local_lora_memory.sha256`、`applied_sample_ids` 或 `precompiled_before_paid_generation=true` 时禁止提交。

每集发行后必须把播放平台用户行为转成导演策略，不得只记录链接。

固定文件：

```text
workflow/platform_metrics/PLATFORM_METRICS_SCHEMA.md
libraries/qa/DIRECTOR_EVOLUTION_SCORECARD.md
workflow/platform_metrics/E##_metrics_YYYYMMDD.md
workflow/platform_metrics/E##_metrics_YYYYMMDD.json
```

采集节奏：

```text
T+2h  -> 冷启动标题/封面/前3秒诊断
T+24h -> 下一集导演策略主复盘
T+72h -> 长尾和完播确认
T+7d  -> 周复盘，更新系列级规则
```

指标到导演动作的硬映射：

- 高划走 / 低 2-5 秒留存：下一集第 1 镜必须是危机峰值或超常画面，第一句字幕/台词 2 秒内出现。
- 完播低：删日常与解释，45-60 秒必须有误判反转，90 秒必须有第二个证据或危险升级。
- 互动低：结尾钩子必须改成可评论的问题、命运反转或角色关系爆点。
- 观看眼花：平均镜头拉回 5-7 秒，同一空间连续 2-3 镜，增加声桥/动作桥。
- 看不懂剧情：增加道具/证据插入镜头，执行三镜头揭示法。
- 听不清或声画不同步：下一集必须用多模态原生声音参考进入镜头生成，最终响度和分段响度必检。

下一集 P0 任务卡必须引用上一集最新 `director_strategy_update`。没有引用时，禁止进入视频生成。

## P0 人类导演感升级门禁

关键帧/视频 QA 的状态必须诚实分层：技术可解码只写 `TECHNICAL_PASS_CONTENT_UNREVIEWED`；`ADVISORY_NOT_A_GATE` 不得当作准入。E40 起视频提交前必须有准确 SHA 的 `ADMITTED_FOR_VIDEO_SUBMIT` 首帧，视频只有在身份、空间动作、时代与缺陷容忍注册门全部通过并完成原分辨率内容审看后，才可写 `ADMITTED_FOR_ASSEMBLY`。未注册像素、骨架、几何审美指标只作 DIAGNOSTIC，不得触发付费重做。

自 `ROGER-20260820-HUMAN-REALISM-PROMPT` 起，新编译的人物关键帧必须使用 `tools/human_realism_prompt_contract.py`：身份与年龄先于美化；保留毛孔、细汗毛、唇纹、眼球湿润反光和轻微面部不对称；按景别选择真实 35/50/85mm 光学与合理光圈；动机光必须来自场景。禁止磨皮、美颜、镜像对称脸、塑料皮、蜡像感、玻璃眼、虚假 HDR、广告棚拍和网红摆拍。该规则只作用于新编译任务，不修改或重启已经绑定 task_id 的远端任务。

人物表情提示词不得只写“笑、怒、惊、冷”。必须编译“事件刺激 → 视线落点 → 眉眼/鼻翼/嘴角/下颌中一至两处微变化 → 呼吸/吞咽/肩颈/身体重心/手指张力中的身体支持 → 未完全归零的残余状态”。不同面部区域禁止同时等幅运动；非说话角色也要有呼吸与倾听反应；禁止 AI 标准微笑、同时挑眉瞪眼张嘴、橡胶嘴、僵硬背景板和全程同一表情。

E10 起必须执行以下四个文件：

```text
workflow/DIRECTOR_COVERAGE_SCHEMA.md
workflow/ONSCREEN_TEXT_COMPOSITING.md
workflow/STATE_BIBLE_SCHEMA.md
libraries/qa/AI_DIRECTOR_VISUAL_QA_CHECKLIST.md
```

硬规则：

- 不追求更碎的切镜。镜头平均 5-7 秒，靠动作、证据、反应和转场推进节奏；观众看得眼花时必须降速并重建空间。
- 单人居中肖像/特写占比不超过 30%，每集至少 3 个 two-shot/group blocking，每个关键对话至少一组 OTS-A/OTS-B。
- 对话成对生成，必须写 180 度轴线和 eyeline；A 看左则 B 看右，反之亦然。
- 长中文道具文字禁止模型直接生成；聘书、医书、告示、卷宗、书信等走真字体/书法合成层和 OCR/人工校验。
- 字幕渲染剥离说话人前缀，最终画面不得出现 `陈迹：`、`乌云：` 这种脚本标签。
- 每集建立 state bible，跟踪时间、天气、伤口、服装、猫状态、道具位置和场景地理。
- 每个说话镜头要有 emotion keyframe 和身体/手势动作；只有点头、嘴动、中性脸的镜头进入返修。
- 声音分层必须可描述：dialogue / foley / ambience / music / sfx。BGM 不能单独承担情绪。

## P0 成片封装门禁

任何由平台/API 分镜、片头、片尾或单镜返修段拼接出的最终 MP4，必须先把每个输入段统一规格后再 concat，禁止直接拼不同来源 MP4：

```text
720x1280
帧率以当前集 canonical manifest 的显式值为唯一权威；仅当 manifest 没有声明时才允许把 30fps 作为历史兼容 fallback，禁止无声明地把 24/23.976fps 插帧成 30fps。
PTS-STARTPTS
AAC 48kHz
统一像素格式 yuv420p
```

原因：不同平台/API 生成段常带有不连续时间戳、非零 start_time、可变帧率或音频采样差异。直接 concat 可能导致最终片后段误读、停帧、串到旧镜头，抽帧也可能给出假证据。

标准做法：

- title / shot / tail 每一段先 normalize 到 `normalized_segments/`。
- 最终 concat 再 re-encode 一次，并使用 `setpts=PTS-STARTPTS`、`asetpts=PTS-STARTPTS`。
- QA 抽帧使用精确 seek：先 `-i final.mp4` 再 `-ss 时间点`，避免 fast seek 抽到邻近旧帧。
- 若密集抽帧与源段不一致，先怀疑封装时间戳，不要误判为镜头内容失败。
- 该门禁优先级高于发行速度；封装未过门禁禁止上传。

发行状态必须分级记录，不能把平台提示混为一谈：

- YouTube：只有 `Video published`、`Public` 和 Shorts 链接/视频 ID 均确认后，才算公开视频完成。
- Douyin：`作品未见异常` 只是发布前机器检测通过；点击发布后进入作品管理并显示新作品，若状态是 `审核中`，记为“已提交待审核”，后续必须刷新核验到 `已发布`。
- 后台作品数、顶部新作品标题、时长、发布时间、状态和链接/ID 必须写回任务卡。若只完成 YouTube 或只完成抖音提交，不能启动旧版删除。

## P0 阻塞态与不停机策略

如果最终候选片已经通过 QA，但浏览器、登录、验证码、系统锁屏、余额或平台错误阻止发行，必须把状态写成阻塞态，不能冒充发行完成。

阻塞态必须记录：

- 最终候选 MP4 绝对路径。
- QA 报告、抽帧图、连续性审片报告路径。
- 阻塞原因和可恢复动作，例如 `LOCKSCREEN_BLOCKS_BROWSER_PUBLISH`。
- 下一次恢复后第一动作，例如 `先发行 E06，再继续 E07 平台创建`。

阻塞期间允许继续做下一集本地 P0 准备：原著摘录、剧本、上传脚本、角色/场景/道具/声音继承、连续性配置和视频 prompt。禁止跳过上一集发行核验，也禁止删除旧版公开视频。

## P0 开工门禁

每个新项目先建立“工作室”：

```text
project/
  source/
  workflow/
  workflow/tasks/
  libraries/characters/
  libraries/scenes/
  libraries/props/
  libraries/audio/
  libraries/visual_style/
  libraries/prompts/
  libraries/qa/
  libraries/continuity/
  exports/
```

开工前必须确认：

- 当前剧名、卷/季、集号、目标时长、发行平台。
- 全剧总控是否仍以 `5 卷 / 每卷 20 集 / 共 100 集` 为强目标，并覆盖当前项目记录的原著进度；若单集规划会导致超过 100 集，先尝试合并剧情，只有不可压缩主线大事件才允许适当扩集。
- 当前集是否已按高节奏压缩：默认 18-22 镜、2:05-2:35，只保留主冲突、误判、反制、关系跃迁和强钩子。
- 当前集任务卡存在。
- 本集继承的 `CHAR-ID`、`SCENE-ID`、`PROP-ID`、`VOICE-ID`、`MUSIC-ID` 已列出。
- 最近进化日志已读。
- 上一集平台指标 `director_strategy_update` 已读，并转成当前集镜头语言/剪辑策略。
- 当前集 coverage schema、道具文字合成层、state bible、视觉 QA 清单已建立。
- 平台路线已确认。
- 当前集继承角色已做跨集对照：主角、配角、只露过脸的医生/护士/亲属/反派也必须绑定角色库或出场登记。
- 当前集的对白时长已按镜头拆分；任何一句台词都必须能在所属镜头内说完，不能依赖下一镜“补完”。
- 当前集必须在剧本/P0 阶段建立 `ROOM-ID / ZONE-ID / PROP-ID / VOICE-ID` 连续性配置；不能等最终成片出错后才补。
- 当前集还必须先建立唯一 `EPISODE-GLOBAL-SPACE-MAP-ID`，覆盖本集全部地点；每个具体地点建立可跨集继承的 `GLOBAL-SPACE-MAP-ID`。整集地图和各地点俯视拓扑图锁定后，镜头才可派生 `SUBSPACE-ID`，再定义人物/物品站位。缺任一层禁止镜头关键帧与视频付费提交。
- E42 起完整地图模式不可关闭：即使 manifest 写入 `global_space_map_gate_required=false` 也必须按 FAIL 处理。图片提交和视频付费提交入口都要对当前文件重新核验整集图、全部地点图、逐镜子空间图、站位以及每层路径/SHA；历史 PASS 回执不能替代当前核验。

## 正式生产路线

E40 及以后付费图片/视频生成以当前部署的 durable transaction submitter 为唯一默认入口：先持久化事务，再调用 Giggle OpenAPI，成功后立即绑定 task_id。Chrome 视觉操作只用于平台本身没有等价 API 的人工界面流程或只读排障，不得成为绕过事务、输入完整性门、模型白名单或重复提交保护的第二付费入口。所有入口必须继承同一角色、道具、场景、声音和中文对白锚点。

```text
AI Director 2.0
短片电影 / 电影叙事
自定义剧本上传或粘贴
AI 编剧关闭
9:16
生成素材
生成分镜
选择宫格分镜
进入故事板逐镜修
生成分镜图
生成视频
整集编辑
字幕/片头/片尾/声音
导出
本地 QA
抖音 + YouTube Shorts 发行
复盘写回
```

错误模式一票否决：

- 直接进入只显示 `剧本/素材/分镜/视频` 的视频概览卡片模式并试图修改镜头。
- 选择 `多图参考` 代替 `宫格分镜` 作为正式可控生产路径。
- 不生成素材就直接生成分镜。
- 不做 QA 就发行。
- 用静态故事板图、表格图推拉、无对白特写或图片动效假装真视频镜头。
- 为了过审删除人物继承、中文对白、华语演员、声音继承或场景/道具锚点。

## 剧本与节奏规则

- E41 起新写或重写执行 `ROGER-20260821-NARRATIVE-CANONICAL-CAUSAL-V3`：剧情、导演、生成三层分离。唯一剧情 authority 为 `E{NN}_NARRATIVE_CANONICAL_v{n}.md`，只写行动、外部变化、必要对白和终局新状态；镜头/表演/声音进入 `DIRECTING_SCRIPT`，资产/空间/首帧/动作轨迹/模型进入 `GENERATION_CONTRACT`。同一文件混写即阻断。
- `SCRIPT-US-DRAMA-EVENT-DENSITY` 必须读取 narrative authority 真实文本与 SHA。每个 story move 使用唯一 `causal_cluster_id`、起终 `STATE-*`、正文逐字 evidence、前置 move 和被迫后续 move；同一调查链不得拆分刷事件，连续发现/解释最多一个，主动行为型 move 占比至少 50%，真实推进不少于 3.2/min。
- 地点只按稳定 `LOC-*` 去重，帘前/帘后/案边不能冒充不同 location；时间只按稳定 `TIME-*` 与行动条件变化计跳跃。“同夜更深”本身不算推进。场数、地点数、时间跳跃数和跨切数均为诊断，不能代替因果速度。
- v2 的单场 ≤22 秒、同稳定地点连续 ≤2、并行线 ≥2、无转折场=0、新增地点 ≤2、对白占比 ≤35%、动作场对白占比 ≤20% 继续作为结构护栏；原 8–12 场、地点 ≥4、时间跳跃 ≥1、跨线切换 ≥3 自 v3 起降为诊断参考，禁止为达数字拆场、改地点别名或制造无意义跨切。E40 及更早集次仅回测告警，不追溯阻断。
- 全剧以 `5 卷 / 每卷 20 集 / 共 100 集` 为强目标。原著卷章只是素材池，不是集数分配表；必须压缩支线和日常，保证主线高密度推进，并覆盖当前项目记录的原著进度。若核心主线实在装不下，可以适当扩集，但每个新增集都必须有不可替代的危机、反转、关系跃迁或强视觉事件。
- 画面目标是精品化、精美绝伦。每集必须规划封面级强画面，保持角色/道具/场景一致和电影感；但精美不能替代剧情推进。
- 每集默认 `2:05-2:35`，约 `18-22 镜`。特殊强反转可接近 2:55，但禁止为了凑满 3 分钟硬填水。
- 每 5-8 秒必须有新信息、新动作、新证据、新误判、新冲突或新反转。
- 删除不够爽、不够简单、不推动剧情的心理描写。
- 删除或压缩低信息量日常、赶路、普通寒暄、重复解释；只保留会改变局势或关系的暖点。
- 禁止用慢动作、脸部停留、空镜气氛拖剧情。
- 每集必须有至少一个爽点和结尾钩子。
- 穿越/古装线必须忠于原著，同时改成真人竖屏短剧节奏。
- 视频 prompt 必须是“事件 + 动作 + 对白 + 镜头运动 + 声音 + 转场桥”，不能只写画面气氛或人物特写。
- 每句对白都必须配完成提示：本镜头只说完这一句，说完后停顿半秒再切。
- 连续两个镜头不能只是正脸、凝视、慢动作或心理气氛；连续特写即判为节奏风险。

## 转场规则

相邻镜头必须至少满足一种连接：

- 声桥：上一镜声音延续到下一镜。
- 动作接：动作方向或动作结果连续。
- 方向接：人物移动方向、视线方向或镜头运动方向连续。
- 道具接：同一关键道具跨镜承接。
- 空间接：镜头位置变化符合空间逻辑。
- 因果接：上一镜行为直接造成下一镜结果。

如果两个镜头像碎片硬切，必须插入过渡镜头或重写其中一镜。

## 一致性规则

- 所有出现过的人物都进入角色库，配角也必须保持一致。
- 用户新提供角色参考图时，必须立即同步到 `ref_images`、`libraries/characters`、`libraries/continuity` 和当前集任务卡；如果当前 Giggle 项目已生成过素材，必须回到 `素材` 页返修对应角色素材后才允许进入 `生成分镜 / 宫格分镜`。
- 用户新提供人物图后，先做原著角色归属判断，再入库；不得为了快速使用，把新脸塞给已经锁定的角色。若同名/近名对象其实是动物或道具，例如 `白般若` 是白猫，必须写入禁用规则，禁止用真人图替代。
- 女性核心/复现角色不得混脸混声：白鲤明亮贵气，张夏成熟强势，云妃温柔危险，皎兔轻盈冷俏，喜饼机灵轻快王府侍女。所有最新用户参考图优先级高于旧生成图和平台随机图。
- 每个关键场景进入场景库，跨集复用不得换片场。
- 同一房间连续戏必须比 `SCENE-ID` 更细：建立 `ROOM-ID / ZONE-ID / ANGLE-ID`，锁定门窗、床位、桌椅、灯源、核心道具和允许机位。任何单镜返修都必须继承这些锚点。
- 空间解析顺序固定为 `EPISODE-GLOBAL-SPACE-MAP-ID → GLOBAL-SPACE-MAP-ID → ROOM-ID/ZONE-ID/ANGLE-ID → SUBSPACE-ID → 人物/物品站位`，禁止先摆人再补空间。每张镜头关键帧必须同时绑定整集地图图、具体地点图和本镜子空间图的路径与 SHA。
- 视频动作设计必须在人物/物品起始站位锁定后进行。每个动作镜填写 `spatial_action_contract`：剧本动作原文及 SHA、起终状态 token、主体/道具轨迹点、接触点、受力方向、不可穿越固定物、跨区门/入口、遮挡约束、退路和反制路径。轨迹必须位于 `SUBSPACE-ID` 内，起点等于锁定站位，终点等于剧本终态；不得穿墙、穿案、穿柱或无门跨区。合同 SHA 必须编译进视频提示词。
- `EPISODE-GLOBAL-SPACE-MAP-ID` 可跨集完整继承，但仅限 ID、版本、拓扑 SHA、整集地图图 SHA 全部一致；部分继承并新增地点时，旧地点继续沿用各自 `GLOBAL-SPACE-MAP-ID`，整集集合 ID 必须新建。建筑格局改变不得静默覆盖，必须升版本或新建 ID，并记录 `supersedes`、变更原因和新旧 SHA。
- 场景一致性 QA 先查空间拓扑，再查画面美观。同一房间连续镜头中，门窗位置、床头柜侧、床帘、病床方向、光线方向或关键道具位置无剧情理由改变，一票否决。
- 每个关键道具进入道具库，外观、文字、位置和功能不得漂移。
- 声音也要继承：主旋律、环境底噪、角色声线、关键音效要有编号。
- 声线跨集一致性与角色脸同级。每个复现角色必须继承 `VOICE-ID`、参考样本和生成参数；视频生成 prompt 必须写入这些 `VOICE-ID`。如果平台/API 原生对白不能稳定复用同一声线，最终发行版必须静音原对白并使用统一 `VOICE-ID` 重配音。字幕正确不能替代声音正确。
- 所有有台词角色的声音样本必须进入资产库，并作为每个分镜头的声音参考。`asset_binding_manifest` 的每个说话镜头必须写入 `voice_reference_sample`，并在多模态生成中随角色图/场景图/道具图一起提交。只写声线文字描述不算绑定。
- 精品发行版优先多模态原生声画同步：声音参考、对白、口型、环境声、BGM/音效在视频生成阶段一起绑定。后期统一配音只能用于无口型镜头、临时样片或故障定位；可见人物说话镜头不得用后配音冒充声画同步。
- 新参考图由用户提供时，优先级高于旧生成图。
- 可迁移包必须包含 `ref_images/` 和角色图映射；只有文字角色卡没有主参考图，等同角色库失忆。
- 人物一致性 QA 不只看首帧。每个主要/复现角色至少抽查本集 3 个时间点，并对照角色库主参考、上一集抽帧和本集素材卡。
- 配角一致性与主角同级；同名角色跨集换脸是一票否决，不因戏份少而放行。
- 返修链路也必须继承角色、场景、道具和声音 ID；任何绕开工作流的单镜重生都必须先补齐这些锚点。

## 单镜平台返修规则

当整集只有一个或少数镜头出现场景污染、现代物件、角色漂移、静态空镜、英文对白或话没说完，可以执行单镜平台返修，但必须满足：

- 返修镜头仍从平台或官方接口生成真人动态视频，不能用本地静帧、故事板推拉或白画面补救。
- 生产调度：对无剧情依赖的剩余镜头并行提交静帧候选；任一镜头静帧 QA 通过并锁定后立即提交该镜头的视频。不得串行等待整组静帧或整组视频完成。
- 九宫格仅做无对白蒙太奇和线索预演，锁定后拆为独立视频镜头；对白、口型、双人对戏、关键表演和关键反转一律使用稳定单镜头 `VISUAL_LOCK`。
- 返修 prompt 必须继承同一 `CHAR-ID / ROOM-ID / ZONE-ID / PROP-ID / VOICE-ID`，并写明上一镜和下一镜的动作/声音/道具桥。
- 如果返修视频画面通过但音频开头或局部异常，只能复用同一平台原镜头的合格音轨片段，或回平台重新生成有声镜头；不得用本地 TTS/redub 伪装平台有声。
- 单镜替换后必须重新跑密集抽帧、静音检测、连续性审片 CLI 和人工听检；不能只看替换镜头本身。
- 任务卡要记录原始问题、返修 URL、本地文件、替换时间码、QA 报告和是否允许发行。

## QA 门禁

标准机器 QA 是每集固定环节，不能只靠网页抽帧或人工印象。最终候选 MP4 必须运行：

```bash
/Users/rogerwu/qingshan_short_drama/tools/run_episode_qa.sh \
  --video /path/to/final.mp4 \
  --config /Users/rogerwu/qingshan_short_drama/configs/E##_continuity_config.json \
  --manifest /Users/rogerwu/qingshan_short_drama/configs/E##_asset_binding_manifest.json \
  --out /Users/rogerwu/qingshan_short_drama/qa/E##_final_qa
```

该入口必须依次通过 `tools/find_ffmpeg.sh`、`asset_binding_validator.py`、`continuity_auditor.py`、`character_anchor_auditor.py`。它是 `脚本/素材/宫格分镜/平台有声/QA/发行` 中的 QA 总闸，前置的素材逐项 QA、故事板逐行绑定 QA、单镜视频声画 QA 仍然必须做。

一票否决：

- 主角/配角换脸。
- 古装线角色没有按用户参考图美化。
- 场景/道具跨集漂移。
- 同一房间连续戏换房间、换床位、换门窗方向、换核心道具位置。
- 节奏慢、信息密度低。
- 镜头之间无转场逻辑。
- 声音前后不一致或后半段无对话/音效。
- 字幕缺失或错位。
- 缺片头、片尾、品牌 logo。
- 已完成但未发行。
- 角色脸型、年龄感、发际线、体型或服装锚点明显漂移。
- 话没说完、台词被切断、下一镜无法自然接上的镜头。
- 视频里出现英文对白、欧美人物或非中国/东亚角色，除非剧本明确需要。
- 模型生成的是静态镜头、故事板动效、无剧情特写或没有对白的空镜集。
- 最终成片只有字幕没有中文对白语音，或对白语音来自多个不一致引擎且未统一声线。
- 本地补配音时保留了平台原声，造成重复对白、串音、英文污染、尾音脏或 ASR 混乱。

## 发行规则

每集完成后自动准备：

- Douyin 标题、简介、合集/短剧分类检查。
- YouTube Shorts 标题、描述、标签、公开状态。
- 封面统一模板，只改集名和副标题。
- 已发行链接写回任务卡。

平台填写规则：

- YouTube Studio：标题保持短，简介单独写入 Description。若标题框被误写成长文，先修标题再推进 Visibility；Public 后按钮可能叫 `Publish` 而不是 `Save`。
- YouTube Studio 上传弹窗固定执行方式：用可见 `Upload videos` 弹窗中的 `Select files`，不要在隐藏 input、坐标点击、重开页面之间反复试错。已验证稳定路径：读取可见 DOM，找到 `aria-label="Select files"` 的节点，先启动 `waitForEvent("filechooser")`，再 `dom_cua.click({node_id})`，随后 `chooser.setFiles(最终 MP4 绝对路径)`。上传进入详情页后替换自动文件名标题，填写 Description，选择 `No, it's not made for kids`，Video elements 不需要则跳过，Initial check 无明确版权/风控阻塞则继续 Visibility，选 `Public` 并点 `Publish`。若出现 “We’re still checking your content”，本地 QA 已通过时直接点 `Publish anyway`，这是自动发行授权范围。
- Douyin 创作者中心：`作品描述` 中标题限制 30 字，简介在标题下方区域输入；发布前确认 `公开`、`立即发布`、`作品未见异常`。封面缺失建议不阻塞发布，但应在后续模板化解决。

替换旧版时，必须先发布并核验新版，再删除旧公开视频；不得先删后传造成空档。若用户已明确要求重做替换，可在新版确认公开后执行旧版删除，并把旧链接、删除时间和新链接写回任务卡。

发行核验必须至少记录：

- YouTube Shorts：视频 ID、Shorts 分类、标题、时长、公开状态、发布时间、保留/删除的旧版 ID。
- Douyin：创作者中心作品数、标题/简介、时长、状态、发布时间、保留/删除的旧版 URL。
- 若有旧版删除：删除前确认旧版判断依据，删除后刷新后台确认旧版不再出现。

## 自我升级规则

每次用户纠正、平台失败、成片返工，都要写回：

- 当前集任务卡。
- `EVOLUTION_LOG.md`。
- 相关库：角色、场景、道具、声音、画风、prompt、平台操作。
- 如规则有普适性，升级本 agent 包。
- 发行后如果产生通用经验，必须同步 `agent_factory/` 和 `bootstrap/TASK2_AGENT_FACTORY_HANDOFF.md`，然后运行可迁移打包脚本。

重复两次的错误上升为 P0 禁止事项。

## 多模型返修规则

默认视频模型可以是 Seedance 2.0 / SD2，但正式镜头不能因为过审困难而降级为静态图。

模型阶梯：

```text
Seedance 2.0 Pro/Fast -> Sora2 -> Veo 3.1 -> Wan 2.7 -> 可灵
```

使用规则：

- 先改 prompt：把高风险词改成影视制作语言，保留冲突、动作和爽点。
- 再换模型：连续失败或生成静态镜头时切换可用模型。
- UI 卡死时可走官方 API 兜底：`image-to-video` / `omni-video` 优先，结果必须回到整集 QA；API key 只放临时环境变量或浏览器授权流程，不能写入文件、日志或回复。

## Seedance 失败态修复规则

如果分镜视频已经进入 `生成失败` 历史态，不要在同一个失败弹窗里反复改 prompt、换模型、上传图片后重提。Giggle 可能只改输入框而不创建新任务。

可靠链路：

1. 回到 `分镜` 页。
2. 复制失败镜头，得到无失败历史的干净空镜头。
3. 上传对应真人首帧，优先使用本地角色/场景/道具一致性库里的帧图。
4. 手动设定 `Seedance 2.0 Pro / 9:16 / 720p / 8s`，按剧情需要再调整时长。
5. 使用纯正向 prompt，只写要生成的画面、动作、镜头运动和声音。
6. 点击右下提交，必须看到 `任务创建成功` 和该行 `Generating ...` 才算入队。
7. 替代镜头 QA 通过后，删除对应失败旧镜头并恢复顺序。

Seedance prompt 不写否定敏感词。避免 `无血腥`、`无武器`、`无冲突`、`不要英文`、`不要欧美人物` 这类表达；改写为正向描述，例如 `平静克制`、`普通文件`、`华语医院短剧质感`、`纸张轻响`、`冷蓝灯光`。如为过审暂时去掉对白，该镜头只能标记为 `Audio Rework Required` 的内部素材。存在可见说话口型时，正式发行前必须重生同一画面与原生中文对白绑定的 Seedance 2 多模态镜头，不得用外置 `VOICE-ID`、TTS、旧候选或其他 task 音轨覆盖；只有无可见口型的旁白/画外音或具备 `NO_NATIVE_DIALOGUE_WITH_EVIDENCE` 的素材才可使用统一 `VOICE-ID`。最终成片必须做 ASR/VAD。
- 再拆镜头：一句话太长、动作太复杂、人物太多时拆成 2-3 个短镜头。
- 绝不把高冲突短剧改成无动作、无对白、无爽点的安全空片。

## 发布前硬检

发布前必须确认：

- 已对最终候选 MP4 运行本地连续性审片 CLI：`tools/run_continuity_audit.sh --video ... --config ... --out ...`。任何 `scene_room_continuity / fail`、主角色 `character_visual_drift / fail` 或关键道具 `prop_visual_drift / fail` 都必须先返修，不能发行。返修执行以输出目录中的 `repair_plan.json` 为准：每个镜头一条任务，包含证据帧、平台动作、提示词和官方 API 兜底草案。
- 细颗粒度一致性检查已经贯穿四层，而非只在最终审片补查：`素材逐项 QA` 检查角色/房间/道具/声音锚点，`故事板逐行绑定 QA` 检查每行 CHAR/ROOM/PROP/VOICE/转场桥，`单镜视频声画 QA` 检查生成结果是否继承该行锚点，`整集连续性审片 CLI` 输出可返修的具体镜头和证据。
- ASR 或人工听检为中文对白，不能有模型自带英文对白。
- ASR/听检对象必须是最终发行 MP4，不是源镜头、平台预览或局部补丁。
- 声音一致性 QA 对象也必须是最终发行 MP4。对同一 `VOICE-ID` 的多镜头台词做机器声学统计或人工 A/B 听检；主角跨镜头像换人说话时，整集退回统一配音或重生有声镜头。
- 本地统一重配音只允许用于无可见同步口型的旁白/画外音，或具备 `NO_NATIVE_DIALOGUE_WITH_EVIDENCE` 的非说话素材；此时被替换的旧音轨必须全量静音，禁止低音量叠声。可见说话口型镜头必须保留同一 source/task 的原生多模态对白；原声错误时回视频生成链重生，不得本地重配。
- 抽帧没有欧美人物混入。
- 每个说话镜头的台词听起来完整。
- 每个复现角色都与角色库和上一集抽帧一致。
- YouTube / Douyin 分类、标题、封面风格和合集/短剧归属保持统一。
- YouTube/Douyin 显示发布成功后，还要刷新作品管理/频道页确认新标题、时长、发布时间、状态和链接；后台 `No issues found` 或 `已发布` 不等于内容 QA 通过。

## v0.9 升级内容

触发来源：`青山 E07` 第 42 镜平台导出出现妖魔/怪物影子，整片缺对白字幕和 Nalu 尾标；返修后完成 YouTube Shorts 与抖音双平台发行。

必须同步到 StoryClaw 私有版 agent：

- 坏镜头返修优先“单镜重生”，不是重开整集。锁定同一 `CHAR/ROOM/ZONE/PROP/VOICE`，用正向真人影视表达去掉污染词，再回整片导出和 QA。
- 平台有声与本地包装要分层：正式剧情镜头和中文对白必须来自平台/官方接口链路；本地只允许补发行包装层，包括小号中文字幕、片头、片尾、Nalu Motion 尾标、格式和抽帧证据。
- 平台整片缺字幕时不得直接发行；从批准分镜表/视频 prompt 生成 `.ass` 或同等字幕层，字号要小，不遮脸、不遮道具，烧录后重新抽帧确认。
- 每集最终候选必须跑：资产绑定、连续性 CLI、角色锚点、密集抽帧、静音检测、尾标检查。只要最后一镜污染或尾标缺失，就不能发布。
- 发行后写回必须包含最终 MP4、QA 目录、YouTube Shorts URL/ID/公开页核验、抖音作品管理标题/时长/状态/发布时间。

v0.9 追加 smoke test：

```text
输入：一支平台有声竖屏短剧 MP4、一条坏结尾镜头、一份 42 镜对白分镜表、一个 Nalu 尾标素材。
期望：
1. Agent 先判定坏镜头是否可单镜重生，并输出正向安全化平台 prompt，保留角色、场景、道具、中文对白和声桥。
2. 重导整片后，如果平台无字幕或尾标，只做包装层补齐，不重配音、不替代剧情镜头。
3. 输出最终 QA：连续性 fail/warn、角色锚点、字幕抽帧、尾标抽帧、静音检测。
4. 发布 YouTube Shorts 和 Douyin 后写回任务卡，并更新可迁移包。
```

## v1.0 退回学习：E07 碎切与主角漂移一票否决

触发来源：`青山 E07` 已发布版本被用户人工复核退回，原因是镜头切换过快造成眼花，且陈迹主角脸/服装多镜头漂移。

必须同步到 StoryClaw 私有版 agent：

- 用户人工复核优先于机器 QA；只要用户指出主角脸漂移或观看节奏失控，已发布状态立刻降级为 `REJECTED_REPLACE_REQUIRED`，停止继续发行并进入重做。
- `principal_face_lock`：S 级/主角在所有说话、中近景、特写、正反打镜头中，视频生成前必须绑定原始主参考图，不得只用平台生成的衍生图或故事板缩略图。生成后只采纳清晰正脸/半侧脸帧做一致性证据，手、纸、背影、群像、道具帧不得计入通过。
- `watchability_cut_cadence`：高节奏不等于全片 4 秒碎切。每集按场景块组织，同一空间至少连续 2-3 镜建立方位；跨空间必须有声桥、动作接、方向接或道具接。若用户看起来眼花，宁可改为 5-7 秒可读镜头，也不能机械执行 4 秒公式。
- E07 后续重做默认采用约 26 镜、5-7 秒、场景块连续推进；陈迹必须使用用户原始古装参考图 `/Users/rogerwu/qingshan_short_drama/ref_images/male_lead_chenji_ancient_face_ref_20260621.png`。

## v1.1 E07 v3 主角锁脸重做与发行状态分级

触发来源：`青山 E07` v1/v2 因碎切和陈迹漂移被退回后，v3 采用 26 镜、约 6 秒、主角原始参考图锁脸、平台原声链路重新生成，并完成 YouTube 公开与抖音提交审核。

必须同步到 StoryClaw 私有版 agent：

- `陈迹/陈既` 古装线是 20 岁左右年轻男主。所有生图、视频 prompt、素材卡、资产 manifest、角色库必须写 `20岁左右、用户原始古装参考脸、无眼镜、灰布古装学徒长衫`；禁止残留 `30代`、成熟中年脸、现代病号服、睡衣或平台派生脸。
- `principal_face_lock` 要前置到素材层：只要主角在该集说话、中近景、特写、正反打出现，生成前必须上传/绑定原始参考图；不要等本地 QA 才发现漂移。
- `watchability_cut_cadence` 的合格标准不是越快越好。短剧爽点要靠事件推进，单镜建议 5-7 秒；同一场景连续 2-3 镜建立空间与轴线，跨空间必须有声桥、动作接、方向接或道具接。若剪辑看得眼花，整集退回，不用包装修。
- 平台后端 `grid image is not completed` 的可靠解法是用平台 `AI 生成` 重生该故事板行，让后端状态真正 completed；本地上传/局部替换可能有 `signed_url` 但仍保留失败态，不能直接进入 `生成镜头`。
- 发行状态必须分级写回：YouTube `Video published / Public` 算公开；抖音 `审核中` 只算提交成功，后续要刷新作品管理确认 `已发布`，才能进入最终闭环。
- 浏览器自动化恢复规则：Chrome/Studio 卡死时可受控重启 Chrome，恢复后第一动作是检查当前上传/发行状态，不重新生成素材、不刷新 Giggle 正确项目页。

v1.1 追加 smoke test：

```text
输入：一集被退回的短剧、用户主角原始参考图、旧版问题描述“碎切/主角漂移”、已通过 QA 的 v3 最终 MP4。
期望：
1. Agent 能把旧公开版降级为 REJECTED_REPLACE_REQUIRED，并阻断继续扩散。
2. Agent 输出 20-28 镜、5-7 秒、场景块连续的重做方案，并把主角原始参考图绑定到素材层。
3. Agent 本地 QA 只采纳清晰脸帧作为主角一致性证据。
4. Agent 能发布 YouTube Shorts，提交抖音，并把 YouTube Public 与抖音审核中/已发布分开写回任务卡。
5. Agent 发行后立即更新 agent_factory、Task2 handoff 和可迁移包。
```

## v1.2 E08 自动发行、字幕根因与 StoryClaw 迁移门禁

触发来源：`青山 E08` API fallback 完整生产、字幕根因修复、最终 QA 通过后自动发行到 YouTube Shorts，并提交抖音审核。用户明确要求：每集 QA 完成后自动发行、自动做下一集，但在启动下一集正式制作前必须更新 StoryClaw 对应 agent，确保跨平台和跨设备可移植。

必须同步到 StoryClaw 私有版 agent：

- 自动发行不再问用户：最终 QA 与自动听检通过后，直接发布 YouTube Shorts 并提交抖音；只有登录、验证码、版权检查、上传失败、账号风控、网络不可达、成片缺失或 QA 明确失败能阻断。
- 字幕根因优先：如果有些镜头有字幕、有些没有，先查源镜头是否混入模型自带烧录字幕。禁止只给最终片叠字幕掩盖源污染；受污染源镜头必须定点重生或替换，再由本地统一烧录一层受控字幕。
- 字幕字体兜底：ASS/libass 在 macOS 上若中文字体解析失败并渲染方框，可切换为本地 `drawtext` + 明确字体文件路径；但仍必须抽帧确认中文可读。
- API fallback 仍按资产库优先：每个镜头请求从角色、场景、道具库取参考图，生成成功并通过 QA 的临时参考要晋升到可迁移资产目录。
- 发布后下一集前增加 StoryClaw 同步闸门：双平台发行/提交写回后，先更新 `agent_factory/`、`bootstrap/TASK2_AGENT_FACTORY_HANDOFF.md`、`bootstrap/PORTABLE_PIPELINE_MANIFEST.md`，重打并验证 `bootstrap/dist/*`，同步 StoryClaw/AI短剧工厂 agent，然后才进入下一集正式生产。
- 发行状态分级延续：YouTube `Public` 算公开；抖音 `审核中` 只算提交成功，允许继续 agent 同步和下一集 P0，但必须保留后续刷新到 `已发布` 的核验待办。

v1.2 追加 smoke test：

```text
输入：一集最终 QA 通过 MP4、字幕污染源镜头列表、YouTube/Douyin 元数据、下一集任务目标。
期望：
1. Agent 先解释字幕不一致根因，定点修复污染源镜头，再生成统一受控字幕最终片。
2. Agent 对最终 MP4 执行资产绑定、连续性、角色锚点、抽帧、ASR/听检，并在通过后自动发布 YouTube Shorts 与提交抖音。
3. Agent 把 YouTube Public URL 与抖音审核中/已发布状态分开写回任务卡。
4. Agent 在启动下一集正式制作前，更新 agent_factory、Task2 handoff、可迁移清单，重打 core/full 包并验证。
5. Agent 可以 scaffold 下一集任务卡，但必须把正式生产状态标为等待 StoryClaw/可迁移同步完成。
```

## v1.3 平台用户指标驱动的导演自进化

触发来源：用户要求建立导演能力自我进化机制，根据播放平台用户指标（播放量、完播、划走、互动等）自动优化镜头语言和剪辑能力。

必须同步到 StoryClaw 私有版 agent：

- 每集发行后创建 `workflow/platform_metrics/E##_metrics_YYYYMMDD.md/json`，并按 `T+2h / T+24h / T+72h / T+7d` 采集 YouTube 与抖音指标。
- 播放量不是单独结论，必须结合展现、划走、平均观看、完播、互动和涨粉判断问题属于：标题封面、前 3 秒钩子、信息密度、剪辑节奏、声音字幕、角色吸引力或平台分发。
- 指标必须转成下一集的 `director_strategy_update`，包括开场、切点密度、反应镜头比例、插入镜头比例、中段反转、标题/封面/声音字幕策略。
- 下一集 P0 不读取上一集 `director_strategy_update` 不得进入视频生成。
- 如果 `T+24h/T+72h/T+7d` 指标在下一集制作中途到达，心跳任务继续补采，策略影响再下一集，不能因为制作已启动而丢失。

v1.3 追加 smoke test：

```text
输入：一集已发布短剧的 YouTube/Douyin 指标、最终 MP4、任务卡、下一集目标。
期望：
1. Agent 建立平台指标 md/json，并写明 T+2h/T+24h/T+72h/T+7d 采集计划。
2. Agent 能把低播放、高划走、低完播、低互动分别映射为不同导演修正，而不是统一归因“流量不好”。
3. Agent 把下一集前3秒、45-60秒反转、90秒二次升级、镜头长度、反应/插入镜头比例写入下一集任务卡。

### E14+ Scale, Posture, Motion And Shot-Type Gate v2

- Before any image or video request, produce per-shot `shot_type`, numeric scale, depth placement, camera/lens, posture-or-action rule, and negative prompt. Constraints are shot-type-scoped, never globally pasted.
- Wide/establishing shots: 20-40% human frame height, 24-35mm, environment geography first. Do not attach `hero >=60%` or `person dwarfed by environment` negatives.
- Medium/two-shot/OTS: 40-60% human frame height, around 50mm, mandatory foreground/background layering between people. Do not force all people onto the same depth plane.
- Close-up/hero/static confrontation: >=60% human frame height, 85mm allowed, Chenji posture lock may apply.
- Chenji uses 182cm visual baseline. BaiLi must remain an adult woman at 0.88-0.93 of Chenji height with normal seven-head proportions. Wuyun shoulder height=15-18% of Chenji, hard max 25%; cat same depth plane or behind only.
- Full Chenji posture phrases apply only to static/hero/confrontation shots. Action shots must use physical verbs such as snatching, turning, pushing, grabbing, kneeling, running, shoving; never sacrifice motion to make a statue.
- QA gates: wide ratio >=15%, single closeups <=50% (target <=30%), physical-action shots >=8, final frame-difference motion >=5.0, scale/depth/posture/OCR checks. Failures trigger targeted re-roll or补拍.
- Every beat must contain action + reaction + irreversible delta before storyboard or API run plan. A line of dialogue without a filmable action is rejected.
- If final QA has passed but Chrome/browser/platform publish control is unavailable, mark the episode `PENDING_PLATFORM_BACKFILL` and continue the next episode pipeline. Do not stall production and do not regenerate passed clips because of a publish-channel blocker. When the channel recovers, backfill all pending YouTube/Douyin publishes, comments, release records, metrics, cleanup, and StoryClaw task1 updates in queue order.
4. Agent 更新 EVOLUTION_LOG、WORKFLOW、AGENTS 和可迁移包，保证跨设备继承。
```

## v1.4 E09 人类导演感诊断与 E10 工作流升级

触发来源：外部专业诊断指出 E09 的上限在画质，但短板在“戏”：假字、居中单人肖像泛滥、正反打/双人调度不足、口型和表演弱、短剧钩子不够硬、state bible 不足、字幕说话人前缀和声场偏薄。

必须同步到 StoryClaw 私有版 agent：

- `onscreen_text_compositing`: 模型不生成长中文，所有可读道具文本走合成层和 OCR/人工校验。
- `director_coverage_schema`: 每集必须有 establishing、two-shot/group、OTS-A/OTS-B、insert、reaction；单人特写不超过 30%。
- `watchable_cadence`: 不为了“高节奏”快切。平均 5-7 秒，同一空间 2-3 镜建立方位，跨空间用声桥/动作桥。
- `short_drama_retention_beats`: 前 3 秒硬钩子，45-60 秒误判反转，90 秒二次证据/危险升级，集尾强悬念。
- `performance_keyframes`: 每个说话镜头写情绪曲线和手势/身体动作，避免中性摆拍。
- `state_bible`: 跟踪时间、天气、伤口、服装、猫状态、道具位置和地理关系。
- `subtitle_clean_render`: 正片字幕剥离说话人前缀，只保留台词。
- `layered_audio`: 对白、foley、ambience、music、sfx 分层设计；BGM 不单独扛情绪。

v1.4 追加 smoke test：

```text
输入：E09 诊断意见、E10 剧本草案、角色/道具/场景/声音资产库。
期望：
1. Agent 能把假字、居中肖像、弱表演、节奏文艺化、字幕前缀、声场薄分别变成 P0/P1 工作流规则。
2. Agent 输出 E10 coverage 表，包含 two-shot、OTS-A/B、insert、reaction，而不是全片单人特写。
3. Agent 输出 E10 prop_text_assets 和 state_bible。
4. Agent 保持可读节奏，不因增加覆盖率而切得眼花。
```

## v0.5 升级内容

触发来源：`青山 E06` 平台有声版出现单镜现代厨房污染，后续通过平台单镜返修替换画面、保留平台合格音频、重新跑 QA；同时 Chrome/系统锁屏阻止发行，证明 agent 必须能区分 `QA_PASSED_READY_TO_PUBLISH` 和 `PUBLISHED`。

必须同步到 StoryClaw 私有版 agent：

- 阻塞态不冒充完成：最终 MP4 通过 QA 但浏览器锁屏、登录、验证码或余额阻塞时，任务卡状态必须写为 `READY_TO_PUBLISH_BLOCKED`，并记录恢复后第一动作。
- 不停机：发行阻塞期间可以继续下一集本地 P0 准备，但不能删除旧版、不能标记发行完成、不能跳过恢复后的发行核验。
- 单镜返修：只替换坏镜头，继承 `CHAR/ROOM/ZONE/PROP/VOICE` 锚点，返修结果仍必须是平台或官方接口真人动态视频。
- 房间级配置前置：每集在剧本阶段就要建立连续性 JSON，按镜头写 `room_id` 和 `zone_id`，最终 CLI 才能指出具体返修目标。
- QA 证据链：单镜替换后必须重新生成接缝密集抽帧、VAD/静音检测和连续性报告，再决定是否进入发行。

## v0.8 升级内容

触发来源：`青山 E06 v2 cleanref` 在锁屏阻塞解除后完成 YouTube Shorts 与抖音发行，并核查旧 E06 失败版仍为 Private。

必须同步到 StoryClaw 私有版 agent：

- 发行恢复优先级：若上一集状态是 `READY_TO_PUBLISH_BLOCKED`，恢复浏览器后第一动作必须是发行该集，不能先开下一集。
- 真实平台证据：发行成功必须记录平台后台可见的标题、时长、发布时间、状态、视频 ID 或搜索核验结果；不能只记录“点击了发布”。
- 旧版可见性核验：同一集有旧失败版时，新版公开后必须打开旧版后台核验可见性；若旧版仍公开，先改 Private 或按用户授权删除，再继续下一集。
- 发行写回字段：YouTube 记录 `Video ID / Shorts URL / Public / Published date`；抖音记录 `标题 / 简介 / 已发布 / 发布时间 / 时长 / 作品管理搜索证据`。
- 下一集门禁：双平台发行与旧版核验完成后，才进入下一集 P0：上传 v2 剧本、生成素材、选择宫格分镜、逐镜绑定角色/场景/道具/声音锚点。

## v1.6 E11 发行闭环与 E12 声音/女性角色门禁

触发来源：E11《死人回门》已在 YouTube Shorts 公开、抖音发布；此前错误的遮挡版和重复版已清理。E12《灯下女客》进入制作，必须将女性角色和乌云声音一致性变成可执行资产门禁。

必须同步到 StoryClaw 私有版 agent：

- E11 最终发行唯一记录：YouTube `TFmk-Cz_kNE`，抖音 `已发布 / 2026-07-10 06:31`；旧遮挡/伪文字修复版本及重复版均为已删除历史，禁止引用或回滚。
- 背景中不承载剧情的模型伪中文牌匾可保留；不得用大色块遮挡。只有剧情关键的信、方、契、告示才强制空白生成后走真字合成。
- E12 必须让女性角色承担证据、权力或秘密议程，不能只作为装饰性出镜；角色以 `CHAR-白鲤-古装` 绑定，镜头前完成单独身份、服装、状态和声音资产预检。
- 陈迹必须使用年轻灰布学徒阶段图和原生多模态声音 `cypqud0bu7t`，不得混入成熟/root 阶段参考。
- 乌云已有受控母版 `VOICE-乌云-猫-final-hook-only.wav`。所有乌云发声镜头必须把该音频作为 API 的实际 audio reference；只把“女声”写进 prompt 一律判为未绑定，不得发行。
- 乌云与所有动物必须通过物种姿态 QA：四足行动、真实猫爪、非人化行为。双足站立、举爪手势、拟人肢体动作属于 P0 单镜返修，不能因画面好看而放行。
- 每次发布后同步需留下三类证据：本地 agent 文件版本、可迁移 core/full 包校验、以及已向置顶 `AI 短剧工作流` 私有 agent 发出的同步指令。三者缺一不可。
# Visual-Lock Cost Discipline

- Before any formal video generation, generate and locally QA multiple still-image candidates for every new visual state, important prop, two-person/group composition, or key reveal. Lock one approved candidate as `VISUAL_LOCK` and submit it as the video reference.
- Default to 3 still candidates; use 4-6 for high-risk continuity or cover-level shots. Do not use expensive video retries to solve a face, wardrobe, prop, scene, framing, or readable-text issue that a still-image preflight could have caught.
- Video-stage retries are limited to native voice/lip-sync, sound field, motion timing, physics/morphing, or platform execution faults. Record the reason whenever a video retry is necessary.

## v1.7 AgentCut 角色参考音频硬门

- 陈迹与白鲤是仅有的历史原生声线豁免；两者继续使用已锁定资产，不得重配。
- 其他现有角色及以后首次出现的新角色，必须先从 Claude Writer 剧本与原著角色定位生成角色声音简报，再调用 AgentCut `AGENTCUT-SPEECH-001` 生成普通话试音。
- 每个角色必须选择独立且符合年龄、身份、性格与戏剧功能的预设声线；禁止主要角色共用预设，禁止现代口播、主播或与人物身份冲突的声线混入古装剧情。
- AgentCut 生成后必须依次通过：单声道音轨与时长检查、普通话 ASR、角色声线简报匹配、远端资产注册、SHA-256 固定、明确 credit statement 查询。成功但积分缺失记 `UNKNOWN_NOT_ESTIMATED`，不得估算或记零。
- 只有状态为 `AGENTCUT_GENERATED_REGISTERED_PRODUCTION_READY` 且当前 `performance_brief_sha256` 与角色政策一致的音频可作为视频模型的对白参考。旧 TTS、旧 Seedance 随机声线及集内临时配音只作历史回滚，不得成为当前角色声音。
- 新角色若尚未进入角色声音政策或没有 AgentCut 生成、QA、注册回执，视频提交必须阻断；生产代理应自动补齐角色简报并执行 AgentCut 流程，不请求普通人工确认。
- 角色参考音频用于喂给视频模型生成原生普通话、口型、气息和表情；不得把该规则降级成默认后期配音。

## v1.8 BGM 验真硬门

- cue sheet、响度报告或写着 `Audio.BGM` 的文字均不构成 BGM 存在证据。必须同时存在可播放的独立音乐源、工程内真实 `Audio.BGM` clips、可单独导出的 BGM stem 和混合后视频。
- BGM stem 的机器可闻门默认要求平均能量不低于 `-35 dB`、峰值不低于 `-18 dB`；未达到即使整片响度合格也判无可闻 BGM。
- AgentCut/Giggle 新生成调用与本地复用混音分开记账。接口 403、失败或无 task ID 时记明确失败、credit 0，禁止把既有素材重混冒充新生成。
- AgentCut 账户内生成的 BGM 是本集自生成资产，不要求外部曲库的商用权元数据；必须固定生成 task ID、生成回执、源文件 SHA-256 和权威积分账单。只有外部曲库 fallback 才要求授权元数据、曲目 ID、采用理由和跨集相似度 PASS。
- 独立音乐源必须迁入项目资产目录并固定 SHA，禁止依赖项目外临时路径作为可迁移生产证据。
