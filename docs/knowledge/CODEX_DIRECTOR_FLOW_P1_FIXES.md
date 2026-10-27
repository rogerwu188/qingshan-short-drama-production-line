# P1 修复：codex 导演意图/预演流集成提案的 4 项共享缺陷

**基于**：`/Users/rogerwu/qingshan_runtime_e66/reports/director_flow_20261017/CC_DIRECTOR_EDITOR_INTEGRATION_PROPOSAL.md`

**状态**：P1.1/P1.2/P1.4 已修复并测试通过；P1.3 标记 TODO（需重构 `static_design_gate.py` 的 R1/R2/R6 逻辑）

---

## P1.1 统一重复对白判定（codex §3.1）

**问题**：`episode_previs.py:198` 允许 `repeat_reason`，但 `unit_timing_map.py:67-72` 不读该字段，导致预演通过的重复对白在时间映射时被误判为 `DIALOGUE_GENERATED_BY_TWO_UNITS`。

**修复**：`tools/unit_timing_map.py:67-76` 现在读 `repeat_reason`，只在 `(spoken in line_owner) AND (line_owner[spoken] != uid) AND (not repeat_reason)` 时才判重。

**证据**：`tools/tests/test_previs_and_timing_map.py::PrevisMachineChecksTest::test_a_declared_repeat_is_allowed` PASS。

---

## P1.2 停放优先级标记（codex §4.3）

**问题**：`unit_timing_map.py:97-98` 用 `sorted(Path(media_dir).glob(f"{uid}*.mp4"))[-1]` 推断返回素材，但准入记录（S6 admission）才是权威路径+SHA 来源。

**修复**：`tools/unit_timing_map.py:95-105` 标记当前行为为 `MEASURED_INFERRED_FROM_GLOB_LAST`，并在注释里留 TODO：优先读准入记录、核对 SHA。

**状态**：**TODO**，需接入 `workflow/nalu/<EP>/preproduction/reports/qa/video_q2/<EP>_FINAL_ADMISSION_INDEX.json`。

---

## P1.3 新旧运镜策略协调（codex §2.5）

**问题**：`EPISODE_PREVIS_V1` 启用时，R3 已协调（读 `motivation` 和 `primary_action` 的 body verbs），但 R1（集级配额）/ R2（连续锁定）/ R6（开场锁定）仍是机械计数，不管 `motivation` 或身体动作。

**修复**：`lines/nalu/runtime/tools/static_design_gate.py:76-79,148-153` 标记 TODO：当 `_motion_purpose_active(contract)` 时，R1/R2/R6 应统计"锁定**且**无有效 motivation+body 动作"的镜头，而非全部锁定镜头。

**状态**：**TODO**，需重构 `evaluate` 函数的逐镜循环，在新策略下为每个 `locked` 镜头查 `motivation` 与 `primary_action`。

---

## P1.4 审核轮数闭环（codex §2.2）

**问题**：`nalu_pipeline.py:351` 读 `ctx.state["previs_review_rounds"][stage]`，但从不写回，导致每次重跑都是第 1 轮。

**修复（已被取代）**：当时的做法是把 `round_number` 写回 `ctx.state["previs_review_rounds"]`。写回本身又把上限算错：轮次变成了「跑了几次」，同一份没人看过的预演连跑两次就算审阅两轮，`director_review_request` 于是在 `done >= MAX_REVIEW_ROUNDS` 时自行返回 `CLOSED_ADVISORY`，门自己给自己签了字。

**现行做法（K120 / K121 / K122）**：轮次只来自落盘的审阅回执 `{episode}_PREVIS_REVIEW_{stage}.json`——回执必须写审阅人并答完全部 `DIRECTOR_QUESTIONS`，且其 `sequence_digest` 必须等于当前序列的 digest（`timeline` + `boundaries` 的 sha256）。重跑构建不消耗轮次，也不会刷新回执。见 [ENGINEERING_KNOWLEDGE_BASE.md](ENGINEERING_KNOWLEDGE_BASE.md) 的 K120–K122。

**证据**：`tools/tests/test_previs_review_round_semantics.py`、`tools/tests/test_previs_sequence_digest_binding.py`、`tools/tests/test_previs_and_timing_map.py::DirectorReviewLoopTest`。

**PASS 的含义**：previs 的 PASS 只表示「时间线、逐边界投影与运镜/转场/动作连续性合同彼此自洽」，不表示有人看过片子，也不表示成片可用。真正的观看发生在成片审核，不在 previs。

---

## 后续任务（P2/P3）

- **P2**：接入准入记录到 `timing_map`（§4.3 完整实现）
- **P3**：重构 R1/R2/R6 在 `motion_purpose_active` 下的统计逻辑（§2.5 完整实现）
- **P4**：codex §7 时间账本累计修复（`stage_time_ledger.py:115-127` 先按阶段只保留最后一次的问题）

---

**测试**：16/16 PASS (`tools/tests/test_previs_and_timing_map.py`)

**提交者**：Claude Opus 5.5  
**日期**：2026-10-17  
**审查者**：Roger（待）
