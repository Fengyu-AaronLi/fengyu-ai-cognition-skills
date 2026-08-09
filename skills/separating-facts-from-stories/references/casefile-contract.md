# Casefile v3.2.0 契约

仅在创建或修正工件时读取。运行时版本：schema `3.2.0`、skill `4.4.0`、validator `4.4.0`。JSON Schema 提供当前工件的形状约束，`scripts/casefile.py validate` 还执行跨字段、来源、状态、历史与 legacy attestation 规则。`scripts/casefile.py self-test` 检查安装后的核心认识论、安全与迁移信任不变量。

## 根字段和模式

根对象只可有：

`schema_version`、`skill_version`、`case_id`、`revision`、`previous_case_sha256`、`mode`、`current_input_id`、`input_sha256`、`inputs`、`source_spans`、`unclassified_observation_candidates`、`candidate_resolutions`、`claims`、`evidence`、`evidence_links`、`unknowns`、`hypotheses`、`hypothesis_request`、`discriminator`、`actions`、`user_decisions`、`safety`、`change_log`，以及仅在受信旧版迁移后出现的 `legacy_epoch`。

`init` 负责首版的 `inputs`、哈希与 `source_spans`。不可改写既有输入、哈希或 spans。

* `standard` 通常必须至少有一个 claim、evidence、unknown、action 和 `user_decisions` 项。若当前输入只有确定生成的待确认候选或候选解决记录，则 claims 与 evidence 可为空；unknown、action 与 `user_decisions` 仍须存在。
* `safety` 必须有锚定的风险信号和 action；首个 action 必须是规定的即时安全行动。revision 1 不得含普通分析。
* `passthrough` 不得含 claims、evidence、unknowns、hypotheses、actions、decisions 或 discriminator，且不能渲染为分析回答。只有运行时能证明纯翻译或纯格式操作拥有唯一完整 operand 时才可进入；前置、后置或宾语结构都必须逐字绑定，第二任务、现实补充和未被操作拥有的材料会取消 passthrough。

revision 2 及以后若保持 `standard`，当前输入不能只被追加到 `inputs` 后忽略。通常必须新增锚定 `current_input_id` 的 claim 和 evidence；当前输入若只生成新候选，或只生成一条 source-bound 候选解决记录，则 candidate-only 或 resolution-only 更新合法。有限观察语法识别出的每个当前事实 span 仍必须同时被 claim 与 evidence 覆盖。任何旧 claim 的状态变化还必须由当前输入中的新增 evidence 支撑并进入 change log。

Safety risk signal 还必须写 `routing_basis`。检测器在完整输入语境中命中的类型使用 `deterministic_backstop`，并锚定完整输入语境 span；人工语义审查补充、且已由 workflow 启动参数绑定的类型使用 `human_semantic_review`，并锚定真正触发人工判断的 span。二者不能互换。

## 旧版迁移与历史语义边界

旧版验证和第一次当前版更新必须同时满足三项条件：工件的精确 canonical SHA 出现在随发行包绑定的 `evals/legacy-migration-corpus.json`；调用方提供冻结的 legacy validation receipt；该 receipt 的 canonical 指纹与 corpus 中该工件的指纹一致。版本字符串、`valid: true` 或调用方自行计算的哈希都不能单独建立信任。

当前 corpus 只覆盖 17 个历史根，版本对限于 `3.0.0/4.0.0` 与 `3.0.0/4.0.1`。`4.0.2`、`4.1.x`、`4.2.0` 以及任何未登记工件都不宣称可迁移。trust registry 缺失或损坏时必须拒绝，不回退到宽松 legacy 规则。

第一次受信迁移会创建不可变 `legacy_epoch`，冻结旧输入、span、claim 与 evidence 的 ID 边界。后续当前版本只追加新材料，不重新解释 epoch 内旧项目。renderer 把这些项目放在 1C“历史版本保留项”，不得使用“当前意愿”“当前事实”或“当前报告”标签。

## 待确认观察与解决记录

运行时把看起来像当前可观察事件、但未通过有限事实语法的完整 span 确定写入 `unclassified_observation_candidates`。每项固定使用 `status: "pending_confirmation"` 与 `reason: "finite_observation_grammar_no_match"`，并保存 `input_id`、`source_span_id`、`source_ref` 和完整 `exact_quote`。它不是事实 claim，也不是供作者改写的解释槽。

后续输入可确定追加一条 `candidate_resolutions` 记录：

```json
{
  "id": "OCR1",
  "candidate_id": "OC1",
  "resolution_type": "user_confirmed",
  "input_id": "I2",
  "source_span_id": "SP2",
  "source_ref": "input",
  "exact_quote": "上一句确实发生了。"
}
```

