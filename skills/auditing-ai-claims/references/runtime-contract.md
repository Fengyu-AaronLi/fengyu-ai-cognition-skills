# Runtime contract

适用版本：3.1.0。

## 职责分工

模型负责：识别关键事实子句、审阅运行时发现的输入缺口、定义判准、判断来源角色、比较语义范围、提出状态和下一步。

运行时负责：冻结整段输入与候选绑定、抓取或导入来源、保存内容工件、生成回执、用事务日志恢复中断、定位原文、计算哈希、强制反证环节、执行硬门、给出下一安全转移、使旧 gate 失效、渲染固定报告和离线回放。

模型不得手工生成或修改来源回执。若回执需要改变，重新运行 `fetch` 或 `capture`，使用新的 `source_id`。

## 运行目录

```text
<run>/
├── .gitignore
├── .runtime-init.json
├── .runtime-key
├── .runtime.lock
├── input.txt
├── ledger.json
├── runtime-attestations.json
├── receipts/
├── artifacts/
├── source-transactions/
├── gate.json
├── report.md
├── state.json
└── events.jsonl
```

`ledger.json` 是语义账本。`receipts/` 和 `artifacts/` 是证据层。`.runtime-init.json` 冻结运行时版本和 audit ID；`.runtime-key` 是工作区私有 HMAC 密钥；`runtime-attestations.json` 保存运行时抓取回执的认证记录。`source-transactions/` 保存来源提交事务。`gate.json` 绑定当前输入、账本、attestation、事务、回执与工件哈希；`state.json` 另存 gate 和报告哈希，支持中断后恢复并检测二者被改。`.runtime.lock` 是同一工作区的协作式文件锁。`events.jsonl` 只是运行日志，不是防篡改审计链。

运行目录默认按私密材料处理。`input.txt` 保存用户原始输入，`report.md` 会复述主张、未知和来源信息；两者都可能含敏感内容。运行时不把 URL 查询参数原文写入回执，只保存查询部分的 SHA-256，但 URL 路径、证据正文和报告不会因此自动脱敏。

## 命令

| 命令 | 作用 |
|---|---|
| `doctor` | 显示版本和网络策略 |
| `start` | 一次完成 `init` 与正向 `scope`；Agent 主路径用 `--candidates-file`，受信本地人工可重复用 `--candidate` |
| `init` | 创建新运行目录并冻结输入哈希 |
| `scope` | 记录触发原因并首次冻结候选清单；冻结后不能覆盖 |
| `exclude-candidate` | 用 `--candidate-id` 将一个 `auto_gap` 明确归类为非事实内容，并保存非空理由和时间 |
| `add-claim` | 直接登记原子主张与判准；每条主张用一个 `--covers` 精确绑定冻结候选 |
| `claim` | 通过 `claim --file` 添加或显式替换结构化主张，仍须记录 `input_candidates` |
| `fetch` | 受控 GET，逐跳检查公开地址并保存运行时回执 |
| `capture` | 导入 caller-attested 外部文件；保留上下文，但不具备 hard confirm 或 refute 资格 |
| `retire-source` | 退役未连接的活动来源，保留回执、工件、原因和时间 |
| `abort-source-transaction` | 当精确重试已不可能时，把未提交事务关闭为 `aborted`，保留快照和原因，禁止复用 source ID |
| `link` | 把来源、证据用途、支持范围、推断跨度和保存正文中的精确引文连接到主张 |
| `quote` | 只定位保存文本中的短引文并输出选择器哈希，不修改账本 |
| `evidence` | 把已登记来源连接到指定主张 |
| `decide` | 直接更新三道门、状态、未知与下一步；`--unknown` 与 `--next-action` 必填 |
| `assess` | 更新三道门与拟议状态，不覆盖已连接证据；JSON 的 `unknowns` 至少含一条非空字符串，`next_action` 必须非空 |
| `countercheck` | 通过 JSON 文件记录可推翻条件、实际检查来源、反向结果和停止理由；时间与 basis hash 由运行时生成 |
| `summarize` | 用 `summarize --file` 在全部主张完成当前反证检查后写入跨主张未知与全局下一步 |
| `finish` | 先执行 `check`，仅在 PASS 时执行 `render`；应是最后一条改变完成状态的命令 |
| `check` | 执行结构、来源、日期、独立性、因果和风险门 |
| `render` | 只渲染与当前 bundle 匹配的 PASS gate |
| `replay` | 只读检查保存的历史完整性，不刷新当前事实 |
| `next` | 只读返回当前阶段和下一安全动作；每步提供静态 `cli_subcommand`、`required_inputs` 和稳定对象 ID，不输出可执行 shell 字符串 |
| `status` | 只读显示可恢复状态、gate 当前性和嵌入的 workflow 状态 |

