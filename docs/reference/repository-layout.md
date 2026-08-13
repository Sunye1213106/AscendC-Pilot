# 仓库结构

用这一页判断改动应该放在哪里。

| 路径 | 归属 |
| --- | --- |
| `adapters/` | Host overlays。 |
| `agents/` | 稳定 Agent 与 deterministic-engine identities。 |
| `engines/` | UO、TG、CE 和 common 的确定性 packages。 |
| `evals/` | Eval cases、harnesses 与大型可复用 fixtures。 |
| `generated/` | 生成的 host runtime output。 |
| `opencode-plugin/` | OpenCode integration：authorize hooks + Session Driver（`ascendc-pilot.ts`、`pilot-driver.ts`）。 |
| `pilot/` | Runtime control plane（含 dispatch、authorize daemon、host_doctor）。 |
| `prompts/` | Task prompt assets。 |
| `schemas/` | Local extension 与 artifact schemas。 |
| `scripts/` | 生成、校验、replay 与 developer tools。 |
| `skills/` | Runtime skill bundles、references、examples、templates。 |
| `tests/` | 仓库级 tests 与 fixtures。 |
| `tools/` | Runtime capability 合同：`tools/source/`、`tools/codemap/`（各含 `METHOD.md` / `capability.yaml`）。 |
| `docs/` | 人类说明文档。 |

## 改什么去哪里

| 任务 | 起点 |
| --- | --- |
| 新增 workflow step | `pilot/ascendc_pilot/workflows/specs.py` |
| 修改权限 | `pilot/ascendc_pilot/ownership.py`, `agents/*.yaml` |
| 新增 agent | `agents/<id>.yaml`，然后重新生成 agent matrix |
| 新增领域方法文本 | `skills/<domain>/SKILL.md` 或 `skills/<domain>/references/` |
| 新增 task prompt | `prompts/tasks/<domain>/` |
| 修改 UO extraction | `engines/understand-operator/src/uo_init/` |
| 修改 TG closure | `engines/testcase-generation/testcase_agent/closure/` |
| 修改 CE impact | `engines/code-engineering/code_engineering/` |
| 修改 host install | `adapters/`, `opencode-plugin/`, `install.*` |
| 修改 Host Session Driver | `opencode-plugin/pilot-driver.ts`、`pilot/ascendc_pilot/actions/dispatch.py`、`drive.py` |
| 修改 runtime capability | `tools/source/`、`tools/codemap/` |
| 修改 authorize 热路径 | `pilot/ascendc_pilot/authorize/`、`opencode-plugin/ascendc-pilot.ts` |
| 新增人类文档 | `docs/` |

## 文档边界

不要再给 `pilot/`、`agents/`、`engines/`、`skills/`、`prompts/`、`tools/`、`adapters/`、`evals/` 等模块目录新增 developer-facing `README.md`。解释性内容放进 `docs/`，并链接实现锚点。
