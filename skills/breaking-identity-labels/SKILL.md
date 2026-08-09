---
name: breaking-identity-labels
description: Use when a user presents a personality, clinical, self-help, social-media, or AI-generated label as a fixed explanation of behavior, ability, responsibility, or future, or asks the model to infer such a label from limited conversation.
---

# 身份标签拆解

## 作用

这是一个由 CLI 支撑的证据审计与现实实验协议，不是回答模板。模型判断语义，运行时约束来源跨度、风险路由、状态迁移、策略退出和报告生成。

标签只能作为线索。不得把它扩写成人格、病因、责任、能力或未来判决。验证通过只表示结构和机械边界成立，不表示心理解释、诊断或因果已被证明。

运行环境要求 Python 3.10 或更高版本，以及提供 Unix `fcntl` 的 macOS 或 Linux。原生 Windows 不在当前支持范围。安装与运维见 [docs/quickstart.md](docs/quickstart.md)。

发行包中的 `SKILL_DIR` 是只读、不可写的程序目录。每次运行必须在 Skill 之外建立一个外部、唯一的 `WORK_DIR`；用户原话、scaffold、analysis、case、状态目录和报告只能写入 `WORK_DIR`。以下治理命令仅在完整源码仓库可用；最小安装包不含测试、工作流和审计脚本，因此这些命令不可用。

## 入口

把 `SKILL_DIR` 解析为本文件所在目录，并把 `WORK_DIR` 解析为 Skill 之外本次运行专用的绝对目录。先用调用环境的文件写入能力把用户原话逐字保存为 `$WORK_DIR/user-input.txt`。不得把用户文字拼进 shell 命令、引号或重定向表达式。再建立无状态证据草稿：

运行时命令族是 `identity_label_case.py scaffold`、`identity_label_case.py prepare-analysis`、`identity_label_case.py compile`、`identity_label_case.py validate`、`identity_label_case.py render`、`identity_label_case.py init`、`identity_label_case.py plan`、`identity_label_case.py start`、`identity_label_case.py record`、`identity_label_case.py review`、`identity_label_case.py replay`、`identity_label_case.py status`、`identity_label_case.py doctor`、`identity_label_case.py recover` 和 `identity_label_case.py next`；完整参数只以当前 `--help` 为准。

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" scaffold --text-file "$WORK_DIR/user-input.txt" --out "$WORK_DIR/scaffold.json"
```

`--text-file` 和 `--stdin` 是不可信原话的安全入口；`--text` 只保留给已经通过参数数组调用、确认没有 shell 拼接的程序。`--out` 原子创建新文件并拒绝覆盖。脚手架输出版本化 JSON、风险标志、路由、来源和逐字跨度。启发式路由不是心理判断；误判必须保存为回归案例并修复分类器，不能在单个 case 中静默改道。

## 先路由，再决定是否拆解

| `route.mode` | 处理 |
|---|---|
| `safety_support` | 停止实验，优先现实安全支持 |
| `support_escalation` | 停止身份实验，建议现实专业评估与支持 |
| `clinical_report_only` | 保留用户报告，不扩写症状、能力结论或实验 |
| `preference_acknowledgement` | 确认偏好，不建立纠正实验或观察任务 |
| `needs_information` | 只回答定义，或问一条会改变路由的最小问题 |
| `deconstruct` | 建立十项分析，并在用户需要时进入验证循环 |

非 `deconstruct` 分支直接渲染 scaffold，不填十项模板：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" render "$WORK_DIR/scaffold.json"
```

安全和现实支持分支必须先输出支持信息，不得在后面追加人格分析或现实实验。偏好与纯临床报告分支必须在确认边界后结束。`needs_information` 只能问一条会改变路由的问题。

## 只对 `deconstruct` 做单次分析

