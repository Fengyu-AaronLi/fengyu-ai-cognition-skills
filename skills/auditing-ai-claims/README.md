# auditing-ai-claims

`auditing-ai-claims` 是一个可恢复的 AI 主张审计工作台。它把整段 AI 回答冻结为输入，把其中每个片段纳入处置范围，再让 Agent 在本地运行时的约束下完成拆分、取证、判断、修复和回放。

它不让另一个 AI 再说一次“这是真的”。它要求每条结论留下可检查的输入位置、来源回执、原文引文、证据用途、支持边界、当前未知和下一步。

当前状态是 `NO-GO / local candidate`。工程能力正在迭代，但新鲜行为会话、语义盲评和正反自动发现尚未完成，不能称为已发行、已开源或已经通过真实使用验收。

## 普通人先看到什么

安装后，把一段 AI 回答原样粘贴给 Agent：

```text
使用 $auditing-ai-claims 审计下面这段 AI 回答。先给我简明主张账本，再保留可回放证据。

[粘贴 AI 回答]
```

完成报告的第一屏只回答六件事：

| ID | 原子主张 | 状态 | 关键理由 | 当前未知 | 下一步 |
|---|---|---|---|---|---|
| C1 | 这句话到底声称了什么 | 已确认、部分支持、被反驳、无法核验或当前未知 | 哪份证据支持到哪里 | 仍缺什么 | 最有效的核验动作 |

来源回执、精确引文、字符位置、证据用途、三道门和哈希放在报告后面的技术部分。普通用户不需要先读一张十几列的工程表，复核者仍能继续追到原始工件。

不能安装 Skill 时可使用 [`zero-threshold-prompt.md`](zero-threshold-prompt.md)。那只是降级提示词，没有本地回执、状态循环、并发锁、硬门或回放能力，不能冒充完整体验。

## 为什么它不是一段提示词

| 常见提示词式核查 | 本工作台的可观察约束 |
|---|---|
| 模型挑几句容易查的内容 | `start` 冻结整段输入，未触及片段自动进入 `auto_gap` |
| 改写后声称对应原文 | 候选保存精确子串、字符区间和 SHA-256，运行时从 `input.txt` 重算 |
| 观点和事实混在一起 | 每个冻结片段只能处于待处理、被主张覆盖、明确排除三种状态之一 |
| 一个链接同时证明所有事情 | `source_identity`、`substantive`、`study_design`、`currentness` 四种用途分别绑定引文 |
| 来源打不开就悄悄换掉 | 失败回执保留；未连接的失败来源只能带理由退休，不能删除或覆盖 |
| 得出结论后只写一句“仍需核实” | 每条 assessment 后强制进入 `claim_countercheck`，反证对象、实查来源和停止理由都绑定当前账本哈希 |
| 抓取中断后留下半个来源 | `source-transactions/` 记录来源提交阶段；使用相同 ID 和元数据重试可幂等恢复 |
| 旧结论沿用到新证据 | 输入、账本、回执或工件一变，旧 gate 与报告立即失效 |
| 多个 Agent 同时改一个账本 | 既有工作区的读操作使用共享锁，写操作使用排他锁 |
| 对话结束后无法复核 | 运行目录保存状态、事件、回执、工件、gate、报告和离线 `replay` |

模型仍负责语义工作，例如拆什么主张、来源支持到哪里、研究设计能否承载因果。运行时负责不该依赖模型自觉的机械底线。gate PASS 表示记录满足当前契约，不表示程序已经证明现实世界绝对正确。

## 收敛循环

完整执行不是一条长命令，而是一个由只读状态机导航的循环：

```text
start
  ↓
next
  ├─ claim_extraction  拆原子主张或排除明确非事实片段
  ├─ claim_assessment  打开来源、绑定引文、判断或保留未知
  ├─ claim_countercheck 记录可推翻条件、实查来源与反向结果
  ├─ audit_summary     汇总跨主张未知与最高信息增益动作
  ├─ gate_repair       只修当前 gate 指出的失败
  ├─ ready_to_finish   执行 finish
  └─ complete          停止，并用 replay 复验保存工件
```

