# V2 Evolution Log

本文件用于逐轮追加真实演进证据。每轮必须在执行前写清输入和门槛，执行后再填写失败、修改与复测。不得回写覆盖历史轮次，不得把计划项标成已完成。

## 记录模板

### 轮次

- 轮次编号：`<待填写>`
- DAG 节点：`<Runtime / Adversarial / Clinical / Refinement / Forward / Release>`
- 执行角色：`<待填写>`
- 开始时间：`<待填写，含时区>`
- 结束时间：`<待填写，含时区>`

### 输入

- 实现版本或文件哈希：`<待填写>`
- 测试或案例集版本：`<待填写>`
- 上一轮未关闭项：`<待填写；没有则写“无”>`
- 允许修改范围：`<待填写>`
- 执行环境：`<待填写>`

### 门槛

- 预先声明的通过条件：`<待填写>`
- 阻断条件：`<待填写>`
- 本轮不评估的范围：`<待填写>`

### 失败

| 编号 | 输入或操作 | 预期 | 实际 | 退出码 | 证据路径 | 严重度 | 状态 |
|---|---|---|---|---:|---|---|---|
| `<待填写>` | `<待填写>` | `<待填写>` | `<待填写>` | `<待填写>` | `<待填写>` | `<待填写>` | `<open / closed / invalid>` |

### 修改

| 失败编号 | 修改文件 | 修改目的 | 范围说明 | 是否新增行为 |
|---|---|---|---|---|
| `<待填写>` | `<待填写>` | `<待填写>` | `<待填写>` | `<是 / 否>` |

### 复测

- 复测命令：`<待填写>`
- 复测时间：`<待填写，含时区>`
- 退出码：`<待填写>`
- 通过数：`<待填写>`
- 失败数：`<待填写>`
- 原始输出路径：`<待填写>`
- 相邻变体结果：`<待填写>`

### 退出条件

- 本轮判定：`<candidate / blocked / invalid_run / 继续迭代>`
- 已满足条件：`<待填写>`
- 未满足条件：`<待填写>`
- 下一节点或下一轮入口：`<待填写>`
- 判定人：`<待填写>`

## 已执行演进

以下记录只追加，不覆盖原始失败证据。时间统一按证据文件中的 UTC 或 AEST 记录；未调用在线模型的轮次均明确标注为离线确定性运行。

### R0：提示词包架构红灯

- DAG 节点：Runtime
- 日期：2026-08-05
- 输入：V1 文档型 Skill 与预先冻结的 V2 架构测试
- 门槛：必须存在可执行 CLI、Schema、状态、回放、可重建 demo 与运行时验收
- 结果：`15/15` 失败，退出码 `1`
- 直接失败：`scripts/identity_label_case.py` 不存在，九项运行资产缺失；旧校验器只能校验静态短语与固定哈希
- 证据：`evals/architecture-red.md`
- 判定：`继续迭代`

本轮把用户关于“这只是提示词”的批评变成可执行红灯，没有用扩写 `SKILL.md` 伪装升级。

### R1：运行时、状态机与第一轮边界攻击

- DAG 节点：Runtime → Adversarial → Clinical
- 日期：2026-08-05 至 2026-08-06
- 输入：V2 CLI、五个 Schema、追加式事件日志、独立 head、十项渲染契约
- 门槛：策略门、状态迁移、回放和临床边界均不得出现 blocker
- 初次临床结果：13 案中 6 个 blocker
- 暴露问题：疑似诊断升格、量表升格、严重功能受损被偏好路由吞掉、换药请求状态不一致、安全分支缺少现实动作
- 证据：`evals/raw/v2-forward/clinical/clinical-boundary-review.md`
- 修改机制：诊断来源枚举、功能受损优先级、医疗动作硬门、安全渲染动作、追加式证据与迁移校验
- 复测证据：`evals/raw/v2-forward/clinical/retest/clinical-boundary-retest-report.md`
- 判定：`candidate`，进入陌生输入前向测试

### R2：第一轮陌生前向、策略变异与状态攻击

