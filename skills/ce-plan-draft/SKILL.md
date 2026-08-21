---
name: ce-plan-draft
description: 把已问清的需求写成命名计划 markdown。执行 /ce-plan 的 plan_draft 时使用。
---

# 写出计划

路径：`ce/plan/{slug}_plan.md`。形状参考 `examples/deter-band-schedule_plan.md`。本步把 intent-grill 已问清的需求写成可被 apply 逐条执行的命名 markdown。不要以 PR 为输入。不要写任何 CE yaml。

一次 apply 做一个 todo。todo 必须小到能单独落地、单独勾选。

## 输入 / 输出 / 停

读：intent-grill 草稿（范围、不做的事、测试内容、未决）、查图卡片。UNRESOLVED 且会改变改哪些文件时，不要假装已决。

写：一份命名 markdown。路径写在反引号里。禁止 `tg_plan_intent.yaml`、`change_capture.yaml`、`ce/review/`。

完成：一份命名 markdown，含实现分析、分步计划、可勾选 Todo、测试内容。

## 必须包含

1. **实现分析。** 查图，列出将改路径与不做的范围。点名文件与符号，不要写「相关代码」。侧别（kernel / tiling / host）与 grill 一致。
2. **分步计划。** 顺序可执行。依赖写清（先改 Host 合同再改 Kernel 读者）。不要把审查或刷图写成 todo。
3. **可勾选 Todo。** 一次 apply 做一个。每条对应声明文件集，apply 才能只改那些文件。不要一条 todo 横跨测试仓与算子仓。
4. **测试内容。** 给 `/tg-plan` 读的散文，不要编码成 yaml，不要在这里展开 `P-*` 矩阵。TG 自己从本节总结义务。

## 步骤

1. 把 grill 的范围 / 不做的事抄成计划边界，不要偷偷扩大。
2. 用查图核对将改路径确实存在、符号对得上。命名相似不够。
3. 把工作切成 `- [ ]` 项。每项能在一回合改完。
4. 测试内容只写「应该观察到什么 / 哪类 shape / 精度还是性能」，把构造留给 TG。
5. 停。不要开始改码，不要内嵌双轴审查。

## 常驻判断

`/ce-plan` 与 `/ce-review` 不要混。本步不审 diff。验证不在 CE：建议测试走 `/tg-plan`。

LLM 禁止写 `.uo`。apply 刷图由引擎做。handoff 只引用路径，不要把本计划全文抄进总结——那是后一步。

没有 `- [ ]` 就不是一份能 apply 的计划。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| grill 仍有会改文件集的 UNRESOLVED | 不要假装已决 |
| 一条 todo 横跨算子仓与测试仓 | 拆开 |
| 把刷图 / 审查写成 todo | 删掉 |
| 测试内容写成 yaml / `P-*` 表 | 改回散文 |
| 以 PR 为输入 | 停；那是审查 |
| 没有 `- [ ]` | 不是能 apply 的计划 |

## 完成勾选

- [ ] 有实现分析（将改路径 + 不做的范围）
- [ ] 有分步计划与可勾选 Todo，一次 apply 一个
- [ ] 有给 `/tg-plan` 读的测试内容
- [ ] 路径写在反引号里；没有 CE yaml

## 循环

1. 把 grill 的范围 / 不做的事写成计划边界。
2. 查图核对将改路径与符号。
3. 切成一次 apply 一个的 `- [ ]`，声明文件集。
4. 测试内容写成给 `/tg-plan` 的散文。
5. 停。不要改码，不要审 diff。

## 输出形状

一份 `ce/plan/{slug}_plan.md`，路径写在反引号里。必须有：实现分析、分步计划、`- [ ]` Todo、测试内容。没有 `- [ ]` 就不算完成。

## 反模式

- 以 PR 为输入
- 一条 todo 横跨算子仓与测试仓
- 把刷图、审查写成 todo
- 测试内容编码成 yaml
- 实现分析只写「相关代码」不点路径
- 开始改码或内嵌双轴审查

## 指针

写计划易错点：`references/gotchas.md`。grill 小节形状：`skills/ce-intent-grill/SKILL.md`。
