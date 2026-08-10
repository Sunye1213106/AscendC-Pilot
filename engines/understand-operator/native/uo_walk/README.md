# uo_walk (optional)

Native libclang walker for faster uo-init cold start. When built, Python
`walk_file` invokes it automatically unless `UO_NATIVE_WALK=0`.

## Build

```bash
mkdir -p engines/understand-operator/native/uo_walk/build
cmake -S engines/understand-operator/native/uo_walk -B engines/understand-operator/native/uo_walk/build
cmake --build engines/understand-operator/native/uo_walk/build
```

Requires libclang (LLVM/Clang SDK). Set `LLVM_DIR` or `CLANG_DIR` if CMake
cannot find headers/libraries.

## CLI

```
uo_walk --file PATH --side host|kernel --args ARGFILE --out OUT.json [--needle N] [--op-root R]
```

`ARGFILE` lists one compile argument per line (same as Python `BuildContext` args).

## Knobs

| Env | Default | Effect |
|-----|---------|--------|
| `UO_NATIVE_WALK` | `1` | Use native walker when binary exists |
| `UO_WALK_BIN` | — | Override path to executable |

On failure, Python falls back to the in-process libclang walker.
