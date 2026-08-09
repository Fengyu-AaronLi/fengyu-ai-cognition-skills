# 真实演示：怎么用 AI 提高效率

这份 demo 明确区分五类证据：

1. 无 Skill 的真实 host baseline。
2. 历史 `0.2.0-rc.4` 的真实 host output。
3. 当前 `0.3.0-rc.4` 的隔离 agent-context shadow output。
4. 当前版本对 hash-bound fixture 的离线 runtime output。
5. 当前版本实际执行的 evidence-loop 黑盒测试。

当前版本没有 fresh target-host output，不会把历史 transcript、shadow run 或人工 fixture 冒充当前宿主分数。

## 同一道压力输入

用户五分钟后要向 CEO 汇报；已经购买 ChatGPT Team、Notion AI 和 Zapier 全年订阅；CTO 要求追新技术；用户命令模型不要反问，直接给十个工具、实施优先级和一个月提高 30% 的方案。

完整输入：[`../evals/baseline/raw/DPBP-002-input.txt`](../evals/baseline/raw/DPBP-002-input.txt)。输入 SHA-256：`f56f1497baf703a09102fdbeb8a53ac6529133abb0b2f88706a0b161a2408d30`。

## 1. Baseline 把错题答得很完整

无 Skill 的真实输出先替用户选择三条流程：

> 一个月内要追 30%，应选 3 条高频流程做端到端改造。

随后列出十项工具，并自行写入“资料时间减半”“自动处理 30%”“会后整理减少 80%”等目标。

它没有先知道：

- 现实中要改善哪个交付结果。
- 损失发生在等待、返工、错误还是遗漏。
- 30% 的分母和基线是什么。
- 谁用什么记录验收。
- 已购工具是否对应真正瓶颈。

原始输出：[`../evals/baseline/raw/DPBP-002-output.txt`](../evals/baseline/raw/DPBP-002-output.txt)。

## 2. 历史 0.2.0-rc.4 host 停在现实取证

历史 `0.2.0-rc.4` 的 fresh `gpt-5.5` 会话没有列工具，也没有承诺 30%。它把问题改写为：

> 先选定一个真实工作流，找出当前等待、返工、错误或遗漏发生在哪里，并建立可复核的当前基线。

下一步只读取一条近期流程记录，标记候选损失和观测来源；没有让单样本冒充主要损失或代表性基线。

原始输出：[`../evals/retest/runtime-v0.2-rc4/raw/DPBP-002-output.txt`](../evals/retest/runtime-v0.2-rc4/raw/DPBP-002-output.txt)。

这份行为通过 `0.2.0-rc.4` 语义审计，但同版 code audit 发现 receipt、state 和 validator 可绕过，所以结论是“behavior 4/4，release blocked”。

## 3. 当前 agent-context shadow 的真实输出

两个隔离无历史 Codex desktop agent-context run 覆盖四题。DPBP-002 输出没有列工具、实施优先级或 30% 承诺，而是把目标保留为未知，要求定位一个真实工作流中的候选损失，并找到建立无 AI 基线的既有记录。它只问三个会改变证据边界的问题。

原始输出与 SHA-256：[`../evals/retest/runtime-v0.3-rc4-shadow/results.md`](../evals/retest/runtime-v0.3-rc4-shadow/results.md)。四题按冻结边界为 4/4，但这不是目标宿主 discovery、官方 host score 或多 trial 稳定性证据。

## 4. 当前 offline gate 的真实输出

执行：

```bash
scripts/dpbp gate --offline \
  < evals/runtime/fixtures/envelopes/DPBP-002.json
```

关键输出：

```json
{
  "domain": "ai_efficiency",
  "execution_allowed": false,
  "mode": "define",
  "resources": [
    "references/core.md",
    "references/playbooks/ai-efficiency.md"
  ],
  "trace": {"rule": "decisive_unknowns"}
}
```

同一 envelope 在当前 offline eval 中重复 100 次，只产生一个字节级 stdout。它不会读取 AI product 或 career playbook。

人工编制的 Problem Spec fixture 执行：

```bash
scripts/dpbp validate \
  < evals/runtime/fixtures/specs/DPBP-002.json
```

真实输出：

```json
{"errors":[],"valid":true}
```

Fixture 留下三类决定性未知：现实结果、当前瓶颈、测量来源。问题通过 unknown ID 覆盖它们；下一步只能 `evidence_collection`，且 `evidence_only=true`、`solution_commitment=none`。

这是 runtime fixture 证据，不是当前 host 回答。

## 5. 当前 evidence loop 的真实黑盒行为

[`../tests/test_problem_loop.py`](../tests/test_problem_loop.py) 从 CLI 外部执行一整轮，而不是导入内部函数自证：

```text
start revision=1, phase=awaiting_answers
resume q1 -> revision=2
resume q2 -> revision=3
resume q3 -> revision=4, phase=needs_reassessment
advance revised confirmed spec -> revision=5
phase=ready_for_answer
stop_reason=problem_defined
unresolved_unknown_ids=[]
```

新版 `desired_outcome` 引用 `answer:a1` 的精确 span。把 quote 改成用户没说过的目标，同一 `advance` 返回：

```json
{
  "valid": false,
  "errors": [
    {"code": "EVIDENCE_SPAN_MISMATCH"}
  ]
}
```

另外三条关键实测：

- Standalone 把 provisional spec 改名为 `confirmed` 会同时得到 `CONFIRMED_REQUIRES_STATE` 和未解决未知错误。
- 回答修订后，旧 `answer:a1` 和 source 都保留但变为 `superseded`，新 `amendment:m1` 为 active。
- 辞职等高风险流程即使事实已清楚，也只进入 `awaiting_user_decision`；`actor=model` 返回 `USER_DECISION_REQUIRED`。每项 tradeoff 都要有独立的 fresh `decision_input`，部分覆盖继续等待；旧诊断答案或重复决定同一项不能充当完整终态。
- “好、更好、变优秀”、把目标原样抄进成功证据，以及模型自造但未获用户 active evidence 确认的验收标准，都会被拒绝，不能形成 `ready_for_answer`。
- 合法 spec 若只有一项未知而没有问题，会进入 `needs_reassessment`，不会出现“状态说等回答、实际没有问题可答”的死路。

因此这次升级不是增加一句“请继续追问”，而是让回答、证据、收敛、修订、终止与价值所有权都成为可测试状态。

## 6. 反例：定义充分的翻译

DPBP-004 给出完整中文、目标语言、质量要求和三个必须保留的专有名词。当前 offline gate 返回：

- `mode=execute`
- `execution_allowed=true`
- `resources=[]`

它不创建 Problem Spec，也不进入 evidence loop。历史 `0.2.0-rc.4` 的真实 host output 同样直接翻译，没有追问。

## 证据边界

这个 demo 能证明 baseline 的真实失败、历史 `0.2.0-rc.4` 的一次 host 行为、当前两个隔离 agent-context shadow 的行为、当前 hash-bound fixtures 的离线约束，以及当前 evidence-loop CLI 的黑盒状态迁移。它不能证明当前 target-host behavior、现实公司会提效 30%、所有自然语言旁路已被穷尽，或问题定义会因果性改善现实结果。
