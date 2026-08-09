# 安装验证记录

## 当前结论

本文件定义安装验收合同，不静态宣告当前安装门通过或失败。实时状态只认同一 source freeze 上由 packager 或 controller 固定 recipe 生成的 manifest、命令 receipt 与具名 gate；缺少这些机器证据时默认未通过。这样实际验证完成后无需改写本文件并让既有 eval 自我失效。

2026-08-05 曾完成一次复制、改名停用、恢复与单案例冒烟，但当时安装的是 prompt-only v7。它没有包含当前的 `scripts/`、`schemas/`、`references/`、测试门、eval context、allowlist manifest 或完整生命周期，因此只能作为历史复制实验，不能证明当前 runtime 可安装。

## 历史 prompt-only 复制实验

历史临时项目：

```text
/tmp/fengyu-sffs-install-20260805-final-v2/project/
```

当时的来源与安装后 `SKILL.md` 记录 SHA 为：

```text
506e72c99bf6b23c9496228ab82178774d7657c3ccaedd502ca9258caa3a7ece
```

该值属于旧 prompt-only v7 的历史记录，且旧记录没有明确说明是否排除了快照末尾的自哈希注释。当前保留快照的整文件 SHA 为 `915afb732775533c1e0f99f5f80bbce7746541e1519902a4304293e86e76c0b8`。两个值不能与当前 `SKILL.md` 或 runtime 源码比较。

历史实验能证明的只有：旧文件集可被复制、改名后仍可恢复，以及一个隔离会话在已安装旧提示词上完成过自我故事冒烟。它不能证明宿主停止发现改名目录，不能撤回已写数据，也不能覆盖当前 runtime。

## 当前 gated install 的验收方法

只有当前源码绑定的 18/18 case、16/16 artifact 机器报告已经存在时，才运行：

```bash
skill_dir="/path/to/fengyu-ai-cognition-skills/skills/separating-facts-from-stories"
eval_root="$skill_dir/evals/raw/with-skill-v30-run"
target_root="/path/to/clean-project/.agents/skills"

python3 "$skill_dir/scripts/package_runtime.py" \
  --target-root "$target_root" \
  --eval-root "$eval_root"

python3 "$target_root/separating-facts-from-stories/scripts/package_runtime.py" \
  --verify "$target_root/separating-facts-from-stories"
```

安装证据至少需要保存：

1. 不存在的干净目标路径。
2. packager 的完整退出码与输出。
3. 安装包 allowlist 和 `runtime-manifest.json`。
4. 安装前后所有被打包文件的 SHA-256 一致性。
5. 安装后 `start → check → finalize → status` 的完整 lifecycle。
6. 安装后 `--verify` 退出码为 0。
7. 安装包包含与 release evidence 同哈希的 `evals/legacy-migration-corpus.json`，真实登记旧件能完成 `validate → start-update → validate`，自造旧件和回执仍被拒绝。
8. 文件级停用、fresh Python 进程确认原活动路径不可见，以及恢复后的再次验证。宿主缓存刷新和真实新会话发现另列为尚未验证，不能由这个文件级回滚门代替。
9. workspace 数据仍然存在且不会随 Skill 改名自动清除的说明。

任何一项未完成都保持 `LOOP`。真实临时路径、环境、命令输出、manifest 哈希和 rollback/restore receipt 保存在对应 eval root 或 controller 的内容寻址 retained basis 中，不回填到这份 source-bound 说明。静态文字不能替代机器回执。

## 可移植证据升级

第七轮已经把安装器自身、`machine-report.json` 与 `evaluation-context.json` 纳入安装包固定路径。三项回归证明：已安装副本能直接执行 `--verify`；原 eval root 改名后仍可验证；包内 machine report 被改动后会被拒绝。

Round145 又把最小 legacy trust corpus 纳入固定 allowlist。安装包不包含 34 个历史 artifact 与 receipt 原件，只携带 17 个登记根的工件哈希与回执 canonical 指纹；干净 runtime copy 已用真实 4.0.1 工件验证合法迁移，并确认未登记工件不能用自造回执授权。

这只是测试环境中的能力升级，不等于当前 source freeze 的 gated clean install 已通过。当前结果必须读取具名 gate。包内哈希也是自校验，不是供应商签名、可信时间戳或外部 CI attestation。
