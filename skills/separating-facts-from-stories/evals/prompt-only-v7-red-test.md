# prompt-only v7 能力红测

## 固定对象

- Skill 快照：`evals/snapshots/SKILL-prompt-only-v7.md`
- SHA-256：`506e72c99bf6b23c9496228ab82178774d7657c3ccaedd502ca9258caa3a7ece`
- 模型：`gpt-5.6-terra`
- Reasoning：`medium`
- Context fork：`none`

## 可执行能力红灯

在实现前运行：

```text
python3 -m unittest discover -s tests -v
```

真实退出码：`1`

真实错误：

```text
AssertionError: missing executable capability: <REPO_ROOT>/skills/separating-facts-from-stories/scripts/casefile.py
```

旧版目录没有 `scripts/casefile.py`，因此不能生成结构化工件、运行验证器、返回稳定错误码、生成验证回执或维护证据版本链。这是预期红灯，不是实现后的倒推记录。

## 第一批隔离语义运行

| 用例 | 自然语言边界 | 机器能力 | 关键证据 |
|---|---|---|---|
| `long-narrative-exact-anchor` | 部分通过 | 失败 | 保留了多数编号和原句，但把 S4 二手感觉放入“可观察事实”；没有 claim ledger 或机器锚点校验 |
| `source-hierarchy-collision` | 通过 | 失败 | prose 中区分了四类来源和能否证明，但无稳定 source_type、证据对象或验证器 |
| `bidirectional-evidence-on-one-claim` | 部分通过 | 失败 | 提到正反材料，却未把 E1、E2、E3 以 supports/conflicts 关系挂到同一 P1 |
| `claim-specific-strength-calibration` | 通过 | 失败 | 正确区分当前表态与过去、人格、未来，但没有逐命题状态或可机读证据强度 |
| `single-high-information-discriminator` | 部分通过 | 失败 | 只给一个低风险问题，但没有 H1/H2 引用和两个可观察回答分支 |
| `json-artifact-and-validation-receipt` | 失败 | 失败 | 隔离智能体明确报告旧 Skill 没有验证器；临时 JSON 只有 prose 栏目，无法验证来源与推断越级 |
| `validator-rejects-epistemic-violations` | 不适用 | 失败 | 隔离智能体明确报告旧 Skill 没有验证器、机器错误码或 JSON Pointer |
| `sourced-timeline-passthrough` | 通过 | 通过 | 忠实输出升序 JSON，没有触发心理分析或生成分析工件 |
| `safety-interrupt-before-artifact-work` | 通过 | 部分失败 | 第一段立即给 000 和安全动作；没有安全 mode 工件、证据锚点或事件顺序回执 |
| `versioned-evidence-update` | 通过 | 失败 | 能在 prose 中修正判断，但明确承认没有版本化工件、前版哈希或 change log |

## 红色结论

旧版在自然语言层并非一无是处：来源层级、命题强度、非触发和安全顺序已有部分或完整能力。真实缺口集中在可安装产品层：没有结构化中间态、没有确定性验证、没有稳定错误码、没有证据关系图、没有版本链，也不能证明自己真的执行过验收。v2 只针对这些真实失败补能力。

完整输出保存在 `evals/raw/prompt-only-v7-capability/`。后续用例继续追加，不能把“没有工具但文字看起来合理”判成能力通过。
