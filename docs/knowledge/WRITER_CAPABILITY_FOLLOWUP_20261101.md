# 线主 2026-11-01 后续决定的落地记录

授权原话见各 config 的 `authorization_followup_2026_11_01`。

## 1. 提交前审核绑定（E14 起强制）
`configs/PROVIDER_REQUEST_REVIEW_BINDING_V1.json`
- `enabled_from_episode: "E14"`；E01–E13 密封不受影响。
- 付费提交前核对：审核记录、模型、提示词、参考素材、请求内容（payload）。
- 不一致 → `MISMATCH` / `MISSING` / `INVALID`，拒绝提交并要求重审；未审核通过不得付费提交。
- 关闭时记为 `UNENFORCED`，绝不记 `PASS` 或 `NOT_REQUIRED`。

## 2. 回执后绑定（E14 起强制，阻断范围有界）
`receipt_binding.enabled: true`，`blocking.bounded_refusal`：
- 只扣住出问题的那个任务：绑定缺失、错绑、冲突 → 该任务素材不得进入后续生产与成片。
- 其他独立任务照常并行，不因一个任务卡整集。
- 供应商可能已接单、只是回执丢失或本地绑定失败 → `PENDING_RECONCILIATION` / `RECEIPT_LOST` / `LOCAL_BINDING_FAILED`：允许继续查询、下载、补齐绑定，保留预算占用或未决扣费风险。
- 绝不为了补绑定再次付费提交。

## 3. 剧本侧：步骤强制，创作判断只报告
`configs/WRITER_CAPABILITY_V1.json`
- `missing_inputs` / `unanswered_script_review` / `open_rule8_items` = true（缺步骤则 S1 不能标完成、不能进付费准备）。
- `ledger_failures` = false，`creative_judgement_blocking` = false。
- 创作的“钩子不强 / 节奏慢 / 情绪不足”是修订意见，可被写手回应或驳回，绝不按分数或单次判断自动否决。
`configs/WRITER_RULE8_RESPONSE_V1.json`
- `blocking: true`；回答必须有镜号/场号依据，或写不适用的理由；不要求加打戏/反转/更响。
`configs/CROSS_SHOT_STATE_PERCEPTION_V1.json`
- `status: OBSERVE_ONLY_E14`，`blocking: false`；逐条记录证据、置信度、处理结果以测误报率。
- 既有验收（错人、剧情缺失等）继续有效，不因试运行取消；看不清不能记通过。

## 4. 接线
- `nalu_pipeline.stage_s1`：`writer_capability_record()` 的 `blocks_stage` 现在参与阶段状态；缺口以 `WRITER_CAPABILITY_STEP_OWED:<code>` 列进 blockers。LEGACY 集返回空，历史集不受影响。
- `writer_capability.blocking_policy()`：缺步骤 = 阻断；存在但不合格的内容（账本诊断）仍是修订意见。
- 测试：`tools/tests/test_writer_capability.py`、`test_writer_rule8_response.py` 已按新决定更新；整套 282 passed / 5 skipped。

## 5. E14 启用清单（给下一集）
```
enabled_from_episode = "E14"                      # PROVIDER_REQUEST_REVIEW_BINDING_V1
receipt_binding.enabled = true                    # 同样从 E14
WRITER_CAPABILITY_V1 blocking.* = {missing_inputs:true, unanswered_script_review:true, open_rule8_items:true}
WRITER_RULE8_RESPONSE_V1 blocking = true
CROSS_SHOT_STATE_PERCEPTION_V1 blocking = false   # E14 观察期
```
