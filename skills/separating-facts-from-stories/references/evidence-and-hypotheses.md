# 证据、工作假设、判别问题与更新

仅在需要比较有限工作假设、建立判别问题或追加版本时读取。

## Evidence 不是结论

evidence 必须引用初始化生成的完整 span，并列出它实际能建立与不能建立的 claim ID。通过 `evidence_links` 明确每一条关系；不要用证据条数投票，也不要把一个行为信号升级成对动机、人格或未来的结论。

每一条 link 使用有限关系、强度和 reason 代码。`strength` 由 validator 按同一 span 和 claim 类型派生，不能写 `moderate`、`strong` 或自行给概率。完整表见 `casefile-contract.md`。

## 有限工作假设

只有用户在一个完整生成 span 中明确、正向地请求“假设、解释、可能性或候选”的比较，才可创建 `hypotheses`。`hypothesis_request` 必须锚定该完整 span，且 `requested_count` 为 1 或 2，并与假设数量相等。含“不要假设”“别给替代故事”等否定请求不能授权创建假设。

最多两个，且每个假设必须来自下列非诊断目录，`text` 必须逐字等于对应文本：

| hypothesis_type | 固定文本 |
| --- | --- |
| `temporary_scope_or_situational_constraint` | 当前变化可能来自临时范围或情境约束 |
| `substantive_role_or_boundary_change` | 当前变化可能反映职责、边界或优先级的实质调整 |
| `communication_or_process_gap` | 当前信息缺口可能来自沟通或流程未对齐 |
| `plan_design_mismatch` | 计划未完成可能与任务设计或执行条件不匹配有关 |
| `capacity_or_resource_constraint` | 当前结果可能与时间、精力或资源约束有关 |
| `repeated_behavior_pattern` | 当前事件可能属于需要继续观察的重复行为模式 |

`confidence` 只能为 `low` 或 `medium`，不能用百分比或排名。每个假设都必须有非空 `support_signals`、`weakening_signals` 和 `exit_condition`，且退出条件必须同时属于该假设的削弱信号。信号只能为：

`formal_scope_unchanged`、`formal_scope_changed`、`behavior_does_not_repeat`、`behavior_repeats`、`explicit_boundary_unchanged`、`explicit_boundary_changed`、`source_context_verified`、`source_context_not_verified`、`small_experiment_improves`、`small_experiment_no_improvement`、`capacity_constraint_observed`、`capacity_constraint_not_observed`。

这让假设可被新观察削弱或退出，但不使其变成关于某人内心的事实。

只有带明确 `source_ref` 的合规 evidence 才能与工作假设建立弱 `supports` 或 `conflicts`。当前角色变化类假设只识别有限的正式职责、权限、参与范围和系统权限信号；可见的另一家公司、无关案例或新闻上下文会 fail closed。用户明确标成 `P数字` 的同类角色或权限变化命题，也可与同案 `E数字` 信号建立同样受限的双向关系。普通解释、动机、身份与预测仍只能连接 `does_not_establish`，不能借此通道升级。

同一个 `E数字` 可能被 runtime 切成多个原子 evidence。当前版本的 validator 会用同源原子恢复“这是当前用户的职责或权限”这一最小范围，但每条 relation 仍按该原子的信号单独派生：参会减少、职责削减或权限移除对角色被削弱命题是弱 `supports`；职责保留或系统权限仍在是弱 `conflicts`；没有识别到单向信号才是 `does_not_establish`。一个来源中已经写过一次反证，不代表其余原子可以省略或降级；若同一原子同时含相反信号，则保持 `does_not_establish`，不强行选边。受信 legacy 工件保持签入时的 validation profile，不用这条新规则反向改写历史项目。

## 单一判别问题

`discriminator` 可为 `null`。若存在一个低风险、可撤回且高信息量的问题，使用一个目录 `question_type` 和其固定问题：

| question_type | 固定问题 |
| --- | --- |
| `formal_role_or_authority_check` | 我目前的正式职责、决策参与范围或审批权限是否发生变化？ |
| `stated_boundary_check` | 对方当前明确表达的安排或边界是什么？ |
| `pattern_over_time_check` | 这个行为是否在相同条件下持续重复？ |
| `artifact_provenance_check` | 这份材料的发送人、时间和完整上下文能否核对？ |
| `plan_barrier_check` | 最先阻断本轮计划执行的可观察环节是什么？ |
| `schedule_or_availability_check` | 这次变化是否有可核对的时间或安排原因？ |