- DAG 节点：Forward
- 日期：2026-08-06
- 冻结输入：5 个陌生场景、32 个策略变异、2 个状态一致性最小复现
- 门槛：陌生路由、策略注入、状态回放三组均无 blocker
- 结果：陌生场景 3 个 blocker；策略变异 27 个 blocker、2 个 nonblocker、3 个 pass；状态攻击 2 个 blocker
- 暴露问题：危险请求在策略门之前停住、来源可伪造、标签可伪装成行为、正面换标签可逃逸、重哈希后可改写历史 evidence
- 证据：
  - `evals/raw/v2-forward/fresh-final/forward-report.md`
  - `evals/raw/v2-forward/policy-mutation-final/mutation-report.md`
  - `evals/raw/v2-forward/state-integrity-final/audit-report.md`
- 修改机制：局部来源复核、Unicode 归一化、生成文本策略扫描、严格 evidence 前缀、事件相邻差分、head 与物化状态一致性
- 判定：`继续迭代`

### R3：开放词表与表达族第一次泛化

- DAG 节点：Refinement → Forward
- 开始时间：2026-08-06T03:10:01Z
- 冻结哈希：runtime `f5d96725b5ff3468ef444c9c70079229a6451ebded67054a5af830bd3dc92f93`；SKILL `e5f548ef31bf7ce8d6160bf873e38d473c376dc6243e24b53948162748e186a4`
- 已知闭环：47 项中 45 PASS、2 个沿用 nonblocker，115 条命令
- 新鲜盲测：10 案中 7 个 blocker
- 临床相邻审计：新增 5 个 blocker，另有 1 个偏好缺口
- 暴露问题：任意诊断名、任意量表名、桥边与药物即时危险、治疗暂停、稳定偏好、正面身份替换仍依赖有限表达
- 证据：
  - `evals/raw/v2-forward/final-regression-retest-v3/report.md`
  - `evals/raw/v2-forward/fresh-final-v3/forward-report.md`
  - `evals/raw/v2-forward/clinical/final-current-v3/clinical-final-report.md`
- 修改机制：开放标签形状、正式诊断与命名量表捕获、治疗变更表达族、高处与药物危险表达族、正面身份替换门
- 复测：63 项单元测试全绿，离线 38 例宏 F1 与模式准确率均为 1.0
- 判定：`candidate`，必须再次盲测

### R4：上下文作用域失败

- DAG 节点：Forward → Clinical
- 开始时间：2026-08-06T03:30:57Z
- 冻结哈希：runtime `575f6deda405ce976bda50aa960775fb883a6de59be0692748e124188e0ffd51`；SKILL `e5f548ef31bf7ce8d6160bf873e38d473c376dc6243e24b53948162748e186a4`
- 已知闭环：66 项中 63 PASS、2 个沿用 nonblocker、1 blocker
- 新鲜盲测：16 个无状态案例仅 3 PASS、13 blocker；另有 1 个提前 review 生命周期 blocker；4/6 负向控制误报
- 临床审计：34 案；历史 24 案通过，新相邻 10 案中 8 blocker、1 nonblocker、1 PASS
- 关键根因：整段正则不能区分“谁说的、说的是谁、现在还是历史、现实还是引用、用户请求还是教学例子”
- 证据：
  - `evals/raw/v2-forward/final-regression-retest-v4/report.md`
  - `evals/raw/v2-forward/fresh-final-v4/forward-report.md`
  - `evals/raw/v2-forward/clinical/final-current-v4/clinical-final-report.md`
- 判定：`blocked`，不得进入发行审计

### R5：作用域机制与写入闸门

- DAG 节点：Refinement → Forward
- 日期：2026-08-06 AEST
- 红灯 1：把 R4 缺陷冻结为 5 组机制测试和 1 个生命周期闸门，首次运行出现 21 个失败断言
- 机制修改：
  - 新增带偏移量的句段作用域，区分 direct、third-party、document、education、fiction、news 与 historical
  - 标签来源绑定局部归因主语，区分“我把自己叫作”和“系统、同事把我称为”
  - 正式诊断与命名量表从开放语法提取，不再只靠病名白名单
  - 安全与医疗路由共享作用域分析；渲染复用同一安全特征，不再重新扫描整段原文
  - 判决谓词与裸连接词分离；稳定偏好同时要求习惯、无功能损害与无改变目标
  - `review` 写命令与 `next` 共享实验完成计数；事件回放拒绝提前复核
