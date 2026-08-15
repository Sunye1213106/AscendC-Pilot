# Eval baseline — uo-query Explore（multi family）

Non-normative checklist for regression gates. Metrics target claim-driven bounded exploration **and sibling completeness**.

## Query families

| family | example focus |
| --- | --- |
| symbol | name / kind locate |
| call_chain | CALLS path |
| tiling_key | dim domain / packing / SplitAxis-style |
| tiling_data | field writers/readers |
| kernel | branch / root |
| template | TEMPLATE / MACRO |
| buffer | BUFFER / storage class |
| cross_layer | Host→Key→Kernel hop |
| unresolved | gaps / NOT_FOUND_IN_SCOPE |
| source_detail | only when span missing |
| sel_coverage | 某维有没有编 / 561003：必须有 `dim_coverage` 或 `legal_key.total_matched` |

## Hard metrics（observe wall-clock only）

| metric | gate |
| --- | ---: |
| median tools | ≤ 8 |
| p95 tools | ≤ 12 |
| same-window duplicate Read | 0 |
| duplicate semantic query | 0 |
| repo_grep_escape (仓级 findstr/grep/rg) | 0 |
| decisive citation present when ANSWERED | 100% |
| PARTIAL then continue explore loop | 0 |

Source Read across **different** windows (next SEL block / override / next TPipe) is allowed. Same-span re-Read is not. Extra `template_match` / `legal_key` hops are not penalized.

Operators: ≥ 2 real ops when available (e.g. add_example + FAG).
