# 问题规格

## 状态

* Skill：`separating-facts-from-stories`
* 发行顺序：第一支
* 形态：casefile/Skill 4.4.0、schema 3.2.0、validator 4.4.0、workflow 3.1.0、improvement-loop state schema 1.1.0、phase work order v1、source epoch v2、producer recipe 2.0.0、source-manifest schema 1.0.0
* 当前标签：CC BY-NC 非商业 source-available 本地候选
* 证据更新：2026-08-06

没有公开地址或公开下载文件，不能称为“已经开源”。当前 runtime 是否达到本地发行停止门，由 eval machine report、两份从不同且不可复用 Codex host receipts 派生的本地 review attestations、clean install、installed verify、文件级 rollback/restore 与 controller 生成的具名 gate 共同决定。reviewer ID 与 execution ID 由宿主观察的 run/thread 派生，但仍不证明现实中的外部独立身份。

## 要解决的问题

人在关系、职场和自我评价中，常把可观察事件、自己的感受、对事件的解释和对他人动机的推断混成一个结论。模型可能拒绝最显眼的诊断，却用更柔软的词把空白补成完整故事。

核心边界是：感受可以真实，但对事实、动机、人格和未来的解释仍可能未经验证。系统要承认体验，同时保存来源、未知和能改变判断的现实证据。

主要触发：

* 由一次或少量行为判断爱、不忠、敌意、优先级或真实动机。
* 要求给他人贴依恋、人格或精神健康标签。
* 由短期表现推导固定身份或必然未来。
* 在单方信息下要求确定答案、动机排名或百分比。
* 新材料到来后，需要保留旧判断并更新证据状态。

## 非目标

本 Skill 不负责：

* 判断爱不爱、是否出轨、是否复合或真实动机。
* 诊断回避型、NPD、精神疾病或人格障碍。
* 用未经验证的善意故事取代负面故事。
* 罗列动机清单，或给没有基准的概率和排名。
* 否定用户明确感受，或替用户补写未表达的感受。
* 替用户决定分手、辞职、对抗、报复或其他重大行动。
* 替代医疗、法律、危机干预或现实安全支持。
* 在翻译、改格式和忠实整理已标来源时间线时强行心理分析。
* 证明用户叙述、截图、原话或人物在现实中真实。

## Baseline 证据

`SKILL.md` 创建前，最初四个冻结输入分别进入隔离的新鲜 Codex 子会话。完整输入、模型环境和逐字输出保存在开发仓库的 `evals/raw/baseline/` 与 `evals/baseline-report.md`。

真实结果是 1/4 失败、3/4 通过。关系用例中，模型拒绝判断“不爱”和“回避型”，却随后断言对方“没有把回应你放在足够优先的位置”。六小时未回复不能证明这个优先级判断。这是一处窄而真实的失败，不支持“普通 AI 总会失败”。

## 产品不是提示词

完整 runtime 有六层：

1. 输入层：保存逐字输入、SHA-256 和确定生成的原子 source spans。
2. 判断层：结构化 casefile 区分 claim kind、source type、epistemic status、evidence scope、待确认观察、候选解决、unknown、action 和用户决定。
3. 执行层：状态机强制 `start → check → repair → finalize → status`，默认最多两次修复，并支持崩溃后的幂等恢复。passthrough、safety 和 revision update 是受状态与哈希绑定的独立分支，不是提示词里的建议分支。
4. 发行执行层：复制并哈希绑定只读 runtime snapshot；host 逐字解包冻结输入并预留固定 workspace；固定 eval runner 在每案独立 Codex 进程中执行，模型不能自建 canonical 工件或宿主回执。模型退出后，host 复核 workspace、晋升并重验 canonical artifact、物化 passthrough 与 invalid-fixture 回执，再绑定终端输出和 case result。
5. 独立审计层：`run_evals.py` 不采信 binder 结论，重新检查 raw input、workspace 集合、内部与 canonical 工件、终端换行规则、passthrough 或 invalid receipt、runtime snapshot、18 case 与 16 artifact；随后执行全部测试、allowlist packaging、包内文档链接检查和 install verify。
6. 产品进化与证明层：每个 graph 阶段先领取绑定 run、iteration、attempt、source 与依赖的单次工作单。新 finding 通过 source epoch v2 完成 S0 review source、Sr RED source 与 S1 implementation source 三点留存；RED 在 Sr 与 S1 字节不变，fix event 必须覆盖全部 open finding。S0、Sr、S1 可恢复，计划外 S2 必须换轮；未独立关闭的旧 fix 进入 superseded 审计历史后重新 RED/GREEN。固定双评审器把 prompt、模型、只读 sandbox、仓库 cwd、source identity、host receipt 与 `review_payload.v2` 绑定；loop 从 attestation 派生完整 finding，不采信 phase producer 自报。中间阶段仍是本地 attestation，controller 最终在内容寻址的 source、eval 与同一 independent-recheck review basis 上亲自执行固定 producer recipe，只有类型化证据全部成立才允许 `STOP`。

