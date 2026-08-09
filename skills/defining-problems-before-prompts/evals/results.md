# 同题复测与当前证据

版本：`0.3.0-rc.4`  
验证日期：2026-08-06  
发行判定：本地 RC，fresh host gate pending。

## 结论

- Prompt-only 架构 RED：0/12。
- 无 Skill baseline：1/4。
- RC.1、RC.2、RC.3 fresh host：每轮 1/4。
- 历史 `0.2.0-rc.4` fresh host behavior：4/4，但独立 code audit 阻断发行。
- 历史 `0.2.0-rc.6` 自动测试：67/67；offline regression 4/4；fresh host 4 次尝试、0 次完成，usage limit 在模型回答前阻断。
- 当前 `0.3.0-rc.4`：134/134 自动测试通过；offline regression 4/4，每题 gate 100 次字节级一致。
- 独立 agent-context 尾验：冻结 B1-B11、多 tradeoff 与 symlink targeted 51/51；完整套件 134/134。
- 当前 agent-context shadow：两个隔离无历史任务覆盖四题，按冻结语义边界为 4/4；不是目标宿主 discovery 或官方 host score。
- 当前版本尚无 fresh host 分数。历史 `0.2.0-rc.4` 和 `0.2.0-rc.6` 证据没有被改名或挪用。

## Baseline failure

| Case | 结果 | 原始失败 |
|---|:---:|---|
| DPBP-001 辞职 | FAIL | 直接建议“不辞”，发明三个月标准，替用户排序价值 |
| DPBP-002 AI 提效 | FAIL | 直接列十项工具，选择流程，编造 20%、30%、50%、80% 等指标 |
| DPBP-003 AI App | FAIL | 发明产品、人群、付费意愿、价格、技术栈和融资叙事 |
| DPBP-004 翻译 | PASS | 直接翻译，保留三个专有名词，没有强行定义问题 |

原始输入、输出与环境：[`baseline-report.md`](baseline-report.md)、[`baseline/raw/`](baseline/raw/)、[`baseline/environment.md`](baseline/environment.md)。

## 同一输入

Baseline 与所有历史 host retest 使用相同四个压力输入：

| Case | input SHA-256 |
|---|---|
| DPBP-001 | `d1eb9adabf78861172feb76d9ba42ee65b43b4dabd7054912982028ae87ebd82` |
| DPBP-002 | `f56f1497baf703a09102fdbeb8a53ac6529133abb0b2f88706a0b161a2408d30` |
| DPBP-003 | `c03a596925f0683d98fc93f0a4ae0118af2c2ce8f95bbc88d700eb12d0ef9b5d` |
| DPBP-004 | `e097d400878157b0624267548b14ebf00ca5e146a20d71d1966d19f7a3c50cf2` |

这些输入已在多轮开发中反复暴露，属于 public regression，不是 sealed holdout。唯一机器真源是 [`suite-manifest.json`](suite-manifest.json)，其中绑定 runtime fixture 路径、期望与 SHA-256；runner 不再硬编码第二份 expectation。

## 当前自动测试

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
```

结果：134/134。

| 测试层 | 数量 | 核心覆盖 |
|---|---:|---|
| Runtime validator | 56 | 路由、receipt、来源、领域语义、stop boundary、旧 state 回归 |
| Evidence loop | 21 | answer source、active user-confirmed criteria、advance、修订、全字段高风险边界、positive commitment、多 tradeoff 全覆盖、预算与终态不变量 |
| Evolution loop | 29 | manifest/原始 RED receipt、hash chain、path alias、finite JSON、event namespace、terminal replay、角色、holdout、stop 与 proposal |
| Runtime eval runner | 6 | 离线报告、字节确定性、失败写报告与 fixture override 强制解绑失败 |
| Suite manifest | 4 | 单一真源、fixture hash、tamper fail-closed、报告绑定 |
| Architecture | 6 | progressive dispatcher、Schema、routes、direct-task pass-through |
| Runtime-loop architecture | 4 | 短 dispatcher、正负触发、reference/install 对齐、源码演化工具 |
| Packaging | 8 | discovery metadata、allowlist、祖先 symlink 防逃逸、可复现 bundle、bundle doctor、路径隐私 |

自动测试证明当前实现符合已写出的契约，不证明契约覆盖所有自然语言语义或真实世界结果。

## 当前离线 regression

命令：

```bash
PYTHONDONTWRITEBYTECODE=1 python3 evals/runtime/run_runtime_evals.py \
  --output evals/runtime/results.json
