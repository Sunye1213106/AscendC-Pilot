# UO 抽检记录

本目录保存 uo-init 在 `TEST/ops-transformer` 上的泛化抽检，**不是当前产品质量入口**，也不是架构权威。当前 FAG 冷启动与查询口径见 [benchmark.md](../benchmark.md)。实现与 benchmark 冲突时，以代码和 benchmark 为准。

- [什么是高质量信息库](high-quality-codemap.md) — 结合 cannbot 定位面与 2026-08-14 FAG/IFA 提取：ready 门槛、加分项、未闭合怎么读
- [瘦身 UO：8 算子基准与实验](slim-8ops.md) — wipe 前数字 + 冷启动对照
- [家族泛化：现在过了什么、还差什么](uo-init-generalization.md) — 只有 FAG verify pass；其余卡在 kernel 解析 / CANN 缺头 / 无 TPL 时 verify 三件套不齐
- [家族泛化：现在过了什么、还差什么](uo-init-generalization.md) — 只有 FAG verify pass；其余卡在 kernel 解析 / CANN 缺头 / 无 TPL 时 verify 三件套不齐
- 精简表：[results/summary.json](results/summary.json)
- 机器可读：`artifacts/uo-init-generalization/pass7-accept/`（对照 pass5 `pass5-families-30/`、pass6 子集 `pass6-prepare-fix/`）