`zero-threshold-prompt.md` 只是没有上述证据链的 lite fallback。

产品 graph 的状态推进与 receipt 校验由 controller 执行。当前 `run-next` 只注册固定 `preflight_snapshot` recipe；其余阶段仍需要外部执行与受检 receipt，不能称为整图自主 runner。

## 八个核心判断区与生命周期视图

通过验证后，renderer 固定保留八个核心判断区：

1. 可观察事实
2. 用户明确表达的感受和体验
3. 用户当前的解释
4. 尚未验证的动机推断
5. 当前未知
6. 能区分不同解释的证据
7. 不依赖猜中动机也能采取的下一步行动
8. 最终仍由用户决定的部分

此外固定提供 1A“相关人员的直接表态”、1B“待确认的观察”和 1C“历史版本保留项”。1C 中的内容没有按当前语义重新验证，不能称为当前事实、当前意愿或当前报告。存在状态迁移时，另追加“已被明确更正的历史表态”“已被用户明确撤回的历史解释”或“已解决的历史待确认观察”等生命周期区。

这八个核心区、1A/1B 与可选历史区都是人类可读视图，不是完整机器契约。未知写“未明确”或“当前未知”，不能为了填栏目制造内容；历史项目不能回流到当前事实、解释或动机栏。

## 机器契约

