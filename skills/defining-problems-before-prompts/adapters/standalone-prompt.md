# Standalone compatibility note

这是给不支持 Agent Skill 运行时的平台保留的兼容说明，**不是 Skill 本体**。

旧粘贴式体验保存在 [`standalone-prompt-v0.1.md`](standalone-prompt-v0.1.md)，只用于复现 `0.1` prompt-only 行为。它没有：

- 离线 gate 和固定 route priority。
- request hash、exact evidence span 或 gate receipt binding。
- 三份 JSON Schema 和字段级 validator。
- progressive references 与领域 coverage。
- 确定性 renderer、stable error code 或 executable stop boundary。
- 原子 state，以及用于 `resume` 的 file lock、revision compare-and-swap 和幂等恢复。

仅复制该文本不能获得当前 runtime 的运行能力，也不能把历史 transcript 4/4 当作当前版本证明。

要使用当前候选，需安装完整目录并实际执行 [`../scripts/dpbp`](../scripts/dpbp)。当前状态仍是本地 RC，fresh host gate 待完成，未发布。
