# UO cold-start baseline (pre-speedup)

Source: `rebuild_uo_construct.log` (FAG arch35, `UO_INIT_PROFILE=fast`, cold TU cache).

| Phase | Wall (s) | Notes |
|---|---:|---|
| discover | 0.063 | |
| BuildContext.load | 0.047 | |
| host\|\|kernel | **286.793** | 4 host TUs + 1 kernel; ThreadPool GIL contention |
| var_model+platform | 23.683 | repeated source reads |
| api\|\|bind | 0.033 | API clang skipped in fast |
| controllability | 1.253 | keypath 96 nodes |
| **extract_host_bundle** | **311.9** | |

Per-TU walk (shows fake parallelism):

| File | total | parse | frame | index | ast_walk |
|---|---:|---:|---:|---:|---:|
| tiling.cpp (alone) | 54.2 | 7.2 | 0.6 | 1.0 | 45.2 |
| varlen_regbase | 178.6 | 9.2 | 55.9 | 73.9 | 39.6 |
| normal_regbase | 263.8 | 9.1 | 69.2 | 104.4 | 80.6 |
| common_regbase | 273.7 | 9.3 | 71.9 | 117.9 | 74.0 |
| apt.cpp (kernel) | 286.7 | 30.4 | **217.0** | 12.6 | 8.0 |

Target: full uo-init pipeline **< 180s** cold.
