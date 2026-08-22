# Skills 布局与写法

Skill 是**执行步文档**：当前 Action 装载的那一份 `SKILL.md`。不是 slash 流水线，也不是五个封闭领域。

编排在 Primary（`intent-reasoning.md`）：产物缺口、init 先于调查、调查拆路与 fanout 隔离上下文。Primary **不读** Skill。

| 种类 | 路径 | 说明 |
|------|------|------|
| 执行 Skill | `skills/<id>/SKILL.md` | 这一步怎么做。中文。 |
| 叠加原语 | 同目录结构 | 如 `source-proof`。由执行步指针触发，不进天花板名单。 |
| Reference | `skills/<id>/references/` | 仅当该步点名才装。目录、长表、域专文。 |
| Workflow spec | `pilot/ascendc_pilot/workflows/*.py` | 阶段、lease、gate。Skill 不复述。 |
| 主控路由 | `intent-reasoning.md` | 拆路、fanout、冲突核对。不在 Skill 树。 |

Action Spec 用 `skill_id` 指向 `skills/<id>/SKILL.md`。prepare 把它写入 session `method.md`。缺文件则失败。确定性 Action 不挂 Skill。

---

## 对照标准（怎么写）

对照对象：可复用的执行 Skill（Matt Pocock 仓里 `diagnosing-bugs` / `code-review` / `wayfinder` / `writing-beats` 这一档），不是 15 行的入口壳。

量过：那一档正文大约 **80–140 行**，中位数约 75。这是写作对照，不是 Anthropic / OpenAI 官方行数标准。**AscendC-Pilot 仓内 lint / engineering budget**：执行步目标 **80–150 行**，硬顶 **200 行**（compose / architecture lint）。路由父本（`bind-init` / `plan` / `solve` / `standalone-review`）允许更短，禁止为过 80 行补背景课。

### 渐进式披露

把「这一步**每次循环都要用**的判断」放进 `SKILL.md`。把「只有走到某分支才要打开的目录 / 长表 / 域专文」放进 `references/`，由正文**一层指针**点名。

| 放 SKILL.md | 放 references/ |
|-------------|----------------|
| 这一步是什么、输入输出、与邻步边界 | 场景 id 目录、字段清单 |
| 带判断的步骤（怎么判、何时停） | 长示例、worked example |
| 每轮都要用的启发式 / 反模式 | 某一域的专文（Key / Kernel / Buffer） |
| 短输出形状（必填字段、完成条件） | 证书 schema、完整对照表 |

指针只深一层：`references/foo.md`。Reference 正文不得再写 `references/*.md`。要复用方法 → `skills/<id>/SKILL.md`。不要链到别人的 `references/`。

不要把 20 份 gotchas 默装进 session。也不要把 SKILL.md 写成「步骤三条 + 详见 references」。

---

## Reference 合同

1. **范围 ≤ owner Skill。** 禁止 workflow 阶段 gotchas（init/plan/solve 混装）。
2. **一个 blob 只属于一个有 `SKILL.md` 的目录。** 跨 Skill 需求升级为 Policy / CONTEXT / Skill 原语 / schema。禁止 `skills/_shared/`。
3. **选择器只有两类显式声明。** `refs` = 当前方法的补充材料；`knowledge_refs` = 跨任务仍成立的静态领域知识。禁止自动选择。Runtime 只拷 Action / 轴上的这两类名单，Skill 正文反引号是给人看的指针，不是第二套发现机制。指针只深一层。
4. **身份是 `(owner_skill_id, relative_path)`。** 禁止 basename fallback；歧义 `REFERENCE_AMBIGUOUS` fail-closed。
5. **删文件测试：** 删掉它是否损失「只有特定分支才需要」的信息？否 → 删。不要用 SKILL 摘要副本。
6. **模型可见中文。** 判断与步骤用中文。保留英文的只有：路径、YAML/字段名、CLI、裁决枚举（`HIT` / `PROVED`）、场景 id（`P-*` / `F-*`）。标题与「何时加载」一律中文。禁止 `When to load` / `Gotchas` 当一级标题。

跨层归属（Policy vs Skill vs Prompt）见 `docs/architecture/agent-content-rules.md`。细节合同以本文件为准。

### 正文骨架

`description`：做什么是能力短句，不是「先…再…」步骤。什么时候用是触发场景（出现什么意图 / 产物 / 问题），不是「执行 <Action> / slash 时使用」。内部 cognitive Skill 的 description 是文档元数据，选择由 ActionSpec 决定；若日后 export 成 host-native Skill，description 才必须编码触发条件。

```markdown
---
name: <id>
description: <做什么>。<什么时候用>。第三人称。
---

# 标题

开篇：这一步解决什么问题；读什么、写什么；不做什么（邻步 / 引擎 / 主控的边界）。

## 输入 / 输出 / 停

缺前置产物时的失败码。禁止事项（一两句，不复述 Policy）。

## 步骤

编号阶段。每步写：做什么、怎么判断、完成或停。需要分支时就地写，不要「见某某文件」。

## 常驻判断

这一步每次都要用的启发式、claim 分层、口径。从 gotchas 里提升上来的，是判断不是背景课。

## 看到这样

现象 → 判断。每轮对照，不要把这张表赶到 references。

## 完成勾选

正向完成条件。勾不上就还没停。

## 循环

这一步每一轮实际怎么转：读什么、调用什么、何时停、不够时下一步。对照 `writing-beats` 的 what-to-do 循环。

## 输出形状

短模板（必填字段）。长 schema 放 references。

## 反模式

这一步最容易做反的几条。不要写成通用编程课。

## 指针

- 分支目录 / 长表：`references/…`
- 领域事实：`knowledge/…`（只由 Action / 轴 `knowledge_refs` 装，不自动选）
- 叠加原语：`skills/<id>/SKILL.md`
```

仓内 lint：执行步少于 80 行视为空壳，超过 200 行失败。这是本仓 engineering budget，不是官方 Skill 标准。路由父本不设 80 行地板。150 以上先考虑把目录/长表示例下沉到 `references/`，不要删判断。

父步（fanout / 序列路由，如 `bind-init`、`plan`、`solve`、`standalone-review`）写清各窗交什么、禁止混轴、本步不代替切片。不要为凑行数写背景课。按 slash 窗口收目录，禁止按主题焊成一份 always-loaded 正文。

切片 HOW 若只属于某一轴，放 `references/<axis>.md`，由 Spec `fanout_axes[].method_ref` 或串行 Action `method_ref` 装进该窗的 `method.md`；`refs` 是该窗才拷的一层指针（轴文件禁止 hop）。父窗口 `SKILL.md` 点名这些文件，prepare 不把它们拷进父 session。同一 Skill 里的后序裁判步用 Action `method_ref` 只装裁判文，不要把两路 HOW 塞进主控窗口。禁止把多窗正文拼进一份始终装载的 `SKILL.md`。

### 禁止

- 复述 Policy / invariant 全文；只点名（如「形态见 `uo-query` Skill」）。
- 复述 workflow 阶段表、lease、finalize。
- 「你是某某角色」。
- 把五个家族或 slash 说明书写进 Skill。
- 为凑行数写背景课（什么是 PDF、什么是 CodeMap）。
- `description` 写成执行步骤，或把 Action / slash 名当成触发条件。

Prompt 只留本题 I/O。确定性 invariant 放 Engine。词表 `agents/CONTEXT.md`。属主：`docs/architecture/agent-content-rules.md`。