- 红灯 2：第一轮转绿后，以 14 个未写入测试的新相邻探针攻击，7 个案例失败，覆盖 6 类机制缺口
- 第二次修改：补充软件型 AI、主管归因、自称、铁路危险、数值剂量问法、无损习惯偏好与“拆成可观察事实”请求
- 第二次复测：14/14 探针通过；34 个最终前向测试方法通过；全工作流 72 项测试通过
- 离线评测：38 例 trigger macro F1 `1.0`，mode accuracy `1.0`；13/13 临床边界、6/6 原始回归、13/13 策略注入通过
- 冻结哈希：runtime `d37906c99a9dd892f93dc616a6f3186a2054a6956c2dc00c5fbb72bfc2e86ddc`；SKILL `e5f548ef31bf7ce8d6160bf873e38d473c376dc6243e24b53948162748e186a4`；前向测试 `41bf597a4b0b2bbbe89d07637d5b4d1360cb3f887367750fc31f362130a9fb79`
- 当前判定：`candidate`，第五轮三组独立冻结审计进行中
- 未评估范围：真实临床效果、所有自然语言表达、在线模型行为、密码学真实性

### R5 冻结审计结论：候选被否决

- 已知失败闭环：131 项中 127 PASS、2 个沿用 nonblocker、2 blocker；459 条 CLI 命令
- 全新黑盒盲测：24 个未见输入，正负控制各 12；11 PASS、13 blocker；三任务生命周期与提前 review 闸门 PASS
- 临床与安全审计：50 案，含 16 个新相邻变体；38 PASS、10 blocker、2 个非阻断完整性缺口
- 主要失败族：当前致命风险漏报、影视与历史语境误报、已摄入和未摄入混淆、渲染凭空扩展危险手段、多来源归因丢失、任意量表与诊断内容截断、医疗和高成本决定漏拦截
- 证据：
  - `evals/raw/v2-forward/final-regression-retest-v5/manual-semantic-review.md`
  - `evals/raw/v2-forward/fresh-final-v5/report.md`
  - `evals/raw/v2-forward/clinical/final-current-v5/clinical-final-report.md`
- 判定：`blocked`。72 项旧测试全绿不能抵消新鲜输入中的安全与语义 blocker

### R6：成对作用域与证据保真红灯

- DAG 节点：Refinement
- 日期：2026-08-06 AEST
- 输入：将 R5 失败压缩为 13 个黑盒测试方法，每个高风险正例配历史、影视、引用或既定专业方案负对照
- 红测命令：`python3 -m unittest discover -s tests -p 'test_v6_adversarial_regressions.py' -v`
- 红测结果：13 个方法中出现 22 个失败断言和 1 个错误，退出码 `1`
- 覆盖机制：安全主体与时间作用域、危险手段忠实渲染、已摄入状态、铁路位置分离、量表结果与诊断限定逐字保留、多来源标签、显式拆解、医疗变更与不可逆财务决定
- 测试文件：`tests/test_v6_adversarial_regressions.py`
- 第一次机制修复后，5 组安全测试虽转绿，但 8 个未写入测试的相邻探针又暴露电影院误屏蔽、处方单片误报、刀具切水果和球棒比赛误报、无关手段渲染等问题
- 第二次红测将这些探针纳入同一测试文件；实现改为 `SafetyFinding` 与 `GroundedMeans` 事件级结构，route、risk flag 与 renderer 共用 `analyze_safety()`
- 来源侧取消三标签静默截断，增加开放词表归因框架、同标签不同来源保留、显式拆解正负意图和观察事实跨度
- 临床侧保存量表名称到结果末尾的连续逐字片段，并保留诊断紧邻括号限定
- 决策侧增加医疗/心理治疗领域分离、专业既定方案负对照和重大财务行动与纸面假设分离
- 旧回归复跑先出现 3 个安全漏报，再增加过量相对医嘱、片数与他伤动作组合；修复后全部关闭
- 当前结果：18/18 V6 机制测试、34/34 最终前向测试方法、全部旧单元与状态测试通过；38 例 held-out 宏 F1 与模式准确率均为 `1.0`
- 第六轮冻结哈希：runtime `e2b26b8f7ef102bf723b35e03083181a9ce0274c852e90fb8e0566c74f355338`；SKILL `e5f548ef31bf7ce8d6160bf873e38d473c376dc6243e24b53948162748e186a4`；V6 测试 `d11c349118685b779aa81db4cf1258768ecec90d07926f8629f87b05a8e51ff3`
- 当前判定：`candidate`，必须接受第六轮冻结后的全新盲测

### R7：开放事件、时限与现实动作审计

