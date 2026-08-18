# Golden E2E：PR → 定向 cases（手工清单）

真仓路径，**不进默认 pytest**。CI 用最小 git fixture + 假 PR URL 覆盖 Intent≠SourceRef、auto 规划、Todo 投影、scope receipt、不弹 TG 两问。本页只记录 fresh OpenCode 上的手工验收。

## 前置

- 已安装 OpenCode 插件，Tab 为 `AscendC-Pilot`
- 可访问 allowlisted PR host（GitHub / GitCode），必要时配置 `GITHUB_TOKEN` / `GITCODE_TOKEN`
- 不必事先 clone 目标算子仓

## 自然语言路径（必须）

在对话里只贴：

```text
帮我给这个 PR 生成针对 case
https://github.com/<org>/<repo>/pull/<id>
```

验收：

1. Primary **只**调用 `pilot_run(workflow=auto, intent=原文)`，不猜 `/ce-review`，不手串 `/uo-init → /tg-*`
2. 系统 clone/fetch/worktree，不要求用户先打开算子目录
3. 识别 operator / architecture；无 CodeMap 时自动 `uo-init` / `uo-update`
4. 分析 PR（ChangeSet + CodeMap → obligations），**不是** `ce-review` 的 code_review 输出
5. 用户可见 Todo 来自 Goal `public_plan`（获取 PR 与代码 → 建立算子理解 → 分析改动影响 → 确定测试范围 → 生成测试用例 → 回放验证 → 输出结果），不见「确认进入规划」「批准规划」
6. **单算子、单架构、workspace 成功时只出现一次** `test_scope` 选择（PR 定向 / 邻域回归 / 当前算子全覆盖）。多算子 / 架构歧义 / 凭证失败 / 用户改目标问人不是 UX 失败
7. 生成 cases + replay / rework；`host_step.done` 以 Goal acceptance（ledger 闭合 + replay receipt PASS）为准，workflow 跑完不等于 Goal 完成
8. 交付 cases 表 + 覆盖说明

## 专家路径（必须仍可用）

同一套系统上单独执行，一次只跑该工作流，不擅自串联：

```text
/uo-init
/tg-plan
/ce-review
```

`/tg-init` / `/tg-plan` 不再弹「确认进入规划」「批准规划」。

## 打断

生成过程中说「不要 fp32」：应更新 Goal constraints、使未生成的 fp32 obligation 失效，并在同一 `pilot_run` session resume，而不是另开协议。
