# Quickstart

## 1. 运行要求

当前支持 Python 3.10 或更高版本，以及带 Unix `fcntl` 文件锁的 macOS 和 Linux。原生 Windows 不在当前支持范围。运行时只使用 Python 标准库。

以下治理命令仅在完整源码仓库可用；最小安装包不含测试、工作流和审计脚本，因此这些命令不可用。发行包中的 `SKILL_DIR` 是只读、不可写的程序目录。

```bash
python3 --version
python3 scripts/identity_label_case.py --help
```

把下文的 `SKILL_DIR` 替换为安装后的 `breaking-identity-labels` 绝对路径。每次调用都要在 Skill 之外创建一个外部、唯一的 `WORK_DIR`，所有输入、scaffold、analysis、case、状态和报告都写在这里。持久 case 建议放在本地文件系统；网络盘和同步盘尚未验证锁与原子替换语义。

```bash
SKILL_DIR="/absolute/path/to/agent-skills/breaking-identity-labels"
WORK_DIR="/absolute/path/to/identity-label-runs/case-unique-id"
mkdir -p "$WORK_DIR"
cd "$WORK_DIR"
python3 "$SKILL_DIR/scripts/identity_label_case.py" --help
```

## 2. 开发构建并安装最小包

在完整源码目录中构建一个不覆盖既有目标的开发候选包。这个入口直接读取活动源码，不能作为冻结发行包；正式发行导出只能在 strict gate 通过后使用 evolution controller 从 frozen completed run 的既有 ZIP 字节导出。

```bash
python3 scripts/build_package.py build \
  --out /absolute/path/to/package-candidate \
  --archive /absolute/path/to/breaking-identity-labels.zip

python3 scripts/build_package.py verify \
  --package /absolute/path/to/package-candidate
```

安装到 agent 的 skills 根目录：

```bash
python3 scripts/build_package.py install \
  --package /absolute/path/to/package-candidate \
  --skills-dir /absolute/path/to/agent-skills

python3 /absolute/path/to/agent-skills/breaking-identity-labels/scripts/build_package.py verify \
  --package /absolute/path/to/agent-skills/breaking-identity-labels
```

安装目标是 `<skills-dir>/breaking-identity-labels`。若目录已存在，安装器拒绝覆盖。`valid: true` 只表示 `PACKAGE-MANIFEST.json`、逐文件哈希、隐私扫描和运行时 smoke 通过，不等于提交、push、发布、公开可用或临床有效。

smoke 包含两条真实链：无状态 `scaffold → prepare-analysis → compile → validate → render`，以及把全部状态写在安装包外部临时目录中的 `init → plan → start → record → review → replay → next`。持久链必须得到 5 个事件、revision 4 和 `complete: true`，并证明执行前后的 package tree 没有变化。

无论验证目录包还是 zip 包，权威入口都是 `scripts/build_package.py verify --package <目标>`。

## 3. 无状态证据草稿

先用调用环境的文件写入能力把用户原话逐字保存为 `$WORK_DIR/user-input.txt`。不要用字符串拼接、`eval`、`sh -c`、未引用变量或 shell 引号容纳用户文字。下方相对路径之所以安全，是因为前一步已经 `cd "$WORK_DIR"`，而不是进入 `SKILL_DIR`。

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" scaffold \
  --text-file ./user-input.txt \
  --out ./scaffold.json
```

程序化调用且使用参数数组时可保留 `--text`；需要流式输入时可用 `--stdin`。面向 agent 的默认入口是 `--text-file`。`--out` 已存在、是符号链接或在并发创建时被其他进程抢先占用，命令都会拒绝覆盖。

输出保存逐字证据跨度、来源事件、风险标志和路由。它不诊断用户，也不会补写缺失行为。先读取 `route.mode`：

- `safety_support` 与 `support_escalation`：直接 `render` 现实支持输出，停止身份实验。
- `clinical_report_only`：保留用户报告，直接 `render`，不填实验。
- `preference_acknowledgement`：确认偏好，直接 `render`，不要求记录或改变。
- `needs_information`：直接 `render` 一条最小补充问题。
- `deconstruct`：才进入下方 analysis、compile 和可选实验。

非 `deconstruct` 示例：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" render ./scaffold.json
```

