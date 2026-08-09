# Fengyu AI Cognition Skills

这是风谕 AI 认知 Skill 的候选仓库。目标不是收集一批长提示词，而是把容易被模型绕过的认知边界做成可审计、可复测、能明确失败的 Agent Skill。

“候选”指的是发行状态，不是存放位置：工程验收尚未走完，不代表仓库没有公开。

**先读这个**：[`docs/使用说明.md`](docs/使用说明.md) 用普通话讲清楚四个 Skill 各自拦什么、什么时候会触发、装完第一句话该说什么，以及它们明确不做什么。

## 当前状态

各组件的工程验收进度不同，准确状态以各 Skill 目录内的 `README.md` 与 `evals/` 中的机器报告为准。根级不对“是否已通过真实使用验收”做统一承诺。

两个措辞边界始终有效：

1. **不要说“已开源”。** 根级许可为 CC BY-NC 4.0，禁止商业使用，因此不符合 [OSI 开源软件定义](https://opensource.org/osd)。准确说法是“非商业开放源码”或 source-available。
2. **不要把“测试全过”说成“已验证有效”。** 测试证明结构契约成立，不证明现实效果。

仓库内保留的是结论性报告与可复现命令。评测过程中体积达 200MB 量级的原始跑批产物（含本机绝对路径与 host session ID）不纳入版本控制，可按报告中的命令重跑复现。

## 当前组件

| Skill | 解决的问题 | 当前形态 |
|---|---|---|
| [`separating-facts-from-stories`](skills/separating-facts-from-stories/README.md) | 防止把观察、感受、解释和动机推断混成事实 | Skill/validator 4.4.0、schema 3.2.0、workflow 3.1.0、loop schema 1.1.0，本地候选；发行状态只认 controller 生成的具名 gate |
| [`breaking-identity-labels`](skills/breaking-identity-labels/README.md) | 把身份标签改写成可观察行为与窄实验 | V2 alpha，本地运行时 |
| [`auditing-ai-claims`](skills/auditing-ai-claims/README.md) | 用状态循环冻结输入、保存来源并阻止越过证据范围的结论 | V3.1，本地候选工作台，NO-GO |
| [`defining-problems-before-prompts`](skills/defining-problems-before-prompts/README.md) | 在执行前检查现实结果、决定性未知、成功证据和价值取舍；清晰任务直接放行 | 0.3.0-rc.4，证据循环与失败演化 workflow，本地候选 |

每个目录自己的 `README.md` 说明安装、命令、验证、局限和回滚。目录内最近的 `LICENSE` 与 `PROVENANCE.md` 优先描述该组件的权利边界。

## 一个 Skill 至少应当留下什么

仓库不把“模型读了一段规则后答得更好”单独视为成熟 Skill。可执行组件应尽量提供：

- 机器可读的输入、中间状态与输出契约。
- 能明确拒绝违规状态的 gate 或 validator。
- 保存原始输入和失败输出的同题回归。
- 对应触发与不触发场景。
- 可复现的命令、环境、错误码和发行边界。
- 明确写出哪些判断仍只能由模型或人完成。

不同认知任务需要的运行时并不相同，这份清单是审计方向，不是要求每个 Skill 复制同一种目录模板。

## 授权与来源边界

根级默认许可为 [CC BY-NC 4.0](LICENSE)，允许在署名、链接许可、标明修改并保持非商业用途的前提下分享与改编。若某个 Skill 目录内另有 `LICENSE`，以距离该文件最近的许可证为准。

dontbesilent dbskill 的具体改编组件、固定提交、进入范围与未采用内容，以 [`NOTICE.md`](NOTICE.md)、[`provenance.yml`](provenance.yml) 及各 Skill 目录内最近的 `LICENSE` 和 `PROVENANCE.md` 为准。本项目不暗示上游作者认可或背书。

用户承诺非商业并不会自行创造许可。可改编 dontbesilent 固定版本的依据是其 CC BY-NC 4.0 许可；每位再使用者仍须自行遵守署名、修改说明和 NonCommercial 条件。

由于 CC BY-NC 限制商业使用，本项目更准确的称呼是“非商业 source-available 候选”。它不符合允许自由商业再分发的 [OSI 开源软件定义](https://opensource.org/osd)。

## 隐私与贡献

请勿把真实私人聊天、可识别个人身份的信息、医疗或法律材料、安全事件细节、公司机密、账号凭证或 API 密钥放入可发行样例。贡献要求见 [`CONTRIBUTING.md`](CONTRIBUTING.md)，安全规则见 [`SECURITY.md`](SECURITY.md)，完整署名见 [`NOTICE.md`](NOTICE.md)。
