# 3.0.0 指定一手材料真实来源复验

> **历史失效声明**：本文件只记录 3.0.0 当时的运行结果。它没有 3.1.0 强制反证状态，且 OpenAI 抓取结果与当前运行不同，不得作为 3.1.0 发行证据。当前复验见 [`live-source-310.md`](live-source-310.md)。下文版本号、哈希、失败和流程保持原样，不做追认式改写。

核验时间：2026-08-06，Australia/Sydney 会话；运行时回执使用 UTC。

这次复验在版本升级后重新建立工作区，没有沿用 2.2.0 的 gate、回执或报告。三个指定页面都由网页访问工具打开原文；本地运行时另外执行透明 HTTP 抓取、精确引文绑定和回放。

## 原文访问结果

| 页面 | 网页原文 | 本地运行时 | 审计处理 |
|---|---|---|---|
| OpenAI, Why language models hallucinate | 成功打开，页面日期为 2025-09-05；原文明确说幻觉仍未被完全解决，并讨论准确率评测激励猜测 | HTTP 403，保存 9,922 字节失败工件，`support_eligible=false` | 失败回执保留后退休；C1 状态为 `unverifiable`，没有把网页工具的可见内容冒充运行时已绑定证据 |
| NIST, AI Risk Management Framework | 成功打开 | HTTP 200，`support_eligible=true` | 身份与 2023-01-26 发布日期分别绑定，C2 `confirmed` |
| Microsoft Research, critical-thinking survey | 成功打开 | HTTP 200，`support_eligible=true` | 标题身份、319 人调查和 `associated` 表述分别绑定，C3 `confirmed`；报告明确不升级为普遍因果 |

## 运行时循环

1. `start` 冻结三条输入候选。
2. 三次 `add-claim` 建立三条原子主张。
3. 三次 `fetch` 产生两条合格回执和一条 HTTP 403 回执。
4. `retire-source` 保存并退休未被引用的 OpenAI 失败来源。
5. NIST 绑定一条 `source_identity` 和一条 `substantive` 引文。
6. Microsoft 绑定一条 `source_identity` 和两条 `substantive` 引文。
7. 三条主张分别 `decide`，随后 `summarize`。
8. `next` 从 `ready_to_finish` 收敛到 `complete=true`。
9. `finish`、`replay` 均返回 0。

## 精确证据选择器

| 主张 | 精确引文 | 字符范围 | quote SHA-256 |
|---|---|---|---|
| NIST 发布日期 | `Released on January 26, 2023` | 3354:3382 | `b8855bd404a0bd15462c63c1b3b3843c1b5be0aac22c4d9b9f6aafe23da26588` |
| Microsoft 调查样本 | `We survey 319 knowledge workers` | 1984:2015 | `8a3b593093b6a8e69f7caab2548df5bc7106a38746eb2b66cba8606db887d584` |
| Microsoft 相关性表述 | `higher confidence in GenAI is associated with less critical thinking` | 2499:2567 | `7fd07ef98cba50120910ea2e0785d92d2cc4f803cbf700b1c1fa8af64422721d` |

## 回执证据

### NIST S2

- 访问时间：`2026-08-06T02:08:40Z`
- 最终 URL：`https://www.nist.gov/itl/ai-risk-management-framework`
- HTTP：200
- 原始字节：91,707
- 原始内容 SHA-256：`56f79ba7425d1b82ba4a886c04443b0d571101f4cde0d4383c595a73d4ebb895`
- 解析文本 SHA-256：`c0579e71f563229e265db1148017e9447cf4456f6fa537bcb233903e43d6fe5e`
- 回执内容哈希：`f7d5b112425220ba73048be9baf116154612d8f3264970f13b2114226527826e`

### Microsoft Research S3

- 访问时间：`2026-08-06T02:08:41Z`
- HTTP：200
- 原始字节：181,218
- 原始内容 SHA-256：`7bac307a34ac0de42cdf8aca094772aad7c442dc3d5b2a4416769c3d05fc5478`
- 解析文本 SHA-256：`efe4d1217300a5e9c42c13ef6bdfbd0d2e4b4ced10146e6a7abb5c05898ee713`
- 回执内容哈希：`fe5b7a157b0ff0009692c494f5b1048cdb072766ef8c5b4c3e3e233ad950f2a5`

## 最终 gate 与回放

```json
{
  "gate_version": "3.0.0",
  "verdict": "PASS",
  "errors": [],
  "warnings": [],
  "summary": {
    "claims": 3,
    "sources": 3,
    "receipts": 3
  },
  "bundle_sha256": "43add3f746d52743a4cb2c99f9e6d7ca6958c05df33093306d01423bd00a82af"
}
```

最终文件哈希：

- ledger：`0d09d94f0f44f3667fc71936568d10ee016a5c12e9501552ec8f1e38513a2370`
- report：`228b11ef3bc332de6227aa6306fd151a1efe106d6abcb27275a9fabceaffd497`
- gate：`ea139c9174ede5361c7bc304817f9c33b4abbad754a5920f7280bb28945cab59`

`replay` 返回：历史完整性 PASS、证据 bundle PASS、保存 gate PASS、报告完整性 PASS、`current_freshness_rechecked=false`。

## 边界

PASS 证明这份已声明账本与保存工件满足 3.0.0 结构和完整性门。OpenAI 页面本身已由网页工具打开，但透明运行时抓取被 403 阻挡，所以本地报告没有把 C1 写成 confirmed。该结果也不把 Microsoft 的调查相关性扩写成“AI 会让所有人变笨”的普遍因果结论。
