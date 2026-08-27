# Agent 内容整理规范

最高指令：**不要通过增加更多文字解决职责不清。优先删除重复内容、收缩职责、建立唯一权威来源；只有确实存在缺失约束时才新增内容。**

本轮装配准则：**Runtime 只装配显式依赖；Skill 只描述方法；Knowledge 只描述领域事实；Workflow 只描述执行图；Engine 只处理确定性逻辑。任何内容如果同时属于两个层，就说明边界还没拆干净。**

不要为修一个 bug 再往 yaml / invariant / POLICY / SKILL / prompt 各补一句不同版本。

## 目标

```text
规则只有一个来源
职责边界清晰
运行时加载内容最少
确定性逻辑进入代码
模型只处理需要语义判断的部分
```

两种负载分开算：

- **人**：只记 slash（`/uo-query` `/uo-init` `/uo-investigate` `/tg-init` `/tg-plan` `/tg-solve` `/ce-plan` `/ce-apply` `/ce-review` `/handoff`）。磁盘 `skills/` 目录不是入口。
- **执行 id**：编排与 `pilot_run.workflow` 写 `uo-init`。聊天 slash 才是 `/uo-init`。入口剥 `/`，两边同一条工作流。模型 playbook 不要把聊天前缀当成工具协议。
- **窗**：每个 LLM Action 只装一份 `method.md`。磁盘 skill 数 ≠ 常驻 token。

本仓路径对照：

| 层 | 权威位置 |
| --- | --- |
| Policy | `pilot/policies/<id>/POLICY.md`（compose 直接注入这一份；没有第二份「短投影」） |
| 编排 / 调查拆路 | `pilot-control`。Primary 不读 Skill。 |
| 与人交互 | `human-voice` |
| Host 运行时（人 / CI） | `pilot/policies/invariants/host-runtime-contract.md`（不 compose） |
| Workflow / Spec | `pilot/ascendc_pilot/workflows/*.py`：机器图 + 装载指针（`skill_id` / `method_ref` / `refs` / `knowledge_refs`） |
| Domain Knowledge | `knowledge/ascendc/*.md`：跨任务仍成立的 AscendC 事实。Action 显式声明才装，无自动选择 |
| Engine / Gate | 文件在不在、到齐 ACK、scan/promote |
| Artifact schema | `schemas/`（`catalog.yaml` 映射 Skill；id 按家族独立版本） |
| Skill | `skills/<id>/SKILL.md`（当前窗口怎么判断）+ `references/`（指针后） |
| Prompt | `prompts/tasks/**`（本题 I/O） |
| Agent | `agents/*.yaml` 的职责与写面 |
| Command `/uo-query` | 瞬时调查，不是 `pilot_run` 工作流 |

写权限在 yaml `write_scopes` + authorize；产物诚实在 `output-quality`。不要另造 `permissions.md` / `mutation.md`。

---

## 1. Policy

Policy 只描述**全局不可违反的约束**。不教某一步怎么绑列。

适合放：证据要求、权限边界、修改限制、状态闭合、安全约束、全局语义不变量。

不适合放：执行步骤、shell、函数名、某 Action 的 I/O、某算子特化、长示例、troubleshooting、workflow 教程。

一个规则只能有一个权威定义。Skill、Prompt、Agent 不得复制 Policy 全文，只引用。compose 注入 POLICY.md 本身，不要再写一份 paraphrased 短文。

---

## 2. Workflow / Spec

机器图：谁跑、隔离、下一态。装载指针：`skill_id` / `method_ref` / `refs` / `knowledge_refs`。`refs` / `knowledge_refs` 只装 Action / 轴上的显式名单，缺文件则 fail-closed。Skill 正文反引号不是第二套发现机制。

`focus` 只写交付物名，不写判断配方。`fanout_axes.focus` 禁止成为迷你 Skill。

判断写进 Spec、编排图画进 SKILL，视为层错位：删副本，不留摘要。

确定性 Action 不挂 Skill。

---

## 3. Engine / Gate

文件在不在、到齐 ACK、scan/promote。字段归属与 `schema:` id 以 `schemas/` 为准。能代码化的审查项离开 `review.md`。

模型只做语义裁判。

---

## 4. Skill

当前窗口怎么判断。执行步按 Action 绑定；轴 HOW 只在 `references/<axis>.md`；叠加原语不进人清单。

三类：

| 种类 | 何时用 | 例子 |
| --- | --- | --- |
| 执行步 | Action `skill_id` 强装 | `bind-init`、`test-plan`、`solve`、`ce-plan-draft`、`uo-query` |
| 轴 playbook | `method_ref`，无独立 skill 目录 | `harness.md`、`target-planning.md`、`spec.md` |
| 叠加原语 | 点名才 Read，不进 `max_skill_ids` | `source-proof`、`proof-review` |

切目录的唯一合法理由：同一 slash 的多窗，或同一叠加原语的多支。禁止「都跟 plan / 测试有关」焊成一份 always-loaded 正文。后序步骤进前窗会 rush。