只有 `deconstruct` 才生成 analysis 工作单。不要复制通用模板，也不要手工重建 scaffold 已经提取的来源跨度。先从当前 scaffold 生成来源绑定的工作单，再由 agent 只用已有证据补全行为、反例、变量、未知和可证伪实验字段：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" prepare-analysis \
  --scaffold ./scaffold.json \
  --out ./analysis.json

# agent 完成 analysis.json 后再编译
python3 "$SKILL_DIR/scripts/identity_label_case.py" compile \
  --scaffold ./scaffold.json \
  --analysis ./analysis.json \
  --out ./case.json

python3 "$SKILL_DIR/scripts/identity_label_case.py" validate ./case.json
python3 "$SKILL_DIR/scripts/identity_label_case.py" render ./case.json
```

## 4. `prepare-analysis` 与 `compile` 的保证

两个命令的完整参数可直接查询：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" prepare-analysis --help
python3 "$SKILL_DIR/scripts/identity_label_case.py" compile --help
```

运行时保证：

1. `prepare-analysis` 逐字提取当前 scaffold 的 analysis，保留 runtime 已绑定的标签、判断和来源跨度，不自动伪造计划；每个 judgment 同时公开稳定 `target_id`，可直接填入实验的 `target_judgment_ids`，不需要反推源码规则。
2. `compile` 只合并 scaffold 与 agent 完成的 analysis，不重新解释用户原话。
3. 输出 `planned`、`revision: 1` 的无状态 case，可直接交给 `validate` 和 `render`。
4. 来源跨度、route、风险标志或策略门不通过时，拒绝写出看似成功的 case。
5. `--out` 已存在时不得静默覆盖。
可选 `--clock` 用于确定性重放。普通交互不应硬编码一个可能早于 scaffold `created_at` 的时间。

## 5. 显式创建持久案例

只有用户明确要求保存案例或运行现实实验时才创建目录：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" init \
  --text-file ./user-input.txt \
  --case-dir ./my-case

python3 "$SKILL_DIR/scripts/identity_label_case.py" plan \
  --case-dir ./my-case \
  --analysis ./analysis.json
```

目录包含：

- `case.json`：当前物化状态。
- `events.jsonl`：append-only 完整快照链。
- `events.head.json`：最近事件数量与哈希锚点。
- `.case.lock`：同一 case 的协作锁文件。

每次写后读取下一安全动作：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" next --case-dir ./my-case
```

`next` 是只读控制器，不会把用户文本插入 shell 命令。

## 6. 启动、记录与复核窄实验

先把用户确认愿意开始这一项具体实验的原话逐字保存为 `./user-confirmation.txt`。确认文件不是 agent 自行填写的布尔值，也不能由“用户想改变”之类的推断代替。运行时会拒绝不含明确开始实验意图的无关文本，并把原文、pre-start case、revision 和实验摘要哈希绑定到 start 事件。

这仍是一条本地一致性边界：确认文件原文字节与事件哈希绑定不等于认证真实用户身份或真人同意。运行时不能证明是谁写了文件，调用方必须如实保存用户原话，不得把 agent 生成的同意句伪装成用户确认。

再用文件写入能力创建 `./observation.json`：

```json
{
  "source_text": "今天在十五分钟准备后完成了三分钟团队更新。",
  "fact": "完成了三分钟团队更新",
  "context": "团队周会",
  "timeframe": "今天"
}
```

最后把仅针对窄命题的复核理由逐字保存为 `./rationale.txt`。不要把这三类自由文本插进 shell 参数。

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" start \
  --case-dir ./my-case \
  --confirmation-file ./user-confirmation.txt \
  --expected-revision 1

python3 "$SKILL_DIR/scripts/identity_label_case.py" record \
  --case-dir ./my-case \
  --kind experiment_result \
  --observation-file ./observation.json \
  --operation-id 'weekly-update-20260806-001' \
  --expected-revision 2

python3 "$SKILL_DIR/scripts/identity_label_case.py" review \
  --case-dir ./my-case \
  --classification weakens \
  --rationale-file ./rationale.txt \
  --expected-revision 3
```

复核分类只有 `supports`、`weakens`、`inconclusive` 和 `invalid`。任一分类都不能确认人格、依恋类型或诊断。

`operation-id` 是调用方为一次逻辑记录生成的稳定重试键。超时后重试同一载荷时必须复用原 ID；运行时返回原事件快照而不新增 revision。相同 ID 携带不同载荷会返回 `operation_id_conflict`，非法 ID 返回 `operation_id_invalid`。不同观察不得复用同一 ID。未提供该参数时保留旧命令兼容性，但调用方无法获得 exactly-once 重试保证。

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" replay --case-dir ./my-case
python3 "$SKILL_DIR/scripts/identity_label_case.py" status --case-dir ./my-case
python3 "$SKILL_DIR/scripts/identity_label_case.py" render \
  ./my-case/case.json \
  --out ./my-case/report.md
```

