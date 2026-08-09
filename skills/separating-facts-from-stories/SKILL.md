---
name: separating-facts-from-stories
description: Use when limited observations or one-sided reports are being turned into facts, motives, diagnoses, fixed identities, or certain futures, or when a prior casefile must be updated with new material.
---

# 事实与故事分离

使用有状态工作流建立、校验并渲染 casefile。不要直接把用户叙述改写成八栏建议，也不要把零安装提示词当成完整 Skill。

`SKILL_DIR` 是本文件所在目录。启动前先做一次语义安全审查。若材料可能涉及正在发生的自伤、他伤、明确威胁、医疗急症或紧迫法律风险，不要等待确定性检测器命中。显式选择 `safety`，并用可重复的 `--safety-signal-type` 绑定人工识别的风险类型；随后先把 runtime 生成的确定性安全模板发给用户，再建档。建档不得延误求助。

将本轮用于分析的材料逐字保存为 UTF-8 文件。姓名、住址、联系方式、账号和公司机密应在进入本流程前由用户或宿主去标识化；一旦保存，不得为了通过验证而改写。为每次处理使用一个不存在、位于项目仓库外且权限受限的新 workspace。运行时会持久保留输入、状态、casefile、回执和输出，不会自动清理。不要把运行时脚本全文塞进上下文。

## 1. 启动并服从状态机

先读 `references/workflow-loop.md`，运行：

```bash
python3 "$SKILL_DIR/scripts/workflow.py" start \
  --input "$INPUT_FILE" \
  --workspace "$WORKSPACE" \
  --case-id "$CASE_ID" \
  --mode "$ROUTED_MODE"
```

没有疑似即时风险时，`ROUTED_MODE=auto`。疑似风险时必须使用 `ROUTED_MODE=safety`。若确定性检测器没有命中，启动命令还必须追加一个或多个 `--safety-signal-type TYPE`；同一参数可重复。确定性风险检测只是 backstop，不是自然语言风险识别的完备证明。

只按返回的 `phase` 和 `next_action` 继续：

* `passthrough_required`：只完成翻译、格式转换或忠实保留来源的时间线整理，不做心理分析。若同一请求还要求判断材料真伪、来源可信度、事件含义或他人动机，必须进入 `standard`，不能把第二项任务藏在格式要求里。将直接响应交给 `complete-passthrough`，不建 casefile。
* `safety_action_required`：读 `references/safety-routing.md`，运行 `safety-template` 得到与已绑定风险类型逐字匹配的响应，先把它发给用户，再用 `acknowledge-safety` 保存同一文件。不要自行增加问题、缓和语、动机分析或后续建议；任何增删都会被拒绝。
* `awaiting_authoring`：填写 workspace 中已绑定输入哈希的 `casefile.json`。

一般不确定不等于即时风险。关系、职场、自我评价中的确定动机、人格或未来判断不得借 `passthrough` 绕过检查；运行时也会拒绝这种路由。

安全路径的固定命令是：

```bash
python3 "$SKILL_DIR/scripts/workflow.py" safety-template \
  --workspace "$WORKSPACE" > "$SAFETY_RESPONSE_FILE"

# 先把该文件逐字发送给用户，再记录同一文件。
python3 "$SKILL_DIR/scripts/workflow.py" acknowledge-safety \
  --workspace "$WORKSPACE" \
  --response "$SAFETY_RESPONSE_FILE"
```

## 2. 填写 casefile

只在 `awaiting_authoring` 或 `repair_required` 阶段编辑 `casefile.json`。先读 `references/claim-taxonomy.md` 与 `references/casefile-contract.md`。需要工作假设时再读 `references/evidence-and-hypotheses.md`。

工作流已生成逐字输入、哈希和完整 `source_spans`。不得编辑、截短、合并或自建 span。每个 claim、evidence、`hypothesis_request` 和 safety signal 都必须引用一个生成的完整 span；`input_id`、`source_ref` 与 `exact_quote` 必须逐字匹配。

填充标准工件时：

