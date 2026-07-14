# uo-query Question Taxonomy

All question types follow the same read-only ladder:

```text
terminology/symbol index -> derived graph -> raw graph -> YAML facts -> source anchors
```

## Types

| Type | Primary evidence |
|---|---|
| boundary | `facts/operator/**` through graph refs |
| host | `facts/host/**` through graph refs |
| compute | `facts/compute/**` through graph refs |
| kernel_overview | `facts/kernel/overview/**` through graph refs |
| kernel_slice | `facts/kernel/slices/**` through graph refs |
| lineage | `graphs/raw/paths.yaml` and fact relations |
| source_evidence | source anchors embedded in YAML facts |
| unresolved | `unresolved` sections in YAML facts and review reports |

If the requested entity is absent from derived and raw graph indexes, answer
that the KB lacks the fact and list the closest terminology matches.
