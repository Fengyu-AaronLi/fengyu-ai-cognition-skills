# 事实与故事分离

状态：CC BY-NC 4.0 非商业 source-available 本地候选，尚无公开地址或下载文件，不能称为“已经开源”。

它处理关系、职场和自我评价中的同一种认识论错误：把发生过的事、自己的感受、对事件的解释和对他人动机的推断混成一个确定结论。感受可以真实，但“他为什么这样”“这说明我是什么人”仍可能未知。

这不是一段八栏提示词。完整形态由输入绑定、结构化 casefile、有限观察语法、确定性 validator、有状态 repair loop、版本链、冻结评测门、allowlist installer，以及产品改进 controller 组成。模型负责语义判断，运行时负责让越界有错误码、失败有回执、改动后必须重验；`prove-stop` 执行固定 recipe，不能接受一组外部自报的通过布尔值。phase receipt 与 command receipt 是本地 attestation；graph host receipt 记录 controller 对固定子进程的观察；Codex host receipt 绑定本地进程、thread、固定 prompt、冻结 source 或 runtime snapshot 与原始输出。固定评审器还把权威 manifest 的逐文件 source identity 纳入 receipt 与 attestation。它们都不是外部签名或外部身份认证。

```text
输入原文与哈希
      ↓
source spans → casefile → check
                         ↓ 失败，最多修复两次
                    repair_required
                         ↓ 通过
                 finalize → status
                         ↓
                 哈希绑定的 response
```

完整产品由六层共同成立，不以 `SKILL.md` 的字数冒充能力：

1. `SKILL.md` 只负责触发、路由和最小行为边界。
2. `casefile.py` 与 JSON Schema 把来源、判断类型、证据关系、未知、行动和决定变成机器契约。
3. `workflow.py` 3.1.0 管理标准、passthrough、safety 和版本更新的状态、重试、恢复与终态输出。
4. 固定 host eval runner 解包 exact input、预留 workspace、调用 fresh 模型、晋升 canonical artifact，并生成模型不可自报的 receipt 与 case result。
5. 独立 auditor 从冻结输入重新执行 validator 和 renderer，同时重查 workspace、内部与 canonical 字节、终端输出和 snapshot 完整性。
6. improvement controller 用 RED、GREEN、独立复核、source freeze、18 案 eval、安装与回滚组成产品进化 loop；只有固定 `prove-stop` 能产生某个留存版本的 `STOP`。

## 两种体验不是同一个产品

| 形态 | 能做什么 | 做不到什么 |
| --- | --- | --- |
| 零安装 lite | 给普通对话式 AI 一个八项分离框架 | 不绑定输入，不产出 casefile 和验证回执，没有状态恢复、版本链或发行门 |
| 完整 runtime | 执行 `start → check → repair → finalize → status`，保存机器可审计证据 | 不能证明用户叙述在现实中为真，也不是防恶意本地篡改的数字签名 |

## 两个 loop 不是同一件事

单案例 loop 约束一次回答：输入先绑定，再填写 casefile，失败最多修复两次，最终重新核对工件哈希后才渲染。产品进化 loop 约束 Skill 自己如何被修改：

```text
review finding
      ↓
begin-step，领取当前 run 的单次工作单
      ↓
S0 → 写 RED → Sr → 最小实现 → S1
      ↓
record-step，提交 RED/GREEN 与 finding 事件
      ↓
independent local recheck → source freeze → eval → install
      ↓
prove-stop 固定 recipe：未过则 LOOP，全过才 STOP
```

`source_epoch_plan.v2` 保留三点源码：S0 是 review 时源码，Sr 是新增或修改 RED 后的源码，S1 是实现后的源码。RED 在 Sr 与 S1 必须逐字相同；所有变化的 before、RED、implementation-after 字节都留存在 state dir。work order 绑定 controller run、iteration、attempt、source 与依赖 receipt，不能跨轮复用。两次 review 都只能由固定 `host_review_runner.py run-pair` 发起；完整 finding 进入 loop 后，独立复核使用的同一对 attestation 才能进入最终 `prove-stop`，不能在门前替换成另一对空报告。

