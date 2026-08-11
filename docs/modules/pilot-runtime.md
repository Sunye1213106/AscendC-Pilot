# Pilot Runtime

## 定位

Pilot 是 workflow、state、gate、context pack、lease、recovery 和 host runtime composition 的控制面。

## 职责

- 启动和恢复 workflow。
- prepare / finalize actions。
- 签发 Action Leases。
- 构建 context packs。
- 校验 gates 和 contracts。
- 维护 run state 与 receipts。
- 暴露 `acp` CLI。
- 加载 operator-local extensions。

## 非职责

- Pilot 不实现领域分析本身。
- Pilot 不把算子产物存到工具 checkout。
- Pilot 不信任 agent 自行宣布 workflow success。

## 入口

- CLI：`acp`、`ascendc-pilot`
- Python package：`ascendc_pilot`
- Host runtime：由 `scripts/compose_runtime.py` 生成

## 输入

- workflow id 与 project root
- `agents/*.yaml`
- `skills/`、`prompts/`、`pilot/policies/`
- Workflow spec 与 ownership tables
- 已有 `.ascendc-pilot/` state

## 处理流程

Pilot 解析 operator workspace，启动 run，准备 action bundle，通过 lease 授权执行，finalize output，校验 gate，然后 advance 或 route rework。

## 输出

- `.ascendc-pilot/<arch>/state/**`
- `.ascendc-pilot/<arch>/runs/**`
- `.ascendc-pilot/<arch>/context/**`
- `generated/` 下的 host files

## 不变量

- status 决定 lease mode。
- 只有 gate 和 finalizer 能推动 workflow success。
- action write paths 必须落在 agent ceiling 和 workflow ceiling 内。

## 实现锚点

- `pilot/ascendc_pilot/cli.py`
- `pilot/ascendc_pilot/workflows/specs.py`
- `pilot/ascendc_pilot/state/machine.py`
- `pilot/ascendc_pilot/actions/`
- `pilot/ascendc_pilot/authorize/lease.py`
- `pilot/ascendc_pilot/context/compiler.py`
- `pilot/ascendc_pilot/local_extension.py`

## 测试

- `pilot/tests/`
- `scripts/tests/`
