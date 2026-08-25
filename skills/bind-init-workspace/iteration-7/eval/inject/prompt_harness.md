<task>
写出 parts/harness.yaml。
</task>

<input>
- Scan receipt: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\repo_scan.yaml
- UO: d:\PR-review\pr_workspace\.ascendc-pr\gitcode.com--cann--ops-transformer--pr-9851\attention\flash_attention_score_grad
- Draft: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\parts\harness.yaml
- Test script root: d:\PR-review\pr_workspace\.ascendc-harness\gitcode.com--coder_linx--fag_debug_tools
- Method: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\inject\method_harness.md
- Edge cases: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\inject\method_harness-edge-cases.md
</input>

<delta_constraints>
1. 只写 harness.yaml；不要写 bind.yaml 或正式 tg/init.yaml。
2. 身份字段由框架写入，不要从 stub 抄进 YAML。
3. `entry` / 表清单以 receipt 为准；没有 `error` 的表不要写成读失败。
4. 默认 mode 是性能时必须写进 findings，不要把默认当精度。
</delta_constraints>

<output>
写入 `parts/harness.yaml`。
</output>
