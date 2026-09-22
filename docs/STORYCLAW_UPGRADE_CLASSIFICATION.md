# StoryClaw 升级影响分类

TalentHub Agent 不直接跟踪 `main`。每次发布先把上一个已发布 tag 与候选 tag 交给分类器：

```bash
.qingshan-venv/bin/python tools/storyclaw_upgrade_classifier.py \
  --base v2026.09.19-storyclaw-port \
  --target v2026.09.20-storyclaw-port \
  --pretty
```

`--base` 和 `--target` 只接受完整 Git commit ID 或精确 tag。分支、`HEAD`、`main`、缩写 commit、倒退和分叉比较都会失败关闭。输出是
`storyclaw.nalu.upgrade_impact.v1` JSON，其中 `changed_paths` 保留完整差异，`reasons` 给出分类依据：

- `ENGINE_ONLY`：可由主机更新器校验 archive SHA 后并排安装、预检并原子切换；正在运行的剧集仍固定原版本。依赖未变化时 channel 明确写 `dependency_profiles_action=REUSE_CURRENT`，不生成 wheel bundle，也不得重装 venv。
- `TALENTHUB_PACKAGE_REQUIRED`：Agent brain、skill、onboarding、intake、installer、构建面或依赖发生变化。必须重新构建并发布 TalentHub Agent，已安装用户使用 `talenthub agent update ai-drama-factory`。发布包绑定 Linux x86_64/glibc 2.31+ 的 CPython 3.10/3.11 CPU 离线 wheel bundles；安装只允许 `--no-index --require-hashes`，无联网或未锁定回退。
- `RUNTIME_MIGRATION_REQUIRED`：持久运行时 schema 或 schema 定义发生变化。必须提供显式迁移、兼容范围、回滚验证并重新发布 TalentHub 包；不能进入 engine-only channel。

Release builder 可直接导入分类器，避免重复实现路径策略：

```python
from tools.storyclaw_upgrade_classifier import classify_release

impact = classify_release(previous_release_tag, release_tag, root=ROOT)
channel_manifest["update_class"] = impact["update_class"]
channel_manifest["dependencies_changed"] = impact["dependencies_changed"]
channel_manifest["runtime_migration"] = impact["runtime_migration"]
channel_manifest["upgrade_impact"] = impact
```

Builder 只有在 `update_class == "ENGINE_ONLY"`、`dependencies_changed == false` 且
`runtime_migration == "NONE"` 时才声明复用现有 venv。其余分类均应重新生成 TalentHub workspace 和上述 release-bound dependency assets；迁移分类还必须附迁移工具与验证证据。包级发布先进入私有 canary，只有独立 clean-install smoke 绑定 registry ZIP、依赖、bootstrap、preflight、零 provider POST 后才发布正式公开 ID，最后才允许稳定指针推进。
