# Attribution and adaptation notice

本 Skill 的红色阶段、主张账本、来源层级、推断跨度、五种状态、时间核验和 eval 套件由本项目独立设计。

2026 年 8 月 5 日，项目所有者将来源边界从“完全不接触 dbskill”改为“在拟公开源码、非商业使用、遵守原许可和明确来源的条件下允许受控借鉴”。此后加入的以下机制参考并改编自 dontbesilent 的 dbskill：

- 从 `dbs-deconstruct` 改编“词义要在具体使用场景中检查”的思路，用于识别“彻底解决、行业第一、安全”等尚无共同判定条件的结论词
- 从 `dbs-goal` 改编“观察到什么才算完成或失败”的边界测试，用于给主张补充成立与反驳条件
- 从 `dbs-goal` 改编“按真实缺口调用测试、已经清楚就放行”的纪律，以及最短够用输出策略，用于避免对明确主张强行跑完整流程

2026 年 8 月 5 日收到“V1 仍然只是用户提示词”的产品批评后，本项目进一步打开同一固定提交中的 `dbs-content-system`、`dbs-skill-cleaner` 和 `dbs-save`，只借鉴下列抽象工程机制：

- 单个 Skill 目录同时携带入口、脚本、模板、文档和验收材料
- 自然语言入口只做路由与编排，机械操作交给可执行工具
- 运行状态写入独立目录，可恢复、可检查，不依赖一次对话记忆
- 先建立明确闸门，再允许进入下一阶段或交付结果

V2 的 Python 运行时，V3 的 `next` 收敛循环、字符覆盖、证据用途隔离、PDF fail-closed、并发锁和恢复分支，以及 V3.1 的安全文件协议、强制反证状态、抓取总时限、回执认证和来源事务恢复，均由本项目重新设计与实现。命令名称、JSON 字段、来源回执、网络限制、哈希协议、状态门、测试夹具和报告渲染没有复制上游代码、目录结构、测试、案例、模板正文或特色表达。

原始来源：

- dontbesilent2025/dbskill，commit [`8282f010964601070334dd7350973386abff6d2b`](https://github.com/dontbesilent2025/dbskill/tree/8282f010964601070334dd7350973386abff6d2b)
- [`skills/dbs-deconstruct/SKILL.md`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-deconstruct/SKILL.md)
- [`skills/dbs-goal/SKILL.md`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-goal/SKILL.md)
- [`skills/dbs-content-system/`](https://github.com/dontbesilent2025/dbskill/tree/8282f010964601070334dd7350973386abff6d2b/skills/dbs-content-system)
- [`skills/dbs-skill-cleaner/`](https://github.com/dontbesilent2025/dbskill/tree/8282f010964601070334dd7350973386abff6d2b/skills/dbs-skill-cleaner)
- [`skills/dbs-save/SKILL.md`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-save/SKILL.md)
- 原许可：[CC BY-NC 4.0](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/LICENSE)

作者与版权：dontbesilent，Copyright 2026。

改动说明：本项目把商业概念与目标审计机制改写成外部事实主张的可判定性闸门，删除商业领域判断、七表本体论、奥派经济学、原案例、原输出模板和特色收尾表达，并把结果接入来源打开、证据范围、推断跨度与状态账本。V2 把入口与执行层分离，V3 加入可恢复状态循环和确定性证据边界，V3.1 再把反证动作和来源提交做成运行时强制状态。`C13-vague-verdict` 是本项目新写的评测案例，不是 dbskill 原案例。

本 Skill 是尚未公开的本地候选包，拟按 CC BY-NC 4.0 提供，具体见同目录 `LICENSE`。公开分享修改版时，必须保留适当署名、原许可链接和修改说明，且不得用于商业目的。本改编不代表 dontbesilent 对本项目的认可或背书。