无持久状态的稳定偏好、临床报告、功能受损、信息补充或安全分支可以直接查询：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" next --case ./case.json
```

`safety_support` 和 `support_escalation` 不得返回身份实验；`preference_acknowledgement` 不得默认添加适应训练或观察任务；`clinical_report_only` 不得补写症状或能力结论。

## 7. 中断、恢复与回滚边界

写入使用独占目录锁、同目录 staging、事务 journal 和原子替换。进程在提交中途退出时：

1. 停止对同一 case 的并发写入。
2. 不手工删除 `.case-transaction.json`、`.case-txn-*`、`*.tmp`、`events.jsonl`、`events.head.json` 或 `case.json`。
3. 保存终端错误与 case 目录清单。
4. 先做只读诊断；只有 journal 结构及所有真实路径都在当前 case 内时才允许恢复。
5. 恢复后必须重新 `replay`，再决定是否重试原操作。

当前已实现的持久写命令会在独占锁内尝试恢复可信的待完成事务。遇到 malformed journal、路径越界、符号链接逃逸或未知文件时必须 fail closed，不能靠删除文件“修好”。

恢复能力的边界：

- 能做：回滚一笔已写 journal、且目标均属于当前 case 的中断事务；清理能证明属于运行时的 staging 残留。
- 不能做：撤销已成功提交的历史 revision；猜测未知临时文件归属；修复人为改写的语义内容；恢复未进入 journal 的外部文件；提供外部真实性证明。
- `events.jsonl`、`case.json` 和 `events.head.json` 若被有权限者协调重写为另一套自洽历史，本地哈希无法发现。需要更强真实性时必须另设只追加外部锚点或签名系统。

## 8. `doctor` 与 `recover`

先用只读 `doctor` 检查，再用 `recover` 回滚可信的待完成事务：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" doctor --case-dir ./my-case
python3 "$SKILL_DIR/scripts/identity_label_case.py" recover --case-dir ./my-case
```

`doctor` 必须只读且输出稳定的机器可读 JSON。顶层报告包含 `valid`、`case_dir`、`journal`、`replay`、`materialized` 和 `errors`；`journal` 单独报告 `present`、`valid`、`recovery_required` 和错误。它检查三层 case 状态，但不修改任何文件，也不把检查变成修复。Python 与平台兼容性仍由本页运行要求和实际解释器检查承担，不伪装成 case doctor 结论。

`recover` 必须取得预先存在的独占锁，只回滚当前 case 内通过路径和 journal 结构校验的待完成事务，随后 replay。没有待恢复事务时是有效 no-op，并返回 `recovered: false`。不可信 journal、越界路径、符号链接、缺失 `.case.lock` 或无法判断的状态应返回稳定非零错误，且不得删除目录外文件。`status`、`replay`、`next`、`doctor` 和 `recover` 都不得为缺锁 case 顺手创建锁；缺失 case 目录同样不得创建。

两个命令的参数面可以直接核对：

```bash
python3 "$SKILL_DIR/scripts/identity_label_case.py" doctor --help
python3 "$SKILL_DIR/scripts/identity_label_case.py" recover --help
```

## 9. 完整源码验收

```bash
make verify
```

该入口运行测试、绑定式离线评测、deterministic runtime demo、demo verifier、历史 analysis replay、独立的 fresh current-candidate sample、package gate 和结构有效性门，允许诚实的 pending 或 blocked 状态。`make workflow` 才执行当前收敛 DAG，但也不会自动 freeze、审计或发布。旧 runtime、评测器、数据集或 workflow 哈希的通过结果不能证明新代码。发现 blocker 时回到冻结红测、最小修复、全量复测和文件化审计循环。

完整的 `run → freeze → audit receipt 1.2 → blocker resolution → next iteration → strict check` 命令、冻结包导出和边界见 [evolution.md](evolution.md)。

进化 controller 的锁是协作式 advisory lock，受控子进程不是 OS sandbox，且控制器不承诺跨所有事件、收据和状态文件的崩溃原子性。需要外部真实性时，应另设签名或只追加外部锚点。