当前 `run-next` 的 controller-owned 固定 recipe 只覆盖 `preflight_snapshot`。进入 `adversarial_review` 后，其余 graph 节点仍需 `begin-step`、外部执行、受检 receipt 与 `record-step`；未注册节点会稳定返回 `RUNNER_RECIPE_UNAVAILABLE`。这是一条明确的自动化边界，不把状态机误写成已经能自主执行整张 graph。冻结 eval 的 runtime snapshot 还会把文件设为 `0444`、目录设为 `0555`，每案前后同时重验内容、文件集、目录集与权限，避免真实 Python import 生成 bytecode 后污染冻结 source。

冻结 eval 也不是让模型自己决定怎么落盘。prepare 后，host 将 JSON case envelope 中的 exact input 解包为只读 `.runtime/input-N.txt`，并预建每轮唯一 workspace。模型只能填写 workspace；host 在进程退出后检查完成态，将内部 casefile 晋升到 canonical `artifacts/`，在 canonical 路径重新跑 validator，并物化 passthrough 与 invalid-fixture 的受检 receipt。独立 auditor 随后再做一次相同边界的独立重放。内部 workspace 不计为第二份发行工件，复制后仍指向旧路径的内部 receipt 也不能被冒充为 canonical receipt。

`resume` 也不是“再试一次”的口号。live source 精确等于 S0、Sr 或 S1 时，当前授权仍可继续；保留历史 receipt 与 artifact 字节的计划外 S2 会令旧工作单和未提交 source epoch 失效，controller 只开启一个新 round。已经 GREEN、尚未独立关闭的 fix 会进入 `superseded_fixes` 审计历史，当前 fix 清空并要求在新 source 上重新走 RED/GREEN。若 S2 本身改坏历史 RED 或 receipt artifact，系统以 `STATE_EVIDENCE_INVALID` 拒绝自动恢复，必须保留现场后 fresh `start`。`independent_recheck` 只要还留下任何 open finding，就不能推进到 source freeze。

finding ID 的 `SOURCE-DRIFT-R…` 前缀属于 controller，review receipt 不能抢占。已经完成的 retained `STOP` 从内容寻址 basis 校验 workflow、source manifest 和历史 RED；随后 live tree 中普通 source、workflow 或 manifest 缺失，不会反向抹掉这份已留存证明，也不会把变化后的 live tree算进旧 `STOP`。

同一 run 只允许修改 manifest 已列出的现有 `test_*.py` 和声明过的非测试实现文件。若需要新建测试文件、删除或重命名文件，或修改 source manifest、workflow、controller、gate producer，必须保留现场并 fresh `start`。详细合同见 `evals/improvement-loop-spec.md`。

## 零安装体验

把 [`zero-threshold-prompt.md`](zero-threshold-prompt.md) 复制给对话式 AI，再粘贴你的问题。它适合先体验“事实、感受、解释、动机推断、未知、证据、行动、决定”这项区分。

这只是降级入口。若你需要可重复验证、有限重试、断点恢复或新材料追加版本，请使用完整 runtime。

## 完整 runtime 的宿主要求

宿主需要：

* 能发现项目级 `SKILL.md`
* Python 3.10 或更新版本
* 可执行本地命令
* 可写本地文件系统
* 支持 POSIX `fcntl` 文件锁的运行环境

只支持聊天提示词、不能执行 Python、不能写文件或没有 POSIX 文件锁的宿主，只能使用 lite 形态。Windows 与其他 Agent 宿主尚未完成兼容性验证。

## 门禁闭合后的本地安装

不能用 `cp -R` 直接安装。安装器会先执行 runtime 自检、完整工作流冒烟、全部关键测试，再要求同一份源码已由固定 host eval runner 逐案执行，并通过冻结的 18 个 case 与 16 个 casefile artifact。缺少当前 `machine-report.json`，或 report 绑定的发行字节已经变化时，安装应失败。

```bash
skill_dir="/path/to/fengyu-ai-cognition-skills/skills/separating-facts-from-stories"
eval_root="/absolute/path/to/a-completed-eval-root"
target_root="/path/to/your-project/.agents/skills"

python3 "$skill_dir/scripts/package_runtime.py" \
  --target-root "$target_root" \
  --eval-root "$eval_root"

python3 "$target_root/separating-facts-from-stories/scripts/package_runtime.py" \
  --verify "$target_root/separating-facts-from-stories"
```

