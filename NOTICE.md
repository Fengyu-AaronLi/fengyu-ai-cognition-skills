# 署名与修改说明

## dontbesilent dbskill

- 作品名：`dbskill`
- 作者：dontbesilent
- 原始仓库：https://github.com/dontbesilent2025/dbskill
- 审计固定提交：`8282f010964601070334dd7350973386abff6d2b`
- 上游许可证：[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
- 上游版权声明：Copyright (c) 2026 dontbesilent

## `separating-facts-from-stories` 如何使用

本项目在 2026-08-05 的非商业来源审计中参考了两个上游文件。

- `skills/dbs-good-question/SKILL.md`
- `skills/dbs-standard-answer/SKILL.md`

参考范围包括解释需要可观察反馈、信息不足时保留未知、候选解释需要可检验信号、证据强度约束结论强度，以及无定义的精确分数会制造确定感。

本项目据此独立编写首批四个扩展压力测试，覆盖二手转述、可证伪工作假设、无依据概率和即时安全优先级。后续转述、感受主体、否定引语、历史链、崩溃恢复、安全响应、并发计数和发行证据测试来自本项目自己的真实红灯。测试输入、判据和原始输出由本项目重新设计，没有复制上游案例、特色表达、标题库或目录结构。

项目独立实现了 input/source span 哈希绑定、casefile/schema、evidence links、有限目录、追加版本、有状态修复循环、崩溃恢复、workspace 文件锁、冻结 evaluation context、独立 replay、allowlist installer、包内可移植评测证据和 manifest verify。历史 prompt-only v7 的八例复测只是演化证据，不代表当前 runtime 已通过发行门。当前结论只以 `skills/separating-facts-from-stories/evals/` 中对应 machine report 与该 Skill 的 `PROVENANCE.md` 为准。

本改编不代表 dontbesilent 对该 Skill 或本仓库的认可或背书。

## auditing-ai-claims

`skills/auditing-ai-claims/` 在初版 Skill 和 baseline 完成后，经项目所有者明确授权，在非商业与署名条件下参考并改编了以下上游文件与目录：

- `skills/dbs-deconstruct/SKILL.md`
- `skills/dbs-goal/SKILL.md`
- `skills/dbs-content-system/`
- `skills/dbs-skill-cleaner/`
- `skills/dbs-save/SKILL.md`

进入该 Skill 的改编范围是：在具体语境中检查关键结论词、用可观察结果界定成立与失败、只处理会改变结论的阻塞性缺口、对明确主张采用最短够用输出，以及入口编排、执行层和独立状态目录分离的抽象工程思路。它们被改造成外部事实主张的判准闸门与可恢复 workflow，并接入本项目独立设计的来源打开、支持范围、推断跨度、三道门和五种状态。

该 Skill 没有搬运上游商业案例、七表本体论、奥派判断、原输出模板、测试或特色收尾。固定提交、原文件链接、具体修改与未采用内容见 `skills/auditing-ai-claims/NOTICE.md` 和 `skills/auditing-ai-claims/PROVENANCE.md`。

本改编不代表 dontbesilent 对 `auditing-ai-claims` 或本项目的认可或背书。

## defining-problems-before-prompts

`skills/defining-problems-before-prompts/` 在项目所有者确认非商业发行方向后，基于 dontbesilent dbskill 固定提交 `8282f010964601070334dd7350973386abff6d2b`，参考并改编了以下文件中的部分方法：

- `skills/dbs-good-question/SKILL.md`
- `skills/dbs-goal/SKILL.md`
- `skills/dbs-deconstruct/SKILL.md`
- `skills/dbs-diagnosis/SKILL.md`

进入本项目的范围包括 Question 与 Problem 的区分、可观察现象与预期冲突、语义是否改变交付和验收、问题消解的前提顺序，以及信息不足时保留未知并连接现实反馈。

本项目独立新增三模式门控、十二项 Problem Spec、确定性 CLI、JSON Schema、版本化状态、验证器、渲染器和冻结回归测试。没有复制上游商业案例、标题库、定价规则、完整输出模板或目录结构。

具体来源、修改范围和未采用内容见 `skills/defining-problems-before-prompts/PROVENANCE.md`。本改编不代表 dontbesilent 对该 Skill 或本项目的认可或背书。

## breaking-identity-labels

`skills/breaking-identity-labels/` 的 Problem Spec、四个初始 baseline 和十项输出契约在审阅 dontbesilent dbskill 之前建立。用户随后确认非商业用途，并允许在 CC BY-NC 4.0 条件下借鉴。项目固定审阅提交 `8282f010964601070334dd7350973386abff6d2b`，参考范围是：把宽泛概念还原到具体用法和可观察事实、信息不足时保留未知并寻找最小缺口，以及路由、运行工具、状态、验收门和发行控制分层的通用工程方法。

本项目独立实现证据跨度与归因事件、临床来源与医疗决定主体边界、稳定偏好和功能受损分流、安全事件、五个 runtime JSON Schema 与十一项 governance Schema、跨字段策略门、追加式状态机、哈希回放、只读 next 控制器、确定性 renderer、陌生输入评测、完整生命周期 demo、allowlist 发行包、隐私扫描、非覆盖安装器，以及 manifest 绑定的进化与审计闭环。没有复制上游商业案例、七表结构、测试、脚本、模板正文、标题库、品牌命令、固定收尾或特色表达。

完整来源、逐文件修改范围、未采用内容和外部研究边界见 `skills/breaking-identity-labels/PROVENANCE.md`。本改编不代表 dontbesilent 对 `breaking-identity-labels` 或本项目的认可或背书；当前状态仍是未发布的本地候选。
