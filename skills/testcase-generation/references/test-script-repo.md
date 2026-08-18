# Test-script repository

**何时加载**：`/tg-init` bind。测试脚本仓常在算子仓外。

脚本仓是算子已有的 runner（脚本 + csv/xls/xlsx），不是第二份 CodeMap。

```text
无 --test-script-root
  → kind: default_input
  → 用 InputSemantics / CodeMap 默认输入

有 --test-script-root
  → engine 只扫描入口、argparse、表头（含 xls/xlsx）
  → Agent 把列 mapping / 精度性能口径写进 init.yaml
  → 生成行必须填满该表，现有 runner 才能直接吃
```

## Agent 必须做

引擎不懂 runner。要读脚本仓：

1. 打开入口（`run_*.py`）和 argparse。确认 `--case`，以及哪些 flag 是精度、哪些是性能。
2. 打开用例表。每列 mapping：脚本读点（如 `get_case` / `CaseConfig.xxx`）+ UO 标识符。
3. 对照 CodeMap：表允许但算子非法的组合、缺的 INPUT、发明的张量。记进 `findings`。
4. 缺列或缺 `generate_inputs` → `test_harness_gap`，由 `/ce-apply` 改**测试脚本仓**，不要在 TG 里改算子仓。

## 规则

1. 不要把某一个算子的列名写进引擎。
2. Host replay 只关 dispatch / key。精度/性能看脚本自己的 modes。
3. 点了脚本仓却扫不到目录 → init 失败，不是 default_input。
4. FAG：精度 `only_grad`，性能 `profiler`；禁止把精度记成 `--golden-only`。
