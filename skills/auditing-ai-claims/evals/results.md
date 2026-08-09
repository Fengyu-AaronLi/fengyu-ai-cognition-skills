# 3.1.0 当前发行评估

## 当前结论

发行状态：**NO-GO / local candidate**。

3.1.0 已从规则型提示词升级为带持久状态、不可跳过 Gate、来源事务、反证回路和确定性 replay 的本地审计工作台。工程回归、27 文件白名单安装、安装后离线 unknown 闭环和三个指定一手页面的真实来源闭环已经通过。

C01 至 C16 尚未在看不到开发上下文的新鲜模型会话中整套重跑，正向自动发现与负向不触发也未重跑。因此当前不能给出 V3.1 行为分数、baseline 改善率、自动发现 PASS 或公开发行结论。

## 当前证据门

| 证据门 | 状态 | 当前边界 |
|---|---|---|
| 工程回归 | PASS，187/187 | 运行时、状态机、网络、事务、回执认证、schema、安装器、渲染与失败门 |
| V3.1 发行契约 | PASS，11/11，包含在 187 项中 | 安装包公开契约与 3.1.0 运行时一致 |
| package contract | PASS，10/10，包含在 187 项中 | 27 文件白名单及元数据契约通过 |
| 干净安装 | PASS | source/target tree hash 完全相同，无 eval、tests、examples 或本地审计数据 |
| 安装后离线 unknown 闭环 | PASS | 没有来源时停在 `current_unknown`，完成 countercheck、Gate 与 replay |
| 三个指定一手来源 | PASS | 3 个 HTTP 200 回执、7 个精确绑定、3 个反证记录、Gate/replay PASS |
| C01 至 C16 新鲜行为 | NOT RUN | 0/16，不计分，不继承旧复测 |
| 语义盲评与逐案来源复核 | NOT RUN | 不生成平均分或失败率 |
| 正向自动发现 | NOT RUN | 安装成功不等于模型自动路由成功 |
| C04、C07 负向不触发 | NOT RUN | 没有把运行时的 scope 能力冒充发现层不触发 |
| 公开发行 | NO-GO | 未公开、未 push、未配置 remote、未声称已开源 |

## 工程证据

最终命令：

```bash
python3 -m unittest discover -s skills/auditing-ai-claims/tests -p 'test_*.py' -v
```

环境：macOS 26.5.2 Build 25F84，arm64，Python 3.14.4。代码完成后全量输出为 `Ran 187 tests in 19.411s`、`OK`；证据文档更新后的最终复跑为 `Ran 187 tests in 19.091s`、`OK`。终端摘要保存在 [`v3/final-regression-310.txt`](v3/final-regression-310.txt)。

本轮新增并关闭的运行级失败包括：

- 抓取超时原先可能退化为每次读取的空闲超时，而不是总截止时间。
- 进程在来源事务不同阶段崩溃时，可能留下无法收敛或无法追责的半提交状态。
- `next` 若携带原始候选文本，控制器可能把不受信内容错误拼接为命令。
- 判断、证据或来源变化后，旧反证记录可能被错误复用。
- `conflict_found`、`no_conflict_found` 和决定性状态需要与真实合格来源绑定。
- 报告同一来源承担多个证据用途时重复展示链接。

所有改动均先留下 RED，再实现并重跑全套。主要原始 RED 证据：

- [`v3/red-round-deadline-transaction.txt`](v3/red-round-deadline-transaction.txt)
- [`v3/red-round-next-safe-input.txt`](v3/red-round-next-safe-input.txt)
- [`v3/red-round-countercheck-state-machine.txt`](v3/red-round-countercheck-state-machine.txt)
- [`v3/red-round-countercheck-adversarial.txt`](v3/red-round-countercheck-adversarial.txt)
- [`v3/red-round-release-contract-v31.txt`](v3/red-round-release-contract-v31.txt)
- [`v3/red-round-source-transaction-abort.txt`](v3/red-round-source-transaction-abort.txt)

## 安装与离线体验

当前证据见 [`install-verification-310.md`](install-verification-310.md)。

| 字段 | 值 |
|---|---|
| 安装类型 | 27 文件白名单原子复制 |
| source/target tree SHA-256 | `af59523e87c587d39fb82d36077d2c76de88483ace48e29b08c968e2a026ab0f` |
| runtime / policy | 3.1.0 / 3.1.0 |
| YAML 元数据 | `YAML_OK` |
| 离线 bundle | `d5257262d07f4461b1142da97dc7049146879c40267b1db2796de74929f5529e` |
| Gate / next / replay | PASS / complete / PASS |

第一次验收夹具因使用不支持的 `price` 枚举被运行时拒绝，Gate 保持 FAIL；修正为 `quantitative_comparison` 后在全新工作区通过。失败没有被覆盖成成功。

## 指定一手来源复验

当前证据见 [`v3/live-source-310.md`](v3/live-source-310.md)。

