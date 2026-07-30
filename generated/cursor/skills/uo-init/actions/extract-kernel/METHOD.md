# 抽取 Kernel 折叠分支

> **`acp` 是真实 CLI。** 本 Action 走 `uo_init.pilot_engines.extract_kernel`（确定性）。

## Goal

在有 tiling key header 与 kernel 入口时，按模板维折叠 kernel 分支；缺失则可 skip。

## Domain Procedure

```text
acp run-action extract_kernel --project <算子目录>
```

## Output

- `uo/kernel/fold_receipt.yaml`
- 合同：`extract-kernel-v1`
