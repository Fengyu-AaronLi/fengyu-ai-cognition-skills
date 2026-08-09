# 历史评测证据索引

本目录保留旧证据，但旧证据不自动适用于当前 3.1.0 候选。任何运行时、Skill、案例或协议发生变化后，旧行为输出只能说明当时版本的表现。

## 仍可作为历史材料读取

- `baseline/`、`baseline-report.md`：无 Skill 的初始 RED 基线，仅作 C01 至 C04 的历史对照，不是 3.1.0 行为结果
- `retest/`：早期 16 例复测原始回答与高层轨迹，已失效，不得复用分数或 PASS
- `results-historical-pre-220.md`：早期复测的原始报告全文，已失效，不得作为 3.1.0 发行证据
- `v2/behavior/`：2.2.0 冻结前的开发期行为与运行目录，只能说明当时版本
- `v2/red*.txt`：TDD RED 阶段的失败证据，保留为开发历史，不是 final 行为结果
- `v2/live-*`：旧运行时的联网烟雾测试，已失效，必须在冻结版本重跑
- `install-verification.md`、`v2/install-*`：旧安装与发现尝试，已失效，必须用真实复制安装重跑
- `install-verification-220.md`：2.2.0 的白名单安装证据，只能说明旧运行时
- `zero-threshold/`：旧零门槛体验，仅作历史演示证据，不是 3.1.0 行为结果
- `v3/live-source-300.md`：3.0.0 的真实来源复验，没有 3.1.0 反证状态，不得作为当前闭环证据
- `v3/release-contract-v31-audit.md`：3.1.0 修复前的 RED 差异审计，表格中的失败项已经被后续实现取代

## 当前 3.1.0 入口

当前工程、安装、真实来源和行为状态统一汇总到 `results.md`。干净安装证据见 `install-verification-310.md`，真实来源复验见 `v3/live-source-310.md`。C01 至 C16 的新鲜行为与自动发现仍为 `NOT RUN`，不得从旧输出迁移分数。不得覆盖旧 raw、trace、run 或 manifest。
