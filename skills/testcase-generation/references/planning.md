# 覆盖义务

**何时加载**：`plan-fuse` 写出 `plan.md` YAML 义务表时。

## 要点

1. 控制面是 `init.yaml` 的列，不是计划目录 `tg/plan/levels/`。
2. 覆盖梯子 L0–L3 写在每条义务的 `cover` 上，不是平行 workflow overlay。
3. 意图有则融合；没有意图默认 L0，仍要有能 root 的精度/性能义务。
4. 未批准 `plan.md` 时不得宣称 solve 完成。
5. 全量 tilingkey 只在意图点名时做。禁止默认 T=D / `tilingkey_full_coverage` 模式。
6. CE 的 `tg_plan_intent` 有则消费，不做文件强制，也不要静默扩成全部合法 Key。