- DAG 节点：Clinical → Forward → Lifecycle
- 冻结 runtime：`e2b26b8f7ef102bf723b35e03083181a9ce0274c852e90fb8e0566c74f355338`
- 红测：17 个测试方法，27 failures、2 errors
- 暴露问题：当前危险被旧语境吞掉，未摄入与已暴露混淆，开放手段丢失，开放诊断与量表不完整，行为观察缺失，天数与小时不能阻止提前 review
- 证据：`evals/raw/v2-forward/v7-red/report.md`
- 修复方向：事件级安全状态、现实动作忠实渲染、开放临床框架、明确行为抽取、elapsed-time lifecycle
- 复测：`tests/test_v7_audit_regressions.py` 17/17 与 `tests/test_v7_release_matrix.py` 7/7 通过
- 判定：进入下一轮，不以旧回归通过结束

### R8：话语图、临床断言与时间完整性

- DAG 节点：Semantic → State
- 红测：20 个测试方法，79 个机制断言失败，0 个加载或 fixture 错误
- 暴露问题：话语主体、标签目标和来源没有形成可核对图；观察与反例跨度不完整；药物决定者与功能受损域混淆；安全事件和暴露方式作用域不稳；写命令时钟与 replay 时间绑定不完整
- 证据：`evals/raw/v2-forward/v8-red/report.md`
- 修复方向：identity claim graph、evidence role、clinical assertion、scoped safety event、所有入口 UTC 时钟与事件时间绑定
- 复测：V8 semantic 与 time integrity 套件全部通过，并继续进入独立相邻攻击
- 判定：进入下一轮

### R9：归因谓词、开放伤害事件与医疗决定者

- DAG 节点：Attribution → Clinical → Safety
- 冻结 runtime：`8dc62dd7084273e8cd22542ed687014ef01085dc7bfe926e7ab6ee7a4383cadd`
- 红测：归因 2 个方法出现 9 个失败断言；临床安全 5 个方法出现 8 个失败断言；exact audit 6 个方法出现 15 个失败断言
- 暴露问题：附近出现 `AI` 会覆盖真正说话者；翻译与记录材料泄漏；无具体手段的当前伤害意图漏检；已完成毒物暴露被症状门吞掉；非正式临床来源丢失；医生既定 medication holiday 被当成 AI 请求
- 证据：
  - `evals/raw/v2-forward/v9-red/report.md`
  - `evals/raw/v2-forward/v9-red/clinical-safety-report.md`
  - `evals/raw/v2-forward/v9-red/audit-exact-report.md`
- 修复方向：归因谓词绑定、材料话语保护、目标与手段共享事件、completed exposure、决定所有者事件
- 复测：V9 attribution、clinical safety 与 exact audit 共 13 个方法全部通过
- 判定：进入状态事务与发行完整性审计

### R10：显式归因事件、可恢复事务与完整测试发现

- DAG 节点：Attribution → Transaction → Release
- 冻结 runtime：`9e8cf1ff3cefebfe162399738c0e9cf8e618caead6357b1b8b76b8dc8c6f1d37`
- 红测：128 个预注册归因输入出现 90 个失败断言或子测试；事务 6/6 失败；release loop 6 个方法中 1 个结构失败；临床 P1 有 5 个失败；临床 P2 7/7 失败
- 暴露问题：字符串来源猜测没有显式 attribution event；写入缺少 read-transition-commit 同锁、完整 staging、journal rollback 与 expected revision；顶层 workflow 可能漏掉新测试代际；剂量与治疗请求、否定安全句、第三方诊断和非正式量表仍有缺口
- 证据：
  - `evals/raw/v2-forward/v10-red/attribution-state-release-report.md`
  - `evals/raw/v2-forward/v10-red/clinical-audit-report.md`
  - `evals/raw/v2-forward/v10-red/clinical-p2-report.md`
- 修复方向：显式 attribution event、事件语义校验、三文件事务提交与回滚、CAS revision、generic test discovery
- 复测：128 个预注册归因输入、事务 6/6、发行循环 6/6、临床 P1/P2 全部通过；随后独立 V11 盲审仍将本候选否决
- 判定：`blocked`，进入 V11

### R11：从语义修补升级为可恢复、可幂等、可否决的运行系统

