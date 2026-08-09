# 3.1.0 指定一手材料真实来源复验

核验时间：2026-08-06，Australia/Sydney 会话；运行时回执使用 UTC。

## 结论

三个指定原始页面均由 3.1.0 运行时实际抓取，HTTP 均为 200，且保存原始字节、解析文本、回执认证和精确引文选择器。三条窄主张完成评估、反证、跨主张汇总、Gate、渲染与 replay。最终 Gate 为 PASS。

这个 PASS 不表示三份材料共同证明“幻觉已解决”或“AI 会让人变笨”。它只证明已冻结主张、已保存证据和报告边界在本次运行中一致。

## 工作流收敛

1. `start --candidates-file` 冻结三条原始候选及字符范围。
2. 三个 `claim --file` 建立 C1 至 C3。
3. 三次 `fetch` 产生 S1 至 S3，来源事务均提交。
4. 七个 `evidence --file` 分别绑定来源身份、研究设计和实质内容。
5. 三个 `assess --file` 冻结三道门、状态、未知与下一步。
6. 三个 `countercheck --file` 冻结可推翻条件、实际检查来源、结果、停止理由、运行时检查时间与 basis hash。
7. `summarize --file` 冻结跨主张未知和最高信息增益动作。
8. `next` 依次进入 `claim_extraction`、`claim_assessment`、`claim_countercheck`、`audit_summary`、`ready_to_finish` 和 `complete`。
9. 最终干净安装副本重新执行 `finish`、`next` 与 `replay`，结果仍为 PASS。

## 来源回执

| ID | 原始页面 | UTC 访问时间 | HTTP | 字节 | 内容 SHA-256 | 解析文本 SHA-256 | 回执 SHA-256 |
|---|---|---|---:|---:|---|---|---|
| S1 | OpenAI, Why language models hallucinate | `2026-08-06T03:46:44Z` | 200 | 442,538 | `99d304f854c5df2a434811fb9750d1cf409235172fecc2b9b64da966a26b69ac` | `6f954f941950dc4c4d1dc76a995121eca6fb815cc0738c1077de3792157329df` | `333cb32a438e45737356e3f45ea950f0fd5a1c0d17bfd0b1de95f0df9023fe70` |
| S2 | NIST, AI Risk Management Framework | `2026-08-06T03:46:43Z` | 200 | 91,707 | `d0ed99078eb621495b0622adbcffaaee374c3fcfceced47ce27651fee88d0d6e` | `c0579e71f563229e265db1148017e9447cf4456f6fa537bcb233903e43d6fe5e` | `3a4c6f37ad3b8025700a4b4e1ea2ff657e997a9226a3132b7bebbcc355d537c3` |
| S3 | Microsoft Research, critical-thinking survey | `2026-08-06T03:46:45Z` | 200 | 181,207 | `25843e5fd08ca8e5731d3cb00bfec4f758ea21fdb17c0953e5a181a1c41bf908` | `efe4d1217300a5e9c42c13ef6bdfbd0d2e4b4ced10146e6a7abb5c05898ee713` | `8ab5ea2011de2966d3b06f5b837dbdfe2a73eb8c27169991e73b25e6835028d7` |

三个回执均为 `support_eligible=true`、`acquisition_type=runtime_fetch`、`transport_attestation=dns_pinned_runtime`。

## 精确证据选择器

| 主张 | 用途 | 精确引文 | 字符范围 | quote SHA-256 |
|---|---|---|---|---|
| C1 | source_identity | `Why language models hallucinate` | 307:338 | `4b717e55ea06d242f2c956eac8bd1907d7d0c31bb4ac804b765ef75ae0b63494` |
| C1 | substantive | `Even as language models become more capable, one challenge remains stubbornly hard to fully solve: hallucinations.` | 786:900 | `5dc5298c2f936e956390bf1c3003262b243241d5349b38fd6c2d9f0f37297407` |
| C2 | source_identity | `AI Risk Management Framework` | 2274:2302，occurrence 1 | `1be3bbabb57be8644aa60faa7f508636d6455f27d1681b7465579b7af481a5fe` |
| C2 | substantive | `Released on January 26, 2023` | 3354:3382 | `b8855bd404a0bd15462c63c1b3b3843c1b5be0aac22c4d9b9f6aafe23da26588` |
| C3 | source_identity | 论文完整标题 | 1539:1691，occurrence 1 | `02b622c585e5cc5066c6d018a6dafdd271c166a7ca131ba36a7b945ac8d3173d` |
| C3 | study_design | `We survey 319 knowledge workers` | 1984:2015 | `8a3b593093b6a8e69f7caab2548df5bc7106a38746eb2b66cba8606db887d584` |
| C3 | substantive | `higher confidence in GenAI is associated with less critical thinking` | 2499:2567 | `7fd07ef98cba50120910ea2e0785d92d2cc4f803cbf700b1c1fa8af64422721d` |

## 主张结果

| ID | 状态 | 审计边界 |
|---|---|---|
| C1 | confirmed | 只确认 OpenAI 官方文章仍把幻觉称为难以彻底解决的挑战，不推出现实回答统一错误率 |
| C2 | confirmed | 只确认 NIST 页面记录 AI RMF 于 2023-01-26 发布，不判断后续版本或具体合规适用性 |
| C3 | confirmed | 只确认 319 人自报调查中的 association，不升级为因果或所有人都会变笨 |

三条反证结果均为 `no_conflict_found`。这表示在明确列出的已检查来源中没有发现冲突，不表示穷尽世界上所有反证。

## 最终 Gate 与回放

| 字段 | 值 |
|---|---|
| claims / sources / receipts | 3 / 3 / 3 |
| errors / warnings | 0 / 0 |
| bundle SHA-256 | `ef6749446f2bc524a4dc9ae27b668612097266a268cd31307f31d6e4a383c8c1` |
| report SHA-256 | `4107d8cc65a413c3bc5c0dba87426de1249ee30e4c2cb3684a1792d1ef7d57b2` |
| gate SHA-256 | `6646dd1d240b91169eab2b4b98317b936202e6e25a116f52ffe81e3131cc93b4` |
| ledger SHA-256 | `3be7b321703ca8ff5157a09fb9076481d69cee71dbd7159ec492192bed0deb7c` |
| replay | historical、bundle、saved gate、report 全部 PASS |
| freshness boundary | `current_freshness_rechecked=false`，replay 不重新联网 |

## 当前未知

- 没有核验具体模型在现实任务中的统一错误率。
- 没有建立生成式 AI 导致客观批判性思考能力下降的因果关系。
- 这些页面以后可能变化，拍摄或发布前必须重新打开。
- 这次运行是运行时证据，不是 C01 至 C16 的新鲜模型行为评测，也不是自动发现测试。
