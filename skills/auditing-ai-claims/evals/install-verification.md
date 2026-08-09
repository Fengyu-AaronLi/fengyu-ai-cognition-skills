# 安装与发现验证

> 历史证据：本文件记录 2.2.0 白名单安装器之前的符号链接试跑，不能代表当前安装或自动发现结论。当前 3.1.0 安装结果见 `install-verification-310.md` 与 `results.md`。

## 结论

项目级安装路径有效，Codex CLI 能发现并读取 `auditing-ai-claims`。但当前结果不能写成“自动路由全部通过”：正向 CLI 案例在读取 Skill 后被 WebSocket TLS 传输故障中断；负向 C04 虽然执行行为正确，发现层仍误加载了 Skill。

## 已测试安装

测试日期：2026-08-05  
系统：macOS 26.5.2，Apple Silicon  
CLI：`codex-cli 0.132.0`

候选仓库使用项目级链接：

```text
.agents/skills/auditing-ai-claims -> ../../skills/auditing-ai-claims
```

链接可解析，落点与候选 `SKILL.md` 相同。没有安装到用户级 Skill 目录。

## 干净会话协议

自动发现使用 `codex exec --ephemeral --ignore-user-config`。这关闭了会话持久化并忽略用户配置，但实测仍会继承机器级项目协议，因此它是“临时新会话”，不是完全空白的操作系统环境。准确模型标识未暴露。

行为复测另使用 `fork_turns=none` 的新鲜隔离会话，每个会话只读取最终 `SKILL.md` 和一个案例。零门槛体验使用另一个 `fork_turns=none` 会话，只读取 `zero-threshold-prompt.md`，明确禁止读取 Skill。

## 自动发现结果

| 输入 | 发现层 | 执行层 | 结论 |
|---|---|---|---|
| C01 论文、DOI 与结论审计 | 成功发现并读取 Skill | 读取后因 WebSocket TLS 故障中断 | 安装发现通过，回答完成未验证 |
| C16 同源报道审计 | 成功发现并读取 Skill | 读取后因 WebSocket TLS 故障中断 | 安装发现通过，回答完成未验证 |
| C04 明确标注的随笔与隐喻 | 仍发现并读取 Skill | 没有建立事实账本，按创意文本放行 | 执行边界通过，发现层不通过 |

正向行为质量不使用传输失败的 CLI 输出评分，而使用 16 个新鲜隔离复测会话的最终答案评分。失败的 CLI 轨迹只证明安装发现与传输故障，不证明模型答错。

## 原始证据与隐私边界

- 最终可分发摘要：`evals/retest/traces/C04-opinion-and-metaphor.md`
- 完整 CLI JSONL：保留在本地 `evals/retest/traces/`，由同目录上层 `.gitignore` 排除
- 正向传输失败轨迹：`C01-transport-failure-1.jsonl` 与 `C16-transport-failure-1.jsonl`，同样只保留本地

完整 JSONL 含本机路径和继承的机器级上下文。未来只能从 Git 索引或经过发行清单的构建产物打包，不能直接压缩整个工作树。

## 回滚

若需要撤销项目级安装，只删除目标项目中的符号链接，不删除候选源码目录。当前任务未执行回滚，也未删除任何文件。
