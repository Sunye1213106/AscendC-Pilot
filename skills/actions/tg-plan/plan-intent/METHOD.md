# 确认规划意图

> **`acp` 是真实 CLI。** Primary 交互 Action。

## Goal

落盘 `tg/plan/plan_intent.yaml`。默认 `mode=tilingkey_full_coverage`。

## Domain Procedure

1. 按 task prompt `tg/plan-intent` AskQuestion（默认 / 用户描述 / PR）
2. 执行：

```text
acp run-action plan_intent --project <算子目录>
```

（若 prepare 要求 human 选择，先选再 finalize。）

## Hard Constraints

- MUST NOT：跳过意图直接 `plan_build`
- MUST NOT：在默认全量路径上追问 CSV 路径
- MUST NOT：自行宣布 workflow passed

## Output

- 合同：`plan-intent-v1`
- 写域：`tg/plan/plan_intent.yaml`