## 退出码

退出码必须按具体命令解释，不能把任意命令的 0 都写成“整份审计已通过”。

| 情况 | 退出码 |
|---|---|
| 一般命令按其局部职责成功完成 | 0 |
| `check` 的当前 gate 为 PASS | 0 |
| `finish` 的当前 gate 为 PASS 且报告渲染成功 | 0 |
| `fetch` 保存的运行时抓取正文具备支持资格 | 0 |
| `replay` 的 `historical_integrity` 为 PASS | 0 |
| 运行时校验、完整性、policy 或抓取失败 | 1 |
| `check` 或 `finish` 的当前 gate 为 FAIL | 1 |
| `fetch` 失败或正文不具备支持资格，即使失败回执已保存 | 1 |
| `capture` 保存 caller-attested 工件与回执，但支持资格固定为 false | 1 |
| `replay` 的历史完整性为 FAIL | 1 |
| `status` 发现 gate stale、`gate.json` 哈希变化、已渲染报告缺失或报告哈希变化 | 1 |
| argparse 命令行用法错误 | 2 |

`replay` 返回 0 只表示保存的历史工件与记录通过其完整性检查，不表示今天的价格、法律、职位、产品能力或其他时效事实仍然成立。

## 快捷层与底层接口

普通对话审计优先把 `next` 当作循环控制器：

```text
start → next → 执行动作 → next → 执行动作 → … → finish → next
```

Agent 的主路径动作是 `claim --file`、`exclude-candidate --candidate-id`、`fetch`、`evidence --file`、`assess --file`、`countercheck --file`、`summarize --file`、修复 gate 或 `finish`。每次写入后重新调用 `next`，不要根据旧阶段继续猜。直接文本参数仅保留给受信本地人工便捷操作。

`next` 的阶段为：

| 阶段 | 含义 | 典型下一动作 |
|---|---|---|
| `claim_extraction` | 仍有未分类输入单元，或尚无原子主张 | 添加主张或明确排除非事实单元 |
| `claim_assessment` | 存在未完成最新证据判断的主张 | 研究后判断，或诚实记录未知 |
| `claim_countercheck` | 存在没有绑定当前主张、证据和 assessment 的反证记录 | 写 falsifier、实查来源、结果和停止理由 |
| `audit_summary` | 各主张已判断但跨主张摘要未冻结 | 写当前未知和最高信息增益动作 |
| `gate_repair` | 确定性结构或证据门失败 | 按错误修复；必要时退役未连接的失败来源 |
| `ready_to_finish` | 当前 bundle 已通过，但报告还未绑定 | 运行 `finish` |
| `complete` | 当前 PASS gate 与报告都绑定当前 bundle | 无写入动作 |
| `not_triggered` | 输入不属于外部事实审计 | 不生成审计报告，无写入动作 |

`next` 返回结构化数据字段，不拼接 shell 命令。每个动作包含静态 `cli_subcommand` 与 `required_inputs`；assessment 动作还列出 `claim_id` 和 `missing_evidence_purposes`。候选文本和主张文本始终是数据，不进入可执行字段。调用方用 schema 与模板准备 JSON 文件。`schemas/workflow-next.schema.json` 描述该输出契约。

## 整段输入覆盖与三分法

`start` 至少接收一个事实候选。Agent 必须使用 `--candidates-file`，其 JSON 顶层只能包含一个 `candidates` 数组；`--candidate` 仅保留给受信本地人工。两种接口互斥。每个声明候选必须是原始 `input.txt` 中只出现一次的精确子串；重复传入或在原文中出现多次都会在冻结前失败，调用方必须扩大候选上下文直到唯一定位，并创建新审计，不能手改 span。

