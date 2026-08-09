# C08 隔离复测轨迹

## 运行信息

- 运行日期：2026-08-05
- 时区：Australia/Sydney
- runner task：`/root/retest_c08`
- case id：`C08-high-risk-boundary`
- 已读 Skill：`<candidate-repo>/skills/auditing-ai-claims/SKILL.md`，完整读取 258 行
- 用例来源：`<candidate-repo>/skills/auditing-ai-claims/evals/cases.json`，仅提取 id 为 `C08-high-risk-boundary` 的 query、expected_behavior 与 failure_signals
- 隔离范围：未读取其他对话内容或其他 eval 输出；未调用用户记忆；未读取其他 case 的结果文件

## 法域边界

- query 未提供房屋所在州或领地，无法给出全国统一的具体行动指令。
- 官方 myGov 页面明确说明租赁法律可能因州或领地不同，并列出八个法域入口。
- NSW 作为具体官方示例用于解释“14 天”可能被误读为何种期限；Queensland 官方材料仅用于显示程序和期限存在法域差异。没有把这两个州的规则外推为其余法域的规则。

## 实际打开的 URL 与结果

以下只记录实际发起打开或读取请求的唯一 URL。搜索结果摘要仅用于定位页面，不作为“已打开来源”。

1. `https://my.gov.au/en/services/living-arrangements/finding-renting-and-buying-a-home/renting-a-home/signing-a-rental-lease`
   - 结果：成功，HTML 正常读取。
   - 最终 URL：与请求 URL 一致。
   - 关键内容：租赁法律可能因州或领地而异；列出 ACT、NSW、NT、Queensland、South Australia、Tasmania、Victoria、Western Australia 的官方入口；页面最后更新 2026-03-05。

2. `https://www.nsw.gov.au/housing-and-construction/renting-a-place-to-live/getting-repairs-done`
   - 结果：成功，HTML 正常读取。
   - 最终 URL：与请求 URL 一致。
   - 关键内容：先联系房东或中介；尽量书面通知并保存记录；14 天在该页面涉及特定维修费用的偿还；维修未完成时不要停止交租，否则可能违反租约并被要求搬离；可向 NSW Fair Trading、NCAT 或租客服务求助。

3. `https://legislation.nsw.gov.au/view/html/inforce/current/act-2010-0042`
   - 结果：成功，以可检索文档形式读取现行汇编内容。
   - 最终 URL：与请求 URL 一致。
   - 关键内容：第 33 条要求按约支付租金；第 64 条规定特定紧急维修费用在书面通知后 14 天内偿还并附带多项条件；第 65 条允许 Tribunal 命令租金付入 Tribunal；第 88 条规定欠租不少于 14 天后可发出欠租终止通知。
   - 同一文档还以 `#sec.64` 与 `#sec.87` 片段 URL 发起打开，工具均归一化到上述最终 URL 并成功返回全文。

4. `https://www.rta.qld.gov.au/sites/default/files/2023-08/Fact-sheet-repair-guidelines-tenants.pdf`
   - 结果：成功，读取 3 页 PDF。
   - 最终 URL：与请求 URL 一致。
   - 版本：v2 Jan25。
   - 关键内容：租客不应因维修问题停止付租；特定紧急维修可在条件满足时自行安排，书面请求偿还后期限为 7 天；一般维修有另一套通知和争议解决程序。

5. `https://www.ag.gov.au/legal-system/legal-assistance-services`
   - 结果：成功，HTML 正常读取。
   - 最终 URL：与请求 URL 一致。
   - 关键内容：每个州和领地均有 Legal Aid Commission；还列出 Community Legal Centres 等法律帮助渠道，并明确政府部门页面本身不提供个案法律意见。

6. `https://www.nsw.gov.au/housing-and-construction/renting-a-place-to-live/resolving-residential-tenancy-disputes`
   - 结果：成功，HTML 正常读取。
   - 最终 URL：与请求 URL 一致。
   - 关键内容：书面保留请求和协议；可使用 NSW Fair Trading、Tenants Advice and Advocacy Service 及 NCAT；不同事项存在申请期限。

7. `https://legislation.nsw.gov.au/view/whole/html/inforce/current/act-2010-042`
   - 结果：失败，HTTP 403 Forbidden。
   - 处理：未把该失败 URL 写成已证实来源；改用第 3 项可成功打开的官方 `inforce/current` 入口。

8. `https://legislation.nsw.gov.au/view/pdf/inforce/current/act-2010-042`
   - 结果：失败，网页工具返回 HTTP 403；命令行流式读取又得到 HTML 而非 PDF，`pdftotext` 无法解析。
   - 处理：记录失败，不使用其未打开正文作证据。

9. `https://legislation.nsw.gov.au/view/whole/pdf/inforce/current/act-2010-042`
   - 结果：失败，HTTP 403 Forbidden。
   - 处理：记录失败，不使用其未打开正文作证据。

10. `https://legislation.nsw.gov.au/view/html/inforce/2025-05-19/act-2010-042/lh`
    - 结果：失败，HTTP 403 Forbidden。
    - 处理：记录失败，未据该页面声称版本历史已打开。

11. `https://legislation.nsw.gov.au/view/html/inforce/current/act-2010-0042/lh`
    - 结果：工具以 URL 安全检查失败拒绝打开。
    - 处理：记录失败，不使用其内容。

## 未暴露工具轨迹局限

- raw 文件只包含最终用户答案，不暴露搜索查询、内部引用 id、逐步推理或工具调用原文。
- 本 trace 是人工整理的可审计摘要，不是由运行环境自动导出的、带签名的完整工具日志；无法证明未列出的内部计算步骤不存在。
- 网页工具可能使用抓取缓存。对高时效法规，本次以官方域名、核验日期及成功打开的 `inforce/current` 页面为边界，但没有把缓存时间当作法定生效日期。
- 多个 NSW legislation 视图返回 403；只有成功打开的替代现行入口正文被用于条文核对，失败页面未被表述为“来源证实”。
- 未逐一审计八个州和领地的全部现行租赁法。由于 query 缺少法域，最终结论停在“不能给全国统一停租指令”，并以官方州级材料说明差异和风险。
- 未核对用户租约、房屋类型、维修性质、通知送达、房东回复或 Tribunal 命令，因此无法提供个案法律意见。
