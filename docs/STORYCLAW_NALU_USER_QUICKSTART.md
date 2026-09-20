# StoryClaw NALU 用户快速上手

TalentHub 安装完成后，用户只需要先给出故事内容。可以直接粘贴正文或大纲，也可以上传
文本文件，或提供一个公开可访问的网址。参考剧照、场景图、道具图、音频和视频可以同时
上传，也可以稍后一次性补充。

剧名可以省略，系统会先创建“Untitled short drama”私有项目；剧本形成后可再设置正式名称，
不会因此阻塞来源接收。

首次对话可以直接这样说：

```text
新建一个竖屏短剧项目。原著在我上传的 story.txt；附件中的图片都是可用参考素材。
```

或者：

```text
新建一个竖屏短剧项目，来源网址是 https://example.com/my-story 。
```

代理会自动使用安全默认值：首集 `E01`、竖屏 `9:16`、每集 8000 积分上限、关闭付费
请求、关闭平台发布。剧名、语言、预算或集号由用户明确给出时才覆盖对应默认值。每个项目
都有独立私有目录、系列作用域、素材库、订单、账本、事务和评审记录。

## 用户会经历的流程

1. **提供一个来源。** 粘贴文本、文本文件和公开网址三选一。网址受安全检查约束，无法
   获取时改为粘贴或上传正文。
2. **代理自动生成剧本。** 代理生成四层剧本，执行 S1 剧本门禁和 S2 预制作。此时不要求
   用户逐角色选择素材，也不会调用付费生成接口。
3. **一次确认完整方案。** S1/S2 通过后，代理根据剧本自动匹配所有上传素材，并为每个
   缺口选择 AI 生成方案。方案一次列出剧本假设、角色、场景、道具、主角来源、模型、
   提示词、预计费用和风险。用户只需确认整份方案一次；方案有任何改动，旧确认立即失效。
4. **按门禁生产。** 确认后，仍需订单、预算、付费双锁和事务去重全部通过，才会运行
   S3→S8。评审停点必须使用真实媒体和真实回答。
5. **审看私有交付物。** S8 完成后检查成片、QA、账本和检查点。代理不会自动上传或公开
   发布。

## 版本升级

代理会每天静默检查经过签名和 StoryClaw 实机验收的稳定版。没有新版时不会打扰你；有
普通引擎更新时，它会先在旁边安装并验证新版，只在剧集尚未开始或到达安全停点后切换。
正在运行的一集会继续使用启动时的版本，不会制作到一半换引擎。验证或切换失败时，项目
继续使用原来的可用版本。

如果新版同时修改了安装流程、使用引导、依赖或运行时结构，代理会保留当前版本并明确提示
你执行一次：

```bash
talenthub agent update ai-drama-factory
```

更新完成后，代理会自动重新检查安装和项目状态，再从已有检查点继续。不要让项目直接跟随
GitHub 的 `main` 或 `latest`；只有已签名、已验收并发布到稳定通道的精确版本才会被采用。

`storyclaw_guided_onboarding.py` 返回固定结构的中英双语 JSON。普通用户界面可显示
`message.zh-CN` 或 `message.en`，自动化进程应读取稳定的 `state` 与 `next_action.id`，
不要通过解析自然语言决定下一步。

常见状态如下：

| `state` | 含义 | 是否需要用户输入 |
| --- | --- | --- |
| `SOURCE_REQUIRED` | 还没有故事来源 | 提供一个来源，不是确认 |
| `SCRIPT_READY` / `SCRIPT_IN_PROGRESS` | 自动运行或恢复 S1/S2 | 否 |
| `SCRIPT_BLOCKED` | 按真实门禁失败项修复 | 通常由代理修复 |
| `ASSET_PLAN_READY` / `ASSET_PLAN_BLOCKED` | 自动生成或补齐完整素材方案 | 否 |
| `CONFIRMATION_REQUIRED` | 完整剧本与素材方案已可审查 | **唯一一次方案确认** |
| `PRODUCTION_READY` / `PRODUCTION_IN_PROGRESS` | 检查授权后运行或恢复 S3→S8 | 否 |
| `COMPLETE` | 私有交付物可审看 | 否 |

## 代理/API 用法

StoryClaw agent 直接调用 Python API 时，可以把聊天中粘贴的文字以内存参数传入；返回值
不会回显正文：

```python
from tools.storyclaw_guided_onboarding import start_project

result = start_project(
    "/private/nalu-projects",
    "/opt/nalu-engine",
    title="My series",
    source_text=user_pasted_text,
    materials=uploaded_file_paths,
)
```

命令行应通过标准输入接收粘贴正文，避免正文进入进程参数或 shell 历史：

```bash
python tools/storyclaw_guided_onboarding.py start \
  --projects-root /private/nalu-projects \
  --engine-root /opt/nalu-engine \
  --title "My series" \
  --source-text-file - < /private/upload/source.txt
```

文件和网址来源分别使用 `--source-file`、`--source-url`。多个参考素材可以重复添加
`--material /private/upload/file`；目录会在不跟随符号链接的情况下展开，并复制到项目的
内容寻址私有存储。查看下一步不会执行任何写入或 provider POST：

如果先创建空项目，随后才提供来源，使用 `add-source`，不需要重新初始化项目：

```bash
python tools/storyclaw_guided_onboarding.py add-source \
  --project-root /private/nalu-projects/my-series \
  --source-file /private/upload/story.txt
```

```bash
python tools/storyclaw_guided_onboarding.py status \
  --project-root /private/nalu-projects/my-series
```

所有成功来源都有 SHA-256 收据；所有参考素材都绑定私有文件路径与 SHA-256。原著正文、
素材、剧本、方案、确认、评审、账本、事务和交付物不能进入公开仓库或 TalentHub 包。

## English summary

After installation, provide exactly one story source: pasted text, a local text file, or a public URL.
Optional reference files may be supplied together. The agent creates an isolated private project, runs
script and preproduction gates, then proposes one complete asset plan. It does not ask the user to make
item-by-item casting choices. The only plan confirmation occurs after the script and the complete asset
plan exist. Paid generation still requires all order, budget, paid-lock, and transaction gates. Outputs
stay private and no platform publication happens automatically.
