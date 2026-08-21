# Skills 布局与写法

Skill 是**执行步文档**：当前 Action 装载的那一份 `SKILL.md`。不是 slash 流水线，也不是五个封闭领域。

编排在 Primary（`intent-reasoning.md`）：产物缺口、init 先于调查、调查拆路与 fanout 隔离上下文。Primary **不读** Skill。

| 种类 | 路径 | 说明 |
|------|------|------|
| 执行 Skill | `skills/<id>/SKILL.md` | 这一步怎么做。中文。 |
| 叠加原语 | 同目录结构 | 如 `precision-testing`、`performance-testing`、`source-proof`。由执行步指针触发，不进主控。 |
| Reference | `skills/<id>/references/` | 仅当该步点名才装。目录、长表、域专文。 |
| Workflow spec | `pilot/ascendc_pilot/workflows/*.py` | 阶段、lease、gate。Skill 不复述。 |
| 主控路由 | `intent-reasoning.md` | 拆路、fanout、冲突核对。不在 Skill 树。 |

Action Spec 用 `skill_id` 指向 `skills/<id>/SKILL.md`。prepare 把它写入 session `method.md`。缺文件则失败。确定性 Action 不挂 Skill。

---

## 对照标准（怎么写）

对照对象：可复用的执行 Skill（Matt Pocock 仓里 `diagnosing-bugs` / `code-review` / `wayfinder` / `writing-beats` 这一档），不是 15 行的入口壳。

量过：那一档正文大约 **80–140 行**，中位数约 75。本仓硬顶 **200 行**（compose / architecture lint）。目标 **80–150 行**。少于约 80 行通常是把判断全赶到 `references/`，模型只看到骨架。

### 渐进式披露

把「这一步**每次循环都要用**的判断」放进 `SKILL.md`。把「只有走到某分支才要打开的目录 / 长表 / 域专文」放进 `references/`，由正文**一层指针**点名。

| 放 SKILL.md | 放 references/ |
|-------------|----------------|
| 这一步是什么、输入输出、与邻步边界 | 场景 id 目录、字段清单 |
| 带判断的步骤（怎么判、何时停） | 长示例、worked example |
| 每轮都要用的启发式 / 反模式 | 某一域的专文（Key / Kernel / Buffer） |
| 短输出形状（必填字段、完成条件） | 证书 schema、完整对照表 |

指针只深一层：`references/foo.md`。不要「见 references/ 再去看另一本 Skill 的 references」。叠加原语用 `skills/<id>/SKILL.md` 指针。

不要把 20 份 gotchas 默装进 session。也不要把 SKILL.md 写成「步骤三条 + 详见 references」。

### 正文骨架

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
- 叠加原语：`skills/<id>/SKILL.md`
```

lint：少于 80 行视为空壳，超过 200 行失败。150 以上先考虑把目录/长表示例下沉到 `references/`，不要删判断。

父步（fanout 索引，如 `bind-init`、`standalone-review`）同样用这副骨架：写清两路各交什么、禁止混轴、本步不代替切片。不要因为「真正的活在切片里」就只留 12 行。

### 禁止

- 复述 Policy / invariant 全文；只点名（如「形态见 code-access」）。
- 复述 workflow 阶段表、lease、finalize。
- 「你是某某角色」。
- 把五个家族或 slash 说明书写进 Skill。
- 为凑行数写背景课（什么是 PDF、什么是 CodeMap）。

Prompt 只留本题 I/O。确定性 invariant 放 Engine。词表 `agents/CONTEXT.md`。属主：`docs/architecture/agent-content-rules.md`。