OpenAI、NIST、Microsoft Research 三个指定页面均由运行时实际抓取，HTTP 均为 200，`support_eligible=true`。三条主张共绑定 7 个精确选择器，并各自完成反证回路。最终 bundle 为 `ef6749446f2bc524a4dc9ae27b668612097266a268cd31307f31d6e4a383c8c1`，Gate、complete 状态和 replay 均 PASS。

Microsoft 调查只被写成 319 名知识工作者自报调查中的 association，没有升级为“AI 会让所有人变笨”的因果结论；OpenAI 文章也没有被换算成现实回答的统一错误率。

## V3.1 新鲜行为复测矩阵

以下均为基础设施 **NOT RUN**，不是 0 分，也不是 Skill 行为失败。

| 案例 | 审计目标 | 预期路由 | 新鲜模型回答 | 运行时工件 | 语义盲评 | 来源复核 |
|---|---|---|---|---|---|---|
| C01 | 伪造论文、作者、DOI | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C02 | 相关性升级因果 | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C03 | 无日期的当前价格 | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C04 | 明示观点与隐喻 | 不触发 | NOT RUN | 应无工作区，未验证 | NOT RUN | 不适用 |
| C05 | 公司自述当独立证据 | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C06 | 来源与主张范围不匹配 | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C07 | 关系动机和个人感受 | 不触发 | NOT RUN | 应无工作区，未验证 | NOT RUN | 不适用 |
| C08 | 高风险专业边界 | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C09 | 只看标题不看正文 | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C10 | 二手来源支撑核心事实 | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C11 | 官方页面身份不匹配 | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C12 | 事实与观点混合 | 部分触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C13 | 模糊总括判词 | 触发并先定义 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C14 | 清晰事实控制 | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C15 | 证据到行动越界 | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C16 | 多链接同源洗白 | 触发 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |

初始四个无 Skill baseline 的原始输出仍保存在 `baseline/raw/`。早期 `retest/raw/` 输出属于旧 Skill 和旧协议，不能迁移为 3.1.0 分数。

## 解除 NO-GO 的剩余门槛

1. 用冻结案例在看不到 Skill 开发过程的新鲜会话中运行 C01 至 C16。
2. 分离执行语义盲评与逐案来源复核。
3. 在真实安装环境验证正向自动发现，以及 C04、C07 的发现层不触发。
4. 任何 allowlist 文件、运行时、案例或评测协议变化后，重跑 187 项工程测试、干净安装、真实来源和全部行为案例。
5. 只有上述证据齐全后才重新判断是否可对外发行。

当前没有公开、没有 push、没有配置 remote，也没有声称已开源。

---

# 历史归档：2.2.0 Final Evaluation

> 以下内容原样保留为旧版本开发记录，不代表 3.1.0 当前状态。当前结论只以上文为准。

## 总结

发行结论：**NO-GO / local candidate**。

2.2.0 已完成可执行运行时、工程回归、独立安全复验、白名单安装、离线 unknown 闭环和三个指定一手页面的真实来源烟雾测试。C01 至 C16 的新鲜会话、语义盲评、逐案来源复核和自动发现因 Codex CLI usage limit 尚未运行，因此不能给行为分数、baseline 改善率或发行 PASS。

## 分栏结果

| 证据门 | 状态 | 结论边界 |
|---|---|---|
| 工程测试 | PASS，88/88 | 运行时、CLI、schema、安装器和失败门通过 |
| 独立阻断复验 | PASS，P0=0，P1=0 | 已发现的最小反例均关闭，不保证不存在未知缺陷 |
| 白名单安装 | PASS | 15 文件真实目录复制、无符号链接、source/target hash 一致 |
| 离线 unknown fixture | PASS | 无来源时能诚实停在 `current_unknown` 并完成 gate/replay |
| 指定一手来源烟雾测试 | PASS | 3 个页面实际抓取，5 条主张、6 条精确绑定，gate/replay PASS |
| C01 至 C16 行为 | NOT RUN | 没有模型最终回答，不计分 |
| 语义盲评 | NOT RUN | 不生成平均分或失败率 |
| 逐案来源复核 | NOT RUN | 不把三页 smoke 当作 16 案来源复核 |
| 自动发现与不触发 | NOT RUN | 安装成功不等于发现成功 |
| 发行 | NO-GO | 未公开、未 push、未创建 remote、未声称已开源 |

## 工程与安全证据

最终命令：

```bash
python3 -m unittest discover -s skills/auditing-ai-claims/tests -v
```

环境：macOS 26.5.2 Build 25F84，arm64，Python 3.14.4。最终结果为 88/88 PASS。最后一轮只读对抗复验再次运行全套测试和原始最小反例，结论为 P0 无、P1 无。

RED 原始摘要：

- `v2/red.txt`
- `v2/red-integrity.txt`
- `v2/red-workflow.txt`
- `v2/red-orchestration.txt`
- `v2/red-report-contract.txt`
- `v2/red-release-blockers.txt`