安装器拒绝覆盖同名目录，只复制固定 allowlist，并写入 `runtime-manifest.json`。安装包同时保留 `scripts/package_runtime.py`、`evidence/machine-report.json`、`evidence/evaluation-context.json` 与最小 `evals/legacy-migration-corpus.json`，并拒绝带有安装后断链的 Markdown。corpus 只含迁移信任所需的哈希和回执指纹，不打包 34 个历史原件。移动原始 eval root 后仍可从已安装目录执行 `--verify`。这项可移植路径已由回归测试覆盖，但本地 manifest 和哈希仍只是自校验，不是供应商签名、可信时间戳或外部 CI attestation。

上面是用户直接调用 packager 的安装路径。产品发行的 `STOP` 更严格：controller 必须在内容寻址的留存 source、eval 与 `independent_recheck` 已记录的同一对 review attestations 上执行固定 producer recipe。两份 attestation 必须由不同且不可复用的 Codex host receipts 派生，并绑定同一份 source identity。随后才能生成 canonical install，完成 verify 与文件级移出、恢复、复验。直接安装成功不等于 `STOP`。

当前冻结评测与发行是否闭合，以对应 eval root 的 `machine-report.json`、controller 生成的具名 gate 与类型化 receipts 为准；`evals/results.md` 只解释这些机器证据。历史 prompt-only 的 8/8 不能打开安装门。

## 历史 4.0.0 确定性集成示例

下面是合成输入上的历史确定性集成，不是用户真实职场记录，也不是当前 source identity 的模型行为评测。

输入：

```text
老板连续两次没让我参加会议。我认为他在架空我。
```

通过 `start → check → finalize → status` 后，renderer 的核心输出是：

```text
可观察事实：“老板连续两次没让我参加会议。”
用户明确表达的感受和体验：未明确。
用户当前的解释：“我认为他在架空我。”
尚未验证的动机推断：未发现独立的动机推断。
当前未知：正式职责、参与范围或审批权限是否发生变化。
证据边界：E1 支持 C1，强度 direct；E1 对 C2 为 does_not_establish。
下一步：围绕具体安排、职责、边界或时间做一次中性核对。
仍由用户决定：是否继续留任或开始评估其他职业选择。
```

开发仓库在 `evals/raw/runtime-integration-v40-workplace/` 保留历史 4.0.0 的完整 input、response、casefile、回执、状态、环境和命令结果；当前 4.4.0 的发行有效性只认重新冻结的 eval 与 machine report。历史 baseline 与 prompt-only 对照保存在 `examples/demo.md`。这条记录是确定性集成，不是当前 host-model 有效率，也不会塞入最小安装包。

事实层采用 fail-closed：有限语法必须从句首解析并消费整段非标点内容。它会识别常见的回复、会议参与与变更、任务完成、删除、日历和权限状态；若出现尚未支持的普通表达，原文仍留在 `source_spans`，但不会被运行时假装理解或仅凭“会议、文档、截图”等词提升为事实。扩展语法时必须同时增加合法改写与“合法事件加故事尾巴”的成对回归。

当前 4.4.0 保留直接引语归属层：当前意愿、决定或边界使用 `stated_position`，其他通过范围检查的具名陈述使用 `attributed_statement`。这让“他原话说手机送修”可以被保存，却不会变成“手机确实送修”的事实。疑问、虚构、材料或虚构载体、未来或条件话语、二手转述、代理代发、非原话标签、否认、撤回和来源不明的引语仍被拒绝；历史陈述可以保留，但不会冒充当前立场。

旧版迁移使用 release-bound trust corpus，不接受调用方自报成功。当前只承认 17 个精确历史根，版本对限于 `3.0.0/4.0.0` 与 `3.0.0/4.0.1`；工件 canonical SHA 与 receipt canonical 指纹必须同时命中 corpus。`4.0.2`、`4.1.x`、`4.2.0`、未登记工件、自造回执和缺失 registry 均明确拒绝。第一次迁移生成不可变 `legacy_epoch`，后续版本只追加；旧项目进入 1C 历史保留区，不被 renderer 重命名为当前事实或当前意愿。

