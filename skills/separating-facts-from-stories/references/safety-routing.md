# 安全路由

只在存在现实安全、医疗、法律、自伤或他伤风险时读取。安全优先于普通 casefile。

## 先行动，再建档

以下情况应进入 `safety`：明确威胁、跟踪、堵门、强行到访、既往暴力或破坏、武器、住址或门锁等即时访问能力、自伤他伤、严重医疗症状，或即将到期的重大法律风险。

第一条用户可见内容必须给出与风险相称的现实动作。不要自行写安全响应；运行 `workflow.py safety-template`，把它的完整输出逐字发给用户，再把同一文件交给 `acknowledge-safety`。模板按已绑定的风险类型确定生成，禁止追加问题、动机分析、弱化语、延迟建议、联系威胁者或单独见面等尾巴。不得先展示普通分析、动机假设或证据整理。

## 运行时检测边界

`--mode auto` 与 validator 使用确定性的安全文本正则来捕捉部分常见中英文急迫信号。该正则只是兜底触发器，不是完整的风险识别器，也不能判断风险真实性、紧迫程度或语境。

因此，人工路由优先：只要输入显示可信的即时风险，即使没有命中正则，也应使用 `--mode safety`，并用一个或多个可重复的 `--safety-signal-type TYPE` 绑定人工识别的风险类型。没有检测器命中且没有显式类型时，启动会以 `MANUAL_SAFETY_TYPE_REQUIRED` 失败。反过来，命中正则也不允许忽略风险或把它降格为关系动机分析。

路由顺序还必须保留语境：纯翻译、纯引用、虚构、明确否定或已经结束的历史，不因其中出现危险词就自动进入 safety；同一输入若另外包含当前现实求助、复发风险或紧迫期限，仍必须先进入 safety。确定性 backstop 只覆盖已经编码的语法，人工语义审查始终高于它。

```bash
python3 "$SKILL_DIR/scripts/workflow.py" start \
  --input "$INPUT_FILE" \
  --workspace "$WORKSPACE" \
  --case-id "$CASE_ID" \
  --mode safety \
  --safety-signal-type other_immediate_risk

python3 "$SKILL_DIR/scripts/workflow.py" safety-template \
  --workspace "$WORKSPACE" > "$SAFETY_RESPONSE_FILE"

# 先逐字发送该文件，再保存同一响应。
python3 "$SKILL_DIR/scripts/workflow.py" acknowledge-safety \
  --workspace "$WORKSPACE" \
  --response "$SAFETY_RESPONSE_FILE"
```

## Safety 工件

每个 `safety.risk_signals` 项都必须有：

* `input_id`、`source_span_id`、`source_ref`、`exact_quote`
* `signal_type`：`explicit_threat`、`prior_violence_or_damage`、`access_or_location_exposure`、`self_harm_risk`、`harm_to_others_risk`、`medical_emergency`、`urgent_legal_risk` 或 `other_immediate_risk`
* `routing_basis`：检测器确实命中的类型写 `deterministic_backstop`；没有命中、但由人工语义审查确认并在启动参数中绑定的类型写 `human_semantic_review`

确定性 backstop 只在完整输入语境上判定，所有命中的类型锚定运行时生成的完整输入语境 span。它不会把翻译、虚构、否定或已解决历史中的孤立引语重新洗成风险。人工补充类型锚定真正触发语义判断的完整 span，并必须与启动参数逐项一致。检测器命中的类型不得伪装成人工判断；人工类型也不得脱离启动时的显式绑定。

这些锚点仍只能引用 init 或 start-update 生成的完整 source span，不能截掉否定、对象、地点或时间条件。输入明确说明用户人在澳大利亚且存在即时风险时，确定性模板的第一条动作会指定 `000`；未明确地点时不得猜测当地号码。

`safety` 模式必须有至少一个风险信号和至少一个 action。首个 action 必须是以下之一且 `timing: "immediate"`：`move_to_safe_place`、`contact_emergency_services`、`contact_trusted_person`、`seek_medical_support`。所有 action 都必须从有限 action 目录取得其文本和字段，见 `casefile-contract.md`。

revision 1 的 safety 工件中，claims、evidence、links、unknowns、hypotheses、hypothesis request 和 discriminator 必须为空或 `null`。从 standard 版本切到 safety 时可以保留旧分析，但不得新增或修改任何普通分析字段。

安全 casefile 的合规性不替代紧急服务、医疗、法律或危机专业人员的评估。
