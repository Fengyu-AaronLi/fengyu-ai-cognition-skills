# V3.1 发行契约差异审计

> **已解决的 RED 记录**：本文件保存修复前的差异审计。表格中的失败项随后已实现并由 `red-round-release-contract-v31.txt` 对应测试转为 11/11 PASS。当前结论见 [`../results.md`](../results.md)，不要把下文 pre-fix 状态当成当前发行状态。

核对日期：2026-08-06

范围：`SKILL.md`、`README.md`、`references/runtime-contract.md`、`references/workflow-loop.md`、全部 schemas、全部 templates、`scripts/install.py`、`agents/openai.yaml`。本轮只读运行时与文档，仅新增独立 RED 测试和评估记录。

## 结论

当前运行时已经实现本轮目标能力，但公开契约仍是旧版本。实现侧 16 个专项测试全部通过，发行契约专项测试为 1 通过、9 失败。当前不能把这棵目录称为一致的 V3.1 安装包，发行状态应继续保持 NO-GO。

已通过的实现侧专项测试：

| 测试组 | 结果 | 覆盖 |
|---|---:|---|
| `test_next_protocol_red_v3.py` | 6/6 | candidates file、summary file、candidate ID、safe next |
| `test_countercheck_red_v3.py` | 7/7 | `claim_countercheck`、basis hash、失效与恢复 |
| `test_redteam_deadline_transaction_v3.py` | 3/3 | 总时限、字节上限、来源事务重试 |

发行契约 RED 原始输出见 `evals/v3/red-round-release-contract-v31.txt`。

## P0 差异

| 路径 | stale 位置 | 当前事实 | 发行契约应改成 |
|---|---|---|---|
| `SKILL.md` | 32、34、38、61、73、79、108 至 112 行 | 仍指示把候选、主张和摘要直接放入命令行；判断后直接汇总，完全跳过 countercheck | 默认走 `start --candidates-file`、`claim --file`、`exclude-candidate --candidate-id`、`assess --file`、`countercheck --file`、`summarize --file`；明确按 `next.cli_subcommand` 与 `required_inputs` 驱动 |
| `README.md` | 48 至 58 行 | 状态图缺 `claim_countercheck` | 顺序必须为 `claim_assessment → claim_countercheck → audit_summary` |
| `README.md` | 89 至 127 行 | 最短示例用原文命令行参数，`decide` 后直接 `finish`；按当前运行时会停在 countercheck，示例无法完成 | 改为文件驱动的可复制闭环，实际创建 candidates、claim、assessment、countercheck、summary JSON，并在每一步重新运行 `next` |
| `references/workflow-loop.md` | 13 至 18、59 至 68、83 至 93 行 | 有抽象“反证回路”，没有 `claim_countercheck` 状态、命令、输入契约或 basis hash 失效条件 | 把反证回路升级为状态机强制阶段，写明每条已判断主张必须生成当前 countercheck 后才能汇总 |
| `schemas/workflow-next.schema.json` | 16、21 至 29、74 至 178 行 | 仍描述旧 next：缺 `claim_countercheck`；旧批量 `candidates`；没有 `cli_subcommand`、`required_inputs`、`candidate_id`、`missing_evidence_purposes` | 按运行时 `build_next_payload` 的每个阶段重写 oneOf，并让每个可执行 step 的命令字段固定为静态 const |
| `schemas/claim-ledger.schema.json` | 162 至 185 行 | `candidate_exclusion.additionalProperties=false`，却不允许运行时实际写入的 `candidate_id` | `candidate_id` 加入 required 与 properties，格式为 `^U[0-9]{3,}$` |
| `schemas/claim-ledger.schema.json` | 353 至 453 行 | `claim.additionalProperties=false`，却不允许运行时实际写入的 `countercheck` | 加入 countercheck 定义及六个运行时字段；已完成审计中的 countercheck 必须存在且与允许结果枚举一致 |

上述两个 schema 不是“少写了说明”，而是会直接拒绝当前运行时生成的合法 JSON。

## P1 差异

| 路径 | stale 位置 | 差异 |
|---|---|---|
| `scripts/claim_audit.py` | 38 至 39 行 | 能力集合已经是下一版，但 runtime 与 policy 仍自报 `3.0.0`。若本轮名称确定为 V3.1，应统一为 `3.1.0`，并同步 doctor、回执、gate 和测试 fixture |
| `references/runtime-contract.md` | 第 3 行 | 仍标记适用版本 3.0.0 |
| `references/runtime-contract.md` | 15 至 29 行 | 工作区树缺 `.runtime-init.json`、`.runtime-key`、`runtime-attestations.json`、`source-transactions/` |
| `references/runtime-contract.md` | 35 至 58、89 至 103 行 | 命令表和阶段表缺 countercheck；safe next 只说“不拼 shell”，没有列出静态 `cli_subcommand`、`required_inputs`、ID 寻址和 `missing_evidence_purposes` |
| `references/runtime-contract.md` | 107、151 至 155 行 | 只写 `--candidate`、旧汇总顺序和旧底层接口，没写 candidates file、candidate ID、summary file 与 countercheck file 的精确 JSON 形状 |
| `references/runtime-contract.md` | 115 行 | 声称重复 auto-gap 可以记录多个 span；当前运行时会拒绝重复文本并要求更大唯一上下文 |
| `references/runtime-contract.md` | 161 至 177 行 | 没有描述事务状态 `prepared → receipt_saved → attested → committed`、相同 source ID 精确重试条件、事务日志不属于事实证据或防篡改链 |
| `references/runtime-contract.md` | 165 行 | 只写默认 20 秒，没有说明 `timeout` 是覆盖重定向和正文读取的单个总时限，也没有写硬上限 60 秒和 5 MiB 不可上调 |
| `README.md` | 145 至 160、214 至 222 行 | 失败恢复和信任边界没有说明事务日志、同 source ID 精确恢复条件、HMAC 只是同机运行时来源证明而非外部签名 |

