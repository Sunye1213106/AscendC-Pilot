# Eval baseline — uo-query Explore（multi family）

Non-normative checklist for regression gates. Metrics target claim-driven bounded exploration.

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

## Hard metrics（observe wall-clock only）

| metric | gate |
| --- | ---: |
| median tools | ≤ 6 |
| p95 tools | ≤ 10 |
| source Read median | ≤ 1 |
| duplicate semantic / same-span Read | 0 |
| decisive citation present when ANSWERED | 100% |
| PARTIAL then continue explore loop | 0 |

Operators: ≥ 2 real ops when available (e.g. add_example + FAG).