每次写操作、抓取失败或 gate FAIL 后都重新调用 `next`。证据不足不是流程阻断。找不到合格来源时，审计仍应以 `unverifiable` 或 `current_unknown` 收敛，明确不知道什么以及下一步怎么查。

## 整段输入三分法

`start --candidates-file` 接收至少一个调用方识别出的事实候选，并把它精确绑定到原始输入中的位置。运行时同时扫描未被候选覆盖的其余文本，生成 `auto_gap`，防止 Agent 只审自己挑中的句子。候选重复出现时必须补足唯一上下文，不能含糊绑定。

每个冻结单元最终必须且只能落入一个去向：

1. 仍待处理，并阻止完成
2. 被一条或多条原子主张覆盖
3. 被明确归为观点、隐喻、创意写作、个人感受、指令、关系动机或其他非事实内容，并保存具体理由

难查、有争议、页面打不开或可能是假的，都不是排除理由。这些事实候选必须进入主张账本，并保留为未知或无法核验。

## 最短运行示例

先检查运行时：

```bash
python3 scripts/claim_audit.py doctor
python3 scripts/claim_audit.py --help
```

下面的本地示例故意不联网。它展示完整 V3.1 状态循环，并只验证“没有证据时仍能诚实完成”，不证明 Model Z 的价格主张。先从 `templates/` 复制 JSON 模板并替换值：

```bash
RUN_ROOT="$(mktemp -d)"
printf '%s\n' '现在最便宜的公开模型是 Model Z。' > "$RUN_ROOT/answer.txt"

cp templates/candidates.json "$RUN_ROOT/candidates.json"
cp templates/claim.json "$RUN_ROOT/claim.json"
cp templates/assessment.json "$RUN_ROOT/assessment.json"
cp templates/countercheck.json "$RUN_ROOT/countercheck.json"
cp templates/summary.json "$RUN_ROOT/summary.json"

# 编辑五个 JSON 文件：候选和主张均使用原文精确子片段；
# assessment 保持 current_unknown；countercheck 使用 inconclusive 和空来源列表。

python3 scripts/claim_audit.py start \
  --input "$RUN_ROOT/answer.txt" \
  --workspace "$RUN_ROOT/audit" \
  --as-of 2026-08-06 \
  --reason "当前价格比较属于高时效外部事实" \
  --candidates-file "$RUN_ROOT/candidates.json"

python3 scripts/claim_audit.py next --workspace "$RUN_ROOT/audit"
python3 scripts/claim_audit.py claim --workspace "$RUN_ROOT/audit" --file "$RUN_ROOT/claim.json"
python3 scripts/claim_audit.py next --workspace "$RUN_ROOT/audit"
python3 scripts/claim_audit.py assess --workspace "$RUN_ROOT/audit" --file "$RUN_ROOT/assessment.json"
python3 scripts/claim_audit.py next --workspace "$RUN_ROOT/audit"
python3 scripts/claim_audit.py countercheck --workspace "$RUN_ROOT/audit" --file "$RUN_ROOT/countercheck.json"
python3 scripts/claim_audit.py next --workspace "$RUN_ROOT/audit"
python3 scripts/claim_audit.py summarize --workspace "$RUN_ROOT/audit" --file "$RUN_ROOT/summary.json"
python3 scripts/claim_audit.py next --workspace "$RUN_ROOT/audit"
python3 scripts/claim_audit.py finish --workspace "$RUN_ROOT/audit"
python3 scripts/claim_audit.py next --workspace "$RUN_ROOT/audit"
python3 scripts/claim_audit.py replay --workspace "$RUN_ROOT/audit"
```

只有最后一次 `next` 返回 `complete=true`，且 `replay` 对保存工件返回 PASS，才能说这次运行完成。这里的完成是“未知被正确记录且反证动作被显式冻结”，不是价格结论得到证明。

