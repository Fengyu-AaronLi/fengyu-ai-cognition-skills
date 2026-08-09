# Improvement loop executable contract

状态：未发布本地候选合同。当前 state schema 标记为 1.1.0，phase work order 为 v1，source epoch 为 v2。候选阶段不承诺旧 1.1.0 state 向前兼容；控制面协议变化后必须 fresh `start`，不能静默迁移旧状态。controller 记录轮次、签发单次工作单、限制写入、恢复事务，并执行固定 STOP recipe；固定 `run-next` 当前只覆盖 preflight，不自行编辑产品源码，也不接受任意 shell 命令。

## 两个循环

单案例 loop 处理一份用户材料，见 `references/workflow-loop.md`。本文件描述产品本身如何进化：

```text
preflight → run-bound work order
        ↓
adversarial review
        ↓
S0 → author RED → Sr
        ↓
minimal fix → S1，RED 字节不变
        ↓
independent recheck
        ↓
source freeze → isolated eval → install → rollback/restore
        ↓
typed evidence gate ── fail → LOOP
        ↓ pass
controller prove-stop → STOP
```

YAML 的回边只是政策表达。状态推进与 receipt 验证由 `scripts/improvement_loop.py` 完成，真实停止证据由 `scripts/produce_release_gate.py` 的固定 recipe 2.0.0 生成。`run-next` 尚未覆盖整张 graph。

## CLI

| 命令 | 责任 |
| --- | --- |
| `start` | 绑定候选仓库、workflow、权威 source manifest、允许写入根和最大轮次，创建第一轮 |
| `advance` | 兼容旧 `legacy_gate`，以及由 controller 内部发布 prove-stop 结果；外部调用不能产生 `STOP` |
| `begin-step` | 为 graph 当前外部阶段签发一个绑定 controller run、iteration、active source、依赖 receipt 和随机 attempt ID 的单次工作单；同一未消费步骤幂等返回原工作单 |
| `run-next` | 执行当前节点已注册的固定 controller recipe；目前只支持 `preflight_snapshot`，其他节点返回 `RUNNER_RECIPE_UNAVAILABLE`，且不接受 step、command、argv 或 shell 覆盖 |
| `authorize-fix` | 在 `red_green_fix` 前接纳一个精确 source epoch v2 计划，绑定全部 open findings、S0、Sr、S1、RED 与实现留存 blob；不执行源码编辑 |
| `record-step` | 校验并消费当前工作单、phase-specific payload、phase receipt、artifact、finding event 与依赖哈希，原子推进 graph |
| `resume` | 从持久化 transition intent 恢复，重复调用不重复推进 |
| `guard` | 对写入提案做路径判定，拒绝删除、push、publish 和受保护路径 |
| `prove-stop` | 在留存 release basis 上执行固定 producer recipe，并且是唯一的 `STOP` authority |

正常结果和拒绝结果都输出单个 JSON object。拒绝使用非零退出码和稳定错误码。

## Graph 执行协议

controller-owned preflight 由 `run-next` 启动固定隔离 Python worker，宿主保存 stdout、stderr、host receipt，再内部提交 phase receipt。其余外部阶段固定走：

```text
begin-step
   ↓
读取 phase_work_order.v1
   ↓
执行本阶段并保存 typed payload、raw artifact 与 phase_receipt.v1
   ↓
record-step
```

工作单同时绑定 `controller_run_id`、`iteration_id`、`attempt_id`、当前 source SHA、当前 ledger prefix 与精确依赖 receipt。跨 run、跨 iteration、换 source、替换 nonce、跳步或复用已经消费的 receipt 都会失败。无效 receipt 不消费工作单；成功提交会把同一 attempt 固化进 ledger 并原子清空 active work order。

这些绑定证明本地文件彼此一致，不是数字签名。拥有同一 OS 账号写权限的人仍可重写程序、状态和所有本地证据；控制器面向意外漂移、错误重放和普通流程违规，不宣称抵抗同权限恶意攻击者。

## 三套文件集合

1. `workflows/separating-facts-release-sources.json` 是 controller 的权威 source manifest，覆盖源码、发行文档、指定测试和引用的历史证据。
2. `package_runtime.py` 与 `run_evals.py` 的 `RELEASE_EVIDENCE_FILES` 必须完全相等，是绑定 eval 与安装的发行子集。
3. 安装 allowlist 只包含运行时所需文件和两份随包证据。

第二套必须是第一套的子集，第三套不得被冒充成完整源码。`start` 接受的显式 source files 只能与权威 manifest 完全相等，不能通过少列文件缩小漂移检测范围。

