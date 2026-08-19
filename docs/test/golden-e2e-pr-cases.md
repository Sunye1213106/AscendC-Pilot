# Golden E2E：PR → 定向 cases（手工清单）

真仓路径，**不进默认 pytest**。CI 用最小 git fixture + 假 PR URL 覆盖 SourceRef、Todo 投影、不弹 TG 两问。本页只记录 fresh OpenCode 上的手工验收。

## 前置

- 已安装 OpenCode 插件，Tab 为 `AscendC-Pilot`
- 可访问 allowlisted PR host（GitHub / GitCode），必要时配置 `GITHUB_TOKEN` / `GITCODE_TOKEN`
- 不必事先 clone 目标算子仓

## 自然语言路径（必须）

在对话里只贴：

```text
分析这个 PR 并生成对应测试用例
https://github.com/<org>/<repo>/pull/<id>
```

验收：

1. Primary 第一次 `pilot_run(workflow=auto, intent=原文含 URL)`。不要用 OpenCode 原生 `skill` 加载编排。交付链是 `/uo-init` → `/ce-review` → `/tg-init` → `/tg-plan` → `/tg-solve`。
2. 系统在 OpenCode 打开目录下 **新建文件夹** clone exact-head，不要求用户先打开算子目录，也不分析本地 fork。空打开目录不落 `.ascendc-pilot`；控制面写在 clone 内 pin 到的算子包（含 `op_host/` / `op_kernel/`）
3. 从 changed-files 识别 operator / architecture（1×1 自动 pin；多算子多架构按对执行）
4. 变更影响用 `/uo-query`（可带 diff）问 CodeMap，**不是**独立 `goal-impact`
5. 语义只走 `/uo-query`，禁止 Grep 算子仓
6. `/ce-apply` 产出的 diff 走 `/uo-update`
7. 生成 cases + replay / rework；`host_step.done` 后跟随 `next_workflow_id`
8. 交付 cases 表 + 覆盖说明

贴 PR URL 且要生成针对性 case 时，CE review 属于依赖链，用来确定 changed/affected scope。不要扫本地 FAG 再发明 arch 选项。

## 专家路径（必须仍可用）

同一套系统上单独执行，一次只跑该工作流，不擅自串联：

```text
/uo-init
/tg-plan
/ce-review
```

`/tg-init` 先问有没有测试脚本仓。`/tg-init` / `/tg-plan` 不再弹「确认进入规划」「批准规划」。

## 打断

生成过程中说「不要 fp32」：应更新 Goal constraints、使未生成的 fp32 obligation 失效，并在同一 `pilot_run` session resume，而不是另开协议。