运行时先冻结声明候选的字符区间，再对每个输入单元执行字符区间减法。声明候选只覆盖自己实际占用的区间，同一句剩余文字会成为 `auto_gap`，不能因为与声明片段相邻或部分重叠而消失。候选清单中的每项都记录：

- `candidate_id`：审计内稳定编号
- `text`：原文精确子串
- `origin`：调用方声明的 `declared`，或运行时发现的 `auto_gap`
- `sha256`：候选 UTF-8 文本哈希
- `spans`：原文中的 `{start, end}` 区间；`declared` 恰好一个，重复的自动补漏文本可以记录多个

`validate_workspace` 会用保存的 `input.txt` 重新计算候选区间。文本、哈希或区间对不上时，旧账本不能完成。候选清单首次写入后冻结；`scope` 不能覆盖它，需要改变清单时必须新建审计。

每个冻结候选在任一时刻必须且只能处于以下一种处置：

1. 仍在 `unreviewed_claims`，等待判断
2. 被至少一条原子主张的 `input_candidates` 覆盖
3. 进入 `excluded_candidates`，并记录 `candidate_id`、分类、非空理由和时间

这是一种处置分区，不是假设每个输入单元都是事实。只有 `origin: auto_gap` 的候选可以进入排除流程。显式声明为事实的 `declared` 候选不能再被改称观点或隐喻。自动补漏中的观点、隐喻、创意写作、个人感受、指令和关系动机可以排除；困难、争议大或暂时找不到来源的事实主张不能因此排除，只能进入账本并保留未知。

每条原子主张只能覆盖一个冻结候选，且 `claim.text` 必须是该候选中的精确连续子片段。若一个候选句包含多个事实，前面的拆分主张使用 `add-claim --keep-candidate-open` 保持候选待处理，最后一条拆分主张关闭它。这样允许一个复合候选拆成多条原子主张，但不允许一条主张吞掉多个候选，也不允许用无关的自由改写替换原文主张。

`quote` 是只读定位器。只有 `link` 或底层 `evidence` 会建立来源与主张的关系。对 `direct`、`partial` 或 `conflict`，`link` 必须用 `--exact` 从保存正文复现原文。

每条证据同时记录支持关系与 `evidence_purpose`。用途只允许：

- `substantive`：正文是否支持或冲突于主张内容
- `study_design`：研究设计能否承载因果推断
- `source_identity`：作者、标识、版本或来源身份
- `currentness`：来源日期和页面状态能否代表核验日

`direct`、`partial` 和 `conflict` 必须同时保存非空精确引文、定位器和 `support_scope`。支持范围要写证据实际覆盖的最窄对象、版本、日期、人群、指标和条件，不能只写“支持”或重复主张。

用途标签不能把上下文材料升级为实体证据，也不能替代 `support`、精确引文、支持范围和推断跨度。决定性状态还要满足用途隔离：

- `confirmed`、`partially_supported`、`refuted` 都需要直接的 `source_identity` 精确证据，才能把来源身份门标为通过
- 内容支持门只读取 `substantive`；身份、研究设计或当前性引文不能暗中兼任正文结论
- 高时效主张进入任一决定性状态都需要直接的 `currentness` 精确证据
- 因果主张进入 `confirmed`、`partially_supported` 或 `refuted`，都需要合格 `causal_basis` 和直接的 `study_design` 精确证据

`capture` 接受浏览器导出、受信本地副本或用户提供文件，但这些文件无法证明自身与所填 URL 的绑定。运行时把它们标为 `caller_attested_import_unverified` 和 `support_eligible: false`。可以保留为 `context` 或待补材料，不能据此通过 `confirmed`、`partially_supported` 或 `refuted` 的硬门。

来源登记时为 `active: true`。任何尚未连接主张的活动来源都可以使用 `retire-source` 记录退役原因和时间；常见恢复场景是失败抓取阻挡 gate。退役只把来源移出可用来源集合，不删除回执或工件，也不会抹掉失败发生过的事实。已连接来源不能退役，必须保留其对判断的影响。`next` 在 `gate_repair` 阶段列出可恢复的未连接失败来源。

证据缺失不阻止诚实完成。每条主张仍须经 `decide` 或 `assess`，状态只能停在 `unverifiable` 或 `current_unknown`，并明确未知和下一步。

