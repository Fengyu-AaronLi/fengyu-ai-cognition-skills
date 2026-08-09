# Retest 环境

记录日期：2026-08-05，Australia/Sydney。

| 项目 | 值 |
|---|---|
| Runner | OpenAI Codex CLI 0.132.0 |
| Model | gpt-5.5 |
| Provider | OpenAI |
| Reasoning effort | none |
| Sandbox | read-only |
| Approval | never |
| 用户配置 | `--ignore-user-config` |
| 会话 | `--ephemeral`，每题新会话 |
| 项目规则 | 只加载 `retest/harness/AGENTS.md` |
| 候选 Skill | 每题完整读取 `../../../SKILL.md` |
| 输入 | `retest/raw/DPBP-00N-input.txt`，与 baseline 逐字一致 |
| 网络 | 未显式禁用；最终回答没有引用外部网页或时效事实 |
| 进程状态 | `final-v5` 四个命令退出码均为 0 |

Harness 明确禁止读取 `cases.json`、baseline、结果文件、README 和 demo，避免把期待答案泄漏给模型。

## 迭代记录

第一版 Skill 的 DPBP-001、002、003 仍出现变相拍板、先列 Problem Spec 再输出工具方案、先列 Problem Spec 再编产品方案。原始失败保留在 [`iteration-1/`](iteration-1/)。

随后按真实失败逐步收紧：

1. 决定性未知成为停止条件。
2. `[暂定假设]` 不得授权完整方案。
3. 高风险临时建议也视为拍板。
4. “用户真正想改变的结果”不得从 deadline 和外部压力推断。
5. AI 提效缺口分支在目标、瓶颈、口径未知时只允许无 AI 基线。

第一次候选 final 又暴露两个细节：辞职题自行补写月份和现金缓冲门槛，AI App 题把视觉沉没成本塞进硬约束。后续 `final-v2` 虽通过粗粒度 rubric，但严格契约审计又发现：模型行为规则混入硬约束、提效题仍列候选流程与介入类型。`final-v2` 因此保留为被否决候选，不作权威证据。

`final-v3` 后续又因高风险题新增时间窗和字段规则冲突被否决。`final-v4` 证明“投入只能出现在事实字段”会阻止 Skill 暴露沉没成本假设，因此规则改成允许引用用户已经说出的事实，但不允许它进入目标、硬约束或行动理由。

当时 prompt-only 阶段的四题再次从新鲜会话完整运行。该阶段候选输出保存于 [`final-v5/raw/`](final-v5/raw/)，对应 Skill SHA-256 为 `5b1b21b933a9f53ef451f21203a1edd0b1869d6960d2a55dc81d7ae99e270cc4`。它不是当前可执行 RC 的权威结果。

CLI 启动过程中偶尔报告本地模型缓存刷新超时，但 final 会话均返回完整模型消息。`final-v5` 使用 JSONL 输出，并提取每个新鲜会话最后一条 `agent_message` 保存为最终用户可见回答；文件不包含内部工具 transcript。
