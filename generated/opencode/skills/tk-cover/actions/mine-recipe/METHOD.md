# mine-recipe

Read `uo/tk/derive_fields.yaml`, `uo/ir/host_codemap.yaml`, and the
current gap clusters. Propose Case mutations that witness open keys or
justify sound exclusion.

Write only `parts/part_{shard}.yaml`:

```yaml
recipes:
  - dim: IsPse
    want: "1"
    rationale: optional_presence pse_shift
    case_patch: {pse: true, pse_shape: bnss}
```

Do not edit `uo/tk/recipe.yaml` — `apply_recipe` merges after contract checks.