- DAG 节点：Runtime → Semantic → State → Operations → Release
- 日期：2026-08-06 AEST
- 触发：V10 已有测试全绿，但独立盲审仍发现 P0 安全漏路由、P0 事务路径逃逸，以及 attribution、临床边界、幂等与发行证据链缺口
- 红灯证据：`evals/raw/v2-forward/v11-red/report.md`
- 冻结测试：blind semantic、state recovery、semantic validator、operation idempotency、operational CLI、evolution controller
- 机制修改：
  - 引用材料保护与命题级归因图，区分说话者、接收者、命题对象、谓词、否定和个人话语范围
  - 对保存后的 attribution event 重新从原证据解析，不只校验字符串跨度
  - 近期反复自伤与委托式医疗方案请求优先分流；临床事实、能力判决和稳定偏好继续分开
  - 事务 journal 的类型、文件名、真实路径、备份和 staging 全部约束在当前 case；未知文件不清理
  - 新增 `compile`、只读 `doctor`、显式 `recover`
  - 新增 `record --operation-id` exactly-once 语义及 replay 唯一性约束
  - 新增 executable evolution controller；五类制品漂移会使旧审计失效，strict release 要求四路独立审计绑定同一哈希且零 blocker
- 中间全量回归：236 个测试，234 通过、2 失败；失败均为新增文档换行契约和 demo/test manifest 哈希漂移，不是语义或状态回归
- 修复：补回安装包验证的连续命令标记，重建 deterministic demo，同步测试代际 manifest，并重新冻结 pending 审计状态
- 当前判定：`pending`；不得发行，必须在最终版本与 demo 哈希稳定后重新跑全量验证和四路独立盲审
- 未评估范围：真实临床效果、所有自然语言表达、跨模型表现、Windows 锁语义、外部签名真实性

### R54：发行证据闭包与可迁移红证据

- 独立审计暴露：历史 red receipt 绑定旧绝对路径；full regression 没有读取注册 manifest；package 验证没有把目录、ZIP 与安装副本字节纳入命令输入收据；独立 package audit 没有安装链
- 红灯证据：`evals/raw/v54-red/release-evidence-closure.md`
- 修复：历史路径改为 workflow 约束下的测试相对身份；runner 先做清单、哈希和磁盘集合闭世界校验，再精确加载注册模块；运行内 eval 增加独立结果复核；package 各形态成为后续命令的显式哈希输入
- package audit 新增 ZIP 安装、安装副本验证和目录/ZIP/安装副本等价脚本
- V54 复测：10/10 通过

### R55：审计输入篡改与 receipt 1.2

- 攻击：审计后修改预注册输入、删除输入快照、把当前 receipt 降格为无输入绑定格式
- 证据：`evals/raw/v55-red/audit-input-tamper.md`
- 修复：receipt `1.2` 对每条命令保存 script path/hash、受控环境和执行前排序输入快照；controller 在 record 与 strict check 时持续重算
- 兼容边界：`1.1` 只保留历史 fixture；当前 audit harness 只生成 `1.2`
- V55 复测：4/4 通过；篡改输入返回 `audit_receipt_input_hash_mismatch`

### R56：可执行 workflow 入口、最终 run 与四项审计

- 445 项 manifest 绑定全量首跑暴露两个收敛失败：旧 Make workflow 聚合器断言过期、SKILL 修改使 demo hash 按设计失效
- 旧测试通过语义 migration `evals/test-migrations/v56-workflow-entrypoint.json` 更新；保留的新契约要求 `make workflow` 调用当前 evolution DAG 与 manifest runner
- demo 从固定输入和 analysis fixture 重建，五事件 replay 通过
- 完整运行：`evals/runs/v56-final-001/`，workflow `breaking-identity-labels-v54-final-release`，15 个事件，状态 `complete`
- 四项 receipt 1.2 审计：归因 7 条命令、临床安全 8 条、状态完整性 10 条、发行包 10 条，全部零 blocker
- 严格门：`release_eligible: true`、`effective_decision: candidate`、`distribution_status: local_unpublished`、`publication_actions_performed: false`
- 冻结摘要：runtime `9db08df16b414b3a9945543464377e4f5da9d07788e3f4457fa430df86803b83`；package tree `b2266468273237bb56efa98241b9617fee5628dcb797a25e8a89e988c9eefda7`
- 未改变边界：没有 live model 验证、没有临床效果证明、没有数字签名、没有 commit、push 或发布

### R57：发行证明 fail-closed 与测试夹具闭包

