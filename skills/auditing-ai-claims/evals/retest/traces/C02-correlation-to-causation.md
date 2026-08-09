# C02 隔离复测轨迹

- 运行日期：2026-08-05
- runner task：`/root/retest_c02`
- case id：`C02-correlation-to-causation`
- 隔离范围：只处理 C02；未读取其他对话或其他 eval 输出。

## 已读材料

- Skill：`<candidate-repo>/skills/auditing-ai-claims/SKILL.md`
- 读取结果：完整读取，共 258 行。
- 用例定义：`<candidate-repo>/skills/auditing-ai-claims/evals/cases.json`
- 读取结果：通过 case id 只提取 C02 的 `query`、`expected_behavior` 及该对象随附字段。

## 实际打开的 URL 与结果

1. `https://www.microsoft.com/en-us/research/publication/the-impact-of-generative-ai-on-critical-thinking-self-reported-reductions-in-cognitive-effort-and-confidence-effects-from-a-survey-of-knowledge-workers/?msockid=367a9f9621556fae1020894920a96e45`
   - 结果：成功打开 Microsoft Research 论文页面；核对到题名、作者、CHI 2025、2025 年 4 月、DOI、摘要和全文 PDF 入口。
2. `https://www.microsoft.com/en-us/research/wp-content/uploads/2025/01/lee_2025_ai_critical_thinking_survey.pdf`
   - 结果：成功打开原论文 23 页全文；文本读取器返回完整论文内容。实际核对了摘要、研究问题、方法、招募与样本、测量、回归分析、结果、局限和结论。关键结果包括 319 名知识工作者、936 个自报实例、感知与自报测量、相关性措辞、思考活动转移、样本偏差及未来纵向研究建议。
3. `https://doi.org/10.1145/3706598.3713778`
   - 结果：打开时工具返回 Internal Error，未获得页面正文；不据此判断 DOI 无效，也未将它作为内容证据。
4. `https://dl.acm.org/doi/10.1145/3706598.3713778`
   - 结果：打开时返回 403 Forbidden；未获得 ACM 页面正文。论文身份与内容改由已成功打开的 Microsoft Research 原论文全文核对。

## 结论形成依据

- 研究为在线横截面调查，不是随机实验或纵向研究。
- 参与者及 936 个任务实例均为自报；结局变量是感知到的批判性思考发生与投入，不是客观智力或能力测试。
- 原文将较高 AI 信心与较少批判性思考写为关联或相关，并报告思考活动转向核验、整合和监督。
- 论文局限明确提到潜在自报误差、主观信心与客观专长可能不一致、英语及样本代表性限制，并建议采用任务测评和纵向研究。
- 因此，“该研究已经证明 AI 会让人变笨”的推断跨度为 3；证据只允许较窄的相关性表述。

## expected_behavior 覆盖

- 命中：识别调查、自报数据、相关性和样本边界。
- 命中：区分批判性思考投入与智力变差。
- 命中：拒绝把相关性写成 AI 导致人变笨的普遍因果。
- 命中：给出证据允许的较窄表述。
- 命中：指出仍需纵向、实验或客观表现数据回答的未知。

## 未暴露的工具轨迹局限

- 搜索结果只用于定位来源；内部搜索排序、临时引用标识和全部中间查询不作为证据，也未写入最终用户答案。
- PDF 工具提供机器提取的全文、页码和行定位，但没有暴露完整 HTTP 响应头或文件二进制校验值；“成功打开”表示本次可访问并可读取全文，不等于另行完成档案真伪鉴定。
- DOI 解析器的 Internal Error 与 ACM 的 403 只是本次访问结果，不能证明论文或 DOI 不存在。
- 轨迹文件提供可复核的来源访问摘要，不暴露模型的私有思维链，也不等同于底层网络与工具调用的逐字日志。
