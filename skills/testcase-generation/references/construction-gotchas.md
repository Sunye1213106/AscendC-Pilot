# TG Init — Gotchas

- **正式产物只有 `init.yaml`**：不要再写 inventory / audit / fingerprint / contract YAML。
- **有脚本仓必须有 mapping**：每一列同时绑脚本读点与 UO 标识符。mapping 空 → init 失败。
- **扫描含 xls/xlsx**：只认 csv 会漏真实跑测表。
- **精度口径写脚本真实怎么跑**：FAG 精度是 `only_grad`，性能是 `profiler`。禁止把精度记成 `--golden-only`。
- **`uo_digest` 由 promote/confirm 写入**：TG 不改 `.uo`。digest 变了必须重跑 `/tg-init`。
- **查语义走 uo-query**：禁止 Grep 算子仓。
- **人确认前不得 plan/solve**：`confirmed` 在 `init.yaml` 上。