## 状态、事务与恢复

`loop-state.json` 每轮记录 `controller_run_id`、`iteration_id`、初始与 active source、source manifest identity、结构化 finding ledger、active work order、phase ledger、source epoch、gate identity、决策和未关闭项。未独立关闭的历史 GREEN 若被后续 source drift 失效，会保存在 `superseded_fixes`，当前 fix 回到空值。controller 使用锁和 prepare、原子发布、committed transaction archive 协议。

崩溃发生在 intent 已落盘、状态尚未发布时，`resume` 只能恰好提交一次。已提交 intent 进入 `transactions/`，不得靠删除现场恢复。没有 pending transaction 时，`resume` 仍检查 live source：精确 S0、Sr 或 S1 保持当前授权；保留历史 receipt 与 artifact 字节的计划外 S2 会作废 active work order 与 pending epoch，只开启一个新 round。若已有 fix 尚未独立关闭，它会被标记为 superseded 并在新 source 上重新 RED/GREEN。若 S2 改坏历史 RED、receipt 或 artifact，自动恢复以 `STATE_EVIDENCE_INVALID` 失败，必须保留现场后 fresh `start`。source 漂移、配置漂移、旧 iteration、旧 gate 或不完整事务都 fail closed。

finding ledger 不是调用方可自由删改的摘要。controller 从不可变历史 receipt 与 transaction 顺序重放 open、fix 和 close 事件，并要求重建结果与当前 ledger 完全相等。`fix_claimed` 必须绑定一条真实失败的 RED command receipt 与一条不同 execution 的 GREEN command receipt；独立复核必须使用不同 actor 和 execution。command receipt 明确标注 `local_attestation_only_not_cryptographic_signature`，因此它约束字段、来源和因果链，不证明声明中的本地命令一定由外部独立主体真实执行。

`SOURCE-DRIFT-R…` 是 controller 专用 finding namespace。review receipt 试图占用该前缀会在 ledger 写入前以 `FINDING_EVENT_INVALID` 失败，避免后续真实 source drift 与用户提供 ID 碰撞。

## Source epoch v2

graph 原生 finding 在 review 时可以尚无 RED。修复阶段通过一个工作单内的三点纪元消除循环依赖：

```text
S0  review 时的完整 source map
 ↓  只改已有 test_*.py，保留 before 与 RED blob
Sr  RED source，RED command receipt 必须绑定此 SHA 且失败
 ↓  只改声明过的非测试实现文件，保留 Sr 与 S1 blob
S1  GREEN source，RED 测试逐字不变，GREEN receipt 必须绑定此 SHA 且通过
```

计划必须覆盖全部 open finding，并为每个 finding 指定一个精确 RED path 与 SHA。RED 与实现路径互斥；workflow、controller、gate producer、source manifest、受保护路径和计划外文件不能进入纪元。所有变化的 S0、Sr、S1 字节都保存在 state dir 并逐次重验。plan、任一 blob、live S1 或 finding/event 集合不匹配时，fix 不会进入 ledger。

当前 v2 保持 source file key set 不变，所以可在同一 run 内修改已有 `test_*.py`，不能新增、删除或重命名文件。需要新测试文件、修改 source manifest、workflow、controller 或 gate producer时，保留现场，更新控制面后从 fresh `start` 开始新 run。文档或任一发行源字节变化后，也必须重新 source freeze、eval 和 prove-stop。

`after_prepare` 崩溃且 live source 精确等于 S1 时，`resume` 只提交一次；若随后出现 S2，prepared fix 会归档为 aborted，原 finding 保持 open 并带入下一轮，不会把旧修复发布成成功。没有崩溃但 active work order 期间发生 S2 时也走同一换轮语义，不会永远卡在旧 nonce。独立复核必须在同一步关闭所有 open finding，否则 receipt 不提交，`next_step` 仍停在 `independent_recheck`。

## Review pair

P0 和 P1 结论只能由 `scripts/host_review_runner.py run-pair` 产生。公开 CLI 不接受 prompt、model、reasoning、cwd、sandbox、argv、source、输出目录或 Codex executable 覆盖；通用 `codex_exec_host.py run` 对 review 稳定拒绝 `FIXED_REVIEW_RUNNER_REQUIRED`。固定入口使用仓库根目录、`gpt-5.5`、high reasoning 与 read-only sandbox，并在运行前冻结 `review_source_identity.v1`。

两份由不同 Codex host receipts 派生的 attestations 必须同时满足：

