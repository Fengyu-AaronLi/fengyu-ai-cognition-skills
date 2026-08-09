# 3.1.0 白名单安装与离线闭环验证

验证日期：2026-08-06，Australia/Sydney。

## 结论

白名单安装、安装后运行时、YAML 元数据解析、离线 `current_unknown` 闭环、最终 Gate 与 replay 均通过。这个结果只证明安装包可执行且能在没有来源时诚实停止，不证明模型会自动发现 Skill，也不证明任何现实价格主张。

## 安装工件

| 字段 | 值 |
|---|---|
| 源目录 | `<REPO_ROOT>/skills/auditing-ai-claims` |
| 干净目标 | `/tmp/aiclaims-install-310-final.V9Fe1E/skills/auditing-ai-claims` |
| 安装方式 | `scripts/install.py` 原子发布白名单目录 |
| 安装文件 | 27 个普通文件 |
| source tree SHA-256 | `af59523e87c587d39fb82d36077d2c76de88483ace48e29b08c968e2a026ab0f` |
| target tree SHA-256 | `af59523e87c587d39fb82d36077d2c76de88483ace48e29b08c968e2a026ab0f` |
| 符号链接 | 0 |
| 被排除内容 | eval、tests、examples、launch、缓存和本地审计工件 |

安装副本自报：runtime `3.1.0`、policy `3.1.0`、Python `3.14.4`、仅标准库、`fcntl` 工作区锁、`pdftotext` 可用、网络限定公共 HTTP(S) 80/443 且逐跳 DNS pinning。

`agents/openai.yaml` 使用本机 Ruby 2.6.10 的 `YAML.safe_load(File.read(...))` 解析，结果为 `YAML_OK`。

## 离线 unknown 工作流

输入是一条没有来源的当前价格比较。安装副本实际经过：

1. `claim_extraction`
2. `claim_assessment`
3. `claim_countercheck`
4. `audit_summary`
5. `ready_to_finish`
6. `complete=true`

结论冻结为 `current_unknown`，反证结果为 `inconclusive`，没有生成来源、引用或现实价格答案。

| 工件 | SHA-256 |
|---|---|
| bundle | `d5257262d07f4461b1142da97dc7049146879c40267b1db2796de74929f5529e` |
| report | `f012777b8760099d0d980f29c4711acb9b556153de990d4af52bb1edee7f87a5` |
| gate | `36fe112c87514b457047a59695232417aafe0c9785a4b80541d3026c2b49e83d` |
| ledger | `e00a00ede597be109a876c92330a7dd21bace3fbd4930051bc15ec7454540fb9` |

Gate 为 PASS，`next` 返回 `complete`，replay 的 historical、bundle、saved gate 和 report 四项完整性均为 PASS；`current_freshness_rechecked=false`。

## 验收过程中的失败回路

第一次验收夹具使用了未冻结的 `price` 类型，安装运行时拒绝并返回 `unsupported claim_type: price`，后续 Gate 保持 FAIL，没有生成报告。夹具改成公开枚举中的 `quantitative_comparison` 后，在新的 `audit-pass` 工作区从头重跑并通过。

第一次 YAML 检查调用了本机 Psych 不提供的 `safe_load_file`，随后改为读取字符串后调用 `safe_load`，再得出 `YAML_OK`。这两个失败工作区不计入 PASS。

## 尚未证明

- 没有运行新鲜模型会话。
- 没有验证正向自动发现或负向不触发。
- 临时目录不是发布位置。
- 没有 commit、push 或公开发行。
