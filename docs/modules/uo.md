# UO - Understand Operator

## 定位

UO 把 AscendC 算子源码转换成结构化 CodeMap，供查询、TG 和 CE 消费。

## 职责

- 解析 operator root 和 architecture。
- 建立 Clang Source Scope 与 build variant。
- 从 Host / Kernel 源码抽取 CompilerFacts。
- 分析 Host、TilingKey、TilingData、Kernel templates、branches 和 dataflow。
- 显式保留 unresolved gaps。
- 提交 canonical `.uo` 产物。
- 导出 query view 与 TG-facing projections。

## 非职责

- 不证明 testcase coverage。
- 不生成最终 testcase。
- 不允许 LLM agent 重写 canonical `.uo` product。

## 入口

- Slash：`/uo-init`、`/uo-query`、`/uo-update`
- CLI：`acp start uo-init`、`acp uo-query`、`acp uo ...`
- Engine CLI：`uo-init`、`uo-dump`

## 输入

- AscendC operator source directory
- architecture，默认 `arch35`
- build context 与 CANN / Clang 可用性
- `/uo-update` 可读取已有 `.ascendc-pilot/` 产物

## 处理流程

```text
prepare -> extract -> analyze -> commit -> verify
```

`prepare` 解析 layout 和 source scope；`extract` 构建 CompilerFacts；`analyze` 运行确定性 CodeMap passes；`commit` 写入 arch-neutral `.uo` product；`verify` 校验结构完整性和导出 view。

## 输出

- `.ascendc-pilot/uo/<op_name>.<arch>.uo`
- `.ascendc-pilot/<arch>/uo/**`
- `.ascendc-pilot/<arch>/runs/**/actions/**`

## 不变量

- Clang Source Scope 是源码事实边界。
- unresolved gaps 保留为显式产物，不静默填补。
- LLM investigation 只能写 bounded reports，不能写 canonical CodeMap。
- TG 消费 UO product，不重建源码理解。

## 失败与恢复

Gate 失败后 workflow 停留在当前 phase 并进入 rework。Scope 失败回到 `prepare`；extraction 失败重跑 `extract`；integrity 失败根据 reason 回到 analyze 或 commit。

## 集成关系

TG 读取 UO contracts、snapshots、TilingKey domains、Host/Kernels projections。CE 读取 UO impact 与 relation views。

## 实现锚点

- `engines/understand-operator/src/uo_init/`
- `engines/understand-operator/src/uo_init/workflow.py`
- `engines/understand-operator/src/uo_init/passes/`
- `engines/understand-operator/src/uo_init/ir/`
- `pilot/ascendc_pilot/uo_artifacts.py`
- `pilot/ascendc_pilot/uo_scope.py`
- `skills/operator-analysis/`
- `agents/deterministic-uo-engine.yaml`
- `agents/uo-query.yaml`
- `agents/uo-gap-investigator.yaml`

## 测试

- `engines/understand-operator/tests/`
- `pilot/tests/test_uo_output_contracts.py`
- `pilot/tests/test_tg_uo_codemap_contract.py`
- `evals/skills/operator-analysis/`