1. 从当前 scaffold 生成来源绑定的分析工作单。不得手抄通用模板：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" prepare-analysis --scaffold "$WORK_DIR/scaffold.json" --out "$WORK_DIR/analysis.json"
```

每个 runtime 提取的 `judgment` 都带可直接复制的稳定 `target_id`。现实实验只能在 `target_judgment_ids` 中引用这些公开 ID，不得根据源码暗猜内部命名。

2. 标签、判决、行为和反例只能引用 `evidence` 的逐字跨度。缺失内容写入 `unknowns`。
3. 可变变量只能标记为 `hypothesis`。不得把创伤、潜意识、依恋恐惧或他人动机写成事实。
4. 实验只能测试一个窄行为命题，且必须有变量、期限、固定条件、指标、支持结果、削弱结果和可逆说明。
5. 用同一脚手架和 analysis 编译 planned case，再验证并渲染：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" compile --scaffold "$WORK_DIR/scaffold.json" --analysis "$WORK_DIR/analysis.json" --out "$WORK_DIR/case.json"
python3 "$SKILL_DIR/scripts/identity_label_case.py" validate "$WORK_DIR/case.json"
python3 "$SKILL_DIR/scripts/identity_label_case.py" render "$WORK_DIR/case.json"
```

`compile` 保留 scaffold 拥有的证据、路由和风险字段，执行与 `plan` 相同的语义和策略校验，拒绝覆盖既有输出。最终回答以有效结构化记录为事实底稿，不得添加记录外的新心理解释。

## 只对 `deconstruct` 做持续观察

只有用户明确要求保存案例或运行现实实验时才创建目录。默认不建立全局身份档案。

观察记录必须先以精确四字段 JSON 保存为 `$WORK_DIR/observation.json`，复核理由必须先逐字保存为 `$WORK_DIR/rationale.txt`。这些文件也必须由文件写入能力创建，不能把自由文本插进 shell argv。

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" init --text-file "$WORK_DIR/user-input.txt" --case-dir "$WORK_DIR/case-state"
python3 "$SKILL_DIR/scripts/identity_label_case.py" plan --case-dir "$WORK_DIR/case-state" --analysis "$WORK_DIR/analysis.json"
python3 "$SKILL_DIR/scripts/identity_label_case.py" start --case-dir "$WORK_DIR/case-state" --confirmation-file "$WORK_DIR/user-confirmation.txt"
python3 "$SKILL_DIR/scripts/identity_label_case.py" record --case-dir "$WORK_DIR/case-state" --kind observation --observation-file "$WORK_DIR/observation.json" --operation-id '<调用方生成的稳定重试键>'
python3 "$SKILL_DIR/scripts/identity_label_case.py" review --case-dir "$WORK_DIR/case-state" --classification '<supports|weakens|inconclusive|invalid>' --rationale-file "$WORK_DIR/rationale.txt"
python3 "$SKILL_DIR/scripts/identity_label_case.py" replay --case-dir "$WORK_DIR/case-state"
```

状态只能沿 `drafted → planned → observing → reviewed` 前进。写操作必须回放旧链、检查期望 revision，并只修改该事件允许的字段。`record` 的调用方应为一次逻辑观察复用同一个 `operation-id`：相同 ID 与相同载荷只提交一次，相同 ID 与不同载荷拒绝写入。每次写后运行只读控制器：

`start` 前必须把用户对当前具体实验的明确同意原话逐字写入 confirmation 文件。运行时会保守检查同意语义，并把原文字节、pre-start case、revision 与实验摘要写入事件链。确认文件原文字节与事件哈希绑定不等于认证真实用户身份或真人同意；调用方仍须如实保存用户原话，不能代填确认。

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" next --case-dir '<case-dir>'
```