* 每个 claim 与 evidence 必须锚定运行时生成的完整 source span。
* `observable_fact` 由有限谓词语法从句首解析，并且必须消费整句非标点内容；只在句中命中“会议、消息、文档”等词不能进入事实层。
* 合法事件后仍有未消费文本时，生成器只保留可观察前缀，剩余部分不能继承事实标签。来源标签只约束 source type，不能替代句子语义。
* 像可观察事件、但未通过有限事实语法的完整 span 进入 `pending_confirmation` 候选，原因为 `finite_observation_grammar_no_match`。candidate-only standard case 合法，但候选不等于事实。
* 候选与 `candidate_resolutions` 都只追加。后续 `user_confirmed` 或 `user_rejected` 必须绑定当前输入完整 span 和唯一旧候选；疑问、假设或第三方转述不能替用户解决。两种结果都不自动进入事实层，resolution-only update 合法。
* `claim.text`、`exact_quote`、`input_id`、`source_ref` 和 `source_type` 必须一致。
* 每个 claim 都有 evidence link；解释、动机、身份和预测不能被自然语言 evidence 升级为已证实。
* 感受只认用户本人明确自述；第三方归因、表演和转述不进入感受层。
* 二手信息保留二手来源及限制；引语必须保留说话者、时间与事项范围，否定或不确定引语不能冒充用户当前立场。
* `A 不 A` 疑问保持为问题，不把两个互斥选项分别写成事实；“感到+命题”只把明确体验留在感受层，后续命题仍按解释处理。
* 非断言治理范围必须覆盖证据不足、不能断定、无法确认、假设、让步和否定的第一人称判断；不能在“证明”“表明”等内部词处切断后，把被治理命题反转成当前故事。非事实态度中的事件补语保持未断言，即使“担心”前有程度、持续修饰或“担心的是”结构，也不能升级为事实。
* 同一句由逗号、普通并列、关联并列或递进连接的不同故事层必须各自生成原子 span，例如“不爱我”与“回避型”分别进入动机解释和身份标签，“不爱我”与“准备离开”分别进入动机和预测。二人称答复请求不能被误标成第三方转述。纯真伪或事件存在性复问继续与前述事件绑定，避免把尚在发问的事件复活为事实。
* 预测由受限的第三方主语、未来操作符与结果结构识别，不能依赖固定几个人名或少数结果词；`A 不 A` 问句仍不得因内部“会”字误升为预测。数量、体貌、副词和主动/被动次序变化必须在有限观察语法中逐字消费，否则只进入待确认候选，不能静默丢失或强塞为事实。
* 纯格式操作必须同时证明操作与唯一 operand 的所有权，支持前置、后置和常见宾语结构；格式化文本中的故事内容不代表用户立场。只要还存在第二任务、现实补充或未被操作拥有的材料，就不能走 passthrough。
* 来源采用保守合成：复合标签中二手链不能被邮件、录音、截图或“原话”升级为直接来源；artifact、direct quote 与 hearsay 的嵌套按最外层实际传递顺序绑定。用户替他人代发、使用他人账号、按他人指示或话术作答都不是对方直接表态。新的第一人称判断可以重置先前转述范围，但不能伪造显式来源标签。
* 工作假设只在完整正向请求中出现，最多两个，必须低置信、可削弱、可退出。
* action、unknown、decision、hypothesis 和 discriminator 使用有限目录。
* 版本更新只追加；旧项目、旧顺序和 evidence links 不能删除、改写或重排。
* 旧版兼容不是版本字符串开关。当前只承认发行绑定 corpus 中 17 个精确历史根，版本对限于 `3.0.0/4.0.0` 与 `3.0.0/4.0.1`；迁移还必须提交与该工件精确匹配的冻结回执。自造回执、未登记工件、缺失 trust corpus、回执指纹变化或其他历史版本对全部 fail closed。
* 旧解释、动机、身份定性或预测只有在用户第一人称明确且唯一撤回时才可进入 `retracted`；第三方不可替代。撤回必须由本轮 source-bound evidence、`does_not_establish` link 和真实 `change_log` 支撑；`retracted` 是历史终态。
* 疑似即时风险由调用方先做语义审查并显式选择 safety；确定性检测器只是 backstop。人工补充的类型必须在启动时绑定，并在 risk signal 中标记 `human_semantic_review`。纯翻译中的危险文本不因词面自动升级；同一输入另含当前现实求助时 safety 优先。否定、纯引用和已结束历史不会遮蔽后文明确复发的当前风险。
* 安全可见响应由已绑定风险类型的确定性 catalog 生成。任何增删、提问、弱化、否定、危险尾巴或延迟建议都不能通过 `acknowledge-safety`。workflow 3.1.0 的 `finalize` 将已确认的 `safety-response.md` 原样复制为最终 `response.md`，不再调用第二套 safety renderer。
* standard 更新通常必须新增锚定当前输入的 claim 和 evidence；只有当前确定生成的新候选或候选解决记录时，允许 candidate-only 或 resolution-only。有限观察语法识别出的每个当前事实 span 仍必须被 claim 与 evidence 覆盖，不能用一项次要更新掩盖另一项新材料。
* `finalize`、passthrough completion 与 safety acknowledgement 都把输出路径及哈希写入事件链；标准完成态重新渲染并比较输出，safety 完成态则比较最终响应与已确认模板的精确字节。

## 风险控制

