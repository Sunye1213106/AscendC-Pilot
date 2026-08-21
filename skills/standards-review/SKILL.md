---
name: standards-review
description: 审查 diff 的 Standards 轴：是否符合仓规范与跨层契约。有 git/PR diff 且走 Standards 轴时使用。
---

# Standards 轴

只做 **Standards** 轴。不要做 Spec（完成度、超范围、粗意图验收是另一路）。Finding 必须有 `path:line`。报告前尝试推翻 H1（「改动不违反跨层契约与仓规范」）。

无 span 的「可能有问题」降级或不报。禁止只陈述变更理解。

## 输入 / 输出 / 停

读：`change_capture/index.md` 的 Added identifiers、查图卡片。不要通读 `diff.md`。无 diff 则停。

写：Task 回复。禁止 Write `ce/**`。不得修改 `.uo`。

完成：每条 FINDING 有 `path:line`；未审 `op_kernel` 时不宣称无高风险。每个 changed file：finding / format-only / UNREVIEWED。

## 步骤

1. **index → 并行查标识符。** 用 Added identifiers 并行查图，不要把 format hunk 当第一跳。卡片给出 `file:line` 后跟窗口。snippet 截断不得下「枚举未用」。
2. **跨层合同优先于本地风格。** Host 改动必须对照 Tiling / Kernel 合同；只看 diff 行不够。同一语义状态经过 D_interface → D_validation → D_dispatch → D_implementation。运行时成功产生的调度状态不得落在实现声明之外（accepted-but-undeclared）。
3. **对每个新增或放宽的组合问：** 下游是否有对应声明与实现？对每个收窄下游问：上游是否仍允许该组合？
4. **并发与 Buffer。** 看 tposition + 调用点。EnQue/DeQue 是 TQue，看 QUEUE 方向；Set/Wait、CrossCore 看 `flag_paired`。happens-before 不是 UO。
5. **每个 changed file** 给出 finding / format-only / UNREVIEWED。影响面用查图，不是全文搜索。UT 不在图里：对 test 文件空卡是预期。
6. **推翻 H1。** 报告前找一条 accepted-but-undeclared 或读者/写者对不上的路径。找不到再维持 H1。

## 常驻判断

Kernel 以字段 readers 行为准，不要把 `kernel_call_boundary` 调用点当成定义。TilingData 来源 ≠ 已校验：必须 locate 到 `OP_CHECK_IF` 且变量同一。

本轴不验收「这次需求做完没有」——那是 Spec。两轴 finding 冲突时留给主控用字段卡裁定，禁止本步再派相同轴。

建议测试走 `/tg-plan`。不落 CE yaml，不合成 LGTM。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| Host 放宽了 dtype / optional / key | 问下游有没有声明与实现 |
| 下游收窄了实现 | 问上游是否仍允许 |
| 只看了 diff 行 | 不够；要对照 Tiling / Kernel 合同 |
| EnQue / DeQue | TQue，看 QUEUE 方向 |
| Set/Wait、CrossCore | `flag_paired`；happens-before 不在图 |
| 想验收「需求做完没有」 | 那是 Spec 轴 |
| 未审 `op_kernel` | 不宣称无高风险 |

## 完成勾选

- [ ] 跨层路径问过 accepted-but-undeclared
- [ ] 每个 changed file 有 finding / format-only / UNREVIEWED
- [ ] 每条 FINDING 有 `path:line`；尝试推翻过 H1
- [ ] 没有做 Spec，没有写 `ce/**`

## 循环

1. 读 index，并行查标识符，跟窗口。
2. 对每个新增/放宽组合走一遍 D_interface → … → implementation。
3. 并发与 Buffer 看 tposition 与 QUEUE / flag_paired。
4. 每个文件落 finding / format-only / UNREVIEWED。推翻 H1。
5. 只交 Standards 轴。完成度问题留给 Spec。

## 输出形状

```text
file: <path>
status: finding | format-only | UNREVIEWED
FINDING: <accepted-but-undeclared | 跨层读者对不上 | 并发/Buffer>  path:line
```

未审 `op_kernel` 不得写「无高风险」。

## 反模式

- 做 Spec 的完成度验收
- 通读 `diff.md`、把 format hunk 当第一跳
- 无 `path:line` 仍报 finding
- 把 `kernel_call_boundary` 当字段定义
- 用 happens-before 当 UO 结论
- 写 `ce/**` 或改 `.uo`

## 指针

仓规范检查：`references/ascendc-checks.md`。跨层契约：`references/cross-layer-contracts.md`。并发：`references/concurrency.md`。易错点：`references/gotchas.md`。
