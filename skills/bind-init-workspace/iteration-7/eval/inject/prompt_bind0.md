<task>
写出 parts/bind0.yaml。
</task>

<input>
- Scan receipt: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\repo_scan.yaml
- UO: d:\PR-review\pr_workspace\.ascendc-pr\gitcode.com--cann--ops-transformer--pr-9851\attention\flash_attention_score_grad
- Architecture: arch35
- Draft: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\parts\bind0.yaml
- Test script root: d:\PR-review\pr_workspace\.ascendc-harness\gitcode.com--coder_linx--fag_debug_tools
- Method: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\inject\method_columns.md
- Edge cases: d:\PR-review\AscendC-Pilot\skills\bind-init-workspace\iteration-7\eval\inject\method_column-binding-edge-cases.md
- FOCUS columns: Testcase_Name, Enable, Dtype, out_dtype, Input_Layout, B, N1, N2, S1, S2, D, D_V, Drop_Out_Possibility, Pre_Tockens, Next_Tockens, Atten_mask_dtype, Atten_mask_shape, sparse_mode, PSE_type, PSE_shape
</input>

<delta_constraints>
1. 只写 bind0.yaml；不要写 harness.yaml、bind1.yaml、bind.yaml 或正式 tg/init.yaml。
2. 身份字段由框架写入，不要从 stub 抄进 YAML。
3. 两列不得共用 `uo.id`。多列共喂的聚合 kwargs 不是任何一列的身份。
4. `call_args.sources[].column` 只能引用本路 mapping key。
</delta_constraints>

<output>
写入 `parts/bind0.yaml`。
</output>
