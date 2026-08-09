# extract

Clang frontend extraction of CompilerFacts (host / tiling key / registry / kernel).

Internal steps: `extract_host` → `extract_tiling_key` → `extract_registry` → `extract_kernel`.
No AscendC business interpretation beyond what existing extractors already emit.
