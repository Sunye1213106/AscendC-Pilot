---
name: tdd-engines
description: >
  Test-driven development for AscendC-Pilot Python engines and harness.
  Use when adding engine features, gates, CLI, schema, or fixing bugs
  test-first in engines/ or pilot/. Not for operator TG closure.
---

# TDD at Pilot seams

红 → 绿，一次一个垂直切片。测的是 Pilot 自己的公共缝，不是算子 Host replay。

先读 `agents/CONTEXT.md`。动到的模块若有 ADR，遵守它。

## 缝在哪

测试只打在事先说清的缝上。本仓典型缝：

- `acp` CLI 退出码与 stdout 机器字段
- workflow gate / lease / occupancy
- schema 与 `quality.yaml` 的 `grade` / `locate_blocking`
- CodeMap query mode 的稳定 JSON/YAML 形状
- compose / authorize 契约（`scripts/check_*.py`、`pilot/tests/`）

先写下缝，跟用户确认，再写第一个失败测试。

## 好测试

通过公共接口断言行为。实现可以整页重写，测试仍过。期望值来自独立事实（fixture、已知字面量、spec），不要用被测代码再算一遍当期望。

## 反模式

- 测私有方法、mock 内部合作者
- 水平切片：先写完全部测试再实现
- 把 TG 的 `Replay reject` 或搜索失败写成 `E`
- 在 `/ce-review` 叙事里「TDD 掉」CE 义务

## 环

1. 写一个失败测试（红）。已经绿就不是这条环。
2. 只写让它绿的最少代码。
3. 重构留给 `pilot-pr-review`，不塞进红绿循环。

Hard guardrail：`T=(R∩T)∪E` 是算子覆盖代数，不是 pytest 命名约定。
