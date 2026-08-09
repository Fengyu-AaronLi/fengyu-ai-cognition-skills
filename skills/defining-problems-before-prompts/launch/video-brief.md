# 视频 Brief：提问前定义问题

类型：观点地图、逻辑骨架与证据调度，不是逐字稿。  
状态：本地候选素材，未归档、未发布、未创建或修改 VP、HL、TP。

## 观点地图

**核心命题**

AI 让答案越来越便宜，但它没有让“什么才算答对”变便宜。

**因果链**

1. 模型可以快速补齐工具、功能、技术栈、排期和漂亮数字。
2. 用户若没有定义现实结果、成功证据和不可接受代价，模型补得越完整，错题越像正解。
3. 把原问题润色成专业 prompt 不会修复这个错误，只会提高错误答案的完成度。
4. 真正有用的 Skill 要能执行路由、证据锚定、验证、停止边界和恢复，而不只是劝模型“先想清楚”。
5. 好的拦截不能停在“信息不足”，还要给一个低成本、可逆、能从现实取得证据的下一步。
6. 问题已经清楚时必须放行，否则问题定义本身会变成官僚流程。

## 逻辑骨架

### 1. 用具体错题开场

问题：“怎么用 AI 提高效率？”

压力条件：CEO 五分钟后看方案；公司已买三套 AI 软件；CTO 命令追新技术；用户要求十个工具、一个月提高 30%、不要反问。

无 Skill 的真实 baseline 直接选择三条流程、列十项工具，并编入减半、30%、50%、80% 等结果。

画面重点：方案看起来很完整，但没有任何人说清 30% 的分母。

### 2. 暴露错题

缺的不是第十一个工具，而是四个定义：

- 要改变哪个现实交付结果。
- 当前损失真正发生在哪一步。
- 用什么记录建立基线。
- 什么证据算成功，什么代价不能接受。

工具采购、汇报完整度和“追上最新技术”都可能是代理问题。

### 3. 展示行为差异

历史 `0.2.0-rc.4` fresh host 输出没有列工具，只把问题改到现实流程：

> 先选定一个真实工作流，找出当前等待、返工、错误或遗漏发生在哪里，并建立可复核的当前基线。

下一步只读取一条近期流程记录，用于标记候选损失和观测来源。单个样本不被宣传为主要损失或代表性基线。

必须同时在画面注明：`0.2.0-rc.4` 行为审计 4/4，但 code audit blocked，不能作为发行版本。

当前 `0.3.0-rc.4` 的隔离 agent-context shadow 面对同一输入，也没有列工具或承诺 30%，而是要求明确真实工作流、候选损失和无 AI 基线。原始输出已保存，但画面必须标成 `current agent-context shadow`：两个隔离无历史 run 覆盖四题得到 4/4，不是目标宿主 discovery、官方 host score 或多 trial。

### 4. 展示它为何不只是 prompt

用极短的运行图，不展示大段规则：

```text
原始请求
  ↓ request envelope
离线 gate
  ├─ execute：直接做，resources=[]
  ├─ define：加载对应 playbook
  └─ defer_to_user：价值决定留给人
       ↓
Problem Spec + exact evidence spans
       ↓
validator 重新计算并绑定 gate receipt
       ↓
deterministic renderer / evidence loop
       ↓
answer → reassess → advance → stop
```

口径：当前 `0.3.0-rc.4` 是短 dispatcher 加标准库 CLI、三份 Schema、固定 routes、progressive references、receipt binding、validator、renderer 和证据状态机。用户回答会成为可引用 evidence；答案可以修订但不会抹除；`confirmed` 的目标和成功标准必须绑定后续 active 用户证据，不能由模型悄悄补齐；轮次耗尽会停止。高风险流在事实定义后对每一项 tradeoff 另等一条 fresh 用户决定输入，部分覆盖继续等待；selected span 必须形成正向承诺，“我决定不了”、重复决定同一取舍、旧诊断答案和背景事实都不能冒充完整终态。

维护者侧还有独立 workflow：真实 failure → base RED → candidate GREEN → 声明式复现 receipt → reviewer promotion → manifest proposal。三份 receipt 必须绑定同一 manifest 输入，ledger 还绑定派生 state checkpoint；sealed holdout、iteration budget 与 saturation stop 阻止“只因为多改了几轮就声称进步”。该工具不自动改 Skill 或 manifest；无密钥哈希不能抵抗同时重写 state 与 ledger，actor ID 与 artifact hash 也只是声明式约束，不是身份认证。

它仍不证明模型知道人的真实目标。语义判断由人或模型提出，运行时负责拒绝已知结构和语义旁路。

### 5. 提升到核心判断

AI 可以让 how 越来越便宜，但 what、done 和 unacceptable cost 仍需要人定义。

研究只提供窄范围背景：

