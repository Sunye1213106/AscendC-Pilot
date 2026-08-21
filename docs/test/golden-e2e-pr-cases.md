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

1. Primary 先 `todowrite`（获取代码 / uo-init / tg-init / uo-query / tg-plan / tg-solve；磁盘已有产物则跳过）。fresh clone 后对当前源码 `/uo-init` 即可，不要再串 `/uo-update`；图过期或 `/ce-apply` 之后才 `/uo-update`。不要默认塞 `ce-review`。不要用 OpenCode 原生 `skill` 加载编排。获取代码格：`pilot_run(workflow=auto, intent=用户目标含 PR URL)`，不要跳过 Todo。
2. 「获取代码」格：系统在 OpenCode 打开目录下 **新建文件夹** clone exact-head。空打开目录不落 `.ascendc-pilot`。clone 仍是 Engine，不要让主控 `git clone` 建 PR worktree。
3. clone 后使用 Engine 回执中的 changed-files：路径令牌唯一则直接使用该 `(算子, architecture)`；多个 AskQuestion 原样选项。禁止在没有证据时默认 arch35。不要为理解语义通读全量 git diff。
4. 变更影响用 `/uo-query`（可带 diff）问 CodeMap，**不是**独立 `goal-impact`。缺 `tg/init.yaml` 且要生成用例时先 `/tg-init`，query stub 带上 init 的 harness/列/值域
5. 语义优先 `/uo-query`；Grep/Glob 可作定位辅助。需主控派 Task 的格（`/tg-init` / `/uo-query` / `/ce-review`）串行
6. `/ce-apply` 产出的 diff 走 `/uo-update`
7. `/tg-init` 缺测试脚本仓会问人。`host_step.done` 后勾掉当前格再 `pilot_run` 下一格
8. 交付 cases 表 + 覆盖说明

贴 PR URL 且最终产物是针对性 case 时，不要把 CE review 推理成依赖。Planning Context 走 `/uo-query`。不要扫本地 FAG 再发明 arch 选项。这是一条手工验收输入，不是黄金链。

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