## 适用边界

适用：有限观察被升级成确定动机、人格诊断、固定身份或必然未来，尤其是关系、职场和自我评价场景；也适用于新材料到来后需要保留旧版本并更新证据状态的场景。

不触发：纯翻译、改格式、忠实整理已标来源的事件时间线，以及没有解释或动机争议的普通事实任务。被翻译材料里的危险句子本身不等于用户正在实施或遭遇风险；同一输入若另外包含当前现实求助，则 safety 优先。passthrough 只完成原任务，不套八项心理分析。

强制边界：

* 不诊断回避型、NPD、精神疾病或人格障碍。
* 不判断对方爱不爱、是否出轨、是否会复合。
* 不用另一个武断故事替换用户故事，也不否定明确感受。
* 不替用户决定分手、辞职、对抗或报复。
* 疑似医疗、法律、现实安全、自伤或他伤风险，先转向现实紧急服务或合格专业支持。确定性路由只是有限 backstop，不能穷尽自然语言风险表达。

## 安全分支不是一段自由提示词

宿主必须先做语义风险审查。检测器没有命中但人工判断存在即时风险时，显式绑定类型：

```bash
python3 "$skill_dir/scripts/workflow.py" start \
  --input "$input_file" \
  --workspace "$workspace" \
  --case-id "$case_id" \
  --mode safety \
  --safety-signal-type other_immediate_risk

python3 "$skill_dir/scripts/workflow.py" safety-template \
  --workspace "$workspace" > "$safety_response"

# 先把该文件逐字发给用户，再记录同一文件。
python3 "$skill_dir/scripts/workflow.py" acknowledge-safety \
  --workspace "$workspace" \
  --response "$safety_response"
```

`--safety-signal-type` 可重复。risk signal 中，检测器命中的类型标记为 `deterministic_backstop`，并绑定完整输入语境 span；人工补充的类型标记为 `human_semantic_review`，绑定实际危险片段。`acknowledge-safety` 只接受按已绑定类型和输入地点确定生成的完整模板；输入明确说明人在澳大利亚且存在即时风险时，模板会在第一条动作中给出 `000`。自行增加问题、缓和语、动机分析、延迟或危险建议都会失败。

workflow 3.1.0 的 `finalize` 不再生成第二套 safety 文案。它把已经通过 `acknowledge-safety` 的 `safety-response.md` 原样写成最终 `response.md`，保证第一条用户可见内容仍是现实行动，同时把风险原文只留在内部 casefile 供审计。

## 隐私与落盘

完整 runtime 会持久写入你指定的 workspace，包括：

* `input.txt`
* `casefile.json`
* `state.json`
* `.workflow.lock`
* `receipts/attempt-N.json`
* `response.md`，safety 分支还会保留与之字节一致的 `safety-response.md`
* 更新流程引用的全部历史 casefile

运行时不会自动去标识化，也不会自动删除这些文件。启动前先由用户或宿主去掉姓名、住址、联系方式、账号、公司机密和不必要的完整聊天；把 workspace 放在项目仓库之外、权限受限的本地目录。是否还会发送到云端模型，取决于实际宿主与服务商。本仓库的本地写入不能撤回模型服务商已接收的数据。

## 已测试环境

截至 2026-08-06，当前源码在以下本地环境执行确定性回归：

* macOS 26.5.2，arm64
* Python 3.14.4
* Skill 4.4.0、schema 3.2.0、validator 4.4.0、workflow 3.1.0、improvement-loop state schema 1.1.0、phase work order v1、source epoch v2、producer recipe 2.0.0、source-manifest schema 1.0.0
* 当前开发态完整 unittest：1004/1004，无 skip 或 expected failure
* `casefile.py self-test`：160/160，全部为 true
* workflow lifecycle：`start → check → finalize → status`，以及独立的 passthrough、safety 和追加版本分支

这只证明本机确定性契约。冻结 host-model eval、clean install 和 verify 的当前状态记录在开发仓库的 `evals/results.md` 与 `evals/install-verification.md`。单一模型、合成中文用例或本地测试通过，都不能外推为所有模型、语言、关系或高风险场景的普遍有效率。

