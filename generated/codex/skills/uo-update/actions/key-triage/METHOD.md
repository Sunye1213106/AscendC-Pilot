# key_triage — KEY 粗分（仅分类与计划）

> 本 Action 只产出 `ir/key_triage.yaml`。禁止写 resolution 正式产物。

## Purpose

对 open gaps / escalate_keys 做分类、分组，生成待处理批次计划，供后续 `key_resolution` 消费。

## Outputs

- 合同产物：**仅** `uo/ir/key_triage.yaml`
- 无待处理 KEY 时：写入 `status: not_applicable` 的 triage 文件（显式无任务证明）

## Forbidden

- MUST NOT：写入 `uo/ir/input_derivable_patch.yaml` 或 `uo/ir/key_shape_resolve/**`
- MUST NOT：闭合 gaps、提升 confidence、生成 resolution 结论
- MUST NOT：自行宣布工作流完成或跳过 `key_resolution`

## Procedure

1. 只处理 Pilot prepare 注入的 target 集合。
2. 标注 simple / complex 分流（供 Host 后续批次派发）。
3. 低置信或缺证据的 KEY 保持 unresolved，不得为过 Gate 假标 high。
4. 停止：写完 triage 产物后结束。
