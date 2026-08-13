# UO 抽检记录

本目录保存 uo-init 在 `TEST/ops-transformer` 上的泛化抽检，**不是当前产品质量入口**，也不是架构权威。当前 FAG 冷启动与查询口径见 [benchmark.md](../benchmark.md)。实现与 benchmark 冲突时，以代码和 benchmark 为准。

- [家族泛化：现在过了什么、还差什么](uo-init-generalization.md) — 只有 FAG verify pass；其余卡在 kernel 解析 / CANN 缺头 / 无 TPL 时 verify 三件套不齐
- 精简表：[results/summary.json](results/summary.json)
- 机器可读：`artifacts/uo-init-generalization/pass7-accept/`（对照 pass5 `pass5-families-30/`、pass6 子集 `pass6-prepare-fix/`）
