# 2.2.0 白名单安装与离线体验验证

## 结论

白名单真实目录安装、`doctor`、无联网 unknown fixture、`finish`、`status` 与 `replay` 均通过。这个结果证明安装包可执行且诚实未知路径闭环，不证明自动发现、联网来源语义或 16 案行为质量已经通过。

## 环境

| 字段 | 值 |
|---|---|
| 本地时间 | 2026-08-06 AEST |
| 系统 | macOS 26.5.2，Build 25F84，arm64 |
| Python | 3.14.4 |
| Codex CLI | 0.132.0 |
| fixture 网络 | 未使用 |

## 安装

从候选源码调用 `scripts/install.py`，目标根为仓库内 `.install-auditing-ai-claims-220-final/`。安装器输出：

| 字段 | 值 |
|---|---|
| 安装方式 | 真实目录白名单复制，staging 校验后原子发布 |
| 运行文件数 | 15 |
| source tree SHA-256 | `03901778a81fc0482c4e84fea2b75ac894e33cbd61ca22eda07cfcad54adf121` |
| target tree SHA-256 | `03901778a81fc0482c4e84fea2b75ac894e33cbd61ca22eda07cfcad54adf121` |
| 符号链接 | 0 |
| 安装目录权限 | `0700` |
| runtime 权限 | `0744` |

目标只包含 `SKILL.md`、许可与来源说明、三份 policy、四份 schema、运行时和三份模板。没有 `README.md`、`evals/`、`tests/`、`examples/`、`launch/`、缓存或本机 attempt。

## 离线 unknown fixture

输入：`现在最便宜的公开模型是 Model Z。`

执行链：

```text
doctor → start → add-claim → decide(current_unknown) → finish → status → replay
```

没有访问定价页，也没有把示例主张写成已确认。结果：

| 检查 | 结果 |
|---|---|
| `doctor` | runtime 2.2.0，policy 2.2.0，exit 0 |
| `finish` | gate PASS，errors 0，warnings 0，exit 0 |
| 主张状态 | `current_unknown` |
| bundle SHA-256 | `05b25bbcfefaa09544ea748783658055be6e07a4fc110c3ebc64cf69fac3051a` |
| gate SHA-256 | `85f2a0547c068ee8f4b5597d154c2dd979f5e0db5aa667df9274ae0c37eeb567` |
| report SHA-256 | `f79a57893b57429625f72abbbc56c9d39d37254d8a3d5fad1b39b29f5f281154` |
| `status` | gate integrity PASS，report current true，exit 0 |
| `replay` | historical、evidence bundle、saved gate、report 均 PASS，exit 0 |
| 当前性刷新 | false |

fixture 运行目录为本地生成物 `.install-auditing-ai-claims-220-final/fixture-run/`，由仓库根 `.gitignore` 排除。

## 未验证

- 干净会话自动发现与自动不触发
- C01 至 C16 的新鲜语义行为
- 安装后的真实联网来源核验

这些项因 Codex CLI usage limit 尚未运行，不能从本次安装 PASS 外推。
