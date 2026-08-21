# Test-script repository

**何时加载**：`/tg-init` bind。测试脚本仓常在算子仓外。

脚本仓是算子已有的 runner（脚本 + csv/xls/xlsx），不是第二份 CodeMap。

```text
无已确认的测试脚本根
  → 先询问：外部脚本仓路径 / default_input / 是否使用已发现的仓内 tests/
  → 未确认不得把算子仓 tests/、ut 当作 harness
  → 意图里没有仓外绝对路径或 git URL 时，禁止主控把发现的仓内 tests/ 写入 `test_script_root` 代答
  → 用户原文或对话里已出现**算子仓外**绝对路径或 git URL 时写入 `test_script_root` / `pilot_run(test_script_root=…)`，不要塞 intent，不要再问三项，不要再让子代理猜
  → 用户中途改路径：interpret-user-turn 覆盖并作废 repo_scan / bind ticket，不要沿用旧 scan
  → 选定 default_input 后用 InputSemantics / CodeMap 默认输入

路径确认后（无仓也继续）
  → 两路草稿：`parts/harness.yaml` 与 `parts/bind.yaml`（ACK 只认到齐数量）
  → 主控通读两份；没问题下一发 `PASS`，有问题 `REWORK bind` / `REWORK harness,bind`。引擎写内部 verdict；放行后 `bind_promote` 合并正式 `init.yaml`

已确认 --test-script-root
  → engine 扫描入口、argparse、表头、每表列画像（`tables[].profile`）以及全表汇总（`corpus_profile`：各可读表 observed 并集）
  → Agent 把列 mapping / 精度性能口径写进草稿；**observed 引用 corpus_profile；shape legal 是 Host 输入区间；`*TemplateNum` 进 template 并 Read 头文件写 mapping；禁止通读 CSV，禁止把表 max 或 Dim 列表当成 shape 合法全集**；promote 才落 init.yaml
  → 生成行必须填满该表，现有 runner 才能直接吃
```

## Agent 必须做

引擎不懂 runner。要读脚本仓：

1. 打开入口和 argparse（常见 `run_*.py`）。确认 `--case`，以及哪些 flag 是精度、哪些是性能。仓内若有用例设计 YAML，一并打开：接口顺序、dtype、合法/非法 range、精度与性能标准、边界开关。
2. 打开用例表。observed 以 scan `corpus_profile` 为准，不要通读几千行。shape 列的 legal 是 Host 可填区间，不是 `*TemplateNum` 列表。模板维用 `uo-query Dim=` 覆盖 + Read 头文件写出 mapping。不要把表 min/max 当成算子支持范围。每列 mapping：脚本读点（如 `get_case` / `CaseConfig.xxx`）+ UO 标识符。shape 列的 observed 用 range；`dim_*` 用先无参数索引再 `Dim=Name`。
3. 对照 CodeMap：表允许但算子非法的组合、缺的 INPUT、发明的张量。记进 `findings`。参数之间有依赖时，记成约束或 `generate_inputs` 缺口，不要当成两列独立可填。
4. 缺列或缺 `generate_inputs` → `test_harness_gap`，由 `/ce-apply` 改**测试脚本仓**，不要在 TG 里改算子仓。

## 规则

1. 不要把某一个算子的列名写进引擎。
2. Host replay 只关 dispatch / key。精度/性能看脚本自己的 modes。
3. 点了脚本仓却扫不到目录 → init 失败，不是 default_input。
4. argparse 同时有精度 mode 和性能 mode → 分别写入 `modes.precision` / `modes.perf`。默认值若是性能 mode，不得把默认当精度。help 写「不调用 pta / 无需 NPU」的 `--golden-only` 是造数，不是精度。
5. 多张 csv/xls 的 **observed** 以 `corpus_profile` 为并集；用户没点名的表不当本次目标。**legal** 是输入域，不看表也不看模板枚举。
6. 比对阈值在脚本函数里而不是 flag 上时，写进 `compare`；argparse 没有的 `atol`/`rtol` 不要编。
7. 不要把某一个测试框架的设计字段名写进引擎或 `init.yaml` schema。runner 吃 CSV/XLS 就填表；runner 吃 JSON/设计文件就按它的入口写 `entry` / `case_arg`。
