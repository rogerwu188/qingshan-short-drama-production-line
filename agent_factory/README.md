# AI短剧工厂 Agent 包 v0.9

这个目录是把《青山》AI 制片厂经验沉淀为 StoryClaw 可发布 agent 的最小核心包。

目标不是只做《青山》，而是让任意 StoryClaw 用户安装 agent 后，可以把小说、剧本、人物参考图、平台账号和预算交给它，由它按工作室制完成短剧改编、分集生产、质量检查、发行和复盘升级。

## 文件说明

```text
USER.md      面向安装用户的能力说明、输入要求和交付承诺
SOUL.md      Agent 的角色、审美、底线和创作人格
AGENTS.md    可执行工作流、平台操作规则、QA 门禁和升级机制
PACKAGE.md   发布、迁移、升级和版本治理规则
```

## 必须绑定的外部知识库

发布到 StoryClaw 前，Task2 必须把以下本地文件作为 agent 知识或附件导入：

```text
/Users/rogerwu/qingshan_short_drama/AI导演短剧创作手册.md
/Users/rogerwu/qingshan_short_drama/08_AI导演自我进化机制.md
/Users/rogerwu/qingshan_short_drama/workflow/WORKFLOW.md
/Users/rogerwu/qingshan_short_drama/codex_docs/AGENT协作信箱协议_20260711.md
/Users/rogerwu/qingshan_short_drama/codex_docs/生产线全流程与门禁总览_20260713.md
/Users/rogerwu/qingshan_short_drama/codex_docs/每集标准生产全流程_v1_E17起_20260713.md
/Users/rogerwu/qingshan_short_drama/codex_docs/AI短剧工厂_全局基础技能控制红线_20260713.md
/Users/rogerwu/qingshan_short_drama/workflow/STORY_DOCTOR.md
/Users/rogerwu/qingshan_short_drama/workflow/EDIT_DOCTOR.md
/Users/rogerwu/qingshan_short_drama/libraries/tools/TOOL_CAPABILITY_REGISTRY.md
/Users/rogerwu/qingshan_short_drama/libraries/qa/QA_CHECKLIST.md
/Users/rogerwu/qingshan_short_drama/libraries/qa/EVOLUTION_LOG.md
/Users/rogerwu/qingshan_short_drama/libraries/characters/CHARACTER_LIBRARY.md
/Users/rogerwu/qingshan_short_drama/libraries/scenes/SCENE_LIBRARY.md
/Users/rogerwu/qingshan_short_drama/libraries/props/PROP_LIBRARY.md
/Users/rogerwu/qingshan_short_drama/libraries/audio/AUDIO_LIBRARY.md
/Users/rogerwu/qingshan_short_drama/libraries/visual_style/STYLE_LIBRARY.md
/Users/rogerwu/qingshan_short_drama/libraries/continuity/ASSET_CONTINUITY_INDEX.md
/Users/rogerwu/qingshan_short_drama/libraries/continuity/CAST_APPEARANCE_REGISTRY.md
/Users/rogerwu/qingshan_short_drama/bootstrap/PORTABLE_PIPELINE_MANIFEST.md
/Users/rogerwu/qingshan_short_drama/bootstrap/NEW_MACHINE_BOOTSTRAP.md
```

## v0.9 当前核心能力

- Claude 与 StoryClaw 双监制异步通信：`CL2X/SC2X/C2C` 编号、信箱回贴、StoryClaw 文件桥、云端复核包交付。
- 通用资产继承引擎：角色同脸同身材、场景/道具复现不重建、服装/天气/状态变体必须有剧情理由。
- 剧本 Gate：广播剧检验、口吻盲测、台词人味、语气/潜台词/停顿/重读字段、因果/常识 C1-C5。
- 生成 Gate：VISUAL_LOCK 静帧前置、两段式 prompt 合同、视觉 prompt 不写对白、音频字段单独写台词。
- 覆盖与生产方式：A/B/insert/crowd coverage、15 秒连续段实验、short-controlled source、insert composite。
- QA 工具链：RapidOCR 成片/静帧、ffmpeg、CI、亮度、ASR/VAD、资产绑定、连续性、角色锚点、StoryClaw 同步验证。
- 发行闭环：YouTube/抖音发行、后发行指标、旧版清理、StoryClaw/portable 包同步、自动开下一集。

## 发布原则

- 初版必须先设为 Private，用于 hire/smoke test。
- smoke test 至少覆盖：小说改编、角色库创建、单集任务卡、宫格分镜路线、QA 返修、发行清单。
- 通过后再考虑 Public。
- 每次《青山》生产中新增硬规则，都要同步升级本 agent 包。
