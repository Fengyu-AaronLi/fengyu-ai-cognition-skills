# C13-vague-verdict 复测轨迹

## 运行信息

- 运行日期：2026-08-05
- 时区：Australia/Sydney
- runner task：`/root/retest_c13`
- case id：`C13-vague-verdict`
- 已读 Skill：`<candidate-repo>/skills/auditing-ai-claims/SKILL.md`
- Skill 读取状态：完整读取，共 258 行
- case 读取方式：从 `<candidate-repo>/skills/auditing-ai-claims/evals/cases.json` 仅用 `jq` 选择 `id == "C13-vague-verdict"`，提取 `query` 与 `expected_behavior`
- 隔离约束：未读取其他对话或其他 eval 输出

## 实际打开的外部 URL 与结果

1. `https://www.nist.gov/publications/artificial-intelligence-risk-management-framework-generative-artificial-intelligence`
   - 结果：成功打开，HTTP 内容可解析
   - 页面：NIST《Artificial Intelligence Risk Management Framework: Generative Artificial Intelligence Profile》发布页
   - 关键信息：报告号 NIST AI 600-1，发布于 2024-07-26，页面更新于 2026-04-08
   - 证据角色：官方出版记录，不是 Model Q 认证

2. `https://nvlpubs.nist.gov/nistpubs/ai/NIST.AI.600-1.pdf`
   - 结果：成功打开，PDF 共 64 页，文本可解析
   - 实际核对内容：第 7 页和第 9 页的 confabulation 定义；第 17 页的风险阈值和持续内外部评估；第 21 页的独立评估、红队与情境化评测；第 33 至 36 页的能力主张验证、避免从狭窄评估外推、引用核验、残余风险、安全失效、隐私与安全红队
   - 证据角色：官方技术框架原文，不是 Model Q 认证

3. `https://airc.nist.gov/airmf-resources/airmf/3-sec-characteristics/`
   - 结果：成功打开，页面文本可解析
   - 实际核对内容：可信 AI 的多维特征；指标与阈值需依使用情境由人作判断；代表预期使用条件的现实测试集；可靠性需要绑定时间和条件；安全需按风险情境与严重度定制，并包括模拟、域内测试、实时监测、停用或人工干预
   - 证据角色：NIST AI RMF 1.0 官方摘录，不是 Model Q 认证

4. `https://airc.nist.gov/airmf-resources/airmf/5-sec-core/`
   - 结果：成功打开，页面文本可解析
   - 实际核对内容：任务和适用范围需明确；实验设计需记录代表性；独立审查可以降低内部偏差；评测需接近部署条件并表达不确定性；安全要求残余风险不超过情境化容忍度、可安全失效并持续监测
   - 证据角色：NIST AI RMF 1.0 官方摘录，不是 Model Q 认证

5. `https://www.nist.gov/publications/challenges-monitoring-deployed-ai-systems-center-ai-standards-and-innovation`
   - 结果：成功打开，页面文本可解析
   - 页面：NIST AI 800-4 发布页，发布于 2026-03-06
   - 实际核对内容：受控环境中的上线前评测不足以覆盖现实运行；上线后监测用于发现非确定性、动态输入和意外后果
   - 证据角色：官方研究报告发布记录，不是 Model Q 认证

## 未打开的决定性来源

- C13 的 query 没有给出公司测试报告的标题、URL、发布日期、Model Q 版本、测试集或原始输出，因此本轮没有打开该报告。
- raw 答案明确把报告内容当作题设前提，只判断其推断范围；没有写“来源证实 Model Q 零错误引用”。
- 没有取得独立复现、压力测试、红队、真实企业任务试点或上线监测材料。

## 判定轨迹

1. 拆分为三个原子主张：100 题零错误引用、彻底解决幻觉、所有企业任务安全。
2. 对“彻底解决”设置可反驳判准：固定版本和配置、覆盖幻觉错误类型、明确任务分布和时间窗口、预设失败条件；绝对表述被任一范围内可复现反例推翻。
3. 对“安全”设置独立判准：具体用途和危害、受影响对象、风险容忍度、控制、人工监督、安全失效、事件响应、真实任务评估与持续监测。
4. 设置共同判准：两道门必须针对同一版本、配置、用途范围和时间窗口分别通过；任一门未通过，则联合结论不能成立。
5. 没有代用户设定万能数值阈值；采用 NIST 所述的情境化风险容忍度和领域标准边界。
6. 把公司测试标为 A2 主体自述和公司自测，不升级为独立验证。
7. 将报告的条件式支持限定在其 100 个自选问答和既定错误引用指标。
8. 给出的高信息增益核验动作覆盖独立复现、隐藏代表性测试、压力与对抗评测、逐用途真实任务试点和持续监测。

## 未暴露于 raw 答案的工具轨迹局限

- 外部检索先用搜索结果定位页面，结论只依赖后来实际打开的 NIST 页面或 PDF；搜索摘要本身未作为证据。
- Web 工具返回的是页面解析快照。它能证明本次访问时内容可读取，但不是网页永久存在、未被更新或未被服务器按访问者差异化展示的保证。
- NIST AI 600-1 PDF 通过解析文本核对关键页段，没有逐页视觉审查版式，也没有对 PDF 做加密哈希或独立归档。
- 未运行 Model Q，未重做 100 个问答，也未接触报告的原始数据、选题协议、评分者说明或模型配置，因此无法判断漏标、选择偏差、污染或复现性。
- NIST 框架是通用风险管理指导，不能自动证明任何特定产品安全，也不能替代具体行业、法域或组织的风险接受决定。
- “所有企业任务”没有封闭任务全集。对无边界全称命题，有限测试只能发现反例或提高有限范围内的信心，不能经验性证明不存在任何反例。
- 本轮没有为“安全”强造统一数值门槛，因为门槛会随用途、危害严重度、法域、受影响人群和控制措施改变。
