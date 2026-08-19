---
name: testcase-generation
description: >
  AscendC 测试生成：`tg/init.yaml` 绑定脚本输入变量与算子变量并写 golden/精度/性能口径；
  `tg/plan.md` 将测试意图落到有限覆盖子集；solve 定向构造、Host 回放、引理闭合后写出 cases。
---

# Testcase Generation

正式产物只有三份（外加脚本可直接吃的 cases 表）：

| 阶段 | 产物 |
| --- | --- |
| init | `tg/init.yaml` |
| plan | `tg/plan.md`（上半散文，下半 YAML 义务表） |
| solve | `tg/worklog.md` + `tg/cases.csv` 或 `.xls` / `.xlsx` |

草稿只留 `runs/`。不要 inventory / audit / review / fingerprint / dimensions / confirmation 旁路 YAML。

## `/tg-init`：测试前置

输入：已有 `.uo`，测试脚本仓**可选**。只建立 harness contract，不是 cases。

- **有脚本仓**（`kind=script_repo`）：扫描脚本 / CSV / XLS，把脚本输入变量（表列、生成器、代码里的读点如 `get_case` / `CaseConfig.xxx`）绑定到算子仓 / UO 标识符。写 `modes`、值域、`golden` 对照、精度口径、性能入口、`generate_inputs`。mapping 空则本步失败。
- **无脚本仓**：不要假装已有仓。用 `pilot_cli` `uo-query` 读算子输入 API（Host 入参 / dtype / shape），按 API 设计控制面，`kind=default_input`。缺生成器另走 CE。
- 有没有测试脚本、路径是什么：派发前由主控问清，写进 stub。本步 producer 查图只用 `pilot_cli`，禁止再派 Task。

## `/tg-plan`：有限覆盖计划

核心输入必须是 **`tg/init.yaml` + Planning Context**。把测试意图融成有限覆盖子集：

- 变量可以是 CSV/XLS 列，也可以是 `init.yaml` 已声明、能从脚本或代码控制的变量；
- 写清精度要求与（仅当 harness 真支持时的）性能要求；
- 缺脚本 / 缺列 / 生成器造不出（含随机数）→ `test_harness_gap`，写出说明书交 `/ce-apply` 生成或修改测试脚本，不要在 TG 里改算子仓。未落地禁止批准规划、禁止 `/tg-solve`。

Planning Context 来自 `/ce-review` 结论、`/ce-plan`「测试内容」、用户显式范围、handoff、或用户已选定只要用例时主控综合的 `/uo-query` 结论。TG 不审查 diff，也不重新解释原始 NL。没有 Planning Context 就不要 plan。本 skill 不编排是否先审查。

## `/tg-solve`

只消费已验证 plan + init：按义务定向构造 cases、Host 动态回放、引理闭合 worklog。`test_harness_gap` 未落地时禁止 solve。

`.uo` 是 TG 的语义事实权威：plan/solve 需要语义时统一用 `uo-query`，但它不替代 Planning Context。

## 核心循环

```text
Planning Context + init.yaml
        ↓
      plan.md
        ↓
construct cases → Host Replay → worklog
        ↓
     open: []
```

Primary 负责自然语言和跨 workflow Todo；本 skill 只定义 TG 领域方法，不承担编排路由。TG 内部 `bind_init` / `plan_fuse` / `construct_cases` 等名称都是 Action，不是用户 skill 或 slash。

## 按需参考

| 需要 | 读取 |
|---|---|
| 绑定测试 harness | `capabilities/bind-init/METHOD.md` |
| 融合义务 | `capabilities/plan-fuse/METHOD.md` |
| 构造用例 | `capabilities/construct-cases/METHOD.md` |
| 写 worklog | `capabilities/analyze-round/METHOD.md` |
| 测试脚本仓 | `references/test-script-repo.md` |
| Planning Context | `references/planning-context.md` |
| 规划启发式 | `references/plan-heuristics.md` |
| Host replay | `references/oracle.md` |
| 踩坑 | `references/gotchas.md` |
