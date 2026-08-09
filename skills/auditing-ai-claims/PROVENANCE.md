# Provenance

## 适用范围

本文件只覆盖 `skills/auditing-ai-claims/` 内的实现、评测和演示材料。它不替候选仓库中的其他 Skill 背书，也不改变其他目录的来源或许可状态。

## 当前状态

截至 2026 年 8 月 6 日，本项目是 V3.1 架构的本地候选工作台，发行门状态为 `NO-GO / local candidate`。

当前没有公开、没有 push、没有创建远程发行，也不声称已开源。候选源码拟按 CC BY-NC 4.0 提供，禁止商业用途。许可证文件存在不等于已经发行，也不等于 OSI 意义上的开源软件。

工程回归、安装试跑和演示都不能替代新鲜行为会话。C01 至 C16 的当前版本行为复测、语义盲评、独立来源复核以及安装后的正反自动发现尚未完成，因此任何文档都不得写成最终可发行状态。

## 直接产品来源

### 1. 项目所有者规格

2026 年 8 月 5 日至 6 日的用户任务说明直接定义了：

- 只审计原则上可核验的外部主张
- 原子主张账本的必需字段和五种状态
- 一手来源优先级
- 日期、证据范围、相关与因果、自述与独立证据边界
- 四个 baseline 和后续复测要求
- 不处理关系动机与个人感受
- 视频演示、零门槛入口和候选发行包
- Skill 必须从提示词升级为可执行 workflow，并通过 loop 多轮收敛
- 普通用户第一屏必须简明，后台证据仍需可回放

这些要求是本实现的主要产品规格。

### 2. 无 Skill baseline

四个隔离 baseline 在候选 `SKILL.md` 创建前运行。观察到的失败直接决定了初始规则：

| baseline 观察 | 进入本项目的约束 |
|---|---|
| 未核验书目信息被排成正式引用 | 来源打开门、身份用途和禁止补写引用 |
| 自报调查的样本边界从替代句消失 | 支持范围、研究设计与因果门 |
| 当前价格无日期确定作答 | 高时效识别、核验日期与当前未知 |
| 隐喻案例正确放行 | 选择性触发和非事实排除边界 |

原始逐字输出保存在 `evals/baseline/raw/`，运行条件保存在 `evals/baseline/run-manifest.json`。这些输出证明无 Skill 情况下实际发生过什么，不证明 V3 已经通过行为复测。

### 3. V3 与 V3.1 多轮工程迭代

用户指出早期实现仍像高级提示词后，本项目用红绿循环将以下能力写成独立可执行契约：

1. `start → next → … → complete` 的只读状态导航
2. 整段输入冻结、`auto_gap` 补漏和待处理、覆盖、排除三分法
3. 候选原文子串、字符区间和 SHA-256 的精确绑定与回放复验
4. 一个复合候选拆成多条原子主张，同时禁止一条主张吞掉多个候选
5. `source_identity`、`substantive`、`study_design`、`currentness` 的证据用途隔离
6. 相关性、自报、客观性能、因果设计、来源独立性和冲突的语义硬门
7. 抓取失败留下回执，未连接失败来源可带理由退休且不可删除轨迹
8. 可选本地 `pdftotext` 适配器，以及缺失、损坏、超时、空输出和超限时的 fail-closed
9. 既有工作区读共享锁、写排他锁的并发协调
10. 普通人六列首屏与技术账本分层
11. 只输出静态子命令、所需输入和稳定对象 ID 的 `next` 文件协议
12. assessment 后强制进入、并绑定当前 claim/evidence 状态的 countercheck
13. 覆盖重定向与正文读取的单一抓取总时限，以及调用方不能抬高的资源上限
14. 来源工件、回执、HMAC attestation 与账本之间的可恢复事务提交
15. 工作区回执认证、事务完整性和报告回放的确定性 gate

这些运行时、CLI、状态机、schema、回执、锁、PDF 适配器、字符选择器、bundle 哈希、错误代码、测试和固定渲染器均由本项目独立实现。没有复制 dontbesilent/dbskill 的代码、测试、案例、字段表、输出模板、目录编号或特色表达。

