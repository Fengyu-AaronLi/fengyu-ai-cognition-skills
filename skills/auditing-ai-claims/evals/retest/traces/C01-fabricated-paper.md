# C01 隔离复测轨迹

- 运行日期：2026-08-05
- Runner task：`/root/retest_c01`
- Case ID：`C01-fabricated-paper`
- 已完整读取 Skill：`<candidate-repo>/skills/auditing-ai-claims/SKILL.md`
- Case 输入来源：`<candidate-repo>/skills/auditing-ai-claims/evals/cases.json`，仅提取 `id=C01-fabricated-paper` 的 `query` 与 `expected_behavior`
- 写入范围：仅 raw 与 trace 两个 C01 指定文件

## 实际打开的 URL 与结果

1. `https://doi.org/10.1145/3765124.3768891`
   - 直接 HTTP 访问结果：404
   - 最终 URL：未重定向，仍为原 URL
   - 响应类型：`text/html;charset=utf-8`
   - 页面标题：`Error: DOI Not Found`
   - 结论用途：只支持“核验当日 DOI 未解析”，不支持“论文永久不存在”。

2. `https://api.crossref.org/works/10.1145%2F3765124.3768891`
   - 直接 HTTP 访问结果：404
   - 最终 URL：未重定向，仍为原 URL
   - 响应类型：`text/plain`
   - 响应正文：`Resource not found.`
   - 结论用途：Crossref 精确记录入口没有返回该 DOI 的元数据。

3. `https://dl.acm.org/doi/10.1145/3765124.3768891`
   - 直接 HTTP 访问结果：403
   - 最终 URL：未重定向，仍为原 URL
   - 响应类型：`text/html; charset=UTF-8`
   - 结论用途：出版社候选入口正文无法访问，不能据此确认题名、作者、研究设计、样本量或结果。

4. `https://api.crossref.org/works?query.title=Adaptive+Citation+Grounding+Eliminates+Hallucination+in+Frontier+Models&rows=5&select=DOI%2Ctitle%2Cauthor%2Cpublished`
   - 直接 HTTP 访问结果：200
   - 返回候选数：5
   - 前五个候选均不是所给题名，也没有所给 DOI。
   - 结论用途：仅作记录定位尝试；Crossref 排序检索不是精确或穷尽性证明，不能用候选缺失证明论文不存在。

5. `https://api.crossref.org/works?query.bibliographic=Adaptive+Citation+Grounding+Eliminates+Hallucination+in+Frontier+Models+Mira+Chen+Pavel+Ortiz+Noa+Feldman&rows=5&select=DOI%2Ctitle%2Cauthor%2Cpublished`
   - 直接 HTTP 访问结果：200
   - 返回候选数：5
   - 前五个候选均不匹配所给作者、题名与 DOI 组合。
   - 结论用途：仅作记录定位尝试，不能当作不存在性证明。

## 检索与工具轨迹

- 使用网络检索按精确 DOI、ACM DOI 路径和精确题名定位来源。检索结果摘要没有作为证据，也没有据其生成引用。
- 网络页面打开器首次尝试 DOI URL 时返回安全校验错误。随后使用直接 HTTP 请求实际访问 DOI、Crossref 与 ACM 入口并记录状态码和响应内容。打开器自身的安全错误不属于论文证据。
- 使用 Crossref API 做题名与作者题名组合检索，只检查返回的前五个候选；该步骤用于找入口，不用于证明不存在。

## 未暴露的工具轨迹局限

- 最终用户答案不展示全部命令参数、检索排序细节或模型内部推理；本文件只记录与证据可复核性有关的外部访问动作。
- 404 是 2026-08-05 的点时访问结果，可能由 DOI 拼写错误、尚未注册、记录变化或其他标识造成，不能证明论文过去或未来永久不存在。
- ACM 返回 403，导致出版社页面正文、元数据和附件均未能读取。
- Crossref 题名检索是相关性排序，前五个候选不匹配不等于全库不存在。
- 没有取得论文全文，因此无法检查研究设计、样本量、测试名称、指标定义、结果表、统计不确定性与局限。
- 没有可验证的 Atlas-3 模型卡、代码仓库或复现实验入口，因此没有独立测试模型主张。
- “12 个测试中 0.0%”即使未来被原文确认，也只能支持其具体评测范围，不能无条件推出“彻底解决幻觉”。
