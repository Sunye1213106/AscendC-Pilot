# 01c — Code Review Orchestrator

编排 `/uo-code-review`。默认 `mode=both`。

## Graph roles（写死）

| Path | Primary | Supplement |
|------|---------|------------|
| bug | CBM | kb_graph |
| functional / semantic | kb_graph | CBM |

CBM = 源码结构图 + 证据；kb_graph = 算子语义。不使用 code-review-graph。

## Steps

1. Resolve `PROJECT_ROOT` / `OP_NAME` / `UO_ROOT`.
2. Run `prepare_review_context.py`. If not ready → stop with hints (`export_kb_graph.py`, `/uo-init` CBM index via `docs/cbm-mcp-setup.md`).
3. If mode in {both, bug}: execute `prompts/review/bug_review.md` → write `review/bug_report.*`.
4. If mode in {both, functional}: execute `prompts/review/functional_review.md` → write `review/functional_report.*`.
5. Write `review/index.yaml` + `review/summary.md`.
6. Never write `diff/**`. Owner is `uo-code-review` in `spec/ownership.yaml`.
7. Read gate: human_overview / kb_graph → Grep hot cards → small-window Read → CBM.
   Never dump `ir/operator_graph.yaml`, full `contracts/testcase.yaml`, or `cross_layer/impact_graph.yaml`.

## Parallelism

Bug and functional paths may run as parallel subagents after context_pack is ready, then merge.

## Language

Follow `00_language.md` (Chinese default for user-facing reports).
