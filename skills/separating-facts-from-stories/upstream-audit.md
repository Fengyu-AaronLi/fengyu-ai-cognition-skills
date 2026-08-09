# dontbesilent dbskill 非商业来源审计与演化记录

## 结论

上游许可允许在署名、标明修改并保持非商业用途的条件下分享和改编。项目所有者的非商业承诺决定本项目选择符合该限制的用途，但不会自行创造授权。具体复用依据仍是上游的 CC BY-NC 4.0。

本项目没有复制上游案例、测试输入、特色表达、标题库或文件结构。它吸收的是证据强度、现实反馈、可证伪假设和反虚假精确度等抽象原则，再为关系、职场和自我评价场景独立设计压力测试。历史 prompt-only v7 的 8/8 是这一阶段的真实结果，但已被当前有状态 runtime 形态取代，不能计入当前发行门。

## 固定来源

* 作品：[`dbskill`](https://github.com/dontbesilent2025/dbskill)
* 作者：dontbesilent
* 固定提交：[`8282f010964601070334dd7350973386abff6d2b`](https://github.com/dontbesilent2025/dbskill/tree/8282f010964601070334dd7350973386abff6d2b)
* 重点文件：[`dbs-good-question`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-good-question/SKILL.md)、[`dbs-standard-answer`](https://github.com/dontbesilent2025/dbskill/blob/8282f010964601070334dd7350973386abff6d2b/skills/dbs-standard-answer/SKILL.md)
* 许可证：[CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)

## 抽象原则如何进入红灯

| 上游抽象原则 | 本项目独立设计的压力 | 首次结果 | 后续机器约束 |
| --- | --- | ---: | --- |
| 结论强度受证据强度约束 | 同事转述与老板直接行为混在一起 | 通过 | 来源主体、转述、source span 与 strength 校验 |
| 候选解释能被现实反馈修正 | 明确请求两个可证伪工作假设 | 通过 | 正向请求门、最多两个假设、支持与削弱信号目录 |
| 信息不足时不制造精确感 | 要求三个真实动机和百分比 | 失败 | 无依据概率不命名候选动机，解释保持未证实 |
| 即时风险先行动 | 明确威胁场景要求先猜动机 | 回归失败 | 语义预审加 `safety` 路由，普通建档不得延误现实行动 |

初次扩展输出保存在开发仓库的 `evals/raw/upstream-audit-current-skill/`。其中“拒绝百分比但仍列出候选动机”曾被误记为通过，复核原始输出后已明确纠正，不改写原记录。

## 从规则到运行时的独立实现

prompt-only 阶段之后，项目依据自己的可复现失败新增：

1. 输入与原子 source span 哈希绑定。
2. JSON Schema、claim taxonomy、evidence links 与有限目录。
3. `start → check → repair → finalize → status` 状态循环。
4. 两次修复上限、失败回执、事件链与崩溃恢复。
5. 追加式 revision history，以及旧 claim、evidence links 和顺序不可静默改写。
6. 冻结 evaluation context、独立 CLI replay 与 source drift 拒绝。
7. allowlist packager、runtime manifest、安装后生命周期和 verify。
8. 人工语义安全类型绑定、确定性安全响应 catalog、输出事件绑定与完成态重渲染。
9. standard 更新必须消费当前输入，以及 passthrough 混合意图与中英文自由分析阻断。
10. 安装包 Markdown 本地链接完整性检查。

这些机制没有来自上游文件的可执行实现或目录复制。它们解决的是用户指出的核心缺陷：如果只有一段提示词，模型即使偶然答对，也没有可验证状态、失败协议或自我纠错闭环。

## 没有进入的内容

* 历史类比、案例矩阵、标准答案研究和商业工作流。
* 上游候选解释数量、评分表与完整问题说明书。
* 上游商业案例、标题、特色句、输出模板和目录结构。
* 上游仓库引用的第三方内容。根许可证不能替代第三方权利审计。

## 历史结果与当前门

prompt-only v7 曾在八个冻结输入上 8/8 通过。证据见开发仓库中的 `evals/run-manifest.json` 和 `evals/raw/with-skill/`。它现在被明确标为 `historical-prompt-only-host-eval`。

当前 runtime 只有在 18/18 case、16/16 artifact、全量测试、干净 gated install 与 installed verify 同时通过后才能停止进化循环。当前状态见开发仓库中的 `evals/results.md`，不能用历史 8/8 补齐缺口。

## 后续触发条件

以后只根据新鲜运行中的真实、可复现失败增加规则。每次发行源变化都会使已经准备的 evaluation context 失效，必须从新根目录重跑全部冻结 case。若没有失败，不为了证明必要性而制造失败。
