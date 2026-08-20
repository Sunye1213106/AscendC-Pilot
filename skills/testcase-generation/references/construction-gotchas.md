# TG Init — Gotchas

- **正式产物只有 `init.yaml`**：不要再写 inventory / audit / fingerprint / contract YAML。
- **有脚本仓必须有 mapping**：每一列同时绑脚本读点与 UO 标识符。mapping 空 → init 失败。
- **扫描含 xls/xlsx**：只认 csv 会漏真实跑测表。仓内若还有用例设计 YAML（接口、dtype、range、standard），打开它写 golden / compare / `generate_inputs`，不要只认表头。
- **精度口径写脚本真实怎么跑**：argparse 的精度/性能 mode 分别写入 `modes.precision` / `modes.perf`；默认值若是性能 mode，不得把默认当精度。`--golden-only`（不调用 pta / 无需 NPU）是造数，不是精度。设计文件里若分开写了精度标准与性能标准，照抄事实，不要发明阈值。
- **`generate_inputs` 缺口要写全**：脚本现在造得出什么、造不出什么。至少核对这些轴（runner 吃不了的标缺口，不要假装已覆盖）：空 tensor、标量 tensor、inf / -inf / nan、上/下边界、末维对齐 vs +1、合法 range vs 非法 range。常规 dtype 覆盖和这些特殊值分开计，不要铺进每一组 shape。
- **参数有依赖禁止独立笛卡尔**：例如 reduce 轴必须落在 rank 内，shape 列与 `*TemplateNum` / `dim_*` 同理。依赖用 `control.recipe` 从可控列复算；生成器做不到 → `test_harness_gap`。
- **预期错误不是精度失败**：设计里带预期报错 / Disable 的行不上精度 oracle，也不要写成 Host HIT 失败。
- **`uo_digest` 由 promote 写入**：TG 不改 `.uo`。digest 变了必须重跑 `/tg-init`。
- **查语义优先 uo-query**：Grep 只作定位辅助。
- **主控裁判放行后才 plan/solve**：`confirmed` 由 `bind_promote` 写在 `init.yaml` 上。