V3 与 V3.1 的 RED 和回归证据保存在 `evals/v3/` 与 `tests/`。准确的当次结果以 `evals/results.md` 为准，本文件不固化一个会随迭代变化的测试计数。

### 4. 私有项目材料

以下五份 Vault 文件按用户要求只读，用于理解项目定位、既有选题边界和观点一致性：

- `AI时代认知更新者-开源Skill内容与变现系统-2026-08-03.md`
- `TP-026-AI理直气壮地说错.md`
- `TP-031-AI为什么一本正经胡说.md`
- `VP-047-最惊艳的AI产品通常最垃圾.md`
- `VP-048-品味是AI时代唯一不可外包的能力.md`

它们不是外部事实证据，不随本包分发。本实现没有复制其中的正文、规则、示例、测试、特色句式或第三方素材。候选文件不包含 VP、TP、HL、已发布文案、客户资料、账户信息或私有知识库内容。

### 5. 开发流程 Skill

项目所有者指定使用 `writing-skills`、`test-driven-development`、`verification-before-completion` 和 `human-writing-dbs-pipeline`。后续迭代还采用 skill 创建规范与 workflow loop 思想。

这些 Skill 只治理开发顺序、红绿复测、完成前证据、入口边界和视频骨架，不是 `auditing-ai-claims` 的运行时依赖，其文字、模板和案例没有复制进候选发行包。

## 外部一手材料

下列材料于 2026 年 8 月 5 日初次打开，并在 2026 年 8 月 6 日的 V3 真实来源复验中再次打开。它们的时效性状态在实际发行或拍摄前仍需重新检查。