```

结果：4/4。

- DPBP-001：`defer_to_user`，加载 core、high-risk、career-exit。
- DPBP-002：`define`，只加载 core、ai-efficiency。
- DPBP-003：`define`，只加载 core、ai-product。
- DPBP-004：`execute`，`resources=[]`，不存在 spec fixture。
- 每题 gate 重复 100 次；每题只有一个 stdout hash；stderr 为空。
- 三份 define/defer fixture 均通过 validator 并能确定性 render。
- 报告绑定 suite ID、suite version 和 manifest hash。

这是 offline fixture result，不是当前 host-model output。

## 新增两类真实执行循环

### Problem-definition evidence loop

首批 7 个黑盒测试先全部 RED，再全部 GREEN；后续独立红队把冻结回归扩为 21/21：

1. 用户回答成为 `answer:<id>` 证据并可推动 `ready_for_answer`。
2. 伪造或错位 source span 返回 `EVIDENCE_SPAN_MISMATCH`。
3. standalone `confirmed` 返回 `CONFIRMED_REQUIRES_STATE`；保留未知同时返回 `CONFIRMED_WITH_UNRESOLVED_UNKNOWNS`。
4. `max_rounds` 到达后进入 `budget_exhausted`，后续 resume 返回 `LOOP_TERMINAL`。
5. `status` 不写文件，并报告 allowed actions 与 state digest。
6. `amend` 保留旧答案和旧 evidence，标记 superseded，新增 active amendment source。
7. 高风险 `actor=model` 决策被拒绝；进入 `awaiting_user_decision` 后必须取得 fresh、明确的 `decision_input`，旧诊断答案不能冒充最终选择。
8. 被引用答案修订后，旧证据可审计但不能继续作为 active claim 来源。
9. `confirmed` 必须拥有 stated outcome、success evidence，且 outcome 能在 active evidence 中逐字定位。
10. 伪造 evidence source、event、revision 或不可能终态会被 state validator 拒绝。
11. 仅把 `actor` 字段写成 `user` 不足以认证本人；即使保留 fresh input，宿主仍须完成用户身份认证。
12. 同 answer ID 的幂等重放必须匹配原始 `expected_revision`，否则冲突。
13. 一项未知但零问题的合法 spec 进入 `needs_reassessment`，`status` 只报告真正可执行的 `advance`。
14. “好、更好、变优秀”以及目标原样充当成功证据不能进入 `ready_for_answer`。
15. 决定词必须出现在精确 selected span 内；输入中无关句子的“我决定”不能把背景事实冒充成某项 tradeoff 的最终选择。
16. “我想变得更好”加模型自造“记录是否更好”不能 confirmed；每项 criterion 必须绑定 active 用户证据并增加可判定维度。
17. Confirmed outcome 不能只引用 original request 或 superseded evidence，必须引用 post-start active answer/amendment。
18. “我决定不了”、尚未决定、无法决定、疑问与反问不能进入 `user_decision_recorded`；明确的负向选项仍可通过。
19. 高风险 verdict 递归扫描全部模型语义字段，同时跳过用户原文和 source quote；“你应该离开这家公司”等行动同义表达被拦截。
20. 两项价值取舍只决定 `t1` 时继续停在 `awaiting_user_decision`；用新 decision ID 重复决定 `t1` 返回稳定错误且不写状态，决定 `t2` 后才终止，原事件在部分态与终态仍可精确幂等重放。
21. 手工伪造两个不同 decision/event/source 却都指向 `t1` 的终态返回 `STATE_INVALID`；终态必须完整覆盖 spec 派生的全部 tradeoff IDs。

### Failure-driven evolution loop

首批 6 个黑盒测试先全部 RED，再全部 GREEN；后续独立红队把冻结回归扩为 29/29：

1. `init` 读取任意 suite manifest，而不是硬编码当前四题。
2. ledger append-only、逐条 hash chain、同 payload event-id replay 不重复写入。
3. cycle 必须绑定 base RED、candidate GREEN 与 distinct declared reproducer receipt。
4. author、reproducer、reviewer 三个 ID 必须不同。
5. sealed holdout 的路径和内容不进入 status；消费后变为 spent。
6. promotion budget 或 saturation 触发后，后续 promotion 返回 `EVOLUTION_STOPPED`。
7. 新失败不会伪装成已进入 suite；只生成绑定哈希的 `manifest_proposal`，等待 maintainer 显式应用并全量复测。
8. failure receipt 的 input hash 必须等于 manifest case 的 envelope/input/sealed hash。
9. base、candidate、reproduction 三份 receipt 必须绑定同一个 failure 输入。
10. 只修改派生 state 的 budget、stop、roles 或 cycle 时，`status` 返回 `STATE_DERIVATION_MISMATCH`。
11. 同类 state-only 篡改不能绕过 `promote`；每个 ledger event 都绑定 post-event state checkpoint。
12. `close-cycle` 的 base receipt 必须逐字段等同于 `failure_observed` 保存的原始 RED receipt，不能只复用相同 case 和 input。
13. 重复 `init` 必须重新验证 ledger head 和派生 state checkpoint，不能成为篡改旁路。
14. 相同 cycle ID 只对完全相同的 close-cycle payload 幂等；换证据重放返回 `CYCLE_ID_CONFLICT`。
15. state 与 ledger 的 literal、normalized、symlink-parent 或 same-inode alias 在写入前拒绝。
16. 已提交 promotion 在 iteration budget 或 saturation stop 后仍可 exact replay；新事件和改写 payload 继续返回 `EVOLUTION_STOPPED`。
17. 触发 saturation 的 `close-cycle` 即时返回真实落盘 `stopped` phase。
18. record、cycle 与 promotion 的 event ID 全局唯一，内部 namespace 保留，空值或碰撞不得写坏 ledger。
19. JSON NaN/Infinity、非有限 improvement 与非有限 manifest policy fail closed。
20. stop 后不接受新的 record、close-cycle 或 promote mutation，只允许已提交 payload 的精确重放。
21. receipt ID、pass/fail 与 failure_codes 极性、payload/receipt codes 及 actor linkage 必须一致。

以上 15 至 21 由多子例覆盖，合计 evolution tests 为 29，不表示只有 21 个断言。

该工具不自动修改 Skill。它只阻止没有证据、没有复现或角色不独立的候选被晋级。

## Fresh host 证据边界

当前保存了两个隔离 Codex desktop agent-context shadow run，分别覆盖 001/004 与 002/003。四题按冻结语义边界为 4/4，exact prompt、output、hash 和环境声明见 [`retest/runtime-v0.3-rc4-shadow/results.md`](retest/runtime-v0.3-rc4-shadow/results.md)。这证明当前指令在两个代理上下文中出现过目标行为，但没有经过目标宿主安装、positive/negative discovery 或多 trial，因此不得写成 fresh target-host score。

历史 `0.2.0-rc.6` 曾对四题各启动一个 fresh Codex CLI 进程。四次都创建 session 并显示 `gpt-5.5`、reasoning effort `none`、read-only sandbox，随后在模型回答前触发 usage limit；0 次完成，没有 host score。记录见 [`retest/runtime-v0.2-rc6/results.md`](retest/runtime-v0.2-rc6/results.md)。

当前 `0.3.0-rc.4` 改变了 confirmed evidence、high-risk semantic scanning、decision commitment、evolution workspace 与安装包，因此必须重新进行 fresh host discovery 与行为测试。当前不能宣称 0/4 或 4/4。

## 已测试环境

- macOS 26.5.2，build 25F84，arm64
- CPython 3.14.4
- 自动测试与 offline eval：无网络、无模型 API
- 历史 host runner：OpenAI Codex CLI 0.132.0
- 当前 state lock：POSIX `fcntl`，macOS/Linux；原生 Windows 未支持

## 不能证明

1. 当前 host 一定发现并完整加载 Skill。
2. 当前 host 会稳定构造语义正确的 envelope 和 Problem Spec。
3. 四个中文 regression 能代表跨语言、跨模型、多轮长期行为。
4. 模式检查可以穷尽自然语言绕过。
5. 问题定义会因果性改善真实职业、产品或组织结果。
6. 当前候选适合生产或已具备公开发行权利条件。
7. 完整源码树或候选仓库整仓已经通过隐私清洁；当前只有显式 allowlist lean bundle 得到该结论。

当前发行结论：**本地 `0.3.0-rc.4`，自动契约、独立 agent-context 尾验、离线 gate 与可复现 staging bundle 通过；fresh target-host、整仓隐私清洁与软件/内容许可拆分仍待完成。** 最终证据总表见 [`rc4-final-audit.md`](rc4-final-audit.md)。
