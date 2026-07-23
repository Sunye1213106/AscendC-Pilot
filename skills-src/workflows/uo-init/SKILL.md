---
name: uo-init
description: >-
  首次建立 UO KB。 Harness 管阶段；本 Skill 只索引 Action。
---

# uo-init

首次建立 UO KB。

## 硬规则（读完再动手）

0. **必须先 Tab 切到 `ascendc-agent`（primary）再跑本 Skill**。默认 Build/其它 agent 没有 harness 权限围栏，会把流程当成“读 METHOD 手干”。
1. **`harness` 是真实 CLI**（本机已安装），不是概念步骤，**禁止**“按 METHOD 手工模拟工作流”。
2. **禁止跳步**：必须先 `harness start` → `harness next` → 当前 `action_id`；不得一上来做 scope 或读源码建 KB。
3. **确定性 Action**（如 `prepare_layout`）：只跑 `harness run-action <id>`，会自动 finalize。
4. **语义 Action**：`run-action` 准备 → 按 Bundle 派发 actor → `--finalize`。
5. **禁止**用 Glob/Read 自编「文件计数表」代替 `harness uo-scope scan`；`common/` 由扫描脚本向上发现，手数必漏。
6. **已废弃**：旧 skill `understand-operator` / `uo-diff`（无 harness）；若仍出现在技能列表，删掉对应 junction 后重装。

## 执行循环

1. `harness start uo-init --project <算子目录>`
2. `harness next --project <算子目录>`
3. `harness run-action <action_id> --project <算子目录>`
4. 语义 Action 产出后：`harness run-action <action_id> --finalize`
5. `harness advance <next_phase>`（仅有可信收据时）

用户说「只分析 arch35」时：在 `scope_confirmation` 用  
`harness uo-scope scan --architecture arch35`（不要自己筛目录）。

## Actions

| action_id | 名称 | method | agent |
|---|---|---|---|
| `prepare_layout` | 创建知识库目录 | `uo-init/prepare-layout` | `deterministic-uo-engine` |
| `scope_confirmation` | 确认分析范围 | `uo-init/scope-confirmation` | `ascendc-agent` |
| `extract_plan` | 抽取计划与分层 IR | `uo-init/extract-plan` | `uo-semantic-resolve` |
| `key_triage` | KEY 粗分 | `uo-init/key-triage` | `uo-key-resolve` |
| `key_resolution` | KEY 语义闭合 | `uo-init/key-resolution` | `uo-key-resolve` |
| `confidence_report` | 生成置信度报告 | `uo-init/confidence-report` | `deterministic-uo-engine` |
| `confidence_review` | 置信度原因审查 | `uo-init/confidence-review` | `uo-confidence-review` |
| `export_integrity` | 导出与完整性校验 | `uo-init/export-integrity` | `deterministic-uo-engine` |
| `kb_review` | KB 产物审查 | `uo-init/kb-review` | `uo-kb-review` |
