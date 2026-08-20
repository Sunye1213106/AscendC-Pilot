---
name: testcase-generation
description: >
  AscendC 测试生成：`tg/init.yaml` 绑定脚本输入变量与算子变量并写 golden/精度/性能口径；
  `tg/plan.md` 将测试意图落到有限覆盖子集；solve 定向构造、Host 回放、引理闭合后写出 cases。
---

# 测试用例生成

薄入口：按当前 slash / 角色读一份。不要一次装完。子代禁止再用 skill 工具；方法已在 session `method.md` / `refs/`。

```text
/tg-init 扫描     → 引擎 repo_scan（主控不读 METHOD）
/tg-init 绑定     → 子代已注入 bind-harness 或 bind-columns
                    + test-script-repo.md、construction-gotchas.md
                    主控不要读切片 METHOD，也不要读父索引 bind-init
/tg-init 裁判     → 主控只读 session method.md（bind-review）
/tg-plan          → 子代已注入 plan-fuse + planning.md、plan-heuristics.md、
                    planning-gotchas.md、planning-context.md
                    缺 Planning Context 则停
/tg-solve         → 子代已注入 construct-cases / analyze-round
                    + construction-contract.md、closure-gotchas.md、oracle.md
查图              → 无参数索引 → 标识符 / Dim= → 窗口 Read；禁止 --mode
```

正式产物只有三份（外加脚本可直接吃的 cases 表）：

| 阶段 | 产物 |
| --- | --- |
| init | `tg/init.yaml` |
| plan | `tg/plan.md`（上半散文，下半 YAML 义务表） |
| solve | `tg/worklog.md` + `tg/cases.csv` 或 `.xls` / `.xlsx` |

草稿只留 `runs/`。不要 inventory / audit / review / fingerprint / dimensions / confirmation 旁路 YAML。

## `/tg-init`：测试前置

输入：已有 `.uo`，测试脚本仓**可选**。只建立 harness contract，不是 cases。

引擎 `repo_scan` 后两路草稿（`parts/harness.yaml` 与 `parts/bind.yaml`），主控通读裁判，放行后 `bind_promote` 落盘。无仓也两路都跑（`kind=default_input`）。有脚本仓时 mapping 空则失败。仓内 `tests/` 未确认、意图未给出仓外路径，都不得当 harness。只绑定测试仓与算子，不要把列标成 PR 焦点。

## `/tg-plan`：有限覆盖计划

核心输入必须是 **`tg/init.yaml` + Planning Context**。把测试意图融成有限覆盖子集：

- 变量可以是 CSV/XLS 列，也可以是 `init.yaml` 已声明、能从脚本或代码控制的变量；
- 写清精度要求与（仅当 harness 真支持时的）性能要求；
- 缺脚本 / 缺列 / 生成器造不出（含随机数）→ `test_harness_gap`，写出说明书交 `/ce-apply` 生成或修改测试脚本，不要在 TG 里改算子仓。未落地禁止批准规划、禁止 `/tg-solve`。

Planning Context 来源见 CONTEXT 词表。没有 Planning Context 就不要 plan。

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

切片 METHOD 与阶段 refs 已按上表注入，不要再装载。仅当注入未覆盖时读：

| 需要 | 读取 |
|---|---|
| shape 列 vs TemplateNum | `examples/add_example_tilingkey/README.md` |
| Host 空 tensor 守卫 | `examples/fa_empty_tensor_host_guard/README.md` |
| 人读踩坑索引 | `references/gotchas.md`（session 不物化此索引） |