`description` 只做人读短句，不写步骤。本仓是 Action 强装，不拿 description 做触发实验。cognitive Skill 是 Pilot 按 ActionSpec 确定性装载的 method package，不是 host 按 description 发现的 native Agent Skill。

写法权威：`skills/SCHEMA.md`。80–150 / 200 是 **AscendC-Pilot 仓内 lint / engineering budget**，不是 Anthropic / OpenAI 官方标准；路由父本允许更短。

先问是图、是确定性、还是判断；判断才加执行步或 overlay。不要尽管加 Skill。

指针只深一层。Reference 不得 hop。要复用方法 → `skills/<id>/SKILL.md`。

---

## 5. Prompt

本题 I/O 路径。稳定指令在前、路径占位在后。不复制 Skill 判断句。

不应该包含：完整 Policy、Skill 全文、长期架构、validator 已能检查的规则。

---

## 6. Agent

身份、写面、**窄天花板**（本角色会接到的执行步 + `uo-query`）。`description` 不写步骤。

叠加原语用 `read_scopes` 的 `method:skills/<overlay>/**`，指针 Read 才进窗，不进 `max_skill_ids` 常列。

主控 yaml 只留入口句。Primary `max_skill_ids: []`。

---

## 7. Reference

仅该窗分支才需要的目录/长表。禁止 hop，禁止 `_shared/`。

lemma / 方案类产物先读 `INDEX.md`（标题+标签+摘要），再最多打开 3 份正文。

---

## 8. 内容归属判断

整理任何一段文字时依次判断：

1. 所有任务都不能违反？→ Policy
2. 能代码化（在不在 / ACK）？→ Engine / Gate。字段归属与 `schema:` id → `schemas/`
3. 谁跑、隔离、下一态、装载哪份 playbook？→ Workflow 指针
4. 当前窗口怎么判断？→ Skill
5. 角色写面与天花板？→ Agent
6. 本题路径？→ Prompt
7. 只有该窗分支才要的目录/长表？→ Reference
8. 这段知识在该 Action 不存在时是否仍成立？是 → `knowledge/`；否 → Skill / reference

---

## 9. 去重规则

经验顺序：Policy > Engine/Gate > Workflow 指针 > Skill 判断 > Agent 天花板 > Prompt I/O。

同一规则出现在多处时，找到真正归属，不是按文件名机械保留。合法耦合只有指针。

示例：

- 多个 Skill 都写「不得伪造 evidence」→ 留在 evidence Policy，Skill 只引用。
- Spec.focus 写 `Dim=` / `--golden-only` → 留 playbook，focus 删到交付物名。
- 路由 SKILL 复述阶段表 → 删；图在 Spec。
- 精度邻域写进 `solve` → 错位；命中后邻域留 `skills/certify/`。

---

## 10. 窗口全表

| slash | 磁盘执行步 | 窗 / method_ref |
| --- | --- | --- |
| `/tg-init` | `bind-init` | harness / columns；review 在 SKILL.md |
| `/tg-plan` | `test-plan` | target-planning / coverage-planning |
| `/tg-solve` | `solve` | construct / replay-classification |
| `/ce-review` | `standalone-review` | spec / standards |
| `/ce-plan` | `ce-plan-draft` | 单窗 |
| `/ce-apply` | `ce-apply` | 单窗 |
| `/uo-query` | `uo-query` | 单窗 |
| `/uo-init` | `propose-include-heal` | 单窗 |
| `/uo-investigate` | `uo-investigate` | 单窗 |
| `/handoff` | `session-handoff` | 单窗 |

叠加原语：`source-proof`、`proof-review`。lemma 是 worklog / 证书里的产物名词，不是 Skill。精度/性能命中后邻域在 `skills/certify/`。领域事实在 `knowledge/ascendc/`。

---

## 11. 冲突处理

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

## 12. 特化规则

禁止因为当前主要测试某一个算子，而把算子特化规则写入公共 Skill 或 Policy。

发现 `if operator == FAG`、写死某个 tiling 字段 / 目录 / KEY：判断是否真正属于通用语义。若不是：删除、移到算子专属 reference，或改成由 UO / relation / compiler facts 推导。

---

## 13. 确定性优先

若某项判断能通过 AST、Clang、schema、图遍历、hash、diff、solver、replay、静态规则可靠完成，则优先确定性实现。不要用 Prompt 写「请认真判断 / 请确保 / 尽量不要」。

模型主要负责：语义理解、候选生成、异常解释、复杂关系判断、review。

---

## 14. 本仓目标结构

保持现仓，不搬目录：

```text
pilot/policies/<id>/POLICY.md
pilot/policies/invariants/host-runtime-contract.md
skills/<skill-id>/SKILL.md
agents/*.yaml
prompts/tasks/
```

不要把 Skill 绑成固定五族。不要按 slash 拆仓。compose 只装配，不撰写「你是谁」或运行时契约。

---

## 15. 整理时的输出

对改动的文件说明 keep / move / delete / rewrite。冲突按第 11 节记录。不得仅评价文笔。
