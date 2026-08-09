# 命题、来源与状态

仅在填充或修正 casefile 时读取。枚举值必须原样写入工件。

## 生成的 source spans 是唯一锚点

`init` 和 `start-update` 为每一轮输入确定性生成 `source_spans`。它们包含 `id`、`input_id`、`source_ref`、`source_label`、字符范围、完整 `text`、`quoted` 与哈希。

不得编辑或自建 span，也不得从 span 中摘取较短子句。claim、evidence、候选解决记录、假设请求与 safety signal 必须：

* 填写该 span 的 `source_span_id`
* 使用相同的 `input_id` 与 `source_ref`
* 令 `exact_quote` 逐字等于 span 的完整 `text`

claim 还必须令 `text` 逐字等于 `exact_quote`。这保证“老板没有说要开除我”不能被截成“要开除我”。

## 事实语法之外的观察候选

原句像当前可观察事件、但有限事实语法不能可靠分类时，运行时可生成 `unclassified_observation_candidates`，固定标记为 `pending_confirmation`，原因为 `finite_observation_grammar_no_match`。它只保存源绑定原句，不是 claim，也不能自行填写 `observation_type` 后送入事实层。只有候选的 standard case 合法，前提是仍填写 unknown、action 与 `user_decisions`。

后续用户可通过唯一泛指或唯一匹配的明确引号解决一个旧候选。运行时把结果追加到 `candidate_resolutions`，类型为 `user_confirmed` 或 `user_rejected`。解决原句必须来自候选之后的当前输入完整 span；疑问、假设和第三方转述不构成用户解决。旧候选不修改，解决记录不可重写。两种结果都只记录用户后续表态，不创建事实 claim。

## claim.kind

* `observable_fact`：动作、说话或回复事件、时间、频次、文档或结果的可观察描述。用户报告仍不等于独立核验；引语内容本身不能因为写在引号里就进入事实层。
* `explicit_feeling`：用户明确说出的自身感受或身体体验。不得根据语气补写；引语、表演、第三方体验和被明确否定的感受不进入用户感受栏。
* `stated_position`：具名说话者直接原话中的当前意愿、决定、承诺或边界，只覆盖该说话者、原话时间和具体事项；不能自动成为用户当前立场。
* `attributed_statement`：用户提供的具名直接引语，但内容不是当前意愿、决定、承诺或边界。它只记录这段话被归属于该说话者，不证明引语中的事件、解释、动机、人格或未来判断为真。历史引语可进入这一层，但不能冒充当前立场。
* `interpretation`：用户或第三方赋予事件的含义，例如“这说明我被架空”。
* `motive_inference`：关于爱、敌意、控制、欺骗、优先级或真实目的的推断。
* `identity_claim`：把有限事件升级为固定人格、依恋类型、精神疾病、能力本质或命运。必须 `diagnostic_boundary: true`。
* `prediction`：关于未来必然或绝不会发生的判断。

`observable_fact` 还必须有 `observation_type`。运行时使用有限谓词语法从句首解析，并要求消费完整 span 的全部非标点内容。只在句中出现“会议、消息、文档、系统”等名词不构成事实类型。合法事件后出现未被语法消费的内容时，生成器会把事实前缀与剩余尾部分开。随后从下列有限目录派生类型：

* `negative_report_event`：完整的否定转述事件，例如“老板没有说过……”；否定只约束这个原子子句，不能豁免后面的故事。
* `communication_event`：发送、回复、未回复、通知或收到信息等事件。
* `participation_or_schedule_event`：参加、邀请、会议、取消、改期或迟到等事件。
* `task_or_action_event`：完成、删除、搬走、维修、打开、登录或其他运行时支持的动作事件。
* `artifact_or_system_state`：截图、文档、系统、权限或审批状态等可观察材料。

类型必须等于运行时从完整 span 推导的结果。无法归类时，原文仍保留在 `source_spans`，但不得被改写成解释，也不得靠自填类型进入事实栏；用相应 unknown 保留尚待核对的现实信息。`explicit_feeling` 必须是用户明确说出的自身感受或身体体验。确定性规则会 fail closed，但仍不是对现实真实性的认证。

