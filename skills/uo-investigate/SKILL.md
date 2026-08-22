---
name: uo-investigate
description: 调查 CodeMap 里留下的 unresolved residual。问某个 gap 为何未闭合、或要指出引擎缺什么时使用。
---

# 调查缺口

分类根因，指出确定性引擎缺什么。不修改 canonical `.uo`。Deterministic pass 无法闭合的 residual 合法存在；不得默认用 LLM 补边、补字段、补 span 进正式图。

评价建库看 `uo/checks/quality.yaml` 的 `grade` 与 `unresolved.locate_blocking`，不要用 `unresolved.yaml` 总条数吓唬人或宣称「图很差所以随便补」。

## 输入 / 输出 / 停

读：lead pack / `ir/unresolved.yaml` 里被点名的 residual（须 freshness）、无参数索引的 `gaps_count`、相关源码窗口。写：每个被查 residual 的根因类别与证据窗口，或 `INSUFFICIENT`。只写 staging / 调查结论，不写 canonical。

完成：每个被查 residual 有根因类别与证据窗口，或标明 INSUFFICIENT。

HOST 运行时叶、PROJECT/BUILTIN 实体不算定位失败。不要把它们当成 locate_blocking。

## 步骤

1. **只查被点名的 residual。** bucket 为 `locate_blocking` / `host_runtime_leaf` / `catalog_unproven` 时先看 freshness。过期视图不能当事实。
2. **分类，不要发明边。** 典型根因：缺 include / 探针失败（那是 heal，不是本步补图）、Clang 没抽到的跨层边缺 span、宏/模板身份混用、命名相似但不是同一符号、源码窗口不够。
3. **证据窗口。** 每个结论落到 `file:line`。禁止凭变量名相似、文件邻近闭合。跨层边（Host→Tiling→Kernel）缺少 source span 时保持 unresolved。
4. **完整性。** 「文件在 projection 路径上」不等于 authority 已填充。空壳 / `not_extracted` 不能当抽取完成。artifact existence ≠ semantic completeness。索引 partial 时不得报「无其他符号」。
5. **停在建议。** 指出引擎缺什么（补抽取、补 span、走 include-heal、保持 unresolved）。不要手改 `.uo`，不要用 digest 当下一轮静态事实。

## 常驻判断

权威分层：正式产品是已 commit 的 `.uo`；dump/query 视图可重建；LLM digest 只是说明层，**不得**成为下一轮静态事实。模型补丁必须走 candidate → evidence → review → accepted fact，不得悄悄写回。

BuildVariant 混用：不同 architecture / 编译宏下的符号不得并进同一无身份。局部变量保存-修改-恢复里，临时写回不是最终 defining site。

查询纪律与 `uo-query` 相同：空结果 ≠ 不存在；SEL 第一页不是全集。本步可以查图，但目的是给 residual 找根因，不是回答用户的产品问题。

## 看到这样

| 现象 | 判断 |
| --- | --- |
| `locate_blocking` | 要根因 + 窗口 |
| `host_runtime_leaf` / BUILTIN | 不是定位失败 |
| 文件在但 `not_extracted` | 不完备，不是「有文件就完成」 |
| 命名相似、文件邻近 | 不能闭合 |
| 跨层边缺 span | 保持 unresolved |
| 探针缺头 | 那是 include-heal，不是补图 |
| 想改 canonical `.uo` | 禁止 |
| 索引 partial | 不得报「无其他符号」 |

## 完成勾选

- [ ] 每个被查 residual 有根因类别与证据窗口，或 INSUFFICIENT
- [ ] 指出了引擎缺什么，没有发明边
- [ ] 没有用 digest 当静态事实，没有手改 `.uo`

## 循环

1. 只取被点名且 freshness 有效的 residual。
2. 分类根因：缺 span、宏身份、include、命名巧合、窗口不够。
3. 每个结论落到 `file:line`。不能证就 INSUFFICIENT。
4. 指出引擎缺什么。停。不要补 canonical 边。

HOST 运行时叶不算定位失败。文件存在但 `not_extracted` 不算完备。

## 输出形状

每个 residual：`id`、`bucket`、根因类别、`file:line` 或 `INSUFFICIENT`、引擎缺什么。不要给出「建议补进 .uo 的边」。

## 反模式

- 用 LLM 补 canonical 边或字段
- 凭变量名相似 / 文件邻近闭合
- 把 HOST 运行时叶当成 locate_blocking
- 文件存在就报完备（内容仍是 `not_extracted`）
- 过期 unresolved 视图当事实
- 用 digest 当下一轮静态输入
- 把 query 空结果写成「图上不存在」

模型补丁必须走 candidate → evidence → review，不得悄悄写回 authority。

## 指针

权威分层：`references/codemap-authority.md`。完整性：`references/codemap-completeness.md`。构建失败 vs 图缺口：`references/codemap-build-gotchas.md`。
