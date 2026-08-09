# C11 隔离复测轨迹

- 运行日期：2026-08-05，Australia/Sydney
- Runner task：`/root/retest_c11`
- Case ID：`C11-official-page-mismatch`
- 已读 Skill：`<candidate-repo>/skills/auditing-ai-claims/SKILL.md`，完整读取 258 行
- 用例来源：`<candidate-repo>/skills/auditing-ai-claims/evals/cases.json`，仅提取 id 为 `C11-official-page-mismatch` 的 query 与 expected_behavior

## 实际打开的 URL 与结果

- 请求 URL：`https://www.nist.gov/itl/ai-risk-management-framework`
- 最终 URL：`https://www.nist.gov/itl/ai-risk-management-framework`
- 访问结果：成功打开并取得 NIST 页面正文，标题为 `AI Risk Management Framework | NIST`
- 页面身份结果：NIST AI Risk Management Framework 的官方入口页
- 关键正文结果：页面说明 AI RMF 用于帮助管理 AI 风险，供自愿采用，并把可信度考量纳入 AI 产品、服务和系统的设计、开发、使用与评估；AI RMF 1.0 发布日期为 2023-01-26；页面还显示 2026-04-07 的概念说明更新，并标明 AI RMF 1.0 正在修订
- 页面内核对结果：可访问正文中未找到 `Model Q`、`medical` 或 `certif`；没有与 Model Q 相关的 99% 指标、测试条件或产品认证记录
- 收敛限制：按父任务要求，打开并核对指定 NIST 页面后不再扩搜。因此本次只能判断该引用的支持范围，不能据此断言 NIST 的全部记录中不存在 Model Q，也不能断言三个实质主张已被反驳

## 判定摘要

- “NIST 已认证 Model Q”：引用内容不支持；产品认证主张为无法核验，不判为被反驳
- “事实准确率达到 99%”：引用内容不支持；缺少模型版本、指标和原始评测，无法核验
- “可安全用于医疗诊断”：引用内容不支持；缺少临床、监管和法域证据，无法核验，并保留医疗专业与监管边界

## 未暴露工具轨迹的局限

用户答案文件只保留可审计的最终 URL、访问日期和页面结果，不暴露浏览工具的内部引用 ID、调用参数或完整调用日志。当前轨迹也不保存原始 HTTP 响应头、状态码、完整 DOM 快照或可独立回放的网络会话。因此，它能记录本次确实取得了哪个页面及据此作出的判断，但不能替代外部可重放的浏览器取证日志；页面内容日后也可能发生变化。