`resolution_type` 只可为 `user_confirmed` 或 `user_rejected`。解决原句必须锚定候选之后的当前输入完整 span。泛指“上一句”只在恰有一个未解决候选时绑定；明确引号只有唯一匹配时绑定。疑问、假设、第三方声称或转述都不能替用户解决候选。一个候选最多解决一次。

候选与解决记录都是 append-only：旧候选保持原样，解决记录另行追加并保留历史。`user_confirmed` 只证明用户后来作了确认，`user_rejected` 只证明用户后来作了否认；二者都不创建 `observable_fact`，也不认证现实真伪。新版本若只有合规解决记录，可不新增 claim 或 evidence。

## Claim 和 evidence

所有锚点都必须引用生成的完整 source span。简化形状如下：

quoted span 还要保留引语的说话者、时间、事项与传递语境。引号里的第一人称属于原说话者，不当然属于当前用户；旧聊天或旧新闻中的原话也不当然代表当前状态。复合标签、后置来源或仍未结束的 Markdown 转述范围只要明确存在二手传递，就不能因邮件、录音、截图或“原话”变成 `direct_quote`。用户替他人代发、使用他人账号、受托、按指示、复用话术或并非原话的直接接收者，也不是他人的直接当前表态。

具名直接引语若表达当前意愿、决定、承诺或边界，使用 `stated_position`；其他通过范围检查的具名陈述使用 `attributed_statement`。二者都用 `direct_quote`、`directly_stated` 和同一完整 quote span 的直接支持关系。`attributed_statement` 只记录用户提供了这段归属于说话者的原话，不把引语中的事件、解释、动机、诊断或预测升级为客观事实。材料或虚构作品中的人物、条件句和未来话语、非原话或待确认标签、非用户本人接收的引语，以及仍处于 Markdown 二手范围内的内容不能进入这一层；疑问、转述、代理代发、否认、撤回或来源不明的引语也不能进入。历史引语可保留为 `attributed_statement`，但不能冒充当前 `stated_position`。

```json
{
  "id": "C1",
  "kind": "observable_fact",
  "observation_type": "participation_or_schedule_event",
  "text": "她连续两次临时取消约会",
  "input_id": "I1",
  "source_span_id": "S1",
  "source_ref": "用户陈述",
  "source_type": "user_direct_observation",
  "exact_quote": "她连续两次临时取消约会",
  "epistemic_status": "reported",
  "diagnostic_boundary": false
}
```

`observation_type` 只允许出现在 `observable_fact`，并须等于运行时从完整原子 span 派生的类型：`negative_report_event`、`communication_event`、`participation_or_schedule_event`、`task_or_action_event`、`artifact_or_system_state`。有限谓词语法必须从句首解析并消费整段非标点文本；合法事件后的未消费尾部会被切开。数量、体貌、副词、主动与被动次序只能通过明确语法进入观察层。来源标签只约束来源类型，不能把任意句子变成 artifact fact。无法归入有限观察类型的 span 会 fail closed，不能进入事实栏。

```json
{
  "id": "E1",
  "input_id": "I1",
  "source_span_id": "S1",
  "source_ref": "用户陈述",
  "source_type": "user_direct_observation",
  "exact_quote": "她连续两次临时取消约会",
  "can_establish": ["C1"],
  "cannot_establish": ["C2"],
  "limitations": ["single_party_report", "limited_sample"]
}
```

上例中的 `S1`、`source_ref` 和完整文本必须实际来自本次 `init` 输出，不能把示例值照抄进另一个 casefile。

`limitations` 只可用：`single_party_report`、`secondhand`、`missing_context`、`missing_timestamp`、`artifact_not_verified`、`not_independent`、`limited_sample`、`time_scope_limited`。

每个 evidence 必须至少连接一个 claim，每个 claim 必须至少有一个 evidence link。一个 `(evidence_ref, proposition_id)` 只允许一条 link：

```json
{
  "proposition_id": "C2",
  "evidence_ref": "E1",
  "relation": "does_not_establish",
  "strength": "none",
  "reason": "source_scope_limit"
}
```

`relation` 只能是 `supports`、`conflicts`、`does_not_establish`；`strength` 只能是 `direct`、`weak`、`none`，由 validator 派生，不得自选：

* `does_not_establish` → `none`
* 同一 span 的事实、明确感受、直接立场或归属陈述的 `supports` → `direct`
* 仅限明确请求、有限目录中的工作假设，其合规 `supports` 或 `conflicts` → `weak`

`motive_inference`、`identity_claim` 与 `prediction` 不允许 `supports` 或 `conflicts`，只能是 `does_not_establish`。普通 `interpretation` 同样 fail closed。唯一例外是用户以 `P数字` 明确标注的角色或权限变化命题，可与同案 `E数字` 且通过有限信号语法识别的职责、参会和系统权限 evidence 建立弱 `supports` 或 `conflicts`；状态最高为 `weakly_supported` 或 `conflicted`，仍不能进入事实层。当前版本中，一个 `E数字` 被原子化时，validator 用同源原子恢复当前用户的最小职责范围，再按每个原子的单向信号派生关系：参会减少、职责削减或权限移除要求 `supports`，职责保留或系统权限仍在要求 `conflicts`；无可识别信号或同一原子信号相反才保持 `does_not_establish`。受信 legacy 工件仍按 corpus 签入时的 profile 验证，不用当前关系强度重写历史语义。工作假设关系也只表示有限信号与低置信度候选相容或相冲突。

