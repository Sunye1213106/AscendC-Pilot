# Agent 内容整理规范

最高指令：**不要通过增加更多文字解决职责不清。优先删除重复内容、收缩职责、建立唯一权威来源；只有确实存在缺失约束时才新增内容。**

不要为修一个 bug 再往 yaml / invariant / POLICY / SKILL / prompt 各补一句不同版本。

## 目标

整理：

```text
Policy
Skill
Prompt
Agent
Action
Reference
```

消除重复规则、职责重叠、相互覆盖和过度上下文。

优先保证：

```text
规则只有一个来源
职责边界清晰
运行时加载内容最少
确定性逻辑进入代码
模型只处理需要语义判断的部分
```

本仓路径对照：

| 层 | 权威位置 |
| --- | --- |
| Policy | `pilot/policies/<id>/POLICY.md` |
| 模型常驻短投影 | `pilot/policies/invariants/*.md`（Primary 只拿编排需要的；全文 POLICY 不进模型） |
| 编排 / 调查拆路 | `intent-reasoning.md`。Primary 不读 Skill。 |
| Skill | `skills/<id>/SKILL.md`（当前 Action 怎么做）+ `references/`（指针后） |
| Prompt | `prompts/tasks/**`（本题 I/O） |
| Agent | `agents/*.yaml` 的职责与写面 |
| Action | Spec + Engine + Gate |
| Command `/uo-query` | 瞬时调查，不是 `pilot_run` 工作流 |


写权限在 yaml `write_scopes` + authorize；产物诚实在 `output-quality`。不要另造 `permissions.md` / `mutation.md`。

---

## 1. Policy

Policy 只描述**全局不可违反的约束**。

适合放：

- 证据要求
- 权限边界
- 修改限制
- 状态闭合条件
- 安全约束
- 全局语义不变量

不适合放：

- 执行步骤
- shell 命令
- Python 函数名
- 某个 Action 的输入输出
- 某个算子的特殊规则
- 长示例
- troubleshooting
- workflow 教程

Policy 应尽可能短。

原则：一个规则只能有一个权威定义。Skill、Prompt、Agent 不得复制 Policy 全文，只引用 Policy。

面向模型的 `invariants/*.md` 是 POLICY 的短投影，不是第二套规则书。投影不得比全文更严或更松，也不得塞进别的 Policy 的领域条款。

---

## 2. Skill

Skill 描述**一种可复用能力以及如何完成它**。一份 Skill 对应一次可触发的执行步或叠加原语，不是 slash 家族说明书。

写法权威：`skills/SCHEMA.md`。对照：别人可执行的 Skill 把**每轮都要用的判断**写在正文（大约 80–150 行），目录和长表放 `references/` 一层指针。不要写成十几行骨架。

一个 Skill 应回答：

```text
什么时候使用
输入是什么
输出是什么
执行步骤是什么（含怎么判断、何时停）
需要哪些工具
完成条件是什么
失败时返回什么
每轮都要用的启发式 / 反模式
```

Skill 可以包含：工作流程指针、工具调用顺序、domain knowledge、少量必要示例、该能力的额外约束。

Skill 不应该：重复全局 Policy、定义新的全局权限、修改其他 Skill 的语义、保存大量项目状态、包含与该能力无关的背景知识。

不要让一个 Skill 同时承担提取 + 推理 + 测试生成 + review + 修复。不要按 slash 建 Skill，也不要在 SKILL.md 里复述 workflow 阶段。Skill 数量不固定；需要新判断时加新 Skill。

---

## 3. Prompt

Prompt 描述**当前这一次任务要做什么**。

应主要包含：任务目标、当前输入、当前上下文、期望输出、本次特殊限制。

不应该包含：完整 Policy、Skill 的完整说明、项目长期架构、大量不会变化的知识、validator 已经能确定性检查的规则。

原则：Prompt 负责本次任务，不负责定义系统。