## 模板、Schema 与安装白名单

当前 `scripts/install.py:23-42` 安装 18 个文件，包含现有 5 个 schema、3 个输入模板与运行时。它足以启动程序，但不足以让安装后的 Agent 无猜测地执行新文件驱动协议。

建议新增并加入 allowlist：

| 类型 | 路径 | 原因 |
|---|---|---|
| caller input | `schemas/candidates.schema.json`、`templates/candidates.json` | `start --candidates-file` 的精确对象只有 `candidates` 数组 |
| caller input | `schemas/claim.schema.json` | `claim --file` 已有模板，没有独立输入 schema |
| caller input | `schemas/evidence.schema.json` | `evidence --file` 已有模板，没有独立输入 schema |
| caller input | `schemas/countercheck.schema.json`、`templates/countercheck.json` | 新命令需要五个 caller 字段，`checked_at` 与 `basis_hash` 由运行时生成，不能出现在输入模板 |
| caller input | `schemas/summary.schema.json`、`templates/summary.json` | `summarize --file` 只允许 `unknowns` 与 `next_action` |
| runtime-owned | `schemas/source-transaction.schema.json` | 让事务恢复记录有机器可读契约；不应创建 caller 模板，避免诱导手写 journal |

因此当前 allowlist 缺 9 个协议工件。若决定复用 `claim-ledger.schema.json#/$defs/claim` 和 `#/$defs/evidence` 而不建独立文件，必须在 runtime contract 与模板中写出可验证的 JSON Pointer，并把对应验证加入安装测试；不能保持现在的隐含状态。

## 已通过项

| 路径 | 结论 |
|---|---|
| `agents/openai.yaml` | PASS。名称、默认提示、隐式触发均与 Skill 一致，没有版本或已发行的虚假声明 |
| `schemas/assessment.schema.json`、`templates/assessment.json` | 当前 assessment 输入字段与运行时一致；countercheck 应保持独立输入，不应塞入 assessment 模板 |
| `schemas/source-receipt.schema.json`、`schemas/gate-report.schema.json` | 本轮新增的控制流没有要求修改其核心 caller 字段；仍应在全量 schema 验证中复测 |
| `templates/claim.json`、`templates/evidence.json` | 文件仍可作为输入起点，但需要独立 schema 或明确的 ledger `$defs` 校验入口 |

## 建议验收测试

1. 版本一致性：runtime、policy、doctor、runtime contract、ledger schema、workflow schema 必须属于同一发行版本。
2. 全阶段 next schema：为 `claim_extraction`、`claim_assessment`、`claim_countercheck`、`audit_summary`、`gate_repair`、`ready_to_finish`、`complete`、`not_triggered` 各生成真实 payload，并逐个通过 schema。
3. 安装后闭环：只使用安装目录内的模板，从 candidates file 开始，依次执行 claim、assessment、countercheck、summary，最后 finish 与 replay；不得回读源码仓库模板。
4. 安全传参：候选、主张、unknown、falsifier、stop reason 和 excerpt 含引号、换行、命令替换符与分号时，任何 `cli_subcommand` 或 `required_inputs` 都不得含原文。
5. Countercheck 新鲜性：claim、evidence 或 assessment 任一变化都必须使旧 basis hash 失效并退回 `claim_countercheck`。
6. Journal 恢复：在 receipt saved、attested、ledger committed 三个边界分别注入崩溃；精确重试能收敛，不匹配重试 fail closed，旧 receipt 和 journal 不被覆盖。
7. 总时限：慢滴流、连续重定向和超大正文都不能把单个 fetch 延长到用户 timeout 之外，也不能用 CLI 把 60 秒或 5 MiB 上限调高。
8. 安装白名单：安装树必须精确等于 allowlist，所有 caller 输入模板都有 schema，runtime-owned journal 只有 schema 没有模板。
9. 文档可执行示例：把 README 的最短示例作为 subprocess 测试真实运行，必须出现 `claim_countercheck`，并最终达到 `complete=true`。
10. Agent 元数据：继续检查名称、默认提示和隐式触发，同时禁止出现“已发行”“绝对正确”或“消灭幻觉”。