每条当前 assessment 之后必须运行 `countercheck --file`。调用方只提供 `claim_id`、`falsifier`、`checked_source_ids`、`result` 和 `stop_reason`；`checked_at` 与 `basis_hash` 由运行时生成。结果值为 `no_conflict_found`、`conflict_found`、`scope_narrowed` 或 `inconclusive`。决定性状态必须至少实际检查一个活动且合格的来源；`conflict_found` 必须有绑定到被检查来源的 conflict 证据。范围缩窄要求先重新 assessment，再提交新的 countercheck，不能直接进入摘要。

`basis_hash` 绑定去除 countercheck 本身后的完整 claim、evidence 和 assessment。主张替换、证据新增、重评或被检查来源退役都会使旧记录失效，并把 `next` 路由回 `claim_countercheck`。`countercheck` 证明的是本轮反向动作已被记录，不证明所有可能反证都已穷尽，也不会把“没找到冲突”自动升级为 confirmed。

所有主张通过当前 countercheck 后，必须运行 `summarize --file`。单主张也不例外。它写入跨主张未知与全局下一步；没有剩余未知时也要保存明确的 none statement。

`finish` 是最后一条改变已触发审计完成状态的命令。`not_triggered` 只通过 `next` 返回路由结果；`finish` 和 `render` 都会拒绝为它生成 `report.md`。完成后可以运行不改写审计状态的 `next`、`status` 或 `replay`。任何后续输入、账本、回执或工件变化都会使旧 gate 和旧报告状态失效，循环会退回判断、汇总或 gate 修复阶段，完成后再次运行 `finish`。

`init`、`scope`、`claim`、`quote`、`evidence`、`assess`、`check` 与 `render` 是底层可组合接口，适合批处理、恢复和测试。两层写入同一种账本与回执，最终都必须由当前 PASS gate 绑定后才能渲染。

`unknowns` 和 `next_action` 不能依赖初始化默认值。每次状态判定都必须显式覆盖这两个字段，避免报告保留与本次证据不一致的旧未知或旧动作。

最终报告的来源回执表必须显示 `support_eligible`、获取方式和失败原因。失败抓取与 caller-attested 导入可以保留为运行轨迹，但必须标成不可用于支持，不能与合格的运行时抓取视觉等价。

## 网络、文件与隐私安全

`source_id` 必须匹配 `^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$`，并在一次审计内按 casefold 唯一，避免 macOS 默认大小写不敏感文件系统把 `S1` 与 `s1` 写到同一文件。`fetch` 与 `capture` 在联网或写文件前拒绝不安全 ID、大小写碰撞和已有 canonical 回执或工件；源工件采用只新建不覆盖写入。账本里的回执路径也必须精确等于 `receipts/<source_id>.json`。

`fetch` 只允许 HTTP 或 HTTPS 的 80、443 端口。它拒绝 URL 凭据、本机名、私网、回环、链路本地、保留地址和 IPv4 映射私网 IPv6；每次重定向只解析一次目标，并把下一跳连接固定到同一已检查地址。回执复验同时检查 redirect chain 每个 `from`、`to`、实际 pinned IP、相邻 hop IP 连续性及末跳与 `resolved_ip` 的一致性，不能只看首尾 URL。

抓取默认总时限为 20 秒，硬上限为 60 秒。这个总时限覆盖 DNS 后的连接、全部重定向和完整正文读取，不会因持续收到少量字节而无限续期。最多 5 次跳转，正文硬上限 5 MiB；CLI 只能降低这些限制，不能提高。解压后的正文同样受上限约束。

来源保存使用 `source-transactions/<source_id>.json` 的可恢复事务。正常生命周期依次为 `prepared`、`artifacts_saved`、`receipt_saved`、`attested`、`committed`。事务在获取元数据、回执快照和哈希确定后冻结；工件、回执、HMAC attestation 和账本分别以幂等方式提交。未进入 `committed` 或 `aborted` 的事务会让 gate 报 `SOURCE_TRANSACTION_INCOMPLETE`。用同一 source ID 和完全相同的来源元数据重试时，运行时会验证已有不可变工件并继续提交；元数据或回执快照不同则拒绝恢复，防止把半次抓取偷换成另一来源。

