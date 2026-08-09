---
name: uo-codemap-build
description: >
  构建并审查单一 AscendC `.uo` CodeMap，覆盖 BuildVariant、宏与编译期变量、
  模板、TilingKey/TilingData、Host→Kernel 关系和输入根推导。首次建立或重建
  UO、检查 CodeMap 完整性，或处理确定性 Pass 无法闭合的语义缺口时使用。
---

# UO CodeMap 构建

目标：把 AscendC 源码、编译上下文和 architecture 编译成一个可查询的 `.uo`，而不是让 Agent 维护多套 YAML 语义副本。

```text
prepare → extract → analyze → resolve → commit → review
```

## 稳定规则

1. **确定性优先**：Clang 抽取、数据流/模板/宏/架构 Pass、patch merge、写入和结构审查由 engine 执行；Agent 不重复解析确定性事实。
2. **只消解显式缺口**：只有 `analyze` 产出的 unresolved semantic gap 才进入 `resolve`；证据不足就保留 unresolved。
3. **关系必须有证据**：`DERIVES`、`FLOWS_TO`、`SELECTS`、`INSTANTIATES`、`LAUNCHES`、`BINDS` 等 relation 必须带可追溯 provenance，禁止用节点共存构造笛卡尔积关系。
4. **编译期是一等语义**：macro、compile var、template arg / instance、BuildVariant 和 ARCH 要显式建模，不能降级成自由文本备注。
5. **生命周期要保真**：保存→修改→恢复等变量生命周期不能被压成循环定义；值版本、控制边和恢复关系必须保持可区分。
6. **单一产品权威**：正式产物是 `.ascendc-pilot/uo/<op>.<arch>.uo`；调试投影只能由 `.uo` 按需导出，不能反向成为 authority。

## 六阶段边界

- `prepare`：确定 operator root、architecture、BuildVariant 和源码范围；只有真实歧义才需要用户判断。
- `extract`：Clang / frontend 产生 CompilerFacts，不做 LLM 语义猜测。
- `analyze`：确定性 AscendC Pass 将 facts 归一为 CodeMap entity / relation，并产生 unresolved。
- `resolve`：只针对分配到当前 Action Bundle 的 unresolved 补充有证据的 staged patch。
- `commit`：写入单一 `.uo` 产品。
- `review`：确定性检查结构、provenance、跨层路径和 unresolved 一致性。

## 按需参考

| 需要判断 | 读取 |
|---|---|
| authority / provenance | `references/authority-model.md` |
| 完整性与 unresolved | `references/completeness.md` |
| 字段推导是否 exact | `references/derivation-quality.md` |
| frontend / extract 覆盖 | `references/extraction-quality.md` |

只在当前问题需要时读取对应 reference；不要一次加载全部参考文件。
