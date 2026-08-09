# 来源与原创性记录

## 适用范围

本文件记录 `separating-facts-from-stories` 的需求来源、研究用途、许可状态，以及相关材料是否进入最终产物。

本 Skill 目录采用本地 `LICENSE` 中的 CC BY-NC 4.0，只允许非商业分享与改编。项目所有者 brief 提供名称、问题、八项需求契约和首批四个评测场景；机器契约、判断实现、扩展回归与运行时由本项目独立编写。扩展评测中采用的第三方方法原则按各自来源署名。任何第三方材料都不会因为出现在本仓库而被重新许可。

“进入最终产物”分为四种状态：

* **进入**：项目所有者提供且有权用于本项目的需求，或本项目形成的原创内容。
* **借鉴进入**：在相容的开放许可下参考第三方原则，明确标注作者、来源、许可与本项目修改。
* **仅事实性释义**：只记录事实、研究范围和局限，不复制原文表达。
* **不进入**：只用于排除性审计，规则、示例、测试、表达和结构均不使用。

## 来源清单

### 1. 项目所有者原创 brief

* **来源**：项目所有者于 2026-08-05 提供的“事实与故事分离”项目 brief。
* **用途**：确定名称、核心问题、核心判断、四个评测场景、八项输出契约、安全边界、交付文件和发行限制。
* **许可状态**：由项目所有者直接提供，用于本项目原创实现；最终版权归属以仓库声明为准。
* **是否进入最终产物**：**进入**。项目名称、问题定义、指定评测输入、边界和交付要求构成产品需求。具体判断步骤、示例输出和测试判据由本项目独立推导。

### 2. Vault 私有本地资料

以下资料位于 FengyuKnowledgeOS，仅作为需求、边界、内部观点一致性和历史数据背景：

* `50-深度思考/54-商业思考/AI时代认知更新者-开源Skill内容与变现系统-2026-08-03.md`
* `50-深度思考/54-商业思考/AI陪练项目体验与开源Skill产品化可行性报告-2026-08-05.md`
* `10-自媒体/14-数据复盘/小红书数据_2026-03-04_深度复盘.md`
* `10-自媒体/12-观点索引/VP-054-课题分离归因.md`
* `10-自媒体/12-观点索引/VP-059-自动定罪程序.md`
* `10-自媒体/12-观点索引/VP-073-论迹不论心是账本问题.md`
* 通过 `npm run kb:search -- "事实 解释 动机 猜测 关系 AI 迎合" --top 10` 召回并打开核对的私有候选原文。

* **用途**：确认真实用户需求、既有观点边界、产品定位，以及关系类内容的历史表现。历史数据的覆盖期截至 2026-04-27，只能作为历史背景。
* **许可状态**：私有项目资料，不随本候选 Skill 重新分发。
* **是否进入最终产物**：**原始资料不分发，聚合历史信号有限进入 launch brief**。最终产物只保留独立推导的抽象需求、边界、关系类内容曾有历史表现，以及“数据并非最新 30 天”的限制说明；不复制原文、私有案例、标题库、逐条平台数据或特色表达。

### 3. Anthropic 官方研究