证据不足、无法确认、不能断定、直接否定判断、假设和让步等治理词必须与被治理命题保持同一断言范围。非事实态度的补语也不等于事件已发生，包括带程度、持续修饰、“所”字或“担心的是”结构的表达。不同 kind 的并列、关联和递进故事分别生成 span；省略重复主语的未来分句仍按预测处理。显式未来时间加第三方结果属于未验证预测，不进入事实层。

## source_type

* `user_report`：用户对事件、解释或判断的普通陈述。
* `user_direct_observation`：用户称自己直接看到、听到或操作得到的外部现象。
* `explicit_self_report`：用户明确报告自身感受或体验，只能用于 `explicit_feeling`。
* `direct_quote`：输入保留了用户本人直接接收的、具名现实说话者的原话，且引用必须落在生成 span 的真实引号范围内。它只证明输入报告了该说话者在相应时间说过这段话。材料或虚构载体、条件句或未来话语、非原话或待确认标签、代理接收，以及仍在 Markdown 二手范围内的内容不满足这个类型。
* `secondhand`：同事、朋友或中间人转述。
* `unverified_artifact`：截图、维修单、附件或记录，缺少可核验来源、时间、上下文或完整性。

对 claim 和 evidence 而言，生成 span 的 `source_label` 有明显来源提示时，validator 都要求相应 `source_type`，例如“同事转述”对应 `secondhand`，“我的感受”对应 `explicit_self_report`，“截图”对应 `unverified_artifact`。复合来源采用保守合成：任何明确二手链都优先于邮件、录音、截图或“原话”等 carrier，载体不能把间接来源升级成直接来源。同句前置、后置、嵌套和 Markdown 列表或引用范围按实际传递顺序绑定；网传、群体传播、渠道获知和被动告知仍是二手。用户代发、使用他人账号、按他人指示、复用他人内容或并非引语的直接接收者，不构成对方直接表态。新的第一人称判断或结论可以结束先前普通转述范围，但不能覆盖显式来源标签。`direct_quote` 还必须落在真实引号 span 内，并排除材料或虚构载体、条件或未来话语、非原话和待确认标签。本地运行时不接受自填的 `verified_artifact` 或 `external_verified`，也不能从标签本身认证外部事实。

## epistemic_status

字段允许的兼容枚举为：`reported`、`directly_stated`、`unverified`、`weakly_supported`、`strongly_supported`、`conflicted`、`contradicted`、`verified`、`superseded`、`retracted`。

当前 validator 对有 evidence link 的 claim 派生状态如下：

* `observable_fact` 与 `explicit_feeling` → `reported`
* `stated_position` 与 `attributed_statement` → `directly_stated`
* `motive_inference`、`identity_claim` 与 `prediction` → 只能有 `does_not_establish`，因此保持 `unverified`
* `interpretation` → 默认同上；只有用户明确标成 `P数字` 的角色或权限变化命题，才可与同案 `E数字` 的有限职责、参与和系统权限信号建立弱 `supports` 或 `conflicts`，状态最多为 `weakly_supported` 或 `conflicted`
* 明确请求的有限工作假设可有弱 `supports` 与 `conflicts`，但假设不是 claim，也不会变成事实
* 上一版活动中的解释、动机、身份定性或预测，只有在当前输入出现用户第一人称、明确且唯一绑定的撤回，并由本轮 source-bound evidence 与 `change_log` 支撑时，才可转为 `retracted`

`verified` 一律被拒绝；动机、身份和预测不能标为 `strongly_supported` 或 `verified`。兼容枚举不等于可由本运行时派生的认识论结论。

`retracted` 是历史终态。原 claim 继续保留，但不再出现在当前解释或动机区；后续版本不得恢复、删除或改写。第三方声称、转述、引语中的否认、“不是他的判断”等归属排除，或没有唯一目标的泛指，都不能触发用户 story 的撤回。

## 不可越级

* 明确感受只证明用户报告了该体验，不证明其解释正确。
* 直接立场和归属陈述只证明输入把完整原话归属于具名说话者，不能证明引语内容为事实、人格、动机或未来，也不能自动成为用户当前立场。
* 二手来源不能冒充直接原话，未核验工件不能冒充外部认证。
* 一条 evidence 只在被明确连接的命题上发生作用。不要把一个行为信号批量套到动机、人格和未来上。
* 确定性运行时无法认证两个自然语言片段具有同一主体、组织、时间和情境，所以不允许 evidence 升级自然语言解释。需要比较时，只能使用用户明确要求的有限工作假设与弱相容性信号。
