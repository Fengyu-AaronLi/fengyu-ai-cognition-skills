# 署名与修改说明

## 上游作品

- 作品名：`dbskill`
- 作者：dontbesilent
- 原始仓库：https://github.com/dontbesilent2025/dbskill
- 固定提交：`8282f010964601070334dd7350973386abff6d2b`
- 重点文件：`skills/dbs-good-question/SKILL.md`、`skills/dbs-standard-answer/SKILL.md`
- 许可证：https://creativecommons.org/licenses/by-nc/4.0/
- 上游版权声明：Copyright (c) 2026 dontbesilent

## 本 Skill 的改编

本 Skill 参考了上游关于证据状态、可观察反馈、可证伪工作假设、结论强度受证据约束，以及避免无依据精确分数的抽象原则。复用许可来自上游 CC BY-NC 4.0；本项目用户的非商业承诺只确定本项目用途符合 NonCommercial 条件，不构成对第三方权利的授权。

本项目独立编写了首批四个扩展压力测试，并在真实红灯出现后继续编写语义、安全、版本、状态恢复、安全响应、并发计数、评测证据和安装门测试。没有复制上游案例、测试输入、特色表达、标题库或文件结构。

本项目独立实现的工程部分包括：输入与 source span 哈希绑定、casefile 与 JSON Schema、claim 与 evidence link、有限目录、追加式版本链、有状态修复循环、崩溃恢复、workspace 文件锁、冻结 evaluation context、独立 runtime replay、allowlist installer、包内可移植评测证据和 manifest verify。

上游原则进入本项目后被改写为关系、职场和自我评价中的独立机器契约；安全优先、八项输出、具体错误码、示例、测试和文件组织均围绕本项目需求重新设计。完整来源、用途、进入范围与排除内容见 `PROVENANCE.md`。

本改编不代表 dontbesilent 对本 Skill 或本项目的认可或背书。