* **来源**：[How people ask Claude for personal guidance](https://www.anthropic.com/research/claude-personal-guidance)，Anthropic，2026-04-30，重新核对日期为 2026-08-06。
* **用途**：确认个人建议对话可能包含单方信息，模型迎合会在用户要求确定结论时加剧，以及样本和自动分类方法存在局限。
* **许可状态**：引用页面未提供可将其正文纳入本项目发行文件的明确开放内容许可。
* **是否进入最终产物**：**仅事实性释义**。保留来源链接、研究对象、样本范围和局限，不复制页面的特色表达、段落或案例。页面中的比例只描述该研究的 Claude.ai 样本与分类口径，不作为所有 AI 用户的发生概率。

### 4. OpenAI 关于迎合的官方说明

* **来源**：[Sycophancy in GPT-4o: what happened and what we're doing about it](https://openai.com/index/sycophancy-in-gpt-4o/)，OpenAI，2025-04-29，重新核对日期为 2026-08-06。
* **用途**：确认过度认同可能由训练和反馈目标共同放大，并可造成不良的模型行为；用于建立“支持用户不等于确认推断”的风险边界。
* **许可状态**：引用页面未提供可将其正文纳入本项目发行文件的明确开放内容许可。
* **是否进入最终产物**：**仅事实性释义**。不复制原文措辞、内部示例或页面结构。

### 5. OpenAI 关于情感使用的官方研究

* **来源**：[Early methods for studying affective use and emotional well-being on ChatGPT](https://openai.com/index/affective-use-study/)，OpenAI 与 MIT Media Lab，2025-03-21，重新核对日期为 2026-08-06。
* **用途**：确认情感性使用集中在部分用户、结果与个人因素及使用时长相关，并记录观察研究、随机试验、语言和自报告等局限。
* **许可状态**：引用页面未提供可将其正文纳入本项目发行文件的明确开放内容许可。
* **是否进入最终产物**：**仅事实性释义**。不复制原文表达。研究中的样本比例和关联只用于描述该研究，不外推为所有平台、语言、地区或 AI 用户的普遍结论。

### 6. dontbesilent dbskill 非商业改编审计

* **作品与作者**：[`dbskill`](https://github.com/dontbesilent2025/dbskill)，dontbesilent。
* **固定来源**：commit [`8282f010964601070334dd7350973386abff6d2b`](https://github.com/dontbesilent2025/dbskill/tree/8282f010964601070334dd7350973386abff6d2b)。重点核对 [`dbs-good-question`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-good-question/SKILL.md) 与 [`dbs-standard-answer`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-standard-answer/SKILL.md)。
* **用途**：检查现有 Skill 是否区分不同证据状态，是否允许有限且可证伪的工作假设，是否同时寻找支持与削弱信号，以及是否拒绝无依据的精确概率。
* **许可状态**：上游为 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)，版权声明为 Copyright (c) 2026 dontbesilent。复用授权来自上游许可证本身，不来自项目用户。项目所有者的非商业承诺只确定本候选选择了符合 NonCommercial 限制的用途和发行方向。
* **是否进入最终产物**：**借鉴进入**。进入的是证据状态、有限可证伪工作假设、同时记录支持与削弱信号、拒绝无依据精确概率等抽象原则。首批四个扩展压力测试由本项目独立编写；后续转述、引语否定、感受主体、历史链、安全路由、并发状态和发行证据测试均来自本项目真实红灯。未复制上游案例、测试输入、标题库、特色表达或文件结构。
* **修改说明**：上游抽象原则被改写成适合关系、职场和自我评价的机器契约。项目独立实现了输入哈希、原子 source span、JSON Schema、claim 与 evidence link、有限目录、追加式版本链、有状态 workflow、崩溃恢复、workspace 文件锁、冻结 eval context、独立 replay、allowlist installer、包内可移植评测证据和 manifest verify。后续真实红灯又触发了候选解决生命周期、第一人称撤回及极性约束、引语说话者与时间、感受体验者、`A 不 A` 疑问、纯翻译与当前风险的范围分离，以及显式复发风险路由。产品层独立加入 executable improvement controller、controller-owned `prove-stop`、固定 producer recipe、两份不同 reviewer 与 execution 的本地 attestation、内容寻址的 source/eval/review 留存快照、canonical install、文件级 rollback/restore，以及同 UID 精确环境 token 的进程族收口。Round90 至 Round95 又独立实现 finding ledger 确定性重放、typed command receipt、controller-run-bound work order、phase-specific payload、S0→Sr→S1 source epoch、graph 原生 finding 写 RED、三点源码 blob 留存、工作单漂移换轮、未关闭 fix 的 superseded 历史、全 open finding 复核门和 retained STOP 的 live-source 独立恢复。Round97 至 Round101 来自冻结关系 eval 与后续回归中的真实 contract blocker，独立加入复合故事分层、主体绑定、真伪复问 fail-closed、故事极性、预测范围和来源所有权。Round102 与 Round103 的两组独立盲矩阵首次共出现 78 个结构变体失败；Round104 与 Round105 的独立复审又首次产生 75 个全新失败；Round108 与 Round109 再固定 22 个来源和结构尾部失败。对应实现采用断言治理范围、关联协调、非事实态度补语、格式操作所有权、数量与语态、来源标签保守优先级、代理代发结构、fresh hearsay、本体化 carrier、后置转述、所有权重置与嵌套来源顺序，而不是移植上游句子、规则或测试。Darwin `EINVAL` 的 zombie 判定与 PID 退出竞态也来自本项目真实失败。它们不是上游文件的移植。历史 prompt-only 8/8 只作为演化证据，不代表当前 runtime 的发行结果。
* **背书声明**：本改编不代表 dontbesilent 对本项目的认可或背书。

### 7. 本地写作、Skill 工程与测试流程

* **来源**：FengyuKnowledgeOS 中的 `writing-skills`、`test-driven-development`、`verification-before-completion`、`human-writing-dbs-pipeline`、`workflow-runner`，以及本地 `skill-creator` 工作说明。
* **用途**：约束开发顺序、先运行 baseline、保存原始输出、红绿重构、状态循环、独立复核、证据停止门、最小 SKILL 入口和视频骨架交付。
* **许可状态**：本地工作流资料，仅用于内部开发过程。
* **是否进入最终产物**：**工程过程进入，文字与模板不进入内容层**。根级 continuous-improvement DAG 与 `.ao-output` 记录了本项目自己的多轮循环；未复制这些 Skill 的规则文本、示例或特色表达。

### 8. 许可解释依据

* **来源**：[CC BY-NC 4.0 官方页面](https://creativecommons.org/licenses/by-nc/4.0/) 与 [Creative Commons 署名建议](https://wiki.creativecommons.org/wiki/Recommended_practices_for_attribution)。
* **用途**：确认分享、改编、署名、标明修改、非商业使用和不得暗示背书等条件。
* **许可状态**：用于解释许可证要求，不复制其正文进入 Skill 运行规则。
* **是否进入最终产物**：**仅事实性释义**。`LICENSE` 提供许可通知，完整官方法律文本随包保存在 `CC-BY-NC-4.0-LEGALCODE.txt`；`NOTICE.md` 提供作品、作者、来源、许可证和修改说明。

### 9. Round123 至 Round146 本地对抗证据

* **Round123 隔离状态**：`tests/test_round123_casefile_recheck_red.py` 首次固定了 6 个方法、9 个真实失败，并继续作为有效回归测试保留。但执行者用于排除历史材料的 glob 写错，误扫到 `evals/raw`，且可能接触 Round102 至 Round121 的既有材料。因此 Round123 不能计为独立盲测，后续报告、视频和独立性数量都不得把它包装成新鲜隔离证据。
* **Round124 与 Round125**：Round124 的新鲜隔离复核固定 3 个方法、4 个失败，覆盖第三方跳楼主体、转述后的用户反应感受和合法时间线来源字段换位；Round125 的 6 个回归控制首次出现 4 个反噬。两轮案例与判断均由本项目当前运行时失败独立产生。
* **Round126 原始盲测**：原件保存在仓库根目录 `tests/test_round126_timeline_fidelity_blind_red.py`，SHA-256 为 `7be94dd385bb3edd362c32bada6488ba2b2a287d2b03a53ef0f54ba90de9c821`。7 个方法中有 3 个首次失败，证明来源值交换、改写和凭空新造可绕过时间线验证。
* **Round127 原始盲测**：原件保存在仓库根目录 `tests/test_round127_safety_feeling_blind_red.py`，SHA-256 为 `3f8668c19b86e8295e3cbce1f5aaf5e8c3ebd42f0bb47351226d0fa9e52fc6bb`。2 个方法固定 4 个失败子例，覆盖第三方当前自伤、死亡愿望、双重否定与第一人称反应感受。
* **正式发行移植**：隔离执行者把 Round126 与 Round127 原件落在仓库根目录，而 packager 只接纳 Skill 内的测试。原件按“不删除”原则原样保留，不进入权威 source manifest。`skills/separating-facts-from-stories/tests/test_round126_timeline_fidelity_blind_red.py` 只调整包内导入路径与格式，案例和断言语义不变；`skills/separating-facts-from-stories/tests/test_round127_safety_feeling_blind_red.py` 将 pytest 参数化改为标准库 unittest 子测试，并调整包内路径，案例和断言语义不变。两份移植版本已进入 source manifest、eval release evidence 与 packager 必需测试集。
* **Round128 反向控制**：6 个方法首次运行全部通过，覆盖单重与双重否定、说话者所有权、感受外部归属、来源缺失、合法 Markdown 表格和单一来源重复。没有为了延长循环而制造失败。
* **Round129 冻结 eval 红灯**：Skill 4.0.1 的全新隔离复测先完成 17 个 case，第 18 个 `versioned-evidence-update` 无法生成合法 revision 2。引语中的 `手机送修，` 与 `刚拿回来` 被 update coverage 强制要求写成当前观察事实，但同一 validator 又正确拒绝把 `quoted=true` span 当作观察事实。合格执行者没有绕过 validator，也没有补写通过结果。未完成运行整体保存在 `evals/raw/with-skill-v30-failed-attempts/round129-versioned-update-red-v401/`；隔离工作区保存在 `/private/tmp/fengyu-versioned-evidence-update.TKF8Dg/`。
* **Round129 最小修复**：`tests/test_round129_versioned_quoted_observation_red.py` 先稳定复现 `CURRENT_OBSERVATION_CLAIM_MISSING` 与 `CURRENT_OBSERVATION_EVIDENCE_MISSING`，随后仅把 quoted span 排除出 update 的强制 observation coverage。引语仍可作为受限证据，但不能被提升成观察事实。专项上下文测试 13/13，全量 unittest 850/850，packaged self-test 144/144。
* **Round130 独立复审 RED**：Round129 修复后的只读复审发现，`他回复：‘手机送修，刚拿回来’。` 这类没有额外附件或未引语事实的自然更新仍稳定报 `CURRENT_INPUT_CLAIM_REQUIRED` 与 `CURRENT_INPUT_EVIDENCE_REQUIRED`。原因不是引语应当成为事实，而是 schema 没有保存“这段话被归属于具名说话者”的一等命题层。刚生成但尚未执行的 4.0.2 eval context 按 source drift 整体移至 `evals/raw/with-skill-v30-failed-attempts/round130-prepared-context-superseded-v402/`，没有继续使用旧冻结证据。
* **Round130 最小实现与反噬**：`tests/test_round130_attributed_statement_red.py` 先出现 2 个稳定失败，再新增 `attributed_statement`。它只允许通过说话者、引语完整性、来源、否认、代理、虚构和疑问范围检查的具名直接引语，状态为 `directly_stated`，并在渲染中明确“不证明引语内容为事件事实”。硬把引语行动写成 `observable_fact` 仍触发 `FACT_TYPE_UNSUPPORTED`。全量门随后真实抓到旧渲染措辞兼容、source manifest 排序和无问号的 `是不是` 引语三个反噬，修复后全量 unittest 854/854，packaged self-test 145/145。
* **Round131 至 Round140 归属与迁移契约**：这些测试和实现来自 Round129 未完成 eval、后续本地复审和独立迁移审计，不来自 dontbesilent。项目独立加入过去时归属陈述、直接与二手边界、单调版本图、delta-scoped parser、显式 legacy corpus、不可变 `legacy_epoch`、多代历史保留、独立 1C renderer 与 schema 3.2.0。历史项目不按当前语义重新分类，也不再使用“当前意愿”或“当前报告”标签。
* **Round141 来源与路由 fuzz**：独立只读矩阵首次发现材料或虚构载体、天气预报、研究论文、条件与未来话语、Markdown 二手范围、非原话或待确认标签、接收者 reset 和混合格式任务逃逸。对应用例、判断与实现均由本项目根据实际失败独立编写；未复制上游规则或表达。
* **Round142 至 Round146 迁移信任闭环**：独立审计证明旧语义只能存活一代、当前历史可注入 epoch、改版本字符串可洗白非法 root，且六字段成功回执可由调用方自行构造。项目依次加入跨多代 epoch ID 边界、当前历史 epoch 注入拒绝、Skill 与 validator 4.3.0、release-bound legacy corpus、工件 canonical SHA 与 receipt canonical 指纹双门、安装态 corpus smoke 和声明真实性测试。最终只宣称 17 个精确历史根可迁移，版本对限于 `3.0.0/4.0.0` 与 `3.0.0/4.0.1`；没有真实工件的 4.0.2、4.1.x 与 4.2.0 明确不受支持。
* **许可与原创性**：Round123 至 Round146 的输入、断言、运行时实现和错误类型均来自本项目真实需求与本地失败，不来自 dontbesilent 的案例、测试、规则文本、标题或文件结构。

### 10. Round147 至 Round174 本地工程证据

* **来源**：本项目在归属、passthrough、版本、开放语法、release binding、host execution、graph runner、eval orchestration 与对抗审查中出现的真实本地失败，以及为这些失败新增的回归合同。
* **用途**：Round147 至 Round151 关闭语义尾部缺口并把行为版本升级为 4.4.0；Round152 至 Round158 加入宿主观察 receipt、host-derived review/eval identity、真实 back edge、active-source producer binding、controller-owned preflight runner 与崩溃后原字节恢复；Round159 至 Round167 加入固定 host eval runner、suite 编排、固定 prompt 合同、input-only preflight、模型与宿主写入区分离、路径逃逸与控制字符拒绝，以及哈希绑定 runtime snapshot；Round168 至 Round173 加入固定双评审入口、phase 对真实 attestation 的重派生、通用 CLI review 禁用、source identity 信任链、`review_payload.v2` finding 投影与 STOP 评审血缘约束；Round174 根据真实 host eval 产生的 bytecode 污染加入只读 snapshot、目录集与权限审计。
* **许可状态**：本项目原创工程与测试。未复制 dontbesilent 的规则文本、案例、测试、特色表达或文件结构。
* **证据边界**：Round159 至 Round173 的单元测试使用 fake Codex fixture，用于验证宿主合同、恢复和拒绝路径；Round174 的触发证据来自保留的真实本地 Codex host eval，但修复后是否闭合仍需新鲜全套复测。Codex host receipt 是本地主机观察，不是外部签名、可信时间戳或同 UID 恶意篡改防护。
* **是否进入最终产物**：**进入**。进入 runtime、eval harness、controller 合同、README、问题规格与视频骨架；真实 18 案、安装和 STOP 状态仍必须由最终冻结 source 的机器证据决定。

### 11. 第二次真实 host run 与 Round175 至 Round183

* **来源**：本项目真实 Codex host root `evals/raw/with-skill-v44-host-run-20260806-r2/`。在服务使用限额到达前，`relationship-silence`、`immediate-safety-override` 与 `bidirectional-evidence-on-one-claim` 完成真实模型执行；prompt、events、stderr、last message、host receipt、workspace、canonical copy 和失败 case result 均原样保留。其余调用的使用限额错误也保留，不当作 Skill 行为失败或通过。
* **用途**：区分模型判断失败与 host、workflow、auditor 合同失败，并把可复现问题转为 Round175 至 Round184 的 RED/GREEN 测试。具体覆盖 exact input 解包、固定 workspace、canonical artifact 晋升、canonical validator replay、safety 唯一终态、passthrough runtime 物化、invalid fixture snapshot、末尾换行边界、独立 workspace 审计、同源 evidence relation 聚合、原子角色或权限信号的确定性关系派生，以及新 validator 对受信 legacy profile 的隔离。
* **真实模型行为边界**：r2 的 bidirectional 工件把“并保留预算审批职责”写成 `does_not_establish`，这是模型行为失败，不归咎于基础设施。Round182 让 auditor 无论 link 顺序都保留同源全部关系；Round183 进一步让 validator 在同一 `E数字` 被切成多个原子时恢复最小职责范围，并要求可识别的单向信号使用弱 `supports` 或 `conflicts`。该坏工件现在会进入 repair loop，改为 `conflicts` 后才通过。safety 工件额外加入 `other_immediate_risk` 的问题仍需 exact raw input 下的新鲜真实复测，不能由静态测试宣布消失。
* **许可状态**：prompt、输入、模型运行产物、宿主脚本、测试和修复均属于本项目内部评测与原创工程证据。没有从 dontbesilent 复制规则、案例、测试、特色表达、标题或文件结构。
* **证据边界**：r2 没有完整 `machine-report.json`，且后续 source 已改变，因此不能计作 3/18、不能续跑、不能进入安装门或 `STOP`。Round175 至 Round183 的 25 项专项回归只证明修复后的确定性合同；Round184 又由第一次完整回归真实打开两个 legacy 迁移失败，并在不改写历史证据的前提下闭合。完整 18 案和独立 review 必须在新 source freeze 与新 eval root 重做。
* **是否进入最终产物**：**进入**。两个被测试直接引用的 r2 工件进入权威 source manifest，其他原始现场保留在开发仓库但不进入最小安装包。README、问题规格、results 与视频素材包仅引用可核对事实和明确局限。

## 原创性与发行声明

1. 原始四个冻结评测输入来自项目 brief 或为其指定非触发场景所作的最小实现，原始输出由隔离模型会话真实生成并保存。
2. 首批扩展压力测试由本项目依据已署名的方法原则重新设计；其后的 adversarial tests 来自本项目运行时的可复现失败。Round123 明确降级为受污染复查，Round124、Round126 与 Round127 才按各自实际隔离状态记录。没有复制上游测试案例或特色表达。
3. 当前产品不是 prompt-only 文档。`SKILL.md` 是最小入口，行为由独立编写的 casefile、schema、validator、workflow、host-managed 输入与工件晋升、固定 host eval runner、固定 host review runner、独立 auditor、packager、improvement controller 与 fixed gate producer 共同约束。回归测试和 self-test 的当前数字只从 fresh run 引用，不沿用历史静态计数。规则只在真实红灯出现后修改；任何修改进入发行证据前都必须全量复测。
4. 外部网页只支持风险背景和研究局限，不作为项目有效性或普遍发生率的证明。
5. 私有 Vault 原文、私有案例和逐条数据不会打包进入发行物；launch brief 只保留去来源化的聚合历史信号和数据截止日期。
6. 当前状态是 **CC BY-NC 非商业 source-available 本地候选**。是否达到本地停止门，以 eval machine report、两份 host-derived review attestations、retained release basis、canonical install、rollback/restore receipts 与 controller 具名 gate 为准。prepared eval 强制固定 prompt、runtime snapshot、逐案 host receipt 与 host-derived case result，并拒绝重复 execution identity；这些本地证据仍不能证明外部独立身份，也不能抵抗同 UID 操作者重写整套文件。本地 attestation、哈希和 cooperative process token 都不是外部签名或 OS sandbox。没有公开地址或公开下载文件，不能声称已经开源、已经公开发行或已经被外部安装验证。