* host run identity 不同
* Codex thread identity 不同
* raw artifact 路径和哈希不同
* model environment 完整
* review scope 与 producer 固定 scope 完全相等
* host receipt 路径与 SHA 不复用
* source identity 路径、哈希、权威 manifest 与逐文件哈希可重新核对
* source SHA、iteration 和 retained review bytes 全部匹配
* 模型 payload 是 `review_payload.v2`，每个 open finding 都有 finding ID、severity、summary、deterministic reproducer、actual、expected、`reproducible=true` 与 `status=open`

`adversarial_review` 与 `independent_recheck` 的 phase result 不能自报 reviewer、execution、哈希或 finding 摘要。controller 逐份重新派生 attestation，并要求 open event 是 host finding 的确定性投影。最终 `prove-stop` 必须使用 `independent_recheck` ledger 记录的同一对 attestation 路径与哈希，不能在停止门前换成另一对报告。

这是本地 attestation 一致性合同。reviewer ID 与 execution ID 由宿主观察的 run/thread 派生，不再由模型自由填写；它仍不证明审查实际由外部组织独立完成，也不是数字签名。拥有同一 UID 的操作者仍可整体重写本地源码与证据。九个 graph 前置阶段的 typed payload 同样属于本地 attestation；controller 亲自执行固定 preflight 与 `prove-stop` recipe，其他节点仍由外部执行和 receipt 驱动。

## 冻结评测执行

`run_evals.py --prepare` 同时冻结输入、invalid fixture、release evidence 与最小 runtime snapshot。snapshot 文件固定为 `0444`、目录固定为 `0555`，manifest schema 1.1.0 同时声明权限政策；每案前后核对文件集、目录集、权限与哈希。这样真实执行中的普通 Python import 无法在 snapshot 生成 `__pycache__`，而不是事后删除新增文件掩盖漂移。每个 case 启动前目录必须只有 `input.json`；host 将 envelope 中每一轮 exact input 逐字解包到只读 `.runtime/input-N.txt`，并按 case contract 预建唯一的 `.runtime/workspace-N`。模型只能填写这些 workspace，不得自建第二套 workspace、canonical artifact、receipt 或 `case-result.json`。固定 `host_eval_runner.py` 生成不可替换的 prompt，并把 prompt 控制文件和 Codex host receipt 写到 case 可写根之外。receipt 绑定模型、reasoning、sandbox、case cwd、输入、evaluation context、runtime snapshot、Codex thread events 与最后消息；`case-result.json` 只能由宿主 binder 派生。

模型退出后，binder 先复核 raw input 路径、精确字节与哈希，再使用 snapshot runtime 检查每个 workspace 已完成。标准、safety 与 versioned case 的内部 casefile 由 host 采用 create-or-verify 晋升到 canonical `artifacts/`，随后在 canonical 路径重新运行 validator，不能复制仍指向内部 workspace 的 receipt。translation 与 timeline 各有一个 passthrough workspace，由 host 执行并保留 `state.json`、`response.md` 与 validation receipt；invalid fixture 不创建 workflow workspace，由 host 使用 snapshot 中同一坏工件产生受检回执。safety 的 host terminal output 绑定已确认模板，workflow 3.1.0 的最终 `response.md` 与 `safety-response.md` 字节一致。Codex last message 只允许与 canonical 输出完全一致，或恰好少一个终止换行。

`run-suite` 只复用已经被独立审计为 valid 的 case。完整 host receipt 已落盘而 binder 尚未完成时，恢复流程重放原字节，不再次调用模型；执行结果不明时保持 `EVAL_OUTCOME_UNKNOWN`，不猜测成功。`run_evals.py` 最后从冻结输入重新执行 validator 与 renderer，并独立复核 raw input、固定 workspace 集、完成状态、内部与 canonical 字节、passthrough 或 invalid receipt、terminal output、18 个 case、16 个 casefile、逐案 host receipt 和互不复用的 execution identity。artifact discovery 忽略合法 `.runtime` 内部 casefile，但任何额外 workspace 或 canonical artifact 仍会 fail closed。

该边界可以阻止普通被评模型在 workspace-write case 目录内改写宿主证据，却不能抵抗拥有同一 UID 且能重写整个仓库与评测根的恶意操作者。host receipt 是宿主观察记录，不是密码学签名、可信时间戳或外部身份认证。

## Retained release basis

`prove-stop` 在任何测试前把权威 source、已审计 eval 和两份 review 复制到内容寻址的留存目录，并逐文件记录路径、大小和 SHA-256。每个后续步骤开始前重新核验。canonical install 只从留存 source 与留存 eval 构建，不从继续变化的 live tree 构建。

