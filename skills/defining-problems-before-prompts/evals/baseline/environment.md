# Baseline 环境

记录时间：2026-08-05，Australia/Sydney。

| 项目 | 值 |
|---|---|
| Harness | OpenAI Codex CLI 0.132.0 |
| Model | gpt-5.5 |
| Provider | OpenAI |
| Reasoning effort | none |
| Sandbox | read-only |
| Approval | never |
| 项目规则 | `--ignore-rules` |
| 用户配置 | `--ignore-user-config` |
| 会话 | `--ephemeral`，每题新会话 |
| 候选 Skill | 未创建、未加载 |
| 输入 | `baseline/raw/DPBP-00N-input.txt` 原文 |
| 网络 | DPBP-002、003 由模型自行使用 web search；DPBP-001、004 未使用 |

执行命令的固定形态：

```bash
RUST_LOG=error codex exec --ignore-user-config --ignore-rules --ephemeral --skip-git-repo-check -s read-only -m gpt-5.5 --color never -C '<baseline/raw>' - < DPBP-00N-input.txt
```

环境异常：最初尝试 `gpt-5.6-terra`，CLI 在模型执行前返回“requires a newer version of Codex”，因此该次请求不计入 baseline。随后固定使用 `gpt-5.5`，四题均退出码 0。CLI 启动时还报告本地 model cache 版本字段不兼容和一个无 YAML frontmatter 的全局 Skill，但没有加载本候选 Skill，也没有阻止四题完成。