## 取证时的四种用途

`link` 不只记录支持、部分支持、冲突或上下文，还必须说明这段原文负责证明什么：

| 用途 | 只回答这个问题 |
|---|---|
| `source_identity` | 作者、DOI、文件、版本或来源身份是否匹配 |
| `substantive` | 正文是否支持或冲突于主张内容 |
| `study_design` | 研究设计是否能承载拟议的因果推断 |
| `currentness` | 来源日期、版本与页面状态是否足以代表核验日 |

一段证明“论文确实存在”的引文不能同时证明实验结果成立。方法段也不能单独证明效果发生。因果主张要进入确认或部分支持，还需要与账本设计字段一致的 `study_design` 直接引文。

## 反证不是一句免责声明

assessment 只是拟议状态。每条主张随后必须运行 `countercheck --workspace … --file …`，显式记录：什么证据会改变当前状态、实际查过哪些来源、查到了什么、为什么本轮停止。运行时生成时间和 `basis_hash`，将这条记录绑定到当时的主张、证据和 assessment。

因此，主张替换、新证据、重评或来源退役都会自动让旧反证记录失效。决定性状态不能用空来源列表关闭反证环节，发现冲突必须先绑定冲突证据。没有发现反证不等于主张已被证明，只能说明本轮所查范围内没有找到。

## PDF 与失败恢复

运行时可以保存 PDF 原始字节，并尝试调用本机已安装的 `pdftotext`。适配器会固定可执行文件路径、记录解析器版本、限制时间和输出大小，并使用固定参数，不执行 shell。

只有解析成功并留下可复现文本时，PDF 才能用于精确引文绑定。解析器缺失、版本无法识别、超时、格式损坏、输出为空或超限时都 fail closed：原始工件和失败原因可以保留，但该 PDF 不能用于确认、部分支持或反驳。运行时不会自动下载解析器，也不会拿搜索摘要填补正文。

网络抓取使用覆盖重定向和正文读取的单一总时限，默认 20 秒、硬上限 60 秒；正文硬上限 5 MiB。调用方只能降低，不能抬高这些上限。持续送入少量字节不会无限延长一次抓取。

抓取失败也不会被静默抹掉。未连接任何主张的失败来源可以运行：

```bash
python3 scripts/claim_audit.py retire-source \
  --workspace .claim-audits/example \
  --source-id S1 \
  --reason "原页面无法导出可复现正文，改查正式镜像"
```

退休只把来源移出活动集合，回执、工件、原因和时间仍然保留。已经连接主张的来源不能靠退休绕过冲突或缺陷。

来源保存还有一个独立事务日志。若进程在工件、回执、attestation 或账本提交之间中断，gate 会拒绝未完成事务；使用同一 source ID 和完全相同的元数据重试会继续提交，不会重复登记或覆盖旧字节。若崩溃发生在工件完整落盘前、原响应已经无法复现，可用 `abort-source-transaction` 保存终止理由并关闭为 `aborted`。它不删除快照或已写字节，且该 source ID 永久不能复用。

## 强制拦截

- 候选不在原始输入中，或字符区间、文本哈希与 `input.txt` 不一致
- 有输入片段未处理，或同一片段同时被覆盖和排除
- 一条主张吞掉多个互不相关的候选
- 没有合格回执却写已确认、部分支持或被反驳
- 搜索摘要、另一个 AI 回答或 caller-attested 文件冒充原始证据
- 精确引文不能在保存正文中复现
- 来源身份引文冒充实质证据，或研究设计引文冒充结果证据
- 高时效主张缺核验日期、当前性状态、理由或相应用途证据
- 公司自述冒充独立性能证明
- 相关性、自报或 benchmark 被扩大成普遍因果
- 多个转述链接把同一根来源洗成独立证据
- 失败抓取、PDF 解析失败、gate 篡改或报告篡改被隐藏
- assessment 之后没有当前 countercheck，或决定性结论的反证检查没有实际合格来源
- 来源事务没有完成，回执缺少运行时 HMAC attestation，或事务快照与账本不一致
- 医疗、法律、金融行动绕过专业边界