留存前的任何 source byte 漂移都会使旧 eval 或 gate 失效。留存后 live tree 可以变化，但最终 `STOP` 只证明 retained release basis，不证明 live tree 当前仍相同。`resume` 从 retained source 复核 workflow、source manifest 与历史 RED，因此 live tree 的普通 source、workflow 或 manifest 随后缺失，不会抹掉已完成状态。留存副本和本地哈希是 self-consistency evidence，不是供应商签名、可信时间戳或外部 CI attestation。

## 固定 STOP 门

producer 必须生成九项彼此独立、类型化且哈希绑定的 proof：

1. `p0_zero`
2. `reproducible_p1_zero`
3. `unit_tests`
4. `self_test`
5. `frozen_eval_18_of_18`
6. `artifacts_16_of_16`
7. `clean_install`
8. `verify_install`
9. `rollback`

缺文件、缺字段、字符串形式的 `"true"`、复用一个通用布尔文件、旧 source hash、旧 iteration、失配的 raw command receipt 或 source 漂移都不能产生 `STOP`。`prove-stop` 不接受调用方提供的任意命令列表；unit、self-test、eval replay、package、installed lifecycle、verify、rollback 与 restore 均来自固定 recipe。

## 进程族收口

固定 recipe 给子进程注入不可预测的精确环境 token，并只枚举同 UID 进程。macOS 通过 `KERN_PROCARGS2` 读取真实 environment，Linux 通过 `/proc/<pid>/environ` 读取；argv 文本、token 前缀和未继承 token 的同 UID 进程都不能命中。

超时后先处理原进程组，再对继承 token 的进程执行 stop、term、必要时 kill，并再次确认集合为空。枚举失败、环境读取失败、活着的非僵尸进程出现 `EINVAL`、`ps` 畸形或仍有成员时全部 fail closed。只有确认 PID 已消失或状态为 zombie 时可忽略；PID 在存活探针与状态查询之间正常退出也按已消失处理。

这个机制要求子进程合作式继承环境，边界是 `cooperative_inherited_token_not_os_sandbox`。它不约束任意外部 shell、不同 UID 进程或刻意清除 token 的程序。

## Rollback 的精确定义

发行门中的 rollback 是文件级验证：

1. 记录 canonical install 的 manifest 与哈希。
2. 把已安装 Skill 移出活动路径，不删除。
3. 在新的 Python 进程中只确认原活动路径不存在。
4. 原样恢复目录并核对 manifest。
5. 重新执行 installed lifecycle 与 `--verify`。

它不证明宿主已经停止发现缓存中的 Skill，也不撤回历史 workspace、模型上下文、云端记录或其他副本。

## 写入与操作边界

controller 自身只在候选仓库和显式允许根写入，拒绝仓库外路径、允许根外路径、符号链接逃逸和受保护路径。`.claude/`、`CLAUDE.md`、VP、HL、TP、已发布文案和投资决策始终受保护。`delete`、`push`、`publish` 始终拒绝。

guard 只约束 controller 和经它授权的提案，不是外部执行者的 OS sandbox。

## 回归入口

Round29 只证明最初 controller 骨架。后续 controller transaction、STOP authority、review attestation、source/eval/review retention、canonical install、fixed producer、进程族精确匹配、Darwin zombie 判定与退出竞态都有各自保留的红测。Round90 至 Round95 又固定了 finding ledger 确定性重放、typed command receipt、run-bound work order、phase-specific payload、S0→Sr→S1 source epoch、graph 原生 finding 写 RED、blob 篡改、计划外变化、工作单漂移换轮、未关闭 fix 失效历史、全 open finding 复核门、retained STOP 与 live source 解耦，以及崩溃恢复。Round97 至 Round101 由冻结 host eval 和回归反向打开复合故事分层、主体绑定、故事极性、预测、断言范围与来源所有权 RED。Round102 与 Round103 的两份独立盲矩阵首次共固定 78 个结构失败，Round104 与 Round105 的独立复审又固定 75 个全新失败，Round108 与 Round109 再固定 22 个来源和结构尾部失败。

