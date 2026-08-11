# tools

Tool usage contracts (source / CodeMap access). Spec references these by capability id.

```text
tools/
  source/     # source-reading, source-navigation, readonly-source-search
  codemap/    # kb-query, structured-ir-query
```

Harness batch/shard/scratch live under `pilot/runtime/`; verifiers under `pilot/gates/`.