- Anthropic 对 2025 年 10 月至 2026 年 4 月约 400,000 个 Claude Code 交互会话、约 235,000 人的观察性研究发现，用户承担多数规划判断，较强任务领域理解与更高会话成功率相关。对象是 agentic coding，研究排除了第三方 IDE、SDK 和 headless 使用；会话成功不等于长期现实结果，不能外推到所有职业或全部 AI 使用。[来源](https://www.anthropic.com/research/claude-code-expertise)
- Anthropic 的 agent eval 工程指南把 task 写成有明确输入和成功标准的测试，并强调 outcome、触发与非触发用例和多次 trial。它是工程实践指南，不是本 Skill 有效性的实验。[来源](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- Microsoft Research 调查 319 名知识工作者的 936 个自报实例。参与者报告部分认知工作转向验证、整合和监管；对 GenAI 越有信心与越少自报批判投入相关。研究为英文、自报、横截面和相关性设计，不能写成“AI 导致批判思维退化”。[来源](https://www.microsoft.com/en-us/research/publication/the-impact-of-generative-ai-on-critical-thinking-self-reported-reductions-in-cognitive-effort-and-confidence-effects-from-a-survey-of-knowledge-workers/)

视频命题是对这些有限证据和本地 eval 的综合判断，不是任何一篇研究的直接结论。

### 6. Solution

回答前过三道门：

1. 这道题真正想改变什么现实结果？
2. 什么证据出现才算成功，什么代价不能接受？
3. 当前问题得到完美答案后，现实结果是否必然改善？

若决定性信息未知，停止补齐方案，做一个可逆取证动作。若任务已经清楚，直接执行。

### 7. 反例收口

同一 Skill 面对“把这段 300 字中文翻成自然英文，保留三个专有名词”时，离线 gate 返回 `execute` 和空引用列表。历史 `0.2.0-rc.4` 的真实 host 输出也直接翻译。

这证明目标不是“凡事先开会”，而是在错题会造成现实代价时拦截。

## 真实演示与证据调度

- Baseline 输入：[`../evals/baseline/raw/DPBP-002-input.txt`](../evals/baseline/raw/DPBP-002-input.txt)
- Baseline 输出：[`../evals/baseline/raw/DPBP-002-output.txt`](../evals/baseline/raw/DPBP-002-output.txt)
- `0.2.0-rc.4` 真实 host 输出：[`../evals/retest/runtime-v0.2-rc4/raw/DPBP-002-output.txt`](../evals/retest/runtime-v0.2-rc4/raw/DPBP-002-output.txt)
- `0.2.0-rc.4` split verdict：[`../evals/retest/runtime-v0.2-rc4/results.md`](../evals/retest/runtime-v0.2-rc4/results.md)
- 当前 agent-context shadow 原始输出与降级说明：[`../evals/retest/runtime-v0.3-rc4-shadow/results.md`](../evals/retest/runtime-v0.3-rc4-shadow/results.md)
- 当前离线 runtime 报告：[`../evals/runtime/results.json`](../evals/runtime/results.json)
- 当前 evidence-loop 黑盒测试：[`../tests/test_problem_loop.py`](../tests/test_problem_loop.py)
- 当前 evolution-loop 黑盒测试：[`../tests/test_evolution_loop.py`](../tests/test_evolution_loop.py)
- `0.2.0-rc.6` host blocked 记录：[`../evals/retest/runtime-v0.2-rc6/results.md`](../evals/retest/runtime-v0.2-rc6/results.md)

画面建议：

1. 左侧滚动 baseline 的十项工具和百分比。
2. 右侧只留下“现实结果 / 瓶颈 / 测量来源”三个空位。
3. 切到当前 agent-context shadow 的现实流程问题，并明确它不是 target-host score。
4. 再切到当前 gate receipt、validator PASS、回答进入 evidence log、tampered span 被拒绝和 `ready_for_answer` stop state。
5. 最后闪过 evolution hash chain 与 `EVOLUTION_STOPPED`，强调自进化也有停止条件。
6. 屏幕角标始终区分 `baseline host`、`0.2.0-rc.4 host`、`current agent-context shadow`、`current offline fixture/state test`，不混证据版本。

## 反例与反证

1. 不是所有问题都需要消解。清楚翻译、计算和格式转换直接做。
2. 不是 AI 永远不能提出目标。候选目标可以存在，但必须标为假设，不能冒充用户事实。
3. 问题定义也会成为拖延。最多三个高价值问题，并给一个停止在取证阶段的现实测试。
4. 单个样本只能暴露候选损失，不能证明主要损失或代表性基线。
5. Runtime 能拒绝已知绕法，不能穷尽自然语言语义，也不能判断用户真正重视什么。
6. `0.2.0-rc.4` 的 4/4 只属于 `0.2.0-rc.4`；当前 shadow 4/4 只属于两个隔离 agent-context run；`0.2.0-rc.6` fresh host 为 4 次尝试、0 次完成；当前版本尚无 fresh target-host 分数。

## 钩子方向

1. **漂亮错题**：普通 AI 用十项工具和多个百分比，把没定义的效率题回答得很专业。
2. **成本倒置**：答案成本趋近于零，定义“什么算答对”仍然昂贵。
3. **反提示词**：真正稀缺的不是 prompt 技巧，而是知道哪道题不该直接回答。
4. **真假 Skill**：一段规则只能劝模型；可执行 Skill 能 gate、validate、render、resume。
5. **简单反例**：面对清楚翻译直接放行，证明它不是增加流程。

## 标题方向

视频标题候选，均不超过 20 字：

- AI会把错题答得很漂亮
- 答案便宜了，答对没有
- 这不是提示词，这是问题门
- AI最会回答错误问题
- 别让AI替你定义成功

封面方向：

> 越会回答  
> 越会跑偏

## 不交付的部分

- 不写完整逐字稿。
- 不替创作者补个人体感或个人经历。
- 不运行归档或发布流程。
- 不写入已发布文案。
- 不创建或修改 VP、HL、TP。
