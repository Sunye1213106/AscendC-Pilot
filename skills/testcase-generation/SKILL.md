---
name: testcase-generation
description: >
  AscendC 测试生成：一份 init.yaml 绑定脚本列与 CodeMap，一份 plan.md
  把意图融成可 root 到列的义务，solve 写出脚本可吃的 cases 表与 worklog.md。
  指标只有 Host replay（无 NPU）和 derived 公式。Replay reject ≠ E。
---

# Testcase Generation

正式产物只有三份（外加脚本可直接吃的 cases 表）：

| 阶段 | 产物 |
| --- | --- |
| init | `tg/init.yaml` |
| plan | `tg/plan.md`（上半散文，下半 YAML 义务表） |
| solve | `tg/worklog.md` + `tg/cases.csv` 或 `.xls` / `.xlsx` |

草稿只留 `runs/`。人确认走 `control/decisions/`。不要 inventory / audit / review / fingerprint / dimensions / confirmation 旁路 YAML。

## 门禁

- 无 `.uo` → `/uo-init`
- 无 `init.yaml` → `/tg-init`；plan **强制** init 产物
- 意图有则融合，不做文件强制
- 无批准的 `plan.md` → `/tg-plan`
- `harness_intent` 未落地 → **禁止 start solve**
- TG **永不改算子仓**；缺列或缺生成器走 CE apply **测试脚本仓**

## 控制面 = 列

义务必须 root 到 `init.yaml` 的 CSV/XLS 列。指标只有：

- **replay**：Host tiling（无 NPU）看 key / TD / OP_CHECK / 分支
- **derived**：这行输入 + 代码逻辑可推

没有第三类「上板误差/耗时」。覆盖梯子 L0–L3 写在义务 `cover` 上。全量 tilingkey 只在意图点名时做，**不是默认模式**。

## 核心循环

```text
init.yaml → plan.md（融合意图）→ 人批准
  → 构造 cases 表 → Host Replay → worklog 四段
  → open: [] 才签发
```

`Replay reject ≠ E`。查语义与 uo-query 同一套，禁止 Grep 算子仓。

## 按需参考

| 需要 | 读取 |
|---|---|
| 绑定列与跑测口径 | `capabilities/bind-init/METHOD.md` |
| 融合义务 | `capabilities/plan-fuse/METHOD.md` |
| 构造用例 | `capabilities/construct-cases/METHOD.md` |
| 写 worklog | `capabilities/analyze-round/METHOD.md` |
| 测试脚本仓 | `references/test-script-repo.md` |
| 规划启发式 | `references/plan-heuristics.md` |
| Host replay | `references/oracle.md` |
| 踩坑 | `references/gotchas.md` |
