# 闭合残余 blocker

> **`acp` 是真实 CLI。** 本 Action 是 **subagent producer**（`uo-gap-resolve`），不是确定性引擎。

## Goal

对 `uo/ir/unresolved.yaml` 中的 blocker 在**封闭词汇表**内给出 patch；只写 staging parts。  
Host prepare 按 ≤30/shard 分片；本 worker **只处理本 shard batch**。

## Domain Procedure

```text
acp run-action resolve_gaps --project <算子目录>
# Primary：按 prepare 返回的 dispatch_tasks[] 原样粘贴各 task_prompt_stub 派发
# 全部 shard 完成后：
acp run-action resolve_gaps --finalize
acp next   # → apply_gap_patch
```

成功标志：本 shard 写出 `parts/part_{shard_id}.yaml`；禁止写 `uo/ir/**`。

## Hard Constraints

- MUST：classification ∈ `scheduling | input_derived | validation_assumption | genuinely_unknown`
- MUST：`input_derived` 时 `var_id` 来自 batch 内白名单 / VariableModel，value 在域内
- MUST：evidence 含可命中源码的 file + line + snippet（含 `!` 的 snippet 须 YAML 引号）
- MUST NOT：发明 symbol / 自由表达式 / 读其它 batch 或其它 part
- MUST NOT：在 prompt 里自行分片或数全局任务
- MUST NOT：`acp finalize` / `acp next` / `acp advance`（仅 Host）

## Output

- staging：`runs/{run_id}/actions/resolve_gaps/parts/part_{shard_id}.yaml`
- 合并由下一 Action `apply_gap_patch` 完成