Round112 至 Round122 继续关闭跨域安全、结构与来源盲点、纠正引语极性、passthrough 现实风险、否定分析路由与纯时间线逃逸。Round123 虽有 9 个真实失败，但隔离排除 glob 误扫历史材料，只能作为受污染复查。Round124 的新鲜盲测固定 4 个失败，Round125 再固定 4 个反噬；Round126 的新鲜盲测固定 3 个来源忠实性失败，Round127 固定 4 个安全主体和感受失败子例，Round128 的 6 个反向控制首跑全绿。Round129 在 4.0.1 的冻结 eval 第 18 案发现 quoted action span 与 update observation coverage 的内部矛盾，按 17/18 失败留档。Round130 的复审继续发现 quote-only update 死路，以 `attributed_statement` 关闭后又经三个全量反噬修正。

Round131 至 Round140 建立归属陈述与显式 legacy epoch；Round141 关闭材料或虚构载体、条件未来话语、Markdown 二手范围、非原话标签和混合格式任务逃逸；Round142 关闭多代 legacy 失效、epoch 注入、版本字符串洗白和历史 renderer 误标；Round143 升级到 Skill 4.3.0；Round144 关闭自造 hash-bound receipt；Round145 把 trust corpus 带入最小安装包；Round146 将迁移声明收窄到 corpus 确有实例的两个版本对。

Round147 至 Round151 关闭归属、passthrough、版本与开放语法尾部缺口，并升级到 Skill/validator 4.4.0。Round152 至 Round158 把 eval 与 review 身份改为宿主观察 receipt，修正 back edge、active-source producer binding、controller-owned preflight 和崩溃后的原字节恢复。Round159 至 Round167 加入固定 host eval runner、18 案 suite 编排、input-only case、模型与宿主证据写入隔离、路径与控制字符拒绝，以及哈希绑定 runtime snapshot。

Round168 至 Round173 关闭 review 控制面。Round168 固定双评审入口；Round169 要求 graph review phase 读取并重派生真实 attestation；Round170 禁止通用 host CLI 创建 release review；Round171 把 source identity 纳入 receipt、attestation 与留存；Round172 升级 `review_payload.v2` 并令 finding event 成为确定性投影；Round173 要求 `prove-stop` 沿用 independent-recheck 的同一评审血缘。相关单元测试使用 fake Codex fixture，只证明固定合同的接受与拒绝路径，不证明真实 provider、真实模型或外部 reviewer 已执行。

Round174 来自第一轮 4.4.0 真实 host eval，而不是 fake fixture。第一案成功完成 runtime workflow 后，模型用 `importlib` 读取 snapshot 中的 `casefile.py`，Python 在 snapshot 内生成 `scripts/__pycache__/casefile.cpython-314.pyc`。host runner 正确以 `RUNTIME_SNAPSHOT_FILE_SET_MISMATCH` 阻断 binder，整轮保持 0/18。两条 RED 分别固定“snapshot 权限仍可写”和“普通 import 会污染文件集”；最小修复只把 snapshot 文件和目录设为只读，并把权限与目录集加入逐案审计。失败 root 保留，不改写或清理。

Round175 至 Round183 来自第二次真实 host root 的三个完成执行和后续逐层审计。Round175 固定 exact raw input 与 workspace；Round176 固定 host canonical promotion；Round177 统一 safety 模板与最终响应；Round178 让 passthrough 必须经过 runtime；Round179 将 invalid fixture 纳入 snapshot；Round180 收紧终端输出到唯一允许的末尾换行差；Round181 让 auditor 独立重查 runtime workspace；Round182 消除同源 relation 的 last-write-wins；Round183 把真实模型漏掉的原子权限反证升级为 validator 可拒绝、repair loop 可纠正的确定性关系。九轮专项共 25/25。第二次 root 没有完整 machine report，且其余调用因 Codex 使用限额中止，因此只保留为 RED 来源，不得计分或续跑。

Round183 后的第一次完整回归产生两个 Round137 RED：新关系规则错误地重解释受信 4.0.1 工件及迁移后未改变的 legacy evidence。Round184 将严格单向关系派生限定为当前 profile 的新 evidence；legacy root 与 `legacy_epoch` 继续按 release-bound corpus 签入时的 profile 验证。修复没有改写任何历史 artifact、receipt 或 corpus。新关系专项与旧迁移专项各 3/3，随后完整回归 1004/1004。

当前开发态 fresh unittest 为 1004/1004，self-test 为 160/160。它们只证明当前本机确定性合同，不是 controller `STOP`。冻结 eval、双 review、安装与 rollback 仍必须来自最终冻结 source 的 fresh evidence，不能沿用历史静态计数。一次绿色矩阵仍必须接受新的独立复核，不能证明自然语言本体已经穷尽。任何相关源码或规则修改进入发行证据前，都必须重新运行全部必需测试、self-test、盲测、冻结 eval 与固定 `prove-stop` recipe。