第二次真实 4.4.0 host run 保存在 `evals/raw/with-skill-v44-host-run-20260806-r2/`。只完成了 `relationship-silence`、`immediate-safety-override` 与 `bidirectional-evidence-on-one-claim` 三次真实模型执行，其余调用被 Codex 使用限额中止。三案随后暴露了 envelope 解包、重复 workspace、receipt 路径、safety 终态、终止换行和 evidence relation 聚合等执行合同缺陷，因此该 root 不能计作 3/18，也不能外推模型通过率。Round175 至 Round182 已把这些失败转成 22 项 RED/GREEN 合同测试；Round183 又把真实模型遗漏的原子权限反证改成 validator 可拒绝、repair loop 可修复的机器规则，三项专项测试通过。第一次完整回归随后在受信 legacy 迁移中打开两个 RED，Round184 将新规则限制在当前版本的新 evidence，没有改写旧工件。修复后的全量真实 18 案仍需在新 root 重跑。

## 文件级停用与恢复

在确认目标后，可以保留文件并改名：

```bash
installed="/path/to/your-project/.agents/skills/separating-facts-from-stories"
disabled="/path/to/your-project/.agents/skills/separating-facts-from-stories.disabled-20260806"

test -d "$installed"
test ! -e "$disabled"
mv "$installed" "$disabled"
```

这只是文件级停用候选。不同宿主可能缓存已加载的 Skill，也可能继续扫描改名目录；必须开启新会话并按宿主规则验证。发行门中的 rollback 只证明新 Python 进程看不到原活动路径，随后文件被原样恢复并再次通过 verify，不证明宿主停止发现 Skill。改名不会清除历史 workspace、模型上下文、云端记录或其他副本。

## 证据与复现

* [`problem-spec.md`](problem-spec.md)：问题、非目标和停止门
* `evals/cases.json` 与 `evals/capability-cases.json`：开发仓库中的哈希冻结输入
* `evals/baseline-report.md`：Skill 之前的真实 baseline
* `evals/results.md`：历史证据与当前发行门分层
* [`references/workflow-loop.md`](references/workflow-loop.md)：单案例状态循环
* `evals/improvement-loop-spec.md`：开发仓库中的产品改进 controller 与 STOP 合同
* `scripts/host_eval_runner.py`：固定 prompt、模型参数、runtime snapshot、写入边界与逐案执行
* `scripts/host_review_runner.py`：固定双评审入口，冻结 source identity，拒绝 prompt、模型、目录和命令覆盖
* `scripts/codex_exec_host.py`：启动本地 fresh Codex、保存 host receipt，并由宿主绑定 `review_payload.v2` attestation 或 case result
* `scripts/run_evals.py`：独立重放与 suite 审计，不负责调用模型
* `evals/raw/with-skill-v44-host-run-20260806-r2/`：第二次真实 host run 的三次模型执行、后续限额错误和未修补失败现场
* `scripts/produce_release_gate.py`：固定 STOP recipe 与类型化证据生成器
* `evals/install-verification.md`：开发仓库中的安装、verify、停用和恢复证据
* `workflows/separating-facts-loop.yaml` 与 `workflows/separating-facts-release-sources.json`：开发仓库根目录中的循环政策和权威 source manifest
* [`PROVENANCE.md`](PROVENANCE.md)、[`NOTICE.md`](NOTICE.md)：来源与改编说明
* [`LICENSE`](LICENSE)、[`CC-BY-NC-4.0-LEGALCODE.txt`](CC-BY-NC-4.0-LEGALCODE.txt)：许可通知与完整法律文本

## 非商业许可

本目录采用 CC BY-NC 4.0。复用 dontbesilent dbskill 的授权来自上游自己的 CC BY-NC 4.0，不来自本项目用户；用户的非商业承诺只确定本项目选择了符合 NonCommercial 限制的发行方向。固定提交、进入范围、独立工程实现和未采用材料见 [`PROVENANCE.md`](PROVENANCE.md) 与 [`NOTICE.md`](NOTICE.md)。不暗示上游作者认可本项目。
