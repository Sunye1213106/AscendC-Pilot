# Policy: semantic-grounding

## 目的

语义表面必须接到可观察的输入根与关系图。禁止用命名、浅拷贝点或「观测上从未出现」闭合角色、取值或不可达。

证据级别仍遵守 `evidence`；本策略不另开例外。

## 规则

1. 角色、sink、条件由 Relation 派生。LLM 只确认关系，不得直接选择最终 extract-plan role。

2. 所有语义表面从 input root 派生。中间局部变量不是根。条件 / 分支 / 模板 / KEY 维必须经 `GROUNDED_IN`（或等价推导链）接到 input_root；否则保持 `unsolved` / `needs_binding`，不得进入可测 coverage。

3. 浅层 ABI `set_*` 写入点若没有 `value_defining_sites`，状态为 `PARTIAL` / `UNKNOWN`。下一步是定向读码回灌 UO，不是在 TG 或 Prompt 里特判算子。

4. 把 outcome 标为 `PROVEN_UNREACHABLE`（E）或 pin 字段取值时，证据级别必须达到 `evidence` 的 high / `source_verified`。仅 UO 字段名、仅最终拷贝点、或仅「观测上从未出现」不足以入 E。

5. 宏合同可物化的项不得标 `mark_missing`；应交宏合同物化。

6. 模板 / 宏 / 重载 / 别名 / 间接调用未落到具体实例或调用目标时，不得对「全部路径 / 无其他调用者 / 无覆盖」下结论。不同模板实参、特化、`#if`、overload、指针别名、函数指针或虚调用都可能改变函数体。

## 硬约束

- 未接到输入根的语义表面保持 unresolved，不得假闭合出题。
- 浅 writer ≠ 结构完备。
- lemma / E / 字段 pin ⇒ `evidence` 高置信 + 源码窗口。
- 模板 / 宏 / 重载 / 别名 / 间接调用未闭合 ⇒ 不得证穷尽。
- 禁止在个别 skill 里弱化或覆盖本策略。
