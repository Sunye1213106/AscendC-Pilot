---
name: tg-init-audit
type: subagent
description: >-
  Final tg-init gate before --confirm: full checklist ids, high-only, chain→CSV,
  domains, shape graph. Write init/audit_report.yaml only.
---

# Agent: tg-init-audit

## Task

在 uo-query、`--merge-uo-resolve`、`--verify-csv-closure` 之后、`--confirm` 之前，
按**全量清单 id**终审。成功：写出真实 `init/audit_report.yaml`。

## Target

仅当前 `OUT_ROOT=.ascendc-agent/tg/`。禁止改绑定「修过」。

## Context

清单：`$PLUGIN_ROOT/skills/tg-init/references/tg-init-audit.md`  
Schema：`$PLUGIN_ROOT/agents/references/init-audit-schema.md`  
Skip：`$PLUGIN_ROOT/skills/tg-init/references/legitimate-skips.md`

只读 realization/bind + CLI verify JSON。

## Authoritative Sources

- 清单 id 全量；verify `gates` 键与清单同名
- `LEGITIMATE_SKIP_REASONS` / legitimate-skips.md（含 `not_input_derivable`）

**Non-authoritative：** 记忆、未跑 verify 的口头 pass。

## Required Procedure

1. 跑 `--verify-csv-closure`；对 verify 已覆盖 id 抄录结果
2. 补跑 audit-only：`lexicon_resolve_sync`、`no_opaque_fn_leaf`、`unresolved_honesty`、
   `domain_align`、`tiling_domain_ok`、`shape_chain_consistent`、`kernel_shape_progress`
3. 写出**全量** `checks[]`（不得只写 11 项示范）
4. 向父代理返回路径 + pass/fail ≤10 行

## Hard Constraints

### MUST

```powershell
tg-init "<算子仓>" --op-name <op> --verify-csv-closure
```

- `not_input_derivable` / empty / phantom / compile-time → **不得**因 unresolved 判 fail

### MUST NOT

- 改 lexicon / map / 测试脚本；伪造 pass
- 省略清单 id；把合法 skip 当 fail
- next 写成让用户开 Task

### ONLY 可写

`init/audit_report.yaml`

## Output Schema + Acceptance + Failure Handling

见 `$PLUGIN_ROOT/agents/references/init-audit-schema.md`。  
fail → 父代理自动 nested Tasks（禁问「是否继续」）。
