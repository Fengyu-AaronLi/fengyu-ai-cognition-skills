# 来源、许可与改写记录

## 适用范围

本文件覆盖 `skills/defining-problems-before-prompts/` 的需求来源、第三方方法、研究证据、修改范围、测试历史和发行边界。

本目录按 [`LICENSE`](LICENSE) 采用 CC BY-NC 4.0。由于 NonCommercial 限制，准确发行标签是“非商业源码开放候选”或 source-available，不是 OSI 意义上的 open source。

## 1. 项目所有者 brief

- 日期：2026-08-05。
- 内容：项目名称、核心命题、十二项 Problem Spec、四个冻结 baseline、压力类型、高风险边界、交付文件与禁止事项。
- 权利状态：项目所有者直接提供，用于本项目。
- 进入范围：冻结输入和产品要求直接来自 brief；运行时设计、Schema、测试、文档组织与具体实现由本项目完成。

项目所有者另行承诺只作非商业用途。该承诺是使用意图，不是第三方许可来源。对 dontbesilent 材料进行分享和改编的法律依据仍是上游固定版本采用的 CC BY-NC 4.0。

## 2. 私有 Vault 资产

开发按 brief 读取了五份私有 Vault 资料，包括发行策略、观点和选题资产。公开候选不列出这些文件的精确路径与标题，也不重新分发其全文。

这些资料用于确认三条内部需求：项目不能退化为 prompt 优化；答案与执行变便宜后，目标、成功标准和代价仍需由人承担；定义充分的任务必须放行。

相关私有观点自身把“问题消解”追溯到 dontbesilent 案例和维特根斯坦语言批判。本项目不把这一思想传统宣称为首创。

## 3. dontbesilent dbskill

