# 有状态工作流与修复循环

`workflow.py` 3.1.0 是默认入口。它把一次处理保存为独立 workspace，并强制执行有限状态迁移。模型负责填写判断，运行时负责输入绑定、验证、失败重试、崩溃恢复和交付门。同一 workspace 的读写状态命令都使用文件锁；`status` 与 `safety-template` 取得共享锁，写命令取得排他锁。崩溃退出后锁由操作系统释放。

## 标准路径

```text
awaiting_authoring
        |
      check
        |
  +-----+------------------+
  |                        |
repair_required      ready_to_finalize
  |                        |
check，最多两次            finalize
  |                        |
blocked                 completed
```

启动后读取命令返回的 `next_action`。在 `awaiting_authoring` 或 `repair_required` 阶段，只编辑 workspace 中的 `casefile.json`。不要编辑 `input.txt`、`state.json`、旧回执或旧版本。

草稿中的 `unclassified_observation_candidates` 与 `candidate_resolutions` 由运行时确定生成，不属于人工填写区。若当前只有 `pending_confirmation` 候选，standard case 可不填 claims 与 evidence；若更新只解决一个旧候选，同样允许 resolution-only。两种情况仍须填写或保留 unknown、action 与 `user_decisions`，且 confirmed/rejected 都不会自动进入事实层。

```bash
python3 "$SKILL_DIR/scripts/workflow.py" start \
  --input "$INPUT_FILE" \
  --workspace "$WORKSPACE" \
  --case-id "$CASE_ID" \
  --mode standard

python3 "$SKILL_DIR/scripts/workflow.py" check --workspace "$WORKSPACE"
python3 "$SKILL_DIR/scripts/workflow.py" finalize --workspace "$WORKSPACE"
python3 "$SKILL_DIR/scripts/workflow.py" status --workspace "$WORKSPACE"
```

`check` 每次都创建新回执并增加尝试次数。默认最多两次。第一次失败进入 `repair_required`，第二次仍失败进入 `blocked`。不得改写尝试次数、覆盖回执或清空必填数组来继续。进入 `blocked` 后，保留 workspace 供复盘；确认问题后另建新 workspace。

`finalize` 只接受 `ready_to_finalize`。它再次验证工件，并要求工件字节哈希与最后一次通过的 `check` 完全一致。通过后才生成 `response.md`。最终输出必须留在 workspace 内。标准 renderer 保留八个核心判断区、1A 直接表态、1B 待确认观察和 1C 历史版本保留项；存在状态迁移时才追加已更正、已撤回或已解决候选等历史生命周期区。1C 不冒充当前事实、当前意愿或当前报告。

安全模式的终态不同。`acknowledge-safety` 已经逐字验证并哈希绑定 `safety-response.md`，因此 3.1.0 的 `finalize` 直接把这份已确认模板复制为最终 `response.md`。它不会再用 casefile renderer 生成第二套用户可见安全文案，也不会在现实行动前插入标题、复述风险原文或追加动机分析。casefile 继续作为内部审计记录。

## 状态证据

`state.json` 保存：

* 输入、工件、回执和输出路径
* 输入哈希、通过验证时的工件哈希、最终输出哈希
* 运行时与 Schema 版本
* 尝试次数和最后一次完整验证结果
* 带前序哈希的事件链
* 启动时绑定的 mode、casefile 路径、输入与历史配置

事件链用于发现意外改写和跳步，不是有密钥的数字签名。拥有本地写权限的人仍可重算整条链，因此不要把它表述为防恶意篡改的密码学证明。

`status` 会检查事件顺序、版本、输入、历史版本、已验证工件、已交付输出和安全响应的哈希。发现不一致时退出码非零。

## 非触发路径

翻译、改格式或忠实整理已标来源时间线时，由调用方明确选择 `passthrough`。这条路径不创建 casefile。当前翻译路由覆盖前置“英文翻译：”、后置“翻译成中文”、无引号“把这句译成英文”以及换行后的“请译为英语”等纯任务形式。被翻译材料包含威胁或伤害字样时，材料仍是翻译 operand；若同一输入另有当前现实求助，则 safety 优先。

```bash
python3 "$SKILL_DIR/scripts/workflow.py" start \
  --input "$INPUT_FILE" --workspace "$WORKSPACE" \
  --case-id "$CASE_ID" --mode passthrough

python3 "$SKILL_DIR/scripts/workflow.py" complete-passthrough \
  --workspace "$WORKSPACE" --response "$DIRECT_RESPONSE"
```

运行时检查响应非空、没有混入本 Skill 的分析栏目或自由动机判断。翻译 passthrough 还不允许响应比源材料增加更多陈述。翻译准确性和格式正确性仍由原任务自己的检查负责。

## 安全路径

调用方必须先做语义风险审查。疑似正在发生的风险直接以 `--mode safety` 启动；`auto` 的确定性检测只是额外 backstop。否定、纯引用和已结束历史不会遮蔽同一输入后文明确复发的当前风险。若检测器没有命中，必须用可重复的 `--safety-signal-type` 绑定人工识别的类型，否则启动失败。先生成确定性模板，把它逐字发给用户，再保存同一可见响应：

