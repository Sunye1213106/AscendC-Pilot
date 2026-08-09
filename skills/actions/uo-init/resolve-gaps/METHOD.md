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

### Reading the batch

1. 只读本 shard 的 batch YAML（及 session prompt/method/bundle）。
2. 需要读码的 blocker 带 `source`：`line_start` / `line_end` 圈定的函数或循环——这是问题所指代码，也是 `snippet` 校验窗口（引用窗口内任一行即可）。
3. 不要打开其它源文件作答；`source` 缺失或不足以裁定 → `genuinely_unknown`。
4. 每个 blocker 的 `readable_vars` 是**唯一合法变量名**；列表外名字一律视为发明。列表无法表达答案时，正确结果是 `genuinely_unknown`。
5. 先读名字再推理：例如 `inputLayout[0] == 'B'` 问的是列表里能承载 layout 的那个 `VAR_*`，别无其它。
6. 写出 `parts/part_{shard_id}.yaml`（顶层 `patches: [...]`）后停止；不要 finalize。

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

诚实的 `genuinely_unknown` 无代价；猜对审查却在机械检查失败会多一轮。

## 两类关于推导本身的问题

`UNWRITTEN_INITIAL_VALUE` 与 `LOOP_SUMMARY_NEEDED` 走同一条队列、同一套闸门、同一个
part 文件，patch 形状不变；差别只在答案的含义。这两类 blocker 的 batch 会附上完整
函数体或循环体（`source` 带 `line_start`/`line_end`），snippet 按该窗口校验。

**`UNWRITTEN_INITIAL_VALUE`** — 成员在未证明被写的路径上被读；`text` 点名成员，
`source` 是读取它的函数。

- 若写覆盖了到达读的每一条路径，且 guards 说明是哪一条 → `input_derived` + 条件。
- 若有声明初值（默认成员初始化 / memset / 构造）且本路径无写 → 该值即答案：
  `input_derived` 绑定到导出变量，或 `validation_assumption`（输入侧够不着时）。
- 若写真的可被跳过而后读 → `genuinely_unknown`（算子性质，不是分析缺口）。

**`LOOP_SUMMARY_NEEDED`** — 值出自解不开的循环；`source` 带整段循环。

- 用已声明变量表达循环*计算*的内容（过滤计数、结果须满足的界）。对一切合法输入
  都成立的条件即使不钉死精确值也有价值（如计数器 `{op: ge, var: …, value: 0}`）。
- 禁止陈述“典型 shape 碰巧成立”的结论；检查会枚举合法输入并抓住例外。

## Output

- staging：`runs/{run_id}/actions/resolve_gaps/parts/part_{shard_id}.yaml`
- 合并由下一 Action `apply_gap_patch` 完成
- patch 字段形状见 task prompt output contract
