# Eval 说明

这套 eval 把四种证据分开：历史 host 行为、当前可执行 runtime、证据循环、维护者演化 workflow。漂亮 transcript 不能证明 validator 防绕过；fixture PASS 也不能证明 host 会产生合规语义。

## 证据层

| 层 | 位置 | 检查对象 |
|---|---|---|
| Prompt-only RED | [`architecture/red-baseline.md`](architecture/red-baseline.md) | 旧版是否真的有脚本、Schema、状态和测试 |
| Baseline host | [`baseline/`](baseline/)、[`baseline-report.md`](baseline-report.md) | 没有 Skill 时怎样回答相同四题 |
| Historical host | [`retest/`](retest/) | 各 RC 的 fresh 模型行为和外部阻断 |
| Offline regression | [`runtime/results.json`](runtime/results.json) | gate、receipt、validator、renderer、fixture hash 与确定性 |
| Agent-context shadow | [`retest/runtime-v0.3-rc4-shadow/results.md`](retest/runtime-v0.3-rc4-shadow/results.md) | 两个隔离无历史代理上下文的四题行为；非目标宿主 discovery 或官方 host score |
| Final local audit | [`rc4-final-audit.md`](rc4-final-audit.md) | targeted 51/51、full 134/134、final bundle、隐私与非代码发行门 |
| Evidence loop | [`../tests/test_problem_loop.py`](../tests/test_problem_loop.py) | 回答、证据、收敛、修订、预算、user decision |
| Evolution loop | [`../tests/test_evolution_loop.py`](../tests/test_evolution_loop.py) | failure ledger、复现、审查、holdout、promotion stop |
| Packaging | [`../tests/test_skill_packaging.py`](../tests/test_skill_packaging.py) | discovery metadata、lean bundle、doctor、可移植路径 |

## 唯一 suite 真源

[`suite-manifest.json`](suite-manifest.json) 是 offline runner 的唯一 case/expectation 真源，绑定 fixture path 与 SHA-256。[`runtime/run_runtime_evals.py`](runtime/run_runtime_evals.py) 读取该文件，不再维护第二份硬编码 case table。

四个原始压力题已经在 RC.1 到当前版本中被反复使用，所以它们是 regression，不是未见 holdout。真正的 `sealed_holdout` 必须是新样本、限制访问、只消费一次；`dpbp-evolve` 的 status 只显示 case ID、hash 和 sealed/spent 状态，不回显路径或内容。

## 运行

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests -v
PYTHONDONTWRITEBYTECODE=1 python3 evals/runtime/run_runtime_evals.py \
  --output evals/runtime/results.json
```

当前结果：134/134 自动测试，offline regression 4/4，每题 gate 重复 100 次。详细口径见 [`results.md`](results.md)。

## 失败如何进入下一轮

```text
failure_observed + base RED receipt
  -> candidate implementation
  -> candidate GREEN receipt
  -> reproduction receipt from a distinct declared actor ID
  -> reviewer approval from a third declared actor ID
  -> promote or emit manifest proposal
```

任何一步不满足都不得 promotion。所有 receipt 输入必须绑定 manifest 中同一 case；ledger checkpoint 会拒绝只修改 state 的旁路。新 case 的 promotion 不自动改 manifest，只生成待 maintainer 应用和全量复测的 proposal。三个 actor ID 和 artifact hash 当前是自我声明，无密钥 checkpoint 也不能抵抗同时重写 state 与 ledger，不等于身份认证或受信 runner 证明。迭代次数达到预算，或最近窗口的改善都低于阈值时，workflow 自动停止。完整命令与账本契约见 [`evolution/README.md`](evolution/README.md)。

## 评分边界

1. 同一个输入可以重跑，但多次开发后不再是 holdout。
2. 外部 runner 在模型响应前失败记 blocked，不记 FAIL 或 PASS。
3. 每个版本只使用自己的 artifact hashes 和输出，不迁移前版成绩。
4. 模型自称完成不算通过；outcome、semantic audit 与 code audit 分开。
5. 当前没有 `0.3.0-rc.4` fresh host score。