如果中断发生在工件完整落盘前，而远端响应已变化或无法再取得，精确重试可能不再可行。此时使用 `abort-source-transaction --source-id … --reason …` 将事务关闭为终态 `aborted`。运行时保留原始快照、可能已写入的工件或回执、终止时间和理由，只移除“事务尚未作出终局处置”这一 blocker。aborted source ID 永久不能复用；保存字节若与快照不一致仍会让 gate 失败。已进入账本的来源不能 abort，只能完成恢复后按来源生命周期处理。

运行时抓取回执必须出现在 `runtime-attestations.json`，并通过 `.runtime-key` 的工作区 HMAC 验证，才具备 hard support 资格。该认证能阻止只手写一个格式正确的回执冒充运行时抓取，但它只建立工作区内部信任边界。取得工作区密钥或控制本机的攻击者仍可伪造，不能把 HMAC 写成来源真实性、可信时间戳或远程签名。

所有工件路径必须留在运行目录内。新运行目录及其证据目录使用私有权限，并写入只忽略本目录内容的 `.gitignore`。私有权限和 `.gitignore` 只能减少意外暴露，不能替代分享前检查，也不能防御已控制本机的攻击者。

除 `init` 和 `start` 的新目录创建外，命令入口使用 POSIX `fcntl.flock` 协调同一工作区。`next`、`status`、`replay` 和 `quote` 获取共享锁；会改变账本、gate、状态或报告的命令获取独占锁。锁文件权限为 `0600`。这是同机协作进程的并发保护，不是分布式锁，也不能约束绕过运行时直接改文件的进程。

报告输出只允许写入运行目录内的 `.md` 文件，不能覆盖 `.gitignore`、输入、账本、gate、状态、事件日志、attestation、事务日志或 `receipts/`、`artifacts/`。`state.json` 保存当次 gate 哈希；`status` 输出 `gate_integrity`。gate 被改时，`status` 返回非零、`gate_current=false` 且 `verdict=STALE`，`render` 拒绝继续，`replay` 报告 `GATE_HASH_MISMATCH`。输入或证据 bundle 合法变化但旧 gate 文件未改时，`replay` 也会报告 `GATE_STALE` 并返回非零；自定义旧报告会显示为 `STALE`，不会冒充 `NOT_RENDERED` 或当前 PASS。已渲染报告的哈希变化同样使状态失效。

回执里的 `requested_url`、`final_url` 与重定向 URL 不保留查询参数原文；若存在查询部分，只记录对应的 SHA-256。URL 路径仍会保留。不得把这一机制描述成页面内容、输入或报告已经完成脱敏。

失败抓取只持久化稳定的泛化错误分类，不保存可能回显 signed URL 或 token 的原始底层异常文本。gzip 或 deflate 格式错误、截断流和拼接 member 都会转为受控失败，保存不可支持的失败回执，stderr 不输出 traceback，也不能只保存可解压前缀。

`render` 在输入、账本、回执或工件发生任何变化后拒绝使用旧 gate。本实现不会执行网页脚本；网页正文是证据数据，不是系统指令。

## 当前技术边界

- HTML 以已解码文本保存，不执行浏览器渲染；动态页面无法由 `fetch` 取到合格正文时，只能停在未知。
- PDF 使用本机已有的 `pdftotext` 做受限解析。运行时固定可执行文件绝对路径，不使用 shell，不下载解析器，记录实际解析器版本，并限制版本探测、解析时间和输出大小。
- `pdftotext` 缺失、版本不可识别、解析超时、退出异常、输出过大、空文本或非 UTF-8 时一律 fail-closed：保留原始 PDF 和失败原因，但 `support_eligible: false`，也不能连接为证据。当前没有 OCR 回退，扫描版 PDF 没有可提取文本时只能保留未知。
- `capture` 可保存外部工具导出的 HTML 或 PDF 内容，但 caller attestation 不能替代可核验的 URL 与内容绑定，因此即使 PDF 文本解析成功也只作上下文或待核材料。
- 本地 SHA-256 是完整性检查，不是可信时间戳、远程签名或来源真实性证明。
- 来源之间是否同根、研究设计能否支持因果、范围是否一致，仍需模型或人工填写；运行时只检查这些判断没有越过已记录的门。