问题必须恰有一个问号，`risk: "low"` 且 `reversible: true`；`distinguishes` 至少两个唯一目标。至少两个回答分支，每个用上节信号目录中的唯一 `answer_type` 和相应固定 `observable_answer`。每个分支必须对 `distinguishes` 里的每个目标给出一次 `strengthens`、`weakens` 或 `keeps_unknown` 更新；各分支的更新效果不能完全相同。

问题核对职责、边界、时间、行为或材料来源，不要求对方证明内心。没有安全且有区分力的问题就保持 `null`。

## 候选解决与 story 撤回

候选解决不走 claim evidence 升级通道。`candidate_resolutions` 直接保存用户后续说明的完整 source span，并指向一个尚未解决的旧候选。`user_confirmed` 与 `user_rejected` 都不产生 `supports` link，不把候选变成事实，也不修改原候选。只有解决记录的 standard 更新可保持 claims 与 evidence 为空。

story 撤回则必须走 evidence 与状态迁移通道。只有上一版活动中的 `interpretation`、`motive_inference`、`identity_claim` 或 `prediction` 可被撤回，而且当前输入必须是用户第一人称、明确并唯一指向该 story 的撤回。第三方声称、转述或归属排除不能代替用户撤回。

撤回时：

1. 保留原 claim 内容，将 `epistemic_status` 改为 `retracted`。
2. 新增锚定当前输入完整 span 的 evidence，把目标 ID 放入 `cannot_establish`。
3. 新增该 evidence 到目标 claim 的 `does_not_establish` link。
4. 在 `change_log` 写真实 `from_status`、`to_status: "retracted"`，并把这条本轮 evidence 放入 `reason_evidence_refs`。

`retracted` 是终态；后续版本只能保留其历史审计位置，不能恢复为活动 story。

## 追加版本

不得覆盖旧工件。先让 `start-update` 用完整历史逐版检查：

```bash
python3 scripts/casefile.py start-update \
  --history revision-1.json revision-2.json current.json \
  --input new-material.txt --output revision-next.json
```

若 revision 1 是发行 corpus 登记的旧根，上述命令还必须传入 `--legacy-receipt frozen-legacy-receipt.json`。只有工件 canonical SHA 与回执 canonical 指纹同时命中 corpus 的 17 个冻结根可迁移，版本对只限 `3.0.0/4.0.0` 与 `3.0.0/4.0.1`；其他旧版、缺少 trust registry 或自造回执全部拒绝。

它会拒绝不存在、顺序错误或无效的历史项，并只允许输出一个新路径。新版本必须：

1. revision 比上一版恰好加一，`case_id` 不变，`previous_case_sha256` 等于上一版的规范化哈希。
2. 保留既有输入、source spans、观察候选、候选解决记录、claims、evidence、unknowns、hypotheses 和 evidence links；只追加一条当前输入及相应内容。
3. 通常新增当前 claim 与 evidence；若本轮只有确定生成的新候选或 source-bound 候选解决记录，candidate-only 或 resolution-only 更新合法。
4. 旧 claim 内容不可改。状态改变须在 `change_log` 记录真实的 `from_status`、`to_status`，并引用本轮新增、锚定当前输入的 evidence。
5. 旧 unknown 必须保持 `status: "open"` 和空 `resolved_by_evidence_refs`。新材料另加 claim 与 evidence，不修改旧 unknown。

创建草稿后，revision 2 可用相邻 `--previous`。revision 3 及以后必须把从 revision 1 到相邻上一版的完整历史传给 `validate`、`render` 和 `diff`：

```bash
python3 scripts/casefile.py validate revision-next.json \
  --history revision-1.json revision-2.json current.json \
  --legacy-receipt frozen-legacy-receipt.json --report receipt.json
python3 scripts/casefile.py render revision-next.json \
  --history revision-1.json revision-2.json current.json \
  --legacy-receipt frozen-legacy-receipt.json --output response.md
python3 scripts/casefile.py diff current.json revision-next.json \
  --history revision-1.json revision-2.json current.json \
  --legacy-receipt frozen-legacy-receipt.json
```

上例中的 `--legacy-receipt` 只在 revision 1 是上述登记旧根时使用，并且 `start-update`、`validate`、`render` 与 `diff` 必须始终传同一冻结回执；全链已经是当前版本时不要凭空添加该参数。

完整历史与相邻增量检查都通过，仍只说明版本工件合规，不说明新材料在现实中已被独立证实。