只有 `complete=true` 才能正常结束。`integrity_failure` 必须停止，安全与严重功能受损分支不得继续生成实验。异常退出后先只读诊断，再显式恢复：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" doctor --case-dir '<case-dir>'
python3 "$SKILL_DIR/scripts/identity_label_case.py" recover --case-dir '<case-dir>'
```

`recover` 只回滚当前 case 内通过路径校验的待完成事务，并在结束后 replay；不是任意清理或历史撤销命令。完整回滚边界见 [docs/quickstart.md](docs/quickstart.md)。

## `deconstruct` 的十项输出契约

1. 原始标签
2. 标签来源及证据状态
3. 标签下面的具体行为
4. 情境、频率和时间
5. 已知反例
6. 可能影响行为的可变变量
7. 目前不能判断的部分与一条最小问题
8. 小规模、可逆、有期限的现实实验
9. 支持或削弱窄行为判断的结果
10. 保留给用户或专业人员的判断

信息不足时保留空值或“未提供”。这十项不得套用到偏好、纯临床报告、现实支持、信息补充或安全分支。单次结果不能验证人格、依恋类型或撤销临床诊断。

## 其他路由的最小输出

- `preference_acknowledgement`：复述用户明确表达的偏好，说明目前没有必须改变的证据，然后结束。
- `clinical_report_only`：保留“用户报告的正式诊断或施测”，说明未核验和不能外推的部分，然后结束。
- `support_escalation`：承认已报告的功能受损，建议现实专业评估或支持，不给身份实验。
- `safety_support`：立即给现实安全支持，只保留用户明确报告的主体、对象、手段和暴露状态，完全跳过十项。
- `needs_information`：只问一条足以改变路由的最小问题，不猜人格。

## 不可越过的边界

- 不诊断、确认或撤销诊断，不把用户报告冒充独立核验。
- 不否认气质和稳定偏好，不把所有问题归因于选择或意志力。
- 不用新的正面身份替换旧标签。
- 不把停药、改药、治疗调整或高成本人生决定写成实验。
- 不提出不可验证的病因或他人动机，不把行为道德化。
- 建议消息不得替用户填入未报告的感受、动机或保证；在用户确认属实前使用占位符或条件句。
- 严重功能受损或现实安全问题优先交给现实支持和合格专业人员。
- 不让来源、说话者、对象、断言极性或材料引用在保存时被改写。

策略错误码见 [references/policy-rules.md](references/policy-rules.md)，证据类型见 [references/evidence-classes.md](references/evidence-classes.md)，安全文字边界见 [references/safety-boundaries.md](references/safety-boundaries.md)。

## 失败与验收

- CLI 非零退出：保留稳定错误码，修复结构化记录后重跑，不得关闭规则换取通过。
- `replay` 失败或事务日志不可信：停止写入，不手工删除未知文件；按 quickstart 的恢复流程处理。
- 环境无法执行脚本：明确说明降级。`zero-threshold-prompt.md` 只是 **portable fallback**，没有来源校验、状态、回放或策略退出码，不能声称等价。
- 完整源码仓库使用 `make verify` 重跑结构有效性门；使用 `make workflow` 执行当前 manifest 绑定的收敛 DAG。工作流分别验证 historical analysis replay 与 fresh current-candidate sample，不能用前者冒充后者。两者都不会冻结、审计或发布。候选冻结、审计收据和 blocker 关闭协议见 [docs/evolution.md](docs/evolution.md)。
- 最小安装包不含 `tests/`、`evals/`、`examples/`、`launch/` 或 `workflows/`。安装后必须核对 manifest：

```bash
python3 "$SKILL_DIR/scripts/build_package.py" verify --package "$SKILL_DIR"
```

只有输出 `valid: true` 且 `PACKAGE-MANIFEST.json` 的逐文件哈希匹配，才能说明安装完整。这不证明临床有效、已提交、已 push、已发布或已公开。完整验收见 [docs/acceptance.md](docs/acceptance.md)，权威顺序见 [SOURCE_OF_TRUTH.md](SOURCE_OF_TRUTH.md)。

直接运行 `build_package.py build` 只生成活动源码开发包。正式发行包只能由 strict gate 对应的 frozen completed run 通过 `run_evolution.py export-package` 导出，且导出不会从活动源码重新构建。
