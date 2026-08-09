# analyze

Run deterministic CodeMap passes: normalize variables, derive key fields, normalize predicates.

Internal steps: `normalize_variables` → `derive_key_fields` → `normalize_predicates`.
Pass graph target is the unified CodeMap IR (not durable YAML projections).
