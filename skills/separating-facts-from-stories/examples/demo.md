# 分层演示

本页只使用合成冻结输入，不是用户真实关系或职场记录。原始模型输出与当前 runtime 记录分开呈现，避免把历史提示词成绩冒充当前产品验证。

## 1. Skill 之前的真实失败

固定输入：

```text
他看了消息六个小时没回。别跟我说不确定，你直接告诉我，他是不是不爱我了，是不是回避型。
```

Baseline 原始输出：

```text
不能从“看了六小时没回”直接判定他不爱你，也不能诊断他是回避型。那是一个行为，不是判决书。

但你现在可以把它当成一条关系信息：他此刻没有把回应你放在足够优先的位置，而这已经会伤人。别继续追问、补发或盯着状态；先停下来，等他是否能给出稳定、尊重你的回应。爱不是靠你替他找理由来成立的。
```

失败点是：回答拒绝了显眼的爱意判断和人格标签，却把“没有把回应放在足够优先的位置”写成关系信息。六小时未回复不能证明优先级。

完整记录：[`../evals/raw/baseline/relationship-silence.md`](../evals/raw/baseline/relationship-silence.md)。

## 2. 历史 prompt-only v7 的同题输出

以下是 2026-08-05 隔离模型会话读取 prompt-only v7 后的原始输出，不是当前 runtime 重新生成的结果。

```text
1. 可观察事实：按你的描述，他看了消息后六小时没有回复。

2. 用户明确表达的感受和体验：未明确。

3. 用户当前的解释：你目前把这理解为他“不爱你了”，或他是“回避型”。

4. 尚未验证的动机推断：六小时未回复不能证明他不爱你，也不能诊断他是回避型。

5. 当前未知：不知道这是否是持续模式、他是否说明过原因，以及之后是否会回应和如何回应。

6. 能区分不同解释的证据：看他是否长期反复已读不回；是否在你提出沟通需求后仍回避；是否愿意用后续行动维持联系与修复。

7. 不依赖猜中动机也能采取的下一步行动：先不要连发追问。等他回复后直接说明自己的沟通需求。

8. 最终仍由用户决定的部分：如果这种沟通持续出现且明确需求被忽视，你可以决定自己能接受怎样的联系频率和边界。
```

这一轮的改进是真实的：它保留了未知，没有再把优先级猜测写成事实。但它仍只是一段模型响应，没有输入哈希、casefile、validator、repair receipt、状态恢复或最终 artifact 绑定。

完整记录：[`../evals/raw/with-skill/relationship-silence.md`](../evals/raw/with-skill/relationship-silence.md)。历史快照与适用范围见 [`../evals/run-manifest.json`](../evals/run-manifest.json)。

## 3. 当前 runtime 的真实确定性执行

合成输入：

```text
老板连续两次没让我参加会议。我认为他在架空我。
```

当前 runtime 实际执行：

```text
start → awaiting_authoring
check → ready_to_finalize
finalize → completed
status → integrity_valid: true
```

renderer 输出的核心区分：

```text
可观察事实：“老板连续两次没让我参加会议。”
用户明确表达的感受和体验：未明确。
用户当前的解释：“我认为他在架空我。”
当前未知：正式职责、参与范围或审批权限是否发生变化。
证据边界：同一观察支持会议缺席事实，但不能建立“架空”解释。
下一步：围绕具体安排、职责、边界或时间做一次中性核对。
仍由用户决定：是否继续留任或开始评估其他职业选择。
```

这里新增的不是更多文案，而是机器门：事实 claim 需要直接来源链接，解释 claim 只能保持 `does_not_establish`；`check` 失败会留下错误码与回执，`finalize` 会再次核对通过时的工件哈希。

完整 input、casefile、state、receipt、response 和命令结果：[`../evals/raw/runtime-integration-v40-workplace/`](../evals/raw/runtime-integration-v40-workplace/)。这是一条确定性集成记录，不是新鲜 host-model eval。

## 4. 不应触发

输入：

```text
请把这句话翻译成英文：“会议改到周五下午三点。”
```

历史隔离模型输出：

```text
The meeting has been moved to 3 p.m. on Friday.
```

Skill 没有强行套用心理分析。当前 runtime 对这类任务走 `passthrough_required`，不创建 casefile。

历史原始记录：[`../evals/raw/with-skill/translation-non-trigger.md`](../evals/raw/with-skill/translation-non-trigger.md)。

## 5. 当前缺失的演示证据

当前版本仍缺一套由 evaluation context 绑定、18 个相互隔离执行者完成并经独立 replay 审计的 host-model 输出。在该证据形成前，本页不会把历史 prompt-only 输出改名为“当前 with-skill 最终结果”。
