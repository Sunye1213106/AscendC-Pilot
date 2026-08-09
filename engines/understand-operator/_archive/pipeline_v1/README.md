# pipeline_v1

Modules that wrote layered YAML / projection artifacts before the single
`.uo` CodeMap product. Files are moved here only after their callers have been
rewired to `uo_init.ir` / `uo_init.store` / `uo_init.passes`.

Until a module is fully superseded it stays under `src/uo_init/` with a thin
adapter into CodeMap.