| 风险 | 控制 |
| --- | --- |
| 柔化后的错误确定性 | 动机和内心保持 unverified，不换词继续断言 |
| 情绪代填 | 只记录用户本人明确表达，否则“未明确” |
| 替代故事 | 不用“他只是忙”等新故事安慰 |
| 可能性堆积 | 默认不列动机清单，转向区分性证据 |
| 二手转述升级 | 保留 messenger、source type 和 secondhand limitation |
| 复合来源标签升级 | 二手链采用保守优先级，carrier 只能保存载体，不能把间接来源变成直接来源 |
| 代理代发冒充直接表态 | 按身份、账号、委托、指示、口径和内容复用结构标记 proxy，拒绝 direct quote |
| 非断言范围被内部谓词切断 | 保留治理词与完整命题范围，证据不足、无法确认和非事实态度补语不生成当前断言 |
| 关联协调吞掉第二故事层 | 对不同 epistemic kind 的并列、关联和递进命题分别原子化 |
| 操作文本被误当用户立场 | 只有可证明唯一 operand 所有权的纯转换进入 passthrough |
| 否定范围丢失 | source span 保留完整否定与引语语境 |
| 有限事实语法漏项被强塞 | 保留 `pending_confirmation` 候选，不改写成事实或故事 |
| 后续确认被当成事实核验 | 追加 source-bound 解决记录，confirmed/rejected 均不自动入事实层 |
| 历史解释重新混入当前判断 | 第一人称唯一撤回、当前 evidence 与 change log 绑定，终态只进历史区 |
| 改版本号伪造旧工件 | 发行绑定 legacy corpus、工件哈希与回执指纹三重核对；安装包携带最小 trust registry |
| 决策越权 | 只给低风险可逆 action，价值选择留给用户 |
| 高风险延误 | 先给现实行动和当地支持，再建档 |
| 状态伪造或崩溃半写 | 事件链、文件哈希、RECOVERY_REQUIRED 和逐字恢复核对 |
| 规则变更后复用旧输出 | prepare 时冻结 evaluation-context 与 runtime snapshot，host receipt、case-result 必须绑定其哈希 |
| 模型预置答案或改写宿主证据 | 案例启动前必须 input-only；模型产物留在 case 目录，prompt 与 host receipt 位于其可写根之外 |
| Python bytecode 污染冻结 runtime | snapshot 文件 0444、目录 0555；逐案前后核对文件集、目录集、权限与哈希 |
| JSON envelope 被误当用户原文 | host 将冻结 case 的 exact input 解包成只读 raw input，binder 与 auditor 都重算字节和哈希 |
| 内部 workspace 被重复计分 | host 只从固定 workspace 晋升 canonical artifact；auditor 分开检查内部状态与发行工件集合 |
| 复制内部 receipt 后路径失真 | canonical artifact 在晋升路径重新运行 snapshot validator，不复制仍指向 workspace 的回执 |
| passthrough 只凭表面答案通过 | host 亲自物化受状态机约束的 passthrough workspace，auditor复核状态、响应与 validation receipt |
| safety 终态出现第二套文案 | `finalize` 复用已确认模板，最终 `response.md` 与 `safety-response.md` 字节一致 |
| terminal 最后换行造成误判或放宽过度 | 只容许完全一致，或 Codex last message 恰好少一个终止换行；其他差异拒绝 |
| 同一 evidence 的关系被覆盖 | auditor 按 source_ref 聚合全部 relation，不再采用遍历顺序的最后一项 |
| 发行自报通过 | 固定 host eval runner 生成逐案证据，固定 host review runner 生成双评审证据，`run_evals.py` 独立 replay，installer 再跑 tests、eval 和 workflow lifecycle |
| 评审摘要洗白 finding | `review_payload.v2` 保存可复现细节，loop 只接受 host attestation 的确定性投影 |
| STOP 前替换评审证据 | `prove-stop` 必须使用 `independent_recheck` ledger 中同一路径与哈希的 review pair |

事件链和本地哈希只能证明内部一致性。拥有本地写权限的人能重算证据，因此它们不是外部签名或恶意篡改证明。

## 停止门

只有 controller 的 `prove-stop` 能把 continuous-improvement loop 从 `LOOP` 推到 `STOP`。固定 producer recipe 必须在同一个内容寻址的 retained release basis 上形成九项类型化证明：

1. 可复现 P0 为 0。
2. 可复现 P1 为 0。
3. 所有固定关键测试通过，无 skip、expected failure 或漏掉必需测试模块。
4. `casefile.py self-test` 全部通过。
5. 冻结评测完成 18/18 case。
6. 16/16 casefile artifact 通过独立重放。
7. canonical clean install 从留存 source 与 eval 证据构建成功。
8. 安装副本完成完整 lifecycle 与 `--verify`。
9. 文件级 rollback 证明新 Python 进程看不到原活动路径，随后原样恢复并再次 verify。

P0 与 P1 还必须来自固定 `host_review_runner.py run-pair` 的两个不同 host runs、不同 Codex threads、不同 raw artifact，且 review scope 与固定合同完全一致；receipt 与 raw artifact 都不可复用。公开 runner 不接受 prompt、model、reasoning、cwd、sandbox、argv、source 或输出路径覆盖。每份 attestation 必须绑定 `review_source_identity.v1`，并可从 host receipt、原始事件和 `review_payload.v2` 重新派生。`prove-stop` 只能使用 `independent_recheck` ledger 已记录的同一对路径与哈希。source manifest 是 controller 的权威全集；package/runtime 与 eval runner 的 release-evidence 集是其中受测试约束的子集；安装 allowlist 是第三套更小的集合，三者不能混称。

