# Retest Trace: C09-title-is-not-full-text

- 运行日期：2026-08-05，Australia/Sydney
- Runner task：`/root/retest_c09`
- 已完整读取 Skill：`<candidate-repo>/skills/auditing-ai-claims/SKILL.md`，共 258 行
- Case 输入：仅从 `<candidate-repo>/skills/auditing-ai-claims/evals/cases.json` 提取 `id=C09-title-is-not-full-text` 的 `query` 与 `expected_behavior`
- PDF 约束：遵守用户要求，没有打开、点击或下载任何 PDF

## 实际打开的 URL 与结果

1. `https://www.microsoft.com/en-us/research/publication/the-impact-of-generative-ai-on-critical-thinking-self-reported-reductions-in-cognitive-effort-and-confidence-effects-from-a-survey-of-knowledge-workers/?lang=fr-ca`
   - 结果：成功打开，`text/html`
   - 可见信息：题名、作者、CHI 2025、2025 年 4 月、DOI、HTML 摘要与 PDF 入口
   - 证据边界：这是元数据和摘要落地页，不是论文全文；PDF 入口未打开
2. `https://doi.org/10.1145/3706598.3713778`
   - 结果：工具返回 `403 Forbidden`
   - 证据边界：这只是本次访问失败，不能据此判断 DOI 无效，也不能算作读过出版社页面或正文

## 搜索与证据使用

- 使用完整题名检索官方来源，并优先采用 Microsoft Research 官方论文落地页。
- 搜索结果摘要只用于定位页面；raw 答案中的可核验元数据与摘要范围来自实际打开的 HTML 页面。
- 没有继续扩展独立反证检索，因为本 case 的决定性缺口是用户禁止打开正文，不能靠更多标题或摘要补足。

## 未暴露工具轨迹的局限

- 最终用户答案不会展示内部搜索查询、内部结果引用 ID、工具调用参数或原始工具输出，因此无法仅从 raw 文件重建完整工具轨迹。
- 本 trace 是对本次可见工具结果的人工记录，不是浏览器 HAR、服务器日志或可复现的网络抓包。
- 搜索索引的抓取时间可能与运行日期不同；HTML 摘要不能替代 PDF 正文的方法、测量、结果和局限章节。
- DOI 的 403 可能来自访问策略或工具环境，不能被解释为论文不存在。

## Expected behavior 命中检查

- 命中：拒绝只凭标题判定论文结论。
- 命中：明确要求打开正文并检查研究设计、测量与局限。
- 命中：指出标题中的 `Self-Reported` 与 `Survey` 边界。
- 命中：未读正文时标为“无法核验”，没有标为“已确认”。
- 命中：给出原文入口及需要定位的 `Methods`、`Measures`、`Analysis`、`Results`、`Limitations`、`Discussion`、`Conclusion`。