* 通常至少有一个 claim、一个 evidence、一个 unknown、一个有限目录中的 action 和一个有限目录中的 `user_decisions` 值。若运行时只生成了 `pending_confirmation` 候选，或本轮只生成了 source-bound `candidate_resolutions`，可保持 claims 与 evidence 为空；unknown、action 与 `user_decisions` 仍必填。
* `unclassified_observation_candidates` 与 `candidate_resolutions` 都由运行时确定生成，不得手写、改序或改写。候选的固定原因为 `finite_observation_grammar_no_match`：原句像可观察事件，但尚未通过有限事实语法。后续 `user_confirmed` 或 `user_rejected` 只记录用户对该候选的明确后续说明，二者都不会自动把候选送入事实层。
* `claim.text` 必须逐字等于 `exact_quote`，不能用释义借锚点进入事实层。
* `observable_fact` 只能引用运行时切出的完整原子 span，必须填写由运行时派生的 `observation_type`。有限观察语法必须从句首解析并消费全部非标点内容；句中只有“会议、消息、文档”等名词，或来源标签写着“截图”，都不能替代这个判断。
* 合法事件后仍有未消费内容时，生成器只保留被有限语法消费的事实前缀，尾部单独成 span；不得重新合并。普通事件表达若暂不在有限语法中，原文仍保留在 `source_spans`，但不能自行填写类型硬塞进事实栏。
* 具名直接引语中的当前意愿、决定或边界使用 `stated_position`；其他通过范围检查的具名陈述使用 `attributed_statement`。两者都只记录原话归属，不证明引语内容为事件事实。材料或虚构作品中的人物、条件句和未来话语、非原话或待确认标签、非用户本人接收的引语，以及仍处于 Markdown 二手范围内的内容都不能冒充直接归属；疑问、转述、代理代发、否认、撤回或来源不明的引语同样不得进入这一层。
* 每个 claim 都必须有 evidence link。事实、明确感受、直接立场和归属陈述还必须有同一 span 的 `supports` 加 `direct` link。
* 状态由 claim 类型和 links 派生。`motive_inference`、`identity_claim` 与 `prediction` 只能用 `does_not_establish`。`interpretation` 默认同样如此；唯一例外是用户用 `P数字` 明确标注的角色或权限变化命题，可与同案 `E数字` 的有限职责、参会和系统权限信号建立弱 `supports` 或 `conflicts`，最高只能得到 `weakly_supported` 或 `conflicted`，不得变成事实。一个 `E数字` 被拆成多个原子 evidence 时，每个原子都必须按自己的可识别信号建立关系；同一来源里已有一项 `conflicts`，不能把另一项明确的权限保留信号降为 `does_not_establish`。
* 只有用户在完整 span 中明确、正向要求比较假设或候选解释，才可有最多两个工作假设；详细规则见 `references/evidence-and-hypotheses.md`。
* `action_type`、`user_decisions`、假设、判别问题和分支回答都必须来自有限目录。不要填写自由动作、人格诊断或动机清单。
* safety 的每个风险信号都必须写 `routing_basis`。检测器命中的类型使用 `deterministic_backstop`，并锚定当前输入的完整语境 span；不要把翻译、虚构、否定或历史引语拆出后重新检测。仅由人工语义审查识别且已经通过启动参数绑定的类型使用 `human_semantic_review`，锚定真正触发人工判断的完整 span。

## 3. 执行有限修复循环

```bash
python3 "$SKILL_DIR/scripts/workflow.py" check --workspace "$WORKSPACE"
```

`check` 失败时，只按返回的稳定错误码、JSON Pointer 和新回执修正对应问题，然后再运行一次。默认最多两次检查；不得编辑 `state.json`、输入、旧回执或尝试次数，不得清空必填数组来换取通过。

* `repair_required`：修正后重跑 `check`。
* `blocked`：停止，不生成貌似完整的回答；说明哪些契约仍未通过。
* `ready_to_finalize`：运行最终交付门。

```bash
python3 "$SKILL_DIR/scripts/workflow.py" finalize --workspace "$WORKSPACE"
python3 "$SKILL_DIR/scripts/workflow.py" status --workspace "$WORKSPACE"
```

