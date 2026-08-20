# 语义接地（面向模型，短）

1. 角色、sink、条件由 Relation 派生，不得凭命名闭合。
2. 语义表面必须接到 input root；否则保持 unresolved / needs_binding。
3. 浅层 ABI `set_*` 无 `value_defining_sites` → PARTIAL / UNKNOWN。
4. 标 `PROVEN_UNREACHABLE` 或 pin 字段必须达到 evidence 的 high / `source_verified`。
5. 模板 / 宏 / 重载 / 别名 / 间接调用未闭合到具体实例或目标时，不得证「全部路径」或「无其他调用者」。

全文：`pilot/policies/semantic-grounding/POLICY.md`。
