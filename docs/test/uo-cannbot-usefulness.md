# UO cannbot 有用性：改动对照

四种查询形态未改（无参数索引 / 标识符 / `Dim=` 或 `Name=Value` / `--file --line`）。配对、happens-before、sanitizer 仍不在 UO。

## 内存根因（卡死）

不是「并发 150 次 agent_query 把图复制 150 份」。实测 **164 次串行查询 RSS 24→31MB**。卡死来自两条叠加：

1. **Extract 并行 libclang。** Windows 默认 `kernel_ir.isolate process`（子进程再开一份 AST）同时 `host_ir.parallel_tus workers=min(n, cpu)`（FAG 4 个 Host TU 线程各持一份 TU）。再加 `host||kernel` 线程池，峰值是 **5 份 C++ AST**，若干 GB，机器换页卡死。
2. **查询每次新开 80MB `.uo`。** IFA 产物 79MB。cover 一次走 `read_meta` + `load_view_blob` + `_connect`，等于连开三遍文件；`legal_key` 还把整表展开成 Python dict。150 次查询 ≈ 反复映射整库。

修复（默认）：

- Host TU **串行**（`UO_HOST_IR_WORKERS` 默认 1）
- Kernel isolate **默认关**（`UO_KERNEL_IR_ISOLATE=process` 才开）
- host/kernel **不再重叠**（`UO_EXTRACT_OVERLAP=1` 才恢复旧并行）
- 进程内 **最多 1 个** 只读 sqlite 连接，`mmap_size=0`，`cache_size=2MB`
- legal-key / template_blocks 缓存 **1 个产物**；legal-key 只展开当前页

不要并行跑多个 `open_query` / 不要同时 extract 四个算子。

## 查询层

| 项 | 改前 | 改后 | 对照 |
| --- | --- | --- | --- |
| sqlite | 每次新连且曾不 close | 共享 1 连接，`q.close()` / `close_uo_connections` 释放 | improve |
| cover legal-key | 全表 expand 成 dict | 紧凑行 + 倒排，只 expand 当前页 | improve |
| index hint | 写死 `IsTnd=1` | 本图第一声明维 + 样例 | improve |
| `dim_names` | 可含 `"0"` | 仅 `source_declared` 且合法标识符 | improve |
| BOOL cover | `true` 对不上 `0/1` | 查询别名 `true/false`↔`0/1` | improve |
| `extras.readers` | 按名字；常空 | entity id；空则 READS 回填 | improve（GMM `groupNum` 2 条） |
| s1Inner readers | 空 | 仍空（图上无 READS） | keep |

## 提取层（已重建四算子 arch35 `.uo`）

| 项 | 改前查询 | 改后查询 | 对照 |
| --- | --- | --- | --- |
| GMM schema | `KERNEL_TYPE`/`QUANT_*_TRANS` 三元组；`Dim=TRANS_B` 空 | 11 维含 `TRANS_B`/`D_T_A`；`TRANS_B=1` 29 块 | improve |
| IFA BOOL | `Dim=HasAttenMask` = `0/false/true` 混用 | `0/1`；`HasAttenMask=true` 仍命中 122 | improve |
| FAG PIPE | `pipeBase`/`pipePost` **225** | **63 / 94 / 213** | improve |
| TPipe 同名指针 skip | 重建后 NSA/IFA launch 被 `TPipe*` 挤掉 | NSA `nsa_compress.cpp:30`；IFA `tPipe:44` + `tPipe1:59` | improve |
| IFA 第三阶段 :198 | 字面搜误中 `INVOKE_*` | 删除错误位点 | improve（不是回退） |

## FAG extract（`UO_KERNEL_MAX_VARIANTS=1`，冷 tu cache）

| | 秒 | 门禁 |
| --- | ---: | --- |
| `extract_host`（含 1 dtype kernel） | **23.9** | 目标 120 / 硬顶 150 |
| analyze+commit+verify（热 IR） | 46.8 | — |

FAG 闭包通常一套 ARGS_DECL，**没有**双跑 `clang -E`。libclang 与 exe 共存保留：默认已串行，墙钟仍远低于 10% 淘汰线。要旧并行：`UO_EXTRACT_OVERLAP=1` 且 `UO_HOST_IR_WORKERS=4`。

## 重建后必跑（已跑）

| 场景 | 查询 | 结果 |
| --- | --- | --- |
| FAG | `IsTnd=1` | 38 块 |
| FAG | `Dim=IsTnd` | `[0,1]` |
| IFA | `HasAttenMask=true` | 122 块 |
| GMM | `Dim=TRANS_B` | `[0,1]` |
| NSA 索引 | `dim_names` | 不含 `"0"` |
| FAG launch | phases | 63/94/213，不是 225 |
| `groupNum` | readers/READS | 2 |
| `s1Inner` | readers/READS | 仍 0 |
| index hint | 无参数 | 不是 `IsTnd=1` |

详细 164 次调用见 `docs/test/results/uo-cannbot/query_battery.json` 与 `docs/test/uo-query-quality.md`。

未改 skill 四种 argv。
