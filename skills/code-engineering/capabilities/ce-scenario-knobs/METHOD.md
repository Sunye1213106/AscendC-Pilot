# CE Scenario Knobs Method

Fill knobs / budget / oracle notes on the engine-written `ce-scenario-set/v1`
skeleton. Do not invent scenario ids or rewrite the skeleton.

## Method

1. Read `ce/scenarios/scenario_set.yaml` (engine `scenario_infer` output).
2. Query CodeMap (`impact`, `kernel_api`, `buffer`, `field`) then open a
   minimal source window for each listed id.
3. Write a **staging overlay** only: `schema: ce-scenario-knobs/v1` plus
   `items[]` with `id`, `knobs`, `budget`, `oracle`, and `path:line` anchors.
4. Host `scenario_apply` merges the overlay into `scenario_set.yaml` before
   `scenario_confirm`. Unknown ids are dropped.

## Forbidden

- Adding ids that are not already in the skeleton / catalog.
- Closing precision or perf with review text.
- Expanding into all legal TilingKeys.
- Writing canonical `ce/scenarios/scenario_set.yaml` yourself.
