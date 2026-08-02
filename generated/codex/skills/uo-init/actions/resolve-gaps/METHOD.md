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

## 一个 patch 会被什么挡下

合入前有三道机械检查，各自带一个反例见证：

- 只能引用**这段代码真的读到**的变量；正确但无关的条件同样被拒
- 条件必须**能判开两边**；恒真或恒假等于把分支换成常量，不是对 guard 的解读
- 代回原表达式后，该维**仍能取到模板声明的值**，且至少能取到一个

机械检查判不了"这是不是代码实际实现的那个条件"，那一步由独立 referee 完成
（`prompts/tasks/uo/review-gap-patches.md`）：只读 part 与 batch，逐条判
accept/reject。判据是**方向**——比代码弱的条件只会放大可行域，可以接受；比
代码强的条件会排除算子真正接受的输入，下游无从发现，必须拒。

## 两类关于推导本身的问题

`UNWRITTEN_INITIAL_VALUE`（成员在未证明被写的路径上被读）与
`LOOP_SUMMARY_NEEDED`（值出自解不开的循环）走同一条队列、同一套闸门、同一个
part 文件，patch 形状不变；差别只在答案的含义，写在 task prompt 里。这两类
blocker 的 batch 会附上完整函数体或循环体（`source` 字段带
`line_start`/`line_end`），snippet 也按该窗口校验——引用窗口内任意一行都算命中。

## Output

- staging：`runs/{run_id}/actions/resolve_gaps/parts/part_{shard_id}.yaml`
- 合并由下一 Action `apply_gap_patch` 完成