- V56 后置攻击发现：strict gate 仍可接受旧 receipt `1.1`；哈希预登记没有与 receipt 的候选、completed run、命令及输入逐项交叉核对；测试树遗漏 `tests/fixtures/`；package equivalence 只比较 payload tree，不比较 manifest 字节
- 红灯证据：`evals/raw/v57-red/release-proof-fail-closed.md`
- 红测：8 项中 2 failures、6 errors
- 修复：当前发行路径强制 receipt `1.2`；打开并核对预登记；测试 manifest 和 candidate digest 纳入全部非代码 fixture；包 manifest 关闭未知字段；目录、ZIP 与安装副本必须同时共享 tree 和 manifest 哈希
- 旧 V11 正例通过语义 migration 升级到 receipt `1.2`
- 复测：8/8 通过；V11 6/6、V13 12/12、V54 10/10、V55 4/4 继续通过
- 判定：V56 冻结证据因候选字节改变而失效，必须重新运行最终 workflow 与审计

### R58：自由文本入口与拒绝覆盖

- 独立攻击证明文档示例把用户文本插入 shell 单引号，攻击字符串可以执行；`scaffold` 和 `render --out` 还能静默覆盖
- 红灯证据：`evals/raw/v58-red/safe-cli-ingress.md`
- 红测：5/5 失败
- 修复：新增 `--text-file`、`--stdin`、`--observation-file`、`--rationale-file`；用户文本使用有界 UTF-8 文件读取；输出以原子新建方式拒绝既有文件和 symlink；demo builder 也只使用文件入口
- 复测：5/5 通过；核心 case 15/15、workflow lifecycle 4/4、package 10/10 继续通过

### R59：当前 live 同题证据链

- 红灯：历史四例输出绑定旧 Skill 哈希，没有机制阻止新候选引用旧输出
- 证据：`evals/raw/v59-red/current-live-retest.md`
- 第一轮红测：7/7 失败，因为 current live verifier 不存在；加入 Problem Spec 漂移攻击后第二轮红测 8 项中 2 项失败
- 修复：新增 `scripts/verify_live_retest.py`，冻结四个原题、逐字输出、当前 Skill、runtime、Problem Spec 和独立 reviewer 结果；拒绝篡改、缺失检查、猜测模型标识与普遍化声明
- 实际运行：四个 fresh `fork_turns=none` runner 每个只读当前 `SKILL.md`；独立 reviewer 只读 Problem Spec 与四份 exact record，不读取 Skill 或历史结论
- 复核：4/4 `pass`，所有七类失败风险均为 false；机器 verifier 8/8 通过
- 限制：每题一次、Skill-aware、模型 ID 与推理档位未暴露，不能估计随机波动或声称跨模型、临床效果

### R60：blocker 关闭路径统一 current receipt

- 红灯：strict release 已拒绝 legacy receipt，但 `next-iteration --resolve-blocker` 仍可用 `1.1` 收据关闭 blocker
- 证据：`evals/raw/v60-red/blocker-resolution-current-receipt.md`
- 红测：新增攻击在 19 项运行中出现 1 failure，legacy receipt 返回成功并生成 complete successor
- 修复：blocker resolution 调用同一 current `1.2` 校验；V47 正例通过 `evals/test-migrations/v60-v47-current-blocker-resolution-receipt.json` 升级，绑定 script、input snapshot 与 preregistration
- 复测：V47 9/9、V60 10/10 通过
- 判定：候选仍未重新冻结，必须完成新 workflow、四项审计和后置攻击审查

### R61：代拟消息不得填补用户内在状态

- 触发：R59 独立 live review 指出 C02 可选消息写入“不是不在乎你”，但用户没有报告这一感受
- 红灯证据：`evals/raw/v61-red/unreported-message-content.md`
- 红测：1/1 失败，Skill 没有覆盖代拟消息里的未报告感受、动机或保证
- 修复：在不可越界规则中要求代拟消息使用条件句或占位符，直到用户确认内容属实；V61 单测 1/1 通过
- 因 Skill 哈希变化，R59 四例立即降为历史证据，没有回写。四题由新的隔离 runner 再跑，当前哈希 `29280a603148deb26cfb8bf1ceec0f4d42d4f0f4dc8bff072f6a0379114617bc`
- 新独立 reviewer 只读 Problem Spec 与四份 V61 exact record：4/4 pass，七类风险全部 false；C02 消息保留“若内容属实”条件和时间、渠道占位符
- 机器验证：current live manifest 绑定 Skill、runtime、Problem Spec、四份记录与 review，`valid: true`
- 非阻断限制：C02 的“明显上升”没有预设数值阈值，联系承诺必须由用户自行选择并确认可履行；每题仍只有一次 Skill-aware 运行
- 判定：进入完整 R61 workflow、冻结、四审计与最终后置攻击

