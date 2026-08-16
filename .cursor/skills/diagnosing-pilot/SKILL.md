---
name: diagnosing-pilot
description: >
  Diagnose hard bugs in AscendC-Pilot engines and harness: uo_init, Clang probe,
  include heal, quality.yaml grade regression, digest mismatch, gate/lease,
  pytest failures, performance of CodeMap build. Use when something is broken,
  throwing, failing, or slow in this repo.
---

# Diagnosing Pilot

本仓引擎 / harness 的诊断环。不要用它替代 TG 的 `T=(R∩T)∪E`，也不要在算子仓里当通用 debugger。

先读 `agents/CONTEXT.md` 和出事模块附近的 ADR / `docs/`。

## Phase 1 — 先做一条会变红的环

完成条件：已经跑过**一条命令**，它在「这个 bug」上失败，输出已贴出（密钥写成 `<REDACTED>`）。没有这条环就不要猜根因。

按这个顺序找环：

1. 失败的 `pytest`（把 path 收到最小文件）。
2. `python scripts/dev/check_install.py` / `acp doctor`。
3. 单算子 fixture：`acp uo-query --project <abs> --mode` 或最小 `uo-init`（用户已给 project 时）。
4. `quality.yaml` 的 `grade` / `locate_blocking` 与上一份产物 diff。
5. Clang 探针 / include-heal 日志（`codemap-build-gotchas.md`），不要手改 `-I` 或开测试开关绕过。
6. digest：`canonical_graph_digest` vs 当前 `.uo`；`UO_DIGEST_CHANGED` 是事实，不是「再查一遍就好」。
7. 差分：旧 commit vs 新 commit 同一条 CLI。
8. 仍不能复现：停下来列出试过的命令，向用户要日志 / 探针缓存 / 算子路径。

把环收紧：更快、断言打在症状上、钉死时间/路径/arch。30 秒且 flaky 的环几乎等于没有。

## Phase 2 — 最小化

同一条红环，削输入和代码范围，直到再删就绿。保留 arch、operator、那一个 mode / gate。

## Phase 3 — 假设 → 插桩 → 修

一次一个假设。用环判定，不用「看起来像」。修好后：

- 把那条环留成回归测试（引擎缝：CLI / gate / schema / quality.yaml）。
- 认知行为回归走 `evals/skills/` dry，不把 TG 搜索失败写成 E。

Hard guardrail：`Replay reject ≠ 不可达`；探针失败走 `acp doctor`，不改假编译环境。