`reason` 只可用：`anchor_matches_report`、`behavior_is_compatible_but_not_diagnostic`、`direct_current_statement_only`、`source_scope_limit`、`counter_signal_with_limited_scope`、`artifact_scope_limited`。

`can_establish` 中每个 ID 必须有 `supports` link；`cannot_establish` 中每个 ID 必须有 `does_not_establish` 或 `conflicts` link。它们不是自由文本槽。

## Story 撤回生命周期

`retracted` 只适用于上一版仍处于活动状态的 `interpretation`、`motive_inference`、`identity_claim` 或 `prediction`。当前输入必须包含用户第一人称、当前、明确且能唯一绑定目标的撤回；第三方的声称、表示、否认，引语中的否认，或“不是他的判断”等归属说明不能代替用户撤回。无法在多个活动 story 中唯一绑定时不迁移状态。

合法撤回保留原 claim，只把其状态改为 `retracted`，并同时满足：

* `change_log` 记录真实 `from_status` 与 `to_status: "retracted"`。
* `reason_evidence_refs` 引用本轮新增、锚定 `current_input_id` 完整 span 的 evidence。
* 该 evidence 以 `does_not_establish` 连接被撤回 claim，且相应 ID 位于 `cannot_establish`。

`retracted` 是终态。后续版本只能把该 claim 保留为历史审计记录，不能恢复成当前解释、改成其他认识论状态或删除。它与候选解决是两条不同通道：前者迁移既有 story claim，后者只追加候选的用户后续说明。

## Unknown、行动和用户决定

unknown 必须显式包含 `id`、`unknown_type`、`text`、`status` 与 `resolved_by_evidence_refs`。`unknown_type` 来自有限目录并派生固定 `text`；`status` 固定为 `open`，`resolved_by_evidence_refs` 固定为空数组。运行时不替现实宣布未知已解决；新材料只能追加新的 claim 与 evidence。

`unknown_type` 只可用：`other_party_motive_or_feeling`、`relationship_status_or_intention`、`formal_role_or_authority_change`、`future_behavior_or_outcome`、`source_provenance_or_context`、`event_cause_or_context`、`plan_barrier_or_capacity`、`pattern_over_time`。固定中文文本以 schema 和运行时目录为准，不自由改写。

action 只能选择 `action_type` 并逐字使用其派生字段：

| action_type | 模式 | 固定文本 | timing | 产生新证据 |
| --- | --- | --- | --- | --- |
| `record_pattern` | standard | 记录后续发生的具体行为、时间和结果 | `next` | true |
| `neutral_check` | standard | 围绕具体安排、职责、边界或时间做一次中性核对 | `next` | true |
| `small_experiment` | standard | 把下一步缩小为一次可观察、可撤回的小实验 | `next` | true |
| `pause_major_decision` | standard | 暂不依据当前动机猜测做重大决定，先补充可观察信息 | `next` | false |
| `move_to_safe_place` | safety | 立即前往有其他人在场或有人值守的安全地点 | `immediate` | false |
| `contact_emergency_services` | safety | 立即联系当地紧急服务，并说明明确威胁、时间和可达性 | `immediate` | false |
| `contact_trusted_person` | safety | 立即联系可信任的人，告知当前位置并保持联系 | `immediate` | false |
| `avoid_contact_or_confrontation` | safety | 不要开门、单独见面或当面对质 | `immediate` | false |
| `preserve_evidence_if_safe` | safety | 只在不增加风险的前提下保存威胁原文、时间和记录 | `next` | true |
| `seek_medical_support` | safety | 立即联系当地急救或合格医疗支持 | `immediate` | false |
| `seek_legal_support` | safety | 尽快联系当地合格法律支持，避免错过紧迫期限 | `immediate` | false |

所有目录 action 的 `risk` 为 `low`、`reversible` 为 `true`、`motive_independent` 为 `true`。`text`、`timing` 和 `produces_new_evidence` 都必须等于表中值。

`user_decisions` 只可用：`relationship_boundary`、`relationship_continuation`、`employment_continuation`、`communication_boundary`、`plan_adjustment`、`evidence_threshold`、`professional_support`、`other_major_choice`。它们标记仍由用户作出的价值选择，不是行动指令。

## 验证范围

验证通过表示工件符合这套机器可检查的约束。它不认证输入中的人、事件、截图或原话在现实中真实，也不证明任何解释、动机或医学法律判断为真。