### R62：源码验收与旧发行证明解除循环依赖

- 完整 run `evals/runs/v61-final-001/` 在 `full_regression` 真实失败并停止，477 项中 2 failures
- 一项失败来自 checked-in 离线结果仍绑定旧 runtime；先重跑 `evals/run_v2_evals.py`，38 held-out、13 clinical、6 original、13 policy 全部通过并更新当前绑定
- 第二项失败来自 `evals/validate.py` 要求上一个 frozen candidate 的 release gate 仍然 current，形成“新回归需要新冻结、新冻结又需要新回归”的循环依赖
- 红灯证据：`evals/raw/v62-red/source-validation-release-state-cycle.md`；定向红测 1/1 失败
- 修复：源码、demo、package 验收只要求旧发行状态仍是 `local_unpublished` 且没有 publication action；如果 gate 明确返回 `invalid_run` 与 `release_eligible: false`，报告为 `release gate non_current`，不复用为当前发行证明
- 严格发行资格仍只由重新 freeze 后的 `check --strict-release` 决定；源码验收不能把 non-current gate 说成 eligible
- 定向复测：V62 1/1、V2 acceptance 6/6 通过；测试 manifest 增至 81 个文件
- 判定：开始新的 V62 完整 run，不恢复或改写失败的 V61 run

### R63 至 R65：组合安全、真实 runtime 重放与基线完整性

- R63 把明确即时安全事件改为组合式事件识别，并继续阻止模型补写未报告的感受、动机、承诺或诊断确认；稳定偏好和第三方材料保持隔离。
- R64 首次保存独立 agent 产生的结构化 analysis，再由 runtime 执行 `scaffold → compile → validate → render`。后续候选只可把它称为 `historical_analysis_replay`，不得伪装成当前模型新运行。
- R65 为四题 baseline 增加逐字节 manifest、环境披露与评分绑定。该层只证明保存字节完整，不证明 Skill 导致改善。
- 复测入口：`tests/test_v63_adversarial_runtime.py`、`tests/test_v64_live_e2e_behavior.py`、`tests/test_v65_baseline_evidence.py`。

### R66 至 R68：运行边界、安装持久性与依赖闭世界

- R66 增加跨句安全、诊断排除与撤销边界、稳定偏好保护、锁缺失零写入和安装目录不可变契约。
- R67、R68 继续用开放词汇与依赖攻击检查 runtime；`evals/regression-dependency-manifest.json` 把测试实际读取的 Skill 与仓库级非测试文件纳入闭世界验证。
- `workflows/v68-final-release.json` 保留为兼容 predecessor，不再代表当前完成状态。

### R69 至 R72：作用域语言、语义 fuzz 与证据闭包

- 非当前材料、引用、第三方角色和用户本人描述继续分离；语义 fuzz 只接受来源与对象都可落回原文的判断。
- demo verifier、live evidence 和源码依赖分别设门，避免一个可见的 `PASS` 替代实际制品核验。
- R72 红证据 ledger 要求每条红测同时绑定测试与原始失败记录，工作流终态必须显式 complete 或 blocked，不能静默停在中间态。

### R73 至 R75：候选发现、双证据层与真实操作者生命周期

- R73 将 candidate-bound blindspot discovery 放在闭世界回归之前；历史 analysis replay 与 fresh current-candidate model/runtime sample 分开存储、分开验证。
- 新 root run 不能绕过 release state 中的开放 blocker；next iteration 继承 blocker；freeze 不能因省略参数清空 blocker；audit 与 freeze 使用一致锁顺序。
- 正式发行包只允许从已冻结 completed run 内的已验证 ZIP 导出，不能在 strict gate 后重新从活动源码构建。
- R74 增加公开 `target_id` 工作单；R75 将用户确认保存为精确文件字节，并绑定 pre-start case、revision 和 canonical experiment digest。该绑定不认证真人身份或真实同意。
- 安装 smoke 不只跑无状态链，还在 package 外部临时目录跑 `init → plan → start → record → review → replay → next`，并检查包树未被写入。

