# Provenance

## Origin

`breaking-identity-labels` 于 2026-08-05 根据项目委托建立。Problem Spec、四个初始 baseline、十项输出契约和第一版 Skill 均在审阅上游 dbskill 之前独立完成并留有逐字记录。

第一轮复测后，用户明确把计划用途限定为公开非商业，并授权在许可证范围内借鉴 dontbesilent dbskill。本项目随后核对 CC BY-NC 4.0 和固定提交，先吸收两个通用判断方法。用户指出 V1 仍接近提示词后，又审计上游的工程结构，并以 clean-room 方式独立实现本项目的 Schema、CLI、状态机、policy gate、评测器和 demo builder。没有复制上游代码、内联案例、特色表达、七表结构、标题库或输出模板。

`human-writing-dbs-pipeline` 仅用于选择“骨架模式”、保留个人体感待补区和禁止代写完整逐字稿；没有调用 `dbs-*` 生成视频内容。

## dbskill attribution and modifications

- 上游作品：`dbskill`
- 作者：dontbesilent
- 原始仓库：[dontbesilent2025/dbskill](https://github.com/dontbesilent2025/dbskill)
- 审阅固定提交：[`8282f010964601070334dd7350973386abff6d2b`](https://github.com/dontbesilent2025/dbskill/tree/8282f010964601070334dd7350973386abff6d2b)
- 上游许可证：[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
- 修改说明：将商业概念拆解中的“回到具体使用、去掉概念再检查”改写为身份标签的内部去标签检查；将问题说明中的“未知、最小补充信息、现实反馈”改写为十项契约第 7 至第 9 项和高成本决定门。

| 审阅文件 | 采纳范围 | 未采纳范围 |
|---|---|---|
| [`skills/dbs-deconstruct/SKILL.md`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-deconstruct/SKILL.md) | 概念需要回到具体用法；去掉概念后检查还剩什么可观察内容 | 商业案例、特色表达、七张表、风格模仿 |
| [`skills/dbs-good-question/SKILL.md`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-good-question/SKILL.md) | 信息不足保持未知；优先找一条最小缺口；用现实反馈修正解释 | 评分体系、完整问题说明书、上游案例和原输出结构 |
| [`skills/dbs/SKILL.md`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs/SKILL.md) | 路由与叶子能力分离、交接契约显式化的仓库级模式 | 品牌、命令名、路由文案、固定收尾和商业 Skill 地图 |
| [`skills/dbs-content-system/`](https://github.com/dontbesilent2025/dbskill/tree/8282f010964601070334dd7350973386abff6d2b/skills/dbs-content-system) | 自包含工具、模板、阶段门、状态产物和独立 acceptance 的工程模式 | 目录名、模板正文、JavaScript 工具代码、内容单元字段和验收数量 |
| [`.github/workflows/ci.yml`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/.github/workflows/ci.yml) | 构建、契约检查和发行状态应分层验证 | workflow 代码、版本号、marketplace 配置和发布声明 |

许可证允许不等于方法适合。本项目明确拒绝 `dbs-action` 和 `dbs-diagnosis` 中从稀疏行为直接推断自卑、创伤、逃避、自欺或“真正原因”的规则。这些做法与本项目禁止不可验证心理原因、行为道德化和人格判决的边界冲突。

仓库当前使用 CC BY-NC 4.0。上游中引用或收录的第三方理论、案例和语料不因进入 dbskill 而自动获得同一许可，本项目没有再分发它们。本改编不表示 dontbesilent 认可或背书本项目。

## V2 clean-room implementation record

| 本项目文件 | 独立实现的功能 | 没有复制的内容 |
|---|---|---|
| `schemas/*.schema.json` | 身份案例、分析和事件的版本化数据契约 | 上游没有对应身份标签 schema |
| `scripts/identity_label_case.py` | 路由、来源跨度、跨字段策略、状态迁移、哈希回放和报告渲染 | 未复制任何上游脚本或函数 |
| `evals/run_v2_evals.py` | held-out 路由、六例回归及恶意注入的可执行评分 | 未采用上游 eval 案例或评分格式 |
| `scripts/build_demo.py` | 从固定输入和分析 fixture 重建 case、events、report 和 manifest | 未采用上游 demo 脚本或录屏资产 |
| `scripts/verify_demo.py` | 独立核验 demo 的当前代码绑定、制品哈希、validate 与 replay | 上游没有对应身份案例 verifier |
| `scripts/run_evolution.py`、`scripts/run_release_audits.py` | completed-run 快照、测试迁移、blocker 继承与关闭、四路文件化审计 | 未复制上游 CI、发布脚本、状态字段或审计案例 |
| `SOURCE_OF_TRUTH.md`、`docs/acceptance.md` | 权威顺序、阶段门和可复现验收 | 未复制上游文案、数量门或目录名 |
| `workflows/v2-evolution.yaml`、`workflows/v51-final-release.json`、`workflows/roles/` | 设计地图、可执行收敛 DAG、失败回流和发行门 | 未复制上游 workflow 或角色文本 |
| `scripts/run_regressions.py`、`scripts/verify_red_evidence.py`、`scripts/verify_evaluation.py` | manifest 闭世界回归、可迁移历史红证据、运行内评测复核 | 独立实现；旧红收据没有当时测试源码哈希，明确不声称历史源码字节已被绑定 |
| `scripts/run_release_audits.py`、`scripts/verify_package_equivalence.py`、audit receipt `1.2` | 逐命令输入快照、预登记语义交叉核对、安装链审计、目录/ZIP/安装副本树与 manifest 字节一致性 | 独立实现；本地哈希不等于签名或执行者身份证明 |
| `scripts/verify_live_retest.py`、`evals/live-retest-manifest.json` | 把冻结原题、当前逐字输出、独立复核、Skill、runtime 与 Problem Spec 绑定，并拒绝猜测模型标识或普遍化声明 | 独立实现；每题单次 Skill-aware 运行不能估计随机波动或临床效果 |
| R63 runtime 修复与 `tests/test_v63_adversarial_runtime.py` | 组合式识别明确即时安全事件；拦截未报告感受、动机、承诺和诊断确认；保留带自述标签的稳定偏好；失败初始化不触碰用户文件 | 独立实现；开放词汇安全识别仍不是临床风险评估，正则与组合规则仍可能漏判 |
| `scripts/verify_live_e2e.py`、两份 live E2E Schema 与 R64 evidence manifest | 重放模型 analysis 进入当前 runtime 后的 scaffold、compile、validate、render，并逐字比较中间制品与交付 | 独立实现；任务句柄和本地哈希不认证模型身份、内部推理或宿主日志 |
| `scripts/verify_baseline_evidence.py`、baseline manifest 与 Schema | 固定四题基线原文、环境披露、评分规则、报告和哈希对应关系 | 独立实现；只证明当前保存字节与冻结清单相符，不证明运行先后、执行者身份或因果改进 |
| `workflows/v65-final-release.json` | 将基线完整性、manifest 回归、离线评测、runtime 端到端样本、demo、包安装与等价性串成一个可重放 DAG | 独立实现；完成本地 DAG 不等于第三方审计、临床有效或公开发行 |
| `workflows/v68-final-release.json`、`evals/regression-dependency-manifest.json` | 在 V65 历史链之上绑定测试真正读取的稳定非测试依赖，并把 Skill 与候选仓库两级输入展开进命令收据 | 独立实现；依赖清单仍需随新增文件读取持续审计，本地哈希不认证执行者身份 |
| R66 runtime、状态与安装修复及三份 `tests/test_v66_*.py` | 组合跨句即时风险；拦截诊断排除、撤销、痊愈、占位符越界动机与承诺；保护混合输入中的真实偏好；缺锁零写入；安装目录保持不可变 | 独立实现；规则是保守边界，不是临床风险评估，也不证明所有自然语言变体均被覆盖 |
| `--text-file`、`--stdin`、`--observation-file`、`--rationale-file` 与拒绝覆盖输出 | 把不可信自由文本和 shell argv 隔离，避免入口注入及静默覆盖 | 独立实现；仍要求调用方不要使用 `eval` 或拼接 shell 命令 |
| `schemas/workflow-next.schema.json`、`schemas/event-head.schema.json` | 只读下一步协议和尾部回退一致性检查 | 上游没有对应身份案例状态契约 |
| R69 至 R72 语义与证据闭包 | 非当前材料、作用域语言、语义 fuzz、源码依赖、demo 与 live 证据分离，以及工作流终态约束 | 独立红灯、最小修复和回归；本地固定样本不支持普遍模型结论 |
| R73 至 R75 演化与操作者闭环 | 候选绑定 blindspot discovery、历史回放与 fresh candidate 双证据层、冻结包导出、release-state blocker 记忆、公开工作单、文件化确认和安装后完整持久生命周期 | 独立实现；任务标识、本地哈希与确认文件都不是执行者身份或真实同意的认证 |
| R76 红证据迁移链 | 对同一路径历史测试哈希要求连续 migration receipt、当前 head、语义字段、替代测试和证据全部可验证，同时原始红证据始终匹配当前字节 | 独立实现；迁移链只解释测试字节演化，不能改写历史失败事实 |
| R77 至 R78 发现循环 | 将引文、术语定义、非个人身份概念排除出个人拆解，并要求每个发现策略生成 nonce 外仍不同的候选探针 | 独立实现；确定性探针发现不是自然语言空间的穷尽证明 |
| R79 工作流红证据快照 | 让 evolution controller 在保留 evidence 当前精确哈希的同时，理解 receipt-backed 历史测试哈希，并把迁移链实际读取的当前文件纳入命令收据 | 独立实现；输入快照证明本地读取字节，不是数字签名或历史执行认证 |
| R80 双账本依赖闭包 | 将 raw red evidence 作为稳定非测试输入闭包，同时把 test modules 及其迁移历史留在 test-generation manifest，避免同一测试字节被两个清单重复治理 | 独立实现；本地闭包证明当前文件集合与哈希一致，不认证历史执行者或失败发生顺序 |
| `workflows/v78-final-release.json` 与 fresh candidate E2E | 在闭世界回归前运行候选绑定发现，分别验证 historical replay 和四个独立 runner 的 fresh composition，再进入完整持久安装 smoke 与冻结导出 | 独立实现；每题一次、Skill-aware、未认证宿主日志的样本不证明跨模型效果或临床有效性 |

本地架构审计还参考了现有工作区的 `spec-driven-workflow`、`decision-logger` 和 `autoresearch-agent`，分别用于理解结构化规范、append-only 记录和单变量实验生命周期。这里只借鉴通用工程模式，没有复制其代码、模板或领域术语。

## Private local inputs

以下 Vault 文件仅做只读问题发现、产品边界和视频入口判断，不随候选 Skill 再分发：

| 本地文件 | 本项目用途 | 明确边界 |
|---|---|---|
| `50-深度思考/54-商业思考/AI时代认知更新者-开源Skill内容与变现系统-2026-08-03.md` | 确认原创 Skill 项目的产品角色和候选仓库 | 不是心理学证据，不作为已开源或已发行证明 |
| `10-自媒体/13-选题库/TP-036-你用身份标签把自己锁进去了.md` | 收集“身份标签变判决”的内容假设 | 文件信号为未验证，不采纳强因果表述 |
| `10-自媒体/13-选题库/TP-037-你的自我认知其实是一份判决书.md` | 提取从身份句改为观察句的问题表述 | 不复制文案，不创建或修改 TP |
| `10-自媒体/13-选题库/TP-042-你学的心理学全用来定自己的罪.md` | 确认心理学术语可能被当作自我定罪工具的风险 | 不把心理学或治疗整体描述为有害 |
| `10-自媒体/13-选题库/TP-021-越懂心理学越走不出来.md` | 确认“高敏感”入口已重复使用，应换 AI 对话场景 | 不采纳其中未经验证的因果断言 |
| `10-自媒体/14-数据复盘/小红书数据_2026-03-04_深度复盘.md` | 确认身份认同入口在历史账号数据中有效 | 只用于视频入口，不外推心理机制或未来流量 |
| `10-自媒体/13-选题库/选题批次-2026-06-28-AI认知弹药批.md` | 核对“AI 记住的只是输入材料”这一内部内容假设 | 不是 AI 记忆或个性化的实证研究 |

关键词检索还覆盖“身份标签、自我认知、高敏感、回避型、MBTI、AI 记忆、个性化”。重复迁移副本、已发布文案和观点卡片只用于确认重复度，未修改、未摘录进项目。

## External evidence

| 来源 | 支持本项目的范围 | 不支持的结论 |
|---|---|---|
| [Fleeson, 2001, DOI 10.1037/0022-3514.80.6.1011](https://doi.org/10.1037/0022-3514.80.6.1011) | 同一个人的人格相关行为可随情境变化，同时个人分布中心可相对稳定 | 不能证明标签都是假的，不能证明换情境就能改变一切 |
| [Bleidorn et al., 2022, PMID 35834197](https://pubmed.ncbi.nlm.nih.gov/35834197/) | 预注册纵向元分析支持成人个体差异相对稳定且仍会随生命历程变化 | 西方样本过度代表，不能推断某个用户 |
| [The Myers-Briggs Company, MBTI scope](https://www.themyersbriggs.com/en-US/Explore-Solutions/MBTI) | 量表发布方自身把 MBTI 界定为偏好而非技能或能力 | 发布方有商业利益，不能单独证明该工具的科学效度 |
| [Fraley et al., 2011, DOI 10.1037/a0022898](https://doi.org/10.1037/a0022898) | 成人依恋表征可能因关系对象而异 | 不能根据两天不回消息诊断个人，也不能解释其动机 |
| [Sims et al., 2021, systematic scoping review](https://pmc.ncbi.nlm.nih.gov/articles/PMC8727520/) | 正式诊断标签的影响可能正面、负面或混合，并受人和环境影响 | 不能推出标签必然固化行为，也不能直接外推社交媒体标签 |
| [NICE NG87](https://www.nice.org.uk/guidance/ng87/chapter/recommendations) 与 [NIMH ADHD guide](https://www.nimh.nih.gov/health/publications/attention-deficit-hyperactivity-disorder-what-you-need-to-know) | ADHD 诊断需要专业综合评估，诊断与治疗边界应由专业人员保留 | AI 不能撤销诊断、替代评估或调整医疗方案 |
| [Sharma et al., ICLR 2024](https://proceedings.iclr.cc/paper_files/paper/2024/hash/0105f7972202c1d4fb817da9f21a9663-Abstract-Conference.html) | 多个 AI 助手在开放任务中表现出迎合用户观点的风险 | 不能证明每个模型或每次个性化都会迎合 |
| [Cheng et al., Science 2026, PMID 41886588](https://pubmed.ncbi.nlm.nih.gov/41886588/) | 预注册实验支持迎合式互动可能降低短期责任承担与冲突修复意愿 | 不能证明长期人格或依恋模式被固化 |
| [Fang et al., ACL 2026](https://aclanthology.org/2026.acl-short.43/) | 在研究设定中，加入用户画像会改变多个模型的情绪推理结果 | 研究没有测试本 Skill 的身份标签，不能直接外推所有 AI 记忆 |
| [WHO Suicide Q&A](https://www.who.int/news-room/questions-and-answers/item/suicide) 与 [NIMH 5 Action Steps](https://www.nimh.nih.gov/health/publications/5-action-steps-help-someone-having-thoughts-suicide) | 立即危险时联系现实急救或危机支持、联系可信任的人并减少接触高致命性手段 | 不能由 CLI 完成个案风险评估、治疗或安全保证 |
| [NSW Poisons Information Centre](https://www.poisonsinfo.nsw.gov.au/first-aid-for-poisoning/) 与 [Healthdirect](https://www.healthdirect.gov.au/swallowed-substances) | 吞咽、吸入或眼部毒物暴露后联系现实急救或毒物信息中心，保留产品信息，不自行催吐，并只在安全时离开暴露区域 | 不能由 CLI 判断毒性、风险等级、症状或个案结局；澳大利亚号码不能直接外推其他地区 |

## Causal language policy

项目只使用“可能强化”“存在越级推断风险”“本次输出出现了”等范围受限表述。没有来源支持“告诉 AI 一个标签必然造成行为固化”或“标签必然决定行为”，因此这些句子不进入 Skill、README 或视频骨架。

## Release status

本项目版本为 `2.0.0-alpha.7`。当前字节是否达到本地候选门槛，只能由源码仓库中的 `python3 scripts/run_evolution.py check --strict-release` 实时判定；本文件、测试通过或某次历史收据都不能自行证明该状态。无论本地门结果如何，它仍是候选仓库中的未提交、未 push、未发布版本，计划采用非商业源码开放方向，也不构成已有安装量、普遍效果或临床有效性的声明。