证据不足时，合法终点是 `unverifiable` 或 `current_unknown`。unknown 报告不是失败；用确定语气补完证据缺口才是失败。

## 安装

需要 Python 3.10 或更高版本。核心运行时只使用 Python 标准库；PDF 文本提取是可选的本地 `pdftotext` 适配器。

项目级安装：

```bash
REPO_DIR=/path/to/fengyu-ai-cognition-skills
SKILL_ROOT="$PWD/.agents/skills"
python3 "$REPO_DIR/skills/auditing-ai-claims/scripts/install.py" \
  --target-root "$SKILL_ROOT"

SKILL_DIR="$SKILL_ROOT/auditing-ai-claims"
test -f "$SKILL_DIR/SKILL.md"
test ! -L "$SKILL_DIR"
python3 "$SKILL_DIR/scripts/claim_audit.py" doctor
```

安装器只复制白名单中的运行文件，不覆盖既有目标，不使用符号链接，并通过同级 staging 目录和原子发布避免半安装。安装成功和 `doctor` 成功仍不等于 Agent 已经能够自动发现 Skill。

发行前必须在新鲜、看不到开发上下文的会话中分别留下真实工具轨迹：

```text
现在最便宜的模型、最新法律或当前公司 CEO 是谁？
```

这类外部当前事实应触发本 Skill，并真的进入 `start → next` 循环。

```text
这是一段个人隐喻，请只评估语言，不做事实核查。
```

没有事实子句时不应触发。当前这组正向与负向自动发现，以及新鲜行为复测，都还是 `NOT RUN`，所以发行状态保持 NO-GO。

## 并发、隐私与信任边界

- 对既有运行目录，`next`、`status`、`replay` 和 `quote` 使用共享文件锁；修改账本、来源、gate 或报告的命令使用排他锁。锁只协调本机进程，不是分布式事务，也不能抵御绕过 CLI 直接改文件。
- 新运行目录使用私有权限并带局部 `.gitignore`。这只降低误提交风险，不代表输入、URL 路径、证据正文或报告已经脱敏。
- URL 查询参数不以明文写入回执，只保存查询部分哈希；URL 路径仍可能敏感。
- 本地 SHA-256 证明记录后的字节一致性，不是可信时间戳、远程签名或来源真实性证明。
- 工作区 HMAC 证明回执经过持有本地运行密钥的运行时路径，不抵御取得密钥或控制本机的攻击者，也不证明远端发布者真实。
- `events.jsonl` 是恢复和排查日志，不是防篡改审计链。
- `replay` 只验证保存的历史工件，不刷新今天的价格、法律、职位或产品能力。
- Skill 不保证绝对正确，也不声称消灭幻觉。

## 工程入口与发行状态

```bash
python3 -m unittest discover \
  -s skills/auditing-ai-claims/tests \
  -v
```

当前工程结果、原始 RED 记录、安装试跑和外部来源试跑以 [`evals/results.md`](evals/results.md) 为准，不在 README 里固化一个会迅速过期的测试计数。

V1 baseline 的原始输出继续保存在 [`evals/baseline/raw/`](evals/baseline/raw/)。它们证明无 Skill 时实际发生过什么，不代表当前工作台已经完成行为验收。完整的新鲜行为复测、语义盲评、独立来源复核和自动发现尚未完成，当前仍是本地候选包，没有公开、没有 push、没有创建远程发行，也不声称已开源。

本目录包含经许可改编的方法机制，拟按 CC BY-NC 4.0 提供，禁止商业用途。来源、固定版本和改动范围见 [`NOTICE.md`](NOTICE.md) 与 [`PROVENANCE.md`](PROVENANCE.md)。