---

## 4. Agent

Agent 描述**角色和决策边界**。

应定义：负责什么、不负责什么、允许使用哪些 Skill、允许使用哪些工具、输入来自哪里、输出交给谁、何时停止、何时升级。

不应该重新定义 Skill 的具体流程，也不应该把 Policy / 编排步骤写进 `description`。

主控 yaml 只留入口句。Init 顺序、调查拆路、谁可以 Task：写在 `intent-reasoning` / authorize。子代 yaml 只留做什么、写哪。

子代 yaml 只留做什么、写哪、不写哪。不要写「禁止再派 Task」（authorize 已拦）。

---

## 5. Action

Action 表示**确定边界的一次操作**。应有明确 input / output schema、precondition、postcondition、failure state。

能由代码确定的事情必须由 Action / validator 完成，不交给 LLM：hash 是否匹配、snippet 是否连续、schema 是否正确、文件是否存在、字段是否缺失、状态转换是否合法。

---

## 6. Reference

Reference 只保存**按需读取的信息**：schema、复杂字段、命令参考、算法背景、长示例、特殊场景。

不得把所有 Reference 默认塞进 Prompt。只有任务真正需要时才读取。全局不可违反的纪律在 Policy，不要另建共享引用目录。

---

## 7. 内容归属判断

整理任何一段文字时依次判断：

1. 所有任务都不能违反？→ Policy
2. 描述一种可重复执行的方法？→ Skill
3. 只针对当前一次任务？→ Prompt
4. 定义执行角色的职责和权限？→ Agent
5. 可以由程序确定性执行或校验？→ Action / validator / script
6. 只是辅助知识或详细说明？→ Reference

---

## 8. 去重规则

同一规则出现在多个地方时，找到它真正应该归属的位置，不是按文件名优先级机械保留。

经验顺序：Policy > Skill > Agent > Prompt。

示例：

- 多个 Skill 都写「不得伪造 evidence」→ 留在 evidence Policy，Skill 只引用。
- Policy 里写「先运行 clang_extract.py」→ 从 Policy 删除，移到对应 Skill / Engine。
- Agent 和 Skill 都描述完整 `/uo-init` 流程 → 流程留在对应 Action Skill（如 `uo-query`）与 Spec；Agent 只说明何时调用。

---

## 9. 冲突处理

两个文件规则冲突时，不允许静默选择一个。必须记录：

```yaml
conflict:
  source_a:
  source_b:
  description:
  recommended_owner:
  recommended_resolution:
```

优先判断：是否层错位重复、是否旧规则未删、是否 Skill 越权改 Policy、是否 Agent 越权重写 Skill、是否实现已变文档未更新。

---

## 10. 特化规则

禁止因为当前主要测试某一个算子，而把算子特化规则写入公共 Skill 或 Policy。

发现 `if operator == FAG`、写死某个 tiling 字段 / 目录 / KEY：判断是否真正属于通用语义。若不是：删除、移到算子专属 reference，或改成由 UO / relation / compiler facts 推导。

---

## 11. 确定性优先

若某项判断能通过 AST、Clang、schema、图遍历、hash、diff、solver、replay、静态规则可靠完成，则优先确定性实现。不要用 Prompt 写「请认真判断 / 请确保 / 尽量不要」。

模型主要负责：语义理解、候选生成、异常解释、复杂关系判断、review。

---

## 12. 本仓目标结构

保持现仓，不搬目录：

```text
pilot/policies/<id>/POLICY.md
pilot/policies/invariants/*.md
skills/<skill-id>/SKILL.md
agents/*.yaml
prompts/tasks/
```

不要把 Skill 绑成固定五族。不要按 slash 拆仓。compose 只装配，不撰写「你是谁」或运行时契约。

---

## 13. 整理时的输出

对改动的文件说明 keep / move / delete / rewrite。冲突按第 9 节记录。不得仅评价文笔。