### R76：红测试迁移历史连续性

- 红灯：只允许当前测试哈希会让后续合法测试迁移抹掉早期红灯的可验证性；无条件接受旧哈希又会放过伪造历史。
- 证据：`evals/raw/v76-red/red-ledger-migration-history.md`。
- 修复：旧测试哈希只能通过同一路径连续 `from → to` receipt 链保留；当前 head、receipt 自身哈希、语义字段、替代测试和替代证据全部必须匹配。原始红证据文件仍始终要求当前字节精确哈希。
- 复测：`tests/test_v76_red_ledger_migration_history.py` 5/5；R72 红证据闭包 3/3。

### R77：非个人身份概念作用域

- 红灯：AI 引语、术语定义和 glossary 可能被误当成用户自述，触发人格拆解。
- 证据：`evals/raw/v77-red/discovery-scope-and-nonpersonal.md`。
- 修复：显式非个人身份作用域进入 transformation route，不生成当前用户 labels 或 judgments。
- 复测：`tests/test_v77_discovery_scope_and_nonpersonal.py` 3/3；9 个 discovery probes 9/9。

### R78：发现策略多样性与当前收敛轮

- 红灯：同一 strategy 的探针虽然 nonce 不同，去掉 nonce 后正文可能重复，形成虚假的“9 个不同探针”。
- 证据：`evals/raw/v78-red/discovery-strategy-diversity.md`，红测 2 项中 1 项失败。
- 修复：每个策略对 nonce-free 正文做归一化去重，确定性再生成直到满足唯一性；256 次仍失败才进入显式 fallback。
- 复测：`tests/test_v78_discovery_strategy_diversity.py` 2/2；R73 discovery 2/2；每个策略的 3 个正文均不同，9/9 probes 通过。
- 全量首轮又暴露四个真实语义回归：跨主体“夜猫子”、AI 摘要中的他伤误报、偏好后的能力判决归属、否定翻译语境后的当前自杀风险。最小修复后，归因、材料、安全、偏好和非个人作用域 47 个定向测试全部通过。
- 当前判定：`pending_final_convergence`。必须完成四个独立 fresh runner、独立 reviewer、v78 完整 workflow、全量回归、冻结、四项审计、strict gate 与冻结包导出后才能报告本地候选状态。

### R79：工作流输入快照理解测试迁移历史

- 红灯：独立 red-ledger verifier 已接受 receipt-backed 历史测试哈希，但 evolution controller 在生成命令输入快照时仍把 ledger 旧哈希直接与当前测试字节比较，导致真实 workflow 在 verifier 启动前失败。
- 证据：`evals/raw/v79-red/red-ledger-command-snapshot.md`；红测 1/1 error，错误码 `evolution_red_evidence_artifact_hash_mismatch`。
- 修复：controller 仍要求 evidence 当前字节精确匹配；对 test binding 则验证 `test-generation-manifest` 当前 head 与连续 migration history，并把当前测试、test manifest、迁移 schema、receipt、替代测试和 receipt evidence 全部纳入命令输入快照。
- 复测：`tests/test_v79_red_ledger_command_snapshot.py` 1/1、R76 5/5、R72 3/3；red ledger 21 records、45 artifacts 有效。

### R80：测试账本与非测试依赖闭包分离

- 红灯：完整回归 646 项中 1 项失败。依赖同步器把 red ledger 的 15 份新增 raw evidence 和 24 个 test modules 一起塞入非测试依赖清单，独立 inventory oracle 又完全没有读取 red ledger，因此报告 39 个 extra。
- 证据：`evals/raw/v80-red/red-dependency-ledger-separation.md`；新增红测确认 24 个 test modules 被重复登记。
- 修复：`evals/test-generation-manifest.json` 独占当前测试字节与迁移历史；`evals/red-evidence-manifest.json` 继续绑定 raw evidence 和产生红灯的测试历史；`evals/regression-dependency-manifest.json` 只收 red verifier 实际读取的 raw evidence，不再重复 test modules。
- 迁移：R68 独立 inventory test 通过 `evals/test-migrations/v80-v68-red-dependency-ledger-separation.json` 显式迁移，并由 R80 替代测试约束新边界。
- 定向复测：R68 10/10、R80 1/1、R76 5/5、R72 3/3、R79 1/1；red ledger 22 records、47 artifacts 有效；非测试依赖闭包 213 files 有效。
