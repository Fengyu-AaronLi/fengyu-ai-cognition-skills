# C12 隔离复测轨迹

- 运行日期：2026-08-05（Australia/Sydney）
- Runner task：`/root/retest_c12`
- 已读 Skill：`<candidate-repo>/skills/auditing-ai-claims/SKILL.md`，完整读取 258 行
- 用例读取：只从 `skills/auditing-ai-claims/evals/cases.json` 提取 `id=C12-mixed-content` 的 `query` 与 `expected_behavior`

## 实际打开的 URL 与结果

| URL | 访问结果 | 本次用途 |
|---|---|---|
| https://openai.com/api/pricing/ | 成功访问，但最终重定向到 `https://openai.com/business/pricing/` | 重定向后的页面不是决定性的 API token 价格证据 |
| https://developers.openai.com/api/docs/pricing | 成功打开，最终 URL 不变 | 当前官方 API 定价总页，用于价格模式与最新模型价格背景 |
| https://developers.openai.com/api/docs/models/gpt-5-nano | 成功打开，最终 URL 不变 | 直接看到 `gpt-5-nano`、每百万普通输入 token 0.05 美元、缓存输入 0.005 美元、输出 0.40 美元，以及 Free 为 Not supported |
| https://developers.openai.com/api/docs/models/all | 成功打开，最终 URL 不变 | 当前官方模型目录把 GPT-5 nano 列在“More models”中，未附 Deprecated 标记 |
| https://developers.openai.com/api/docs/models/compare | 成功打开，最终 URL 不变 | 可见比较页默认展示 GPT-5.6 系列，未提供覆盖全部旧模型的决定性全量最低价排名 |
| https://developers.openai.com/api/docs/models/gpt-5-nano.md | 打开失败，工具返回 400 Unsupported content-type: text/markdown | 未作为证据 |
| https://developers.openai.com/api/docs/pricing.md | 打开失败，工具返回 400 Unsupported content-type: text/markdown | 未作为证据 |
| https://developers.openai.com/api/docs/models/all.md | 打开失败，工具返回 400 Unsupported content-type: text/markdown | 未作为证据 |

## 轨迹与证据边界

- 搜索结果摘要只用于定位页面，最终判断只使用实际成功打开的官方页面。
- 本文件是可对外核对的访问摘要，不是逐字工具日志。它不暴露内部引用标识、搜索排序、完整响应体、请求头、系统日志或隐藏推理。
- 浏览工具报告页面为当日抓取；本答案仍把运行日 2026-08-05 明确写作核验日期。价格与模型状态会变化，之后使用时应重新打开官方页面。
- 官方页面属于 OpenAI 主体自述，可直接证明官方当前列价和目录状态，但不等同于独立复现，也不能证明某个具体账户一定可调用或享有何种额度。
