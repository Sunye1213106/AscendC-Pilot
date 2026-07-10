---
name: testcase-generator
description: >-
  Shared scripts and paths for testcase-generator plugin commands.
  Internal skill — use /tg-init /tg-plan /tg-generate /tg-probe /tg-audit directly.
disable-model-invocation: true
---

# testcase-generator — 共享脚本

本 skill 提供 CLI 脚本入口，供 `/tg-*` 命令调用。

## 脚本位置

安装后 junction 到 `~/.cursor/skills/testcase-generator/`。

源码树：

```text
testcase-generator-plugin/testcase_generator/scripts/tg_*.py
```

## 命令映射

| Skill | Script |
|---|---|
| tg-init | tg_init.py |
| tg-plan | tg_plan.py |
| tg-generate | tg_generate.py |
| tg-probe | tg_probe.py |
| tg-audit | tg_audit.py |
| tg-repair | tg_repair.py |
| tg-pr | tg_pr.py |
| (report) | tg_report.py |

## PATHS

见同目录 `PATHS.md`。
