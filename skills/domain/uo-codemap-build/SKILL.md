---
name: uo-codemap-build
description: >
  构建并审查单一 AscendC `.uo` CodeMap，提取 API、Host 调用/读写、TilingKey、
  TilingData、模板、Kernel、分支与源码证据。首次建立或重建 UO、检查结构完整性，
  或处理确定性提取无法闭合的源码关系时使用；不用于求解完整 TilingKey 输入公式。
---

# UO CodeMap 构建

目标：把 AscendC 源码和 architecture 编译成一个 Agent 可查询的源码语义图。

```text
prepare → extract → analyze → resolve → commit → review
```

## 职责边界

UO 回答：**有什么、在哪里、谁调用、谁读写、受什么 guard 控制、Key/Data/Kernel 如何连接、证据来自哪里。**

UO 不回答：

- 某个 19 维 packed TilingKey 是否一定可达；
- 每个 Key 维度关于输入的完整 closed-form expression；
- 全量 Key 的 SAT/UNSAT；
- container cardinality、event exclusion、read-coverage implication 等程序证明问题。

这些按需推理属于 TG 的 case construction / replay / local lemma 闭环。

## 稳定规则

1. **确定性提取优先**：Clang、source pass、数据流/模板/宏/架构 Pass、写入和结构审查由 engine 执行。
2. **关系必须有证据**：`CALLS`、`READS`、`WRITES`、`DERIVES`、`FLOWS_TO`、`SELECTS`、`INSTANTIATES`、`LAUNCHES`、`BINDS` 必须能回到源码或 compiler provenance。
3. **不为闭环制造公式**：某个 Key producer 很复杂时，保留 producer、all-writes、guards、upstream roots 和 source span；不要把循环/容器状态强行展开成巨大表达式。
4. **编译期是一等语义**：macro、compile var、template arg / instance、BuildVariant、ARCH 显式建模。
5. **生命周期保真**：保存→修改→恢复、同一字段多次赋值、跨函数读写必须能被 Agent 查询，不能只留下最终值。
6. **单一产品权威**：正式产物是 `.ascendc-pilot/uo/<op>.<arch>.uo`；中间 YAML 只是 Action receipt/debug evidence。

## 六阶段边界

- `prepare`：确定 operator root、architecture、BuildVariant 和源码范围。
- `extract`：Clang/frontend 提取 Host/Kernel/source facts。
- `analyze`：构建结构 CodeMap 并检查 API→Host→TilingKey/TilingData→Template/Kernel 的证据路径；不运行 deep Key derivation/global SAT。
- `resolve`：只处理结构关系仍然缺失或真歧义的 gap；证据不足就保留 unresolved。
- `commit`：写入单一 `.uo`。
- `review`：检查结构、provenance、跨层路径和 unresolved 一致性。

## TG 最需要 UO 提供的查询事实

- TilingKey：维度名、顺序、位宽、domain、Host packing 参数、producer、all writes、guards。
- TilingData：struct/field、Host setter/writer、Kernel reader、registration。
- Kernel：入口、template args/instances、calls、branches、predicates、输入输出流。
- Source evidence：file/line/snippet/provenance/status。

## 按需参考

| 需要判断 | 读取 |
|---|---|
| authority / provenance | `references/authority-model.md` |
| 结构完整性与 unresolved | `references/completeness.md` |
| frontend / extract 覆盖 | `references/extraction-quality.md` |

只在当前问题需要时读取对应 reference；不要一次加载全部参考文件。