```bash
python3 "$SKILL_DIR/scripts/workflow.py" start \
  --input "$INPUT_FILE" --workspace "$WORKSPACE" \
  --case-id "$CASE_ID" --mode safety \
  --safety-signal-type other_immediate_risk

python3 "$SKILL_DIR/scripts/workflow.py" safety-template \
  --workspace "$WORKSPACE" > "$VISIBLE_SAFETY_RESPONSE"

# 先把文件逐字发给用户，再执行确认。
python3 "$SKILL_DIR/scripts/workflow.py" acknowledge-safety \
  --workspace "$WORKSPACE" --response "$VISIBLE_SAFETY_RESPONSE"
```

响应必须与当前风险类型和明确地点的 catalog 渲染逐字相同。输入明确显示用户人在澳大利亚且存在即时风险时，第一条会指定 `000`。任何问题、弱化语、否定、延迟、额外建议或危险尾巴都会被拒绝。确认后才能进入 casefile 填写与验证。安全响应的路径与哈希同时绑定顶层状态和事件链；完成 casefile 后，最终 `response.md` 必须与已确认的 `safety-response.md` 字节一致。

## 发行评测中的 host-managed 执行

开发仓库的冻结评测不是让模型自由决定文件布局。`host_eval_runner.py` 先把每个冻结输入逐字解包到只读 `.runtime/input-N.txt`，再按案例类型预留固定 workspace。模型只能填写这些 workspace，不得自建第二套工作区、canonical artifact、receipt 或 `case-result.json`。

模型退出后，宿主按固定顺序收口：

1. 重新核对 raw input 的路径、字节和 SHA-256。
2. 用冻结 runtime 检查每个 workspace 已到合法完成态。
3. 将内部 casefile 原子晋升到 canonical `artifacts/`，并在 canonical 路径重新执行 validator。
4. 对 passthrough 案由宿主执行 `start → complete-passthrough`，保留 `state.json`、`response.md` 与内部 validation receipt，而不是只看一段表面答案。
5. 对 invalid fixture 使用 snapshot 中冻结的同一坏工件，由宿主运行 validator 并晋升内部回执。
6. 最后才绑定 Codex last message、canonical response、工件集合与 host receipt，生成 `case-result.json`。

独立 auditor 不信任 binder 的结论。它再次核对固定 workspace 数量、raw input 字节、内部与 canonical casefile 的字节一致性、passthrough 或 invalid receipt、终端输出，以及 runtime snapshot 的文件集、目录集、权限和哈希。Codex 传输层仅允许最后消息比 canonical 输出少一个终止换行；其他差异一律拒绝。

## 新材料与完整历史

新材料必须放入新的 workspace，并提供从 revision 1 到当前版的完整历史：

```bash
python3 "$SKILL_DIR/scripts/workflow.py" start-update \
  --history "$REVISION_1" "$REVISION_2" "$CURRENT_CASEFILE" \
  --input "$NEW_INPUT" \
  --workspace "$NEW_WORKSPACE"
```

若历史根属于受信 legacy，命令还必须提供 `--legacy-receipt "$LEGACY_RECEIPT"`。运行时只承认 release-bound corpus 中 17 个精确工件，版本对限于 `3.0.0/4.0.0` 与 `3.0.0/4.0.1`；版本字符串、自造成功布尔值和自行计算的工件哈希都不能授权迁移。安装包必须包含同一 trust corpus，缺失或指纹不符时 fail closed。

运行时逐版验证哈希链后才创建下一版。standard 更新通常必须新增锚定当前输入的 claim 和 evidence；当前输入只生成新候选或 source-bound 候选解决记录时，candidate-only 或 resolution-only 更新合法。泛指只能绑定唯一未解决候选，明确引号只能绑定唯一匹配；疑问、假设和第三方转述不会生成解决记录。候选和解决 ledger 都只追加，旧候选不改写。

有限观察语法识别出的每个当前事实 span 仍必须被 claim 与 evidence 覆盖，不能用一项次要更新掩盖另一项新材料。旧 story 只有在用户第一人称明确且唯一撤回时才可转为 `retracted`；第三方不能替代。迁移必须由本轮新增、锚定当前输入并以 `does_not_establish` 连接目标的 evidence 与真实 `change_log` 支撑，且该状态以后只能保留在历史区。后续仍执行 `check` 与 `finalize`。历史文件发生变化、缺版、旧项目重排或顺序错误都会阻止继续。

## 恢复与停止条件

进程中断后先运行 `status`，只按它返回的 `phase` 和 `next_action` 继续。不要凭聊天记忆猜测阶段。

若回执或响应已原子落盘、状态文件尚未完成迁移，`status` 返回 `RECOVERY_REQUIRED`。重试同一条命令时，运行时会重新计算当前结果，只在孤立文件逐字段或逐字一致时接续；不一致返回 `RECOVERY_CONFLICT`，不会覆盖。启动配置被改写则返回 `STATE_CONFIG_MUTATED`，不能按崩溃恢复处理。

一次 session 只有以下停止条件：

* `completed`，输出和状态完整性检查通过
* `blocked`，两次修复仍未通过，未生成可交付回答
* `safety_action_required`，现实安全动作尚未先发出

验证失败、执行超时或状态不明都不属于完成。

这里描述的是单案例执行 loop。产品级的对抗审查、红绿修复、留存快照与 `prove-stop` 合同见开发仓库中的 `evals/improvement-loop-spec.md`。
