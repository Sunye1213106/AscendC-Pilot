# Testcase Generator

`testcase-generator` consumes the understand-operator knowledge base and generates tiling-key coverage plans, probe cases, coverage audits, and test artifacts. It is a **sibling plugin** to [`understand-operator`](../understand-operator/) — not a sub-command inside it.

**Default UI language: Chinese (zh-CN)** for progress blocks and review summaries. See `prompts/00_language.md`.

## Positioning

| Project | Responsibility |
|---|---|
| `understand-operator` | Understand AscendC operators; build KB (IO, tiling, kernel, dataflow, evidence) |
| `testcase-generator` | Read KB; generate coverage obligations, tilingkey candidates, probe cases, audits |
| `ascendc-st-design` | From aclnn docs → ST CSV (接口参数空间 L0/L1/L2) |

`testcase-generator` does **not** re-scan source code or re-analyze host tiling semantics.

与 ST 设计互补：ST 覆盖接口参数；TG 覆盖 tiling_key / family / tilingdata，并用 `observed_tiling_key` 做可验证审计。映射见 `testcase-generator-plugin/references/st-alignment.md`。

## Coverage Levels（对齐 ST，对象不同）

| Level | TG 含义 | 候选来源 |
|---|---|---|
| L0 | 门槛 | seed + family 代表 + 关键单字段 |
| L1 | 功能组合 | targeted obligations + **pairwise** |
| L2 | 异常/不可达 | unreachable + legal 负例（**不是** pairwise） |

默认：`--level L0,L1`。

## Input / Output Paths

**Input (read-only):**

```text
<repo>/.understand-operator/<op_name>/
  quality.yaml
  operator.yaml
  tiling/key_space.yaml
  tiling/families.yaml
  tiling/data_model.yaml
  tiling/coverage_model.yaml
  kernel/paths.yaml
```

If canonical tiling files are missing, stop and run `/uo-init` or `/uo-update` first.

**Output:**

```text
<repo>/.testcase-generator/<op_name>/
  kb_snapshot.yaml
  route.md
  plan/coverage_obligations.yaml
  generate/*
  probe/observed_keys.jsonl
  audit/coverage_audit.yaml
  report/final_report.md
```

## Full Workflow

```text
/uo-init or /uo-update   # prerequisite
/tg-init
/tg-plan                 # human review gate
/tg-generate
/tg-probe --mock         # or real probe when available
/tg-audit
/tg-report
/tg-repair               # optional stub
```

## PR Workflow

```text
/uo-update               # produces change_set + update_plan
/tg-pr                   # focused obligations (MVP stub)
/tg-generate /tg-probe /tg-audit
```

## Commands

| Command | Purpose |
|---|---|
| `/tg-init` | Validate UO KB; write `kb_snapshot.yaml` + `route.md` |
| `/tg-plan` | Expand coverage obligations; human review |
| `/tg-generate` | Factor/rule/L0·L1·L2 candidates/set-cover/realize |
| `/tg-probe` | Run tiling probe; output `observed_keys.jsonl` |
| `/tg-audit` | Coverage audit (observed_key only) |
| `/tg-repair` | Missing obligation repair (MVP stub) |
| `/tg-pr` | PR incremental tests (MVP stub) |

## Python vs LLM Boundary

**Python (deterministic):** YAML parse, obligation expansion, factor/rule compile, candidate generation, constraint pruning, set cover, probe case generation, tiling_key decode, coverage audit, percentages.

**LLM (explanation only):** plan summary, missing rule/realization suggestions, multi-round failure diagnosis, final report narrative.

**LLM must NOT:** compute coverage, substitute probe, treat expected_key as observed_key, modify audit results.

## Mock vs Real Probe

| Mode | `verified` | `coverage_verified` |
|---|---|---|
| `--mock` | `false` | `false` |
| Real `ExternalTilingProbe` | `true` | `true` |

Mock probe echoes `expected_key` as `observed_key` for development only. Never claim verified coverage under mock.

## Important Rules

1. **Family coverage != tiling_key coverage**
2. **expected_key is a target; observed_key is evidence**
3. Do not read legacy branch_matrix as full tilingkey enumeration
4. **L2 ≠ pairwise**（pairwise 属于 L1）
5. 先 family-local 再 targeted/pairwise，禁止全输入笛卡尔积

## References

- `references/st-alignment.md` — 与 ascendc-st-design 映射
- `references/coverage-levels.md` — L0/L1/L2 细则
- `references/factor-extraction.md` — 因子提取
- `references/constraint-types.md` — 约束类型

## Quick Start — Cursor

```powershell
cd testcase-generator
pip install -e .
./install.ps1 cursor
```

In Agent mode:

```text
/tg-init D:\path\to\operator --op-name flash_attention_score_grad
/tg-plan D:\path\to\operator --op-name flash_attention_score_grad
/tg-generate D:\path\to\operator --op-name flash_attention_score_grad --level L0,L1
/tg-probe D:\path\to\operator --op-name flash_attention_score_grad --mock
/tg-audit D:\path\to\operator --op-name flash_attention_score_grad
/tg-report D:\path\to\operator --op-name flash_attention_score_grad
```

## CLI (manual)

```bash
tg-init --project-root <repo> --op-name <op>
tg-plan --project-root <repo> --op-name <op>
tg-generate --project-root <repo> --op-name <op> --level L0,L1
tg-probe --project-root <repo> --op-name <op> --mock
tg-audit --project-root <repo> --op-name <op>
tg-repair --project-root <repo> --op-name <op> --max-rounds 3
tg-pr --project-root <repo> --op-name <op>
tg-report --project-root <repo> --op-name <op>
```