- 作品：[`dontbesilent2025/dbskill`](https://github.com/dontbesilent2025/dbskill)
- 作者：dontbesilent
- 固定提交：[`8282f010964601070334dd7350973386abff6d2b`](https://github.com/dontbesilent2025/dbskill/tree/8282f010964601070334dd7350973386abff6d2b)
- 核对日期：2026-08-05
- 上游许可：[`CC BY-NC 4.0`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/LICENSE)
- 许可说明：[`Creative Commons BY-NC 4.0`](https://creativecommons.org/licenses/by-nc/4.0/)
- 背书状态：本项目与上游无隶属关系，不暗示 dontbesilent 认可、合作或背书。

重点核对文件：

- [`dbs-good-question`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-good-question/SKILL.md)
- [`dbs-goal`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-goal/SKILL.md)
- [`dbs-deconstruct`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-deconstruct/SKILL.md)
- [`dbs-diagnosis`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-diagnosis/SKILL.md)

明确借鉴并改写的部分：

1. Question 与 Problem 的区分。
2. 先钉可观察现象、找预期冲突、接现实反馈入口。
3. “语义做工”判断：一个词是否改变交付物、路径、验收或风险。
4. 问题消解的前提顺序：模糊概念、隐藏假设、逻辑关系、事实前提和信息充分性。
5. 信息不足时不装确定，只给少量关键问题和一个最小现实动作。

本项目的修改与新增：

1. 从商业诊断改写为职业、效率、产品和清楚执行任务的通用门控。
2. 新增 `execute`、`define`、`defer_to_user` 三模式。
3. 新增十二项 Problem Spec、typed decisive unknown、stable unknown ID 和 question-to-unknown coverage。
4. 新增辞职、AI 提效、AI App 和翻译四个冻结压力测试。
5. 新增确定性 routes、request envelope、gate receipt 和 exact request hash。
6. 新增 Python 标准库 CLI、三份 JSON Schema、精确 evidence span、validator、deterministic renderer、stable error code。
7. 新增 receipt recomputation and binding、结构化 next-test stop boundary、atomic state，以及用于 `resume` 的 file lock、revision compare-and-swap 和 idempotent replay。
8. 把核心边界拆成 progressive references；清楚任务不读取 Problem Spec playbook。
9. 新增 prompt-only 架构 RED、离线 100-repeat eval、fresh host regressions、独立语义审计和独立 code review。
10. 新增回答 evidence source、state-aware convergence、answer amendment、bounded rounds、terminal states，以及只能由终态后 fresh `decision_input` 记录的用户价值决定。
11. 新增 failure-driven evolution runtime：hash-chain ledger、manifest input-bound base RED/candidate GREEN/reproducer receipt、派生 state checkpoint、三角色声明分离、sealed holdout、promotion budget 和 saturation stop。
12. 新增 hash-bound suite manifest、OpenAI discovery metadata、explicit allowlist packager、父目录 symlink 防逃逸与 lean install bundle。

未复制的部分：上游商业公理、定价规则、标题库、推文案例原文、商业体检报告、Agent 可解性评分表、完整提示词流程、目录结构和测试代码均未进入本运行时。

## 4. Anthropic：Claude Code 与领域经验

- 来源：[`Agentic coding and persistent returns to expertise`](https://www.anthropic.com/research/claude-code-expertise)，2026-06-16。
- 实时核对：2026-08-06。
- 样本：官方页面和报告当前公开口径为 2025-10 至 2026-04 约 400,000 个 Claude Code 交互会话，来自约 235,000 人。
- 范围：CLI、Claude Code 桌面端和 claude.ai；排除 Anthropic 内部使用、第三方 IDE、SDK 和没有人工轮次的 headless 会话。
- 用途：窄范围支持“这些 agentic coding 会话中，人更多承担做什么、采取什么路径和什么算完成的规划判断；任务领域理解更强与更高会话成功率相关”。
- 限制：观察性研究，不证明精确定义问题导致成功；领域经验指标包含问题界定和验证行为；成功是会话级分类，不代表长期产品结果；不能外推到全部职业或全部 AI 使用。
- 许可处理：页面未标明允许把正文整体纳入本项目的开放内容许可，只作事实性释义和链接引用。

## 5. Anthropic：Agent eval 工程指南

- 来源：[`Demystifying evals for AI agents`](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)，2026-01-09。
- 实时核对：2026-08-06。
- 类型：工程实践指南，不是固定样本实验。
- 用途：指导同一输入复测、明确成功标准、同时覆盖触发与非触发、保存 transcript 与 outcome、隔离环境和人工检查。
- 限制：它支持 eval 方法，不证明本 Skill 的现实效果，也不证明人们普遍不会定义问题。
- 许可处理：页面未标明开放内容许可，只作事实性释义和链接引用。

## 6. Microsoft Research：GenAI 与批判思维

- 来源：[`The Impact of Generative AI on Critical Thinking`](https://www.microsoft.com/en-us/research/publication/the-impact-of-generative-ai-on-critical-thinking-self-reported-reductions-in-cognitive-effort-and-confidence-effects-from-a-survey-of-knowledge-workers/)，CHI 2025；[官方 PDF](https://www.microsoft.com/en-us/research/wp-content/uploads/2025/01/lee_2025_ai_critical_thinking_survey.pdf)。
- 实时核对：2026-08-06。
- 样本：319 名知识工作者、936 个自报工作实例；Prolific 招募，英文问卷，参与者自报每周至少一次在工作中使用 GenAI。
- 用途：窄范围支持“参与者报告部分认知工作从执行和信息搜集转向验证、整合与监管；对 GenAI 越有信心与越少自报批判投入相关”。
- 限制：横截面、自报、相关性研究，不测量客观思考质量，不支持因果结论；样本偏年轻、技术熟练，96.87% 使用 ChatGPT，不能代表全部知识工作者或公众。
- 许可处理：PDF 标明 CC BY 4.0。本项目只作署名释义，没有复制长段正文。

## 7. 本地开发流程

开发使用并遵循：

- `writing-skills`
- `test-driven-development`
- `verification-before-completion`
- `human-writing-dbs-pipeline`

用途：先红后绿、保留原始失败、把真实模型旁路编译成 regression、同题复测、第三方许可分层，以及视频只交付骨架。这些是内部开发流程，不作为本候选 Skill 的外部文本来源分发。

## 8. 版本与失败账本

### 0.1 prompt-only 原型

旧候选只有行为规则、十二项输出格式和模型 transcript，没有脚本、Schema、稳定错误、状态恢复或自动测试。架构 RED 12/12 失败。它保留为历史证据，不再代表当前 Skill。

### 可执行 RC.1

新增离线 gate、Schema、validator、renderer 和 state 后，fresh host strict result 仍为 1/4。模型在合规字段中变相建议拖延、让工具回流，并把 App 方案冒充现实结果。

### RC.2

Fresh host strict result 仍为 1/4。上一轮旁路被拦截后，模型又通过未经证实的选项后果、问题中的用例菜单、产品形态目标和无来源阈值绕过。

### RC.3

Fresh host strict result 仍为 1/4。模型漏掉财务承受和替代选择，把“用 AI 提效”重新当成结果，用单样本冒充主要损失和基线，并让产品沉没成本回流。这些失败推动 decisive unknown categories 和 domain coverage 进入 Schema。

### 0.2.0-rc.4

四个 fresh host 输出通过独立语义审计，behavior score 为 4/4。但独立 code audit 复现了 receipt 未绑定、coverage 语义空壳、next-test boundary 不足、pending question 可伪造，以及 Schema 与 runtime 不一致。`0.2.0-rc.4` 因此是“行为通过、架构 blocked”的回归证据，不是可发行版本。

### 0.2.0-rc.5

`0.2.0-rc.5` 修复并测试 receipt binding、stable unknown ID、question coverage、structured stop boundary、state derivation、`resume` revision CAS、file lock、atomic replace、idempotent replay 与 duplicate fact value。首次并发 `start` 不在当前契约保证范围内。

当前证据：

- 67/67 unit、architecture 和 runtime-eval-runner tests 通过。
- 四个离线冻结 case 通过，每题 gate 100 次输出字节级一致。
- `doctor` 11/11 local asset checks 通过。
- 独立 release review 在 duplicate-fact-value 修复后未发现剩余 blocking defect。
- Fresh host 发起 4 次、完成 0 次。四次都在模型响应前被 Codex CLI usage limit 阻断。

`0.2.0-rc.5` 没有 host score。`0.2.0-rc.4` 的 4/4 不被重标为 `0.2.0-rc.5` 证据。

### 0.2.0-rc.6

最终发行审计发现 frontmatter `description` 不应概述执行流程，否则宿主可能只依赖摘要而跳过完整 Skill。`0.2.0-rc.6` 将 description 收窄为纯触发条件；可执行 runtime 与通过独立 review 的 `0.2.0-rc.5` 代码相同。

当前证据：

- 67/67 自动测试通过。
- 四个离线冻结 case 通过，每题 gate 100 次输出字节级一致。
- `doctor` 11/11 通过。
- Fresh host 固定 `gpt-5.5`、reasoning effort `none`、read-only sandbox 和四个新鲜 session；四次都在模型回答前被 Codex CLI usage limit 阻断，完成 0 次。

`0.2.0-rc.6` 没有 host score，不能把 `0.2.0-rc.4` 或 `0.2.0-rc.5` 的证据重标给它。

### 0.3.0-rc.1

本轮不是继续扩写规则，而是把两条缺失的 workflow 编译进可执行契约。

Problem-definition evidence loop 使用户回答成为可引用来源；`advance` 才能确认收敛；`amend` 保留 superseded 历史；轮次预算和 terminal phase 阻止无限追问；高风险 tradeoff 只接受 `actor=user`。

Failure-driven evolution loop 不自动编辑 Skill 或 manifest，只记录 failure、run receipt、复现声明、reviewer promotion 和新 case 的 manifest proposal。公开 regression 与 sealed holdout 明确分区，迭代预算与 saturation 可以强制停止。三个 actor ID 和 artifact hash 当前是 self-attested/hash-declared，不能被表述成经过身份认证的独立复现。四个反复使用的历史输入被重新标记为 regression，不再声称拥有 holdout 价值。

当前证据：

- 102/102 自动测试通过。
- 四个 hash-bound offline regression case 通过，每题 gate 100 次字节级一致。
- suite manifest 成为 runtime runner 的单一 case/expectation 真源。
- lean bundle 可复现构建并独立运行 `doctor`。
- 当前没有 fresh host score，不能继承 `0.2.0-rc.4` 的 4/4。

### 0.3.0-rc.2

独立状态机与发行审查复现了七类新失败：高风险终态无法接收新的用户决定、旧诊断答案可冒充最终选择、零问题状态动作矛盾、低信息回答可假收敛、evolution receipt 未绑定 manifest 输入、派生 state 可脱离 ledger 被修改，以及 packager 未检查 symlink 父目录。

本轮把这些失败写成回归后再修复：最终选择必须来自终态后的 fresh `decision_input`；零问题状态进入 `needs_reassessment`；低信息目标和循环成功证据被拒绝；evolution receipt 绑定相同 manifest 输入；ledger 记录 post-event state checkpoint；packager 逐级检查路径祖先。

当前证据：

- 109/109 自动测试通过，其中 evidence loop 14/14、evolution loop 11/11、packaging 8/8。
- 四个 manifest-bound offline regression case 通过，每题 gate 100 次字节级一致。
- 当前仍没有 fresh host-model score、认证 actor、受信 runner 或未使用 sealed holdout。
- 普通 SHA-256 checkpoint 只能发现 state-only 篡改，不能抵抗同时重写 state 与 ledger。

### 0.3.0-rc.3

RC.2 独立尾审把候选重新拉回 RED：`decide` 只检查整段输入是否出现决定词，导致无关句子的“我决定”可以替选中的背景事实背书；`close-cycle` 没有绑定最初 `failure_observed` 的原始 RED receipt；篡改派生 state 后重复 `init` 可以绕过 checkpoint。修复第一轮还发现相同 cycle ID 可通过重放掩盖换证据，因此继续新增一轮 RED。

RC.3 的运行时要求 selected span 自身表达用户选择；evolution state 保存 observed RED receipt 的规范化摘要；cycle 必须精确复用该 receipt；相同 cycle ID 只对完全相同 payload 幂等；重复 `init` 也走 ledger/head/state checkpoint 校验。

当前证据：

- 113/113 自动测试通过，其中 evidence loop 15/15、evolution loop 14/14、packaging 8/8。
- 四个 manifest-bound offline regression case 通过，每题 gate 100 次字节级一致；报告绑定 RC.3 suite manifest hash。
- 两次显式 allowlist staging bundle 的 source/target tree hash 一致，bundle official quick validator 与 15/15 doctor 通过；这不是 live host 安装或发现证据。
- 修复后的独立尾验尚未完成，当前仍没有 fresh host-model score、认证 actor、受信 runner 或未使用 sealed holdout。
- 精确 span 与决定词检查不证明选择在自然语言语义上完整回应了 tradeoff；宿主仍须负责身份和语义相关性。

### 0.3.0-rc.4

RC.3 尾审冻结了十一类 blocker：空洞同义改写可假收敛、“我决定不了”可终止、高风险 verdict 可藏入未扫描字段、state/ledger 路径别名覆盖、终态幂等顺序错误、即时 phase 与落盘 state 不一致、事件命名空间碰撞、空 event ID、NaN/Infinity、stop 后继续变异，以及矛盾 RED receipt 可成功记录。

`0.3.0-rc.4` 没有继续扩禁词表。确认态的 outcome 与 success criterion 必须引用 active post-start user evidence；success criterion 使用结构化 `{value, sources}`，并且比 outcome 新增可判定维度。高风险 verdict 递归扫描模型语义字段，用户原文和 source quote 不参与该门。用户决定还必须形成正向承诺，未决定与疑问不能结束 loop。

Evolution runtime 新增路径 alias、finite number、事件 namespace、receipt polarity/actor、terminal immutability 与 exact replay 契约。两文件各自原子写入，但没有跨 state/ledger 的事务恢复；普通哈希与 actor 身份限制保持不变。

冻结 finding set 修完后的尾验又暴露多取舍终态缺陷：只决定 `t1` 就会结束整个 loop，或可伪造两个事件都指向 `t1` 的终态。新增回归要求每个预期 `tradeoff_id` 只出现一次，部分覆盖继续等待，全部覆盖才终止；原事件精确重放仍保持幂等。

当前证据：

- 134/134 自动测试通过，其中 evidence loop 21/21、evolution loop 29/29、packaging 8/8。
- 四个 manifest-bound offline regression case 通过，每题 gate 100 次字节级一致；报告绑定 `0.3.0-rc.4` manifest hash。
- 两个隔离 Codex desktop agent-context shadow run 覆盖四题并按冻结语义边界得到 4/4；它们不是目标宿主 discovery、官方 host score 或多 trial 稳定性证据。
- 两次 `0.3.0-rc.4` allowlist staging bundle 的 source/target tree hash 一致，source 与 bundle official quick validator、bundle 15/15 doctor 和 bundle privacy scan 通过；这不是 live host 安装或发现证据。
- 独立 agent-context 尾验对冻结 B1-B11、多 tradeoff 与 symlink 攻击集复放 51/51，并独立跑完整套件 134/134；这是独立工作上下文中的代码与契约复放，不是认证外部实验室或目标宿主行为认证。
- Fresh host-model、认证 actor、受信 runner 和新 sealed holdout 均未完成。

## 9. 原创性结论

本项目可主张独立创作的部分包括：针对 brief 设计的三模式门控、十二项数据契约、确定性 CLI、路由配置、三份 Schema、receipt binding、evidence span、bounded evidence-loop state protocol、failure-ledger and promotion protocol、suite manifest、packager、冻结测试、回归测试和本项目独立编写的说明文字。

该主张不包括本文件已标明来自上游的概念、术语、规则或表达。本项目不能主张首创问题消解、意义取决于使用、Question 与 Problem 的区别，或以可观察反馈检验解释。

准确表述是：**这是一个明确署名上游、在 CC BY-NC 4.0 下完成的原创组合与改编 Skill，不是完全独立于 dontbesilent 方法的纯原创作品。**

## 10. 权利与发行结论

1. 用户的非商业承诺本身不创造借鉴许可。允许分享和改编的依据是 dontbesilent 固定版本采用的 CC BY-NC 4.0。
2. 对外分享原材料或改编物时必须署名 dontbesilent、链接许可、说明本项目的修改，并且不得暗示上游认可或背书；单纯私人使用不应被表述成同一触发条件。
3. 不允许商业用途。若未来用于付费产品、获客、客户交付、商业课程或其他商业场景，必须取得上游额外授权，或移除改编内容并重新独立实现和评测。
4. 准确标签是“非商业源码开放候选”或 source-available，不是 OSI open source。
5. 当前整包暂用 CC BY-NC 4.0；[Creative Commons 官方不建议把 CC 许可证用于软件](https://creativecommons.org/faq/#can-i-apply-a-creative-commons-license-to-software)。对外发行前应拆分可执行代码与内容/上游改编层的许可，或明确记录继续采用该方案在 source/object code、专利与兼容性上的限制。
6. 截至 2026-08-06 的本地检查，候选仓库未配置 Git remote，当前文件未纳入 commit；本次工作未执行 commit、push 或发布。这个结论只描述已检查的本地状态，不证明其他主体或渠道从未分发材料。
7. 当前版本是本地 `0.3.0-rc.4`。Fresh host gate、跨模型、多 trial、目标宿主真实安装验证、整仓隐私审查和软件许可拆分未完成，不得宣称已经发布、已经开源或生产稳定。
8. 隐私清洁结论只覆盖 `install-manifest.json` 的 lean bundle。完整 Skill 源码树的历史 host 环境记录仍含四个 Codex session ID；候选仓库整仓另有其他组件和私有工作流绝对路径。完整源码树或整仓发行前必须单独脱敏和复核。