| 来源 | 在本项目中的证据角色 | 不能据此声称什么 |
|---|---|---|
| [OpenAI：Why language models hallucinate](https://openai.com/index/why-language-models-hallucinate/)及[原始预印本](https://arxiv.org/abs/2509.04664) | 公司一手说明与原始理论研究，支持先进模型仍会生成流畅错误，评测可能奖励猜测 | 不能证明某模型已消灭幻觉，不能证明引用本身导致用户误信；对自家模型的性能陈述不是独立验证 |
| [NIST AI RMF 页面](https://www.nist.gov/itl/ai-risk-management-framework)及 [AI RMF 1.0 PDF](https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.100-1.pdf) | 政府风险框架，支持按使用情境记录方法、不确定性、外部有效性和独立审查 | 不是特定产品认证，也不是法律合规证明 |
| [Microsoft Research 论文页](https://www.microsoft.com/en-us/research/publication/the-impact-of-generative-ai-on-critical-thinking-self-reported-reductions-in-cognitive-effort-and-confidence-effects-from-a-survey-of-knowledge-workers/)及 [CHI 2025 论文 PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/01/lee_2025_ai_critical_thinking_survey.pdf) | 原始调查研究，支持特定样本和自报实例中的相关性 | 不能证明 AI 导致人变笨、长期能力下降，或引用越多越容易误信 |

外部页面和论文没有打包进仓库，只保留必要链接与短转述。OpenAI、NIST、Microsoft、ACM 及论文作者没有为本 Skill 背书。

## 合成评测夹具

C01 中的论文题名、作者、Atlas-3 和 DOI 是故意构造的测试输入，用于观察模型会不会继续引用、补写细节或把假前提加工成正式成品。

DOI `10.1145/3765124.3768891` 在 2026 年 8 月 5 日经 resolver 返回 HTTP 404，历史记录见 `evals/baseline/doi-resolution.txt`。404 只说明该标识在核验日没有解析成功，不能写成任何相似论文永久不存在。公开视频前必须重新检查页面状态。

C02 基于 CHI 2025 论文的公开方法与摘要边界设计。测试输入是本项目自行撰写的转述，没有复制论文正文。

## 经许可参考的第三方 Skill

初版主张账本、来源层级、推断跨度、五种状态和 C01 至 C12 先在未打开 dbskill 上游文件的条件下完成。此后用户明确承诺拟公开源码且不作商业用途，并允许在遵守许可证和署名的前提下参考 dontbesilent/dbskill。

2026 年 8 月 5 日核对的上游版本固定为 commit `8282f010964601070334dd7350973386abff6d2b`：

- [上游 LICENSE](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/LICENSE)，CC BY-NC 4.0
- [`dbs-deconstruct/SKILL.md`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-deconstruct/SKILL.md)
- [`dbs-goal/SKILL.md`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-goal/SKILL.md)
- [`dbs-good-question/SKILL.md`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-good-question/SKILL.md)，只作对比审查
- [`dbs-diagnosis/SKILL.md`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-diagnosis/SKILL.md)，只作重叠审计
- [`dbs-content-system/`](https://github.com/dontbesilent2025/dbskill/tree/8282f010964601070334dd7350973386abff6d2b/skills/dbs-content-system)，只参考重型 Skill 的抽象产品形态
- [`dbs-skill-cleaner/`](https://github.com/dontbesilent2025/dbskill/tree/8282f010964601070334dd7350973386abff6d2b/skills/dbs-skill-cleaner)，只参考入口编排与执行层分离的抽象模式
- [`dbs-save/SKILL.md`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-save/SKILL.md)，只参考独立状态目录和恢复语义的抽象模式

实际进入本项目的许可参考范围只有抽象机制：

1. 检查关键结论词在当前主张中产生什么可观察差异
2. 为结论词补充成立条件与失败边界
3. 按阻塞性缺口调用测试，已经明确的内容不强制展开
4. 按风险和主张数量提供最短够用输出
5. 将入口编排、持久状态和执行工具分开

这些机制被重新实现为外部事实主张审计，并与整段输入冻结、来源回执、精确引文、证据用途、状态循环和 gate 结合。没有移植上游的维特根斯坦模式、事实核查规则、商业案例、奥派经济学判断、七表本体论、原输出模板或特色收尾表达。

署名、原许可链接、固定版本和修改说明同时记录在 `NOTICE.md`。候选包拟按 CC BY-NC 4.0 提供，不得用于商业目的。

CC BY-NC 4.0 没有 ShareAlike 条款。全仓采用相同许可是本项目自己的候选发行政策，不是上游强制要求。免费发布本身也不能证明用途必然非商业。任何收费交付、课程、广告变现、商业集成或商业获客前，都必须重新审计实际用途，并取得上游许可或移除改编机制。

原子主张、来源日期、相关与因果区分、证据范围、状态机、文件锁和 fail-closed 都是通用概念。本项目不宣称发明这些概念。

## 工程证据与行为证据分开

本项目保留三类不同证据，不能相互冒充：

| 证据 | 能证明什么 | 不能证明什么 |
|---|---|---|
| 单元与集成测试 | 当前代码在夹具中满足已编码契约 | 新鲜 Agent 会正确理解复杂来源 |
| 安装、doctor、fixture 与 replay | 文件复制、运行契约和历史完整性可工作 | Skill 会自动触发，或现实主张正确 |
| 新鲜行为与自动发现轨迹 | 看不到 Skill 开发上下文的 Agent 实际怎样触发、拆分、取证和输出 | 所有未来输入都不会失败 |

当前第三类证据尚未完成。一次行为 harness probe 在模型执行前遇到 Codex CLI usage limit，没有产生模型回答或审计目录。它只证明基础设施阻塞，既不计行为失败，也不能计 PASS。

## 发行前仍需完成

- 重跑 C01 至 C16 的完整新鲜行为会话
- 完成无 Skill、降级提示词和完整工作台三组消融
- 完成语义盲评与独立来源复核
- 在干净安装后记录正向自动发现的真实工具轨迹
- 记录纯观点、隐喻和创意文本的负向不触发轨迹
- 验证普通用户首屏和技术附录的分层体验
- 重新核验所有时效性示例与外部页面
- 由项目所有者另行决定是否公开、何时公开以及由谁 push

上述门完成前，准确表述只能是：`NO-GO / local candidate`。