后四轮独立审查实际打出的发布级问题包括：整目录安装泄露、模板与 gate 不一致、路径穿越、大小写碰撞覆写、私网重定向、记录 IP 与实际 pinned IP 不一致、gate 篡改、stale replay 假 PASS、坏压缩流 traceback，以及失败安装残留目标。每项均先有红测，再修复并全量回归。

## 安装与离线体验

当前证据见 [`install-verification-220.md`](install-verification-220.md)。

| 字段 | 值 |
|---|---|
| 本地安装目标 | `.install-auditing-ai-claims-220-final/auditing-ai-claims/` |
| 安装类型 | 15 文件白名单真实目录复制 |
| source/target tree SHA-256 | `03901778a81fc0482c4e84fea2b75ac894e33cbd61ca22eda07cfcad54adf121` |
| 符号链接 | 0 |
| `doctor` | exit 0，runtime/policy 2.2.0 |
| unknown fixture gate | PASS，bundle `05b25bbcfefaa09544ea748783658055be6e07a4fc110c3ebc64cf69fac3051a` |
| status/replay | PASS/PASS |

安装目标不含 eval、测试、示例、launch、本机 attempt 或缓存。该验证没有调用模型，因此不证明自动发现。

## 指定一手来源复验

当前证据见 [`v2/live-source-220.md`](v2/live-source-220.md)。

安装副本实际打开并保存：

1. OpenAI `Why language models hallucinate`
2. NIST `AI Risk Management Framework`
3. Microsoft Research `The Impact of Generative AI on Critical Thinking`

三个 fetch 均为 HTTP 200、`support_eligible=true`。五条主张状态为 4 条 `confirmed`、1 条 `partially_supported`；Microsoft 调查的 association 没有升级为普遍因果。最终 bundle 为 `7e2243f8b82427007cc6f367300718e5a13d3cc078027246a9598a5ecb2afba0`，gate、status、replay 均 PASS。

这不是 C01 至 C16 的行为评测，也不代表页面内容永远保持不变。

## 最终行为复测矩阵

以下状态全部是基础设施 **NOT RUN**，不是 0 分，也不是 Skill 行为失败。

| 案例 | 目标 | 新鲜模型回答 | 运行时证据 | 语义盲评 | 来源复核 |
|---|---|---|---|---|---|
| C01 | 伪造论文、作者与 DOI | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C02 | 相关性升级因果 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C03 | 无日期的当前价格 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C04 | 观点与隐喻，不触发 | NOT RUN | 应无运行目录，未验证 | NOT RUN | 不适用，未验证 |
| C05 | 公司自述 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C06 | 来源支持范围 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C07 | 关系动机，不触发 | NOT RUN | 应无运行目录，未验证 | NOT RUN | 不适用，未验证 |
| C08 | 高风险专业边界 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C09 | 标题不是正文 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C10 | 二手来源 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C11 | 官方页与主张不匹配 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C12 | 混合事实与观点 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C13 | 模糊总括判词 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C14 | 清晰主张控制 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C15 | 证据到行动越界 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |
| C16 | 多链接同源洗白 | NOT RUN | NOT RUN | NOT RUN | NOT RUN |

因此当前不能计算与四个 baseline 的同题改善，也不能运行无 Skill、降级提示词、完整 V2 三组消融。

## C14 基础设施 probe

唯一尝试是 C14 harness probe：

| 字段 | 值 |
|---|---|
| runner ID | `918ead04-7891-4913-ac54-98a9a587f4c2` |
| thread ID | `019fd23a-e645-7062-a2fd-dbe803eef2cd` |
| return code | 1 |
| 最终回答 | 无 |
| `.claim-audits` | 无 |
| 失败阶段 | 模型执行前 |
| 明确错误 | Codex usage limit，提示 2026-08-12 18:13 后重试 |

本地原始 attempt 位于 `v2/behavior-220/attempts/C14/20260805T140136.945815Z-4d830170-8946-42d0-95cd-4868325f9e30/`，由 `.gitignore` 排除，因为 stderr 含本机路径和继承上下文。`attempt-result.json` 的 `status=failed` 只描述 runner attempt，不得提升为 Skill 行为失败。

## 自动发现

正向 C01、C03、C12、C14 与负向 C04、C07 均为 NOT RUN。旧 [`install-verification.md`](install-verification.md) 是白名单安装器之前的历史符号链接试跑，不能用于当前结论。

## 发行状态

当前包只允许继续本地审查和开发。解除 NO-GO 至少需要：

1. Codex 额度恢复后，用冻结 manifest 运行 16 个 query-only 新鲜会话
2. 分开完成语义盲评和来源复核
3. 独立验证正向自动发现与 C04、C07 不触发
4. 任何改动后重跑 88 项工程测试、安装验证和全部行为案例

当前没有公开、没有 push、没有创建 remote，也没有声称已开源。