只有 `finalize` 成功，且 `status` 返回 `integrity_valid: true` 与 `phase: completed`，才可交付 workspace 中的 `response.md`。`finalize` 会再次验证并核对通过检查时的工件字节哈希，不能先验证一个文件再替换成另一个文件。

验证器检查工件结构、输入与来源锚点、有限目录、证据关系、状态迁移和版本链。它不能证明用户叙述在现实中为真，也不能替代事实核查、医疗、法律或安全专业判断。

渲染保留八个核心判断区，并增加 1A 直接表态、1B 待确认观察；存在历史状态变化时，另加已更正表态、已撤回解释或已解决候选等生命周期区。历史区不回流到当前事实、解释或动机区。

## 4. 新材料只追加版本

不得覆盖旧 casefile，也不得复用旧 workspace。`start-update` 必须收到从 revision 1 到当前版的完整历史，逐版验证后才创建新 workspace：

```bash
python3 "$SKILL_DIR/scripts/workflow.py" start-update \
  --history "$REVISION_1" "$REVISION_2" "$CURRENT_CASEFILE" \
  --input "$NEW_INPUT_FILE" \
  --workspace "$NEW_WORKSPACE"
```

新版本只追加当前输入和确定生成的 spans。标准更新通常必须增加锚定当前输入的 claim 和 evidence；若本轮只有新候选或候选解决记录，则 candidate-only 或 resolution-only 更新合法，但仍必须保留 unknown、action 与用户决定。候选解决必须绑定当前输入中的完整 span，且只能追加到 `candidate_resolutions`。

若 revision 1 是受支持旧版，`start-update` 还必须追加 `--legacy-receipt "$LEGACY_RECEIPT"`。这不是任意回执入口：当前只迁移发行绑定 corpus 中 17 个精确历史根，版本对限于 `3.0.0/4.0.0` 与 `3.0.0/4.0.1`。工件哈希或回执指纹不在 corpus、trust registry 缺失、其他版本号或自造回执全部停止。第一次迁移生成不可变 `legacy_epoch`；旧项目只在 1C 历史保留区展示，不重新标成当前事实、当前意愿或当前报告。

有限观察语法能识别出的每个当前事实 span 都必须被 claim 与 evidence 消费，不能用一条次要新材料掩盖另一条重要更新。保留旧项目。旧解释、动机、身份定性或预测只有在用户以第一人称明确且唯一地撤回时才可转为 `retracted`；第三方声称、转述或归属排除不能替代用户撤回。该状态是终态，必须由本轮新增、锚定当前输入并以 `does_not_establish` 连接目标的 evidence 支撑，同时在 `change_log` 记录真实前后状态。旧 unknown 保持 `status: "open"` 与空 `resolved_by_evidence_refs`。随后对新 workspace 执行同一个 `check → repair → finalize → status` 循环。

若新材料出现即时风险，`start-update` 会切换到 `safety`。它可保留旧分析，但安全版本不得新增或改写普通分析。

会话中断后先运行 `status`，不要靠聊天记忆猜当前阶段。若返回 `RECOVERY_REQUIRED`，只重试被中断的同一条 `check`、`finalize`、`complete-passthrough` 或 `acknowledge-safety` 命令；运行时只会接纳与当前确定性结果逐字一致的孤立回执或响应。同一 workspace 的状态命令由 `.workflow.lock` 串行化，不要绕过 CLI 直接并发改写文件。`STATE_CONFIG_MUTATED`、`RECOVERY_CONFLICT` 或其他完整性错误必须停止并保留现场。

## 强制边界与隐私

* 不诊断回避型、NPD、精神疾病或人格障碍。
* 不判断爱不爱、是否出轨、是否会复合。
* 不用另一个武断故事替换用户故事，不否定明确表达的感受。
* 不替用户决定分手、辞职、对抗或报复。
* 医疗、法律、安全、自伤或他伤风险转向现实专业支持。
* runtime 会把处理材料和派生产物写入 workspace。未经用户明确要求，不把私人聊天、姓名、住址、联系方式、公司机密或完整医疗记录写入项目目录或可提交路径。