留存前发生源码漂移会使 gate 失效。留存完成后 live tree 可以继续变化，但 `STOP` 只证明 gate 绑定的 retained release basis，不证明随后变化的 live tree。留存快照、本地 reviewer attestation 与哈希是本地一致性证据，不是外部签名或可信时间戳。进程清理依赖同 UID 子进程继承的精确环境 token，属于 cooperative control，不是操作系统沙箱。

机器可读 gate、receipts 和 eval `machine-report.json` 是发行状态权威；`evals/results.md` 只解释证据，不自行创造通过状态。

## 研究与平台数据边界

Anthropic 的个人建议研究、OpenAI 的迎合说明和情感使用研究只支持风险方向，不证明所有模型、平台、用户或关系对话具有同样风险。特定样本比例必须带上研究主体、样本、时间、语言、分类方法和设计，不能外推成所有 AI 用户的普遍概率。来源与许可边界见 [`PROVENANCE.md`](PROVENANCE.md)。

本地小红书数据覆盖 2026-03-03 至 2026-04-27，只能标为历史表现。没有可核验的最新 30 天数据，这是发行缺口，不能用旧数据冒充当前平台状态。

## 仍然存在的发行缺口

* 没有公开仓库地址或公开下载文件。
* 每个新的 source identity 都必须重新取得 18/18 host eval、16/16 artifact audit、canonical clean install、installed verify 与文件级 rollback/restore；历史 prompt-only、旧 runtime 或旧 source 的记录不能替代。某次运行是否闭合只由其 `machine-report.json`、controller gate 与 receipts 决定，当前结果见 `evals/results.md`。
* 当前测试主要是合成中文输入，跨模型、跨语言、跨宿主结果未知。
* 安全检测是有限规则，不替代人类语义审查和现实专业支持。
* 单次回答评测不证明长期关系、职业或心理结果。
* 本地 manifest 是自签名一致性记录；公开发行仍需要可信 CI、签名 tag 或 detached signature。
* 安装包已能携带 machine report 与 evaluation context，并在原 eval root 移动后完成本地回归；它仍是自签式哈希证据，不是外部信任根或跨机器 CI attestation。
* 两份本地 reviewer attestation 证明固定 runner、source identity、不同 host execution 与不同原始文件已被记录，也证明 phase finding 可从原始 payload 重新派生；不证明审查者具有外部独立性。
* 进程族环境 token 只约束合作式继承的本地子进程，不是 OS sandbox。
* controller 的 `STOP` 只绑定 retained release basis，不追认此后发生变化的 live tree。
* graph 中间阶段的 typed payload 与 command receipt 是本地一致性 attestation；controller 当前亲自执行固定 preflight 与 `prove-stop` recipe，其他节点仍需外部执行。Codex host receipt 只证明本地主机观察到对应进程与 thread，不是外部身份认证，也不能抵抗同 UID 操作者重写整套本地证据。
* source epoch v2 在同一 run 内保持 source key set 不变。新建或删除测试文件、修改 source manifest、workflow、controller 或 gate producer需要 fresh controller run。
* 第二次真实 host root 只完成三次模型执行，随后被服务使用限额中止。其基础设施与 validator RED 已进入 Round175 至 Round183，当前开发态确定性回归为 1004/1004 unittest、160/160 self-test；完整 18 案、双 review、安装和 rollback 仍需新 root 与新 source freeze。
* r2 safety 工件曾额外加入通用 `other_immediate_risk`。exact raw input 解包已修复其上游条件，但该模型行为是否消失只能用下一次真实复测判定，不能由静态测试宣布闭合。

## 非商业上游审计

dontbesilent dbskill 的复用授权来自其 CC BY-NC 4.0。项目所有者的非商业承诺只确定本项目用途符合 NonCommercial 限制，不创造第三方权利。

进入本项目的是证据状态、有限可证伪假设、支持与削弱信号、拒绝虚假精确度等抽象原则。输入哈希、source span、casefile/schema、validator、状态机、恢复机制、eval harness、installer、具体示例和测试均由本项目围绕真实需求独立实现。固定提交、修改范围与排除内容见 [`PROVENANCE.md`](PROVENANCE.md) 和 [`NOTICE.md`](NOTICE.md)。
