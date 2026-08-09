---
name: uo-kb-query
description: >
  基于统一 UO CodeMap 与源码证据回答算子 API、Host、TilingKey、TilingData、Kernel、模板、宏、架构与数据流问题。
  用于查询、解释、定位与完整性检查，不修改 UO。
---

# UO CodeMap 查询

## 权威入口

查询优先读取 `.ascendc-pilot/uo/<op>.<arch>.uo`。调用方只使用 `uo_init.uo_query.open_query(...)` / `CodeMapQuery`，不得依赖底层 SQLite 表结构或手写 SQL。

旧 `indexes/kb_graph.sqlite` 仅是迁移期 fallback；新 `.uo` 存在时不得绕回旧库。

## 核心循环

```text
理解问题
 ↓
解析实体 / 关系 / 路径
 ↓
CodeMap 结构化查询
 ↓
必要时读取源码切片验证
 ↓
回答并附 provenance / source span
```

## 查询面

优先按问题使用最窄的结构化接口：

- API：`operator_api`、`input_roots`、`output_roots`
- TilingKey：`tiling_keys`、`selected_kernel`；保留声明顺序、bit width / offset 与 packed-key registration
- TilingData：`tiling_data`、`tiling_fields`、`tiling_registrations`、`field_impact`
- 代码图：`search`、`neighbors`、`callers`、`callees`、`find_path`、`upstream`、`downstream`
- 编译期：宏、compile var、template arg / instance、active build variant、available arch
- 质量：`audit`、`unresolved`、`summary`

## 证据规则

1. 结构化边必须有源码、编译器或确定性 pass provenance；不能用节点共存推断关系。
2. `TilingKey → Kernel`、`Template → Kernel`、`Input → Kernel` 等跨层链必须沿真实 relation 回答，禁止补 Cartesian 边。
3. 当前源码声明的 API、TilingKey、TilingData、Kernel ABI 优先于历史 archive；历史自由文本只作为线索，不自动升级为 relation。
4. 同名多候选时返回歧义；不得静默择一。
5. 查询未命中不等于源码不存在。必要时定位源码验证，并把结果标成 `PARTIAL` 或 `UNKNOWN`。
6. `unresolved` 仍存在时，不得把对应子图描述成 compiler-complete。语法级 call inventory 不能冒充完整 C++ call-target graph。

## 结果

- **ANSWERED**：结构化证据足以直接回答
- **PARTIAL**：主问题可回答，但存在明确 unresolved / compiler gap
- **UNKNOWN**：证据不足，不能可靠推断
