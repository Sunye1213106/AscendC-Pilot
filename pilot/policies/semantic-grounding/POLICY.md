# Policy: semantic-grounding

语义表面必须接到可观察的输入根与关系图。证据级别仍遵守 `evidence`。

1. 角色、sink、条件由 Relation 派生，不得凭命名闭合。
2. 语义表面必须接到 input root；否则保持 unresolved / needs_binding，不得进入可测 coverage。
3. 浅层 ABI `set_*` 无 `value_defining_sites` → PARTIAL / UNKNOWN。下一步是定向读码回灌 UO，不是在 TG 或 Prompt 里特判算子。
4. 标 `PROVEN_UNREACHABLE` 或 pin 字段必须达到 `evidence` 的 high / `source_verified`。仅 UO 字段名或「观测上从未出现」不够。
5. 模板 / 宏 / 重载 / 别名 / 间接调用未落到具体实例或目标时，不得证「全部路径」或「无其他调用者」。宏合同可物化的项不得 `mark_missing`。
