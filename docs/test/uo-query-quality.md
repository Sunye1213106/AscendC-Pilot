# UO query 质量 / 速度 / 体积（cannbot 四种形态）

对齐 `skills/uo-query/SKILL.md`：无参数索引、标识符、`Dim=` / `Name=Value`、`--file --line`（只从上一张卡复制）。同一机器、串行、一次只开一个算子。

源：

- 基线（未覆盖）：`docs/test/results/uo-cannbot/query_battery.json`（另存 `query_battery.baseline.json`）
- 契约后：`docs/test/results/uo-cannbot/query_battery.after.json`
- 四算子重 extract：`docs/test/results/uo-cannbot/reextract_contract.json`

token ≈ UTF-8 字节 / 4（payload `json.dumps`）。卡片上限仍是 `MAX_PAYLOAD_CHARS=24000`（约 6000 token）。

契约 A/B 改了提取，压测前对 FAG / IFA / GMM / NSA `arch35` 各做了 `extract → analyze → commit`。本 after 是重图 + 契约 C 查询规则的合并结果，不是 query-only。

## 前后总表

| 指标 | 基线 | after | 怎么读 |
| --- | ---: | ---: | --- |
| 调用次数 | 164 | 163 | FAG `PIPE_MTE3` 不再给出 file:line，少跟 1 次 around |
| `ok=true` | 153 | 151 | 12 个空卡：原 11 个 catalog 类型 + `PIPE_MTE3`（AscendC 枚举，与 `HardEvent` 同类） |
| 墙钟 | 103.9 s | 151.2 s | 主要是 IFA cover 扫更大 `.uo`（见下） |
| RSS 起 / 峰 / 终 | 24 / 31 / 31 MB | 24 / 32 / 32 MB | 串行查询仍不把图解成数百 MB |
| p50 / p95 / max | 45 / 1432 / 4339 ms | 68 / 1784 / 6953 ms | p50 被 cover 拖高；索引仍快 |
| 平均 payload | 2774 B ≈ 693 token | 3651 B ≈ 912 token | 定义窗 + 局部写点卡片变长 |
| 最大 payload | 21463 B ≈ 5366 token | 20321 B ≈ 5080 token | 仍低于 24000 / 6000；未撞顶 |

11→12 个 `ok=false` 都是 **catalog / 枚举根** 当标识符（`LocalTensor` / `TQue` / `HardEvent` / `TPipe` 类型名 / `PIPE_MTE3`）。名字卡故意不返回 catalog 根——不是泄漏。实例名 `pipe` / `pipeBase` 仍能命中。`LocalTensor` / `TQue` 在四算子上 after 仍空，没有回归成 catalog 命中。

调用数 163 不是少跑了题：标识符集合不变，只是空 catalog 卡没有 file:line，battery 无法复制 around。

## 形态：延迟与体积

| 形态 | 基线 n / p50 / avg B / max tok | after n / p50 / avg B / max tok | 预期？ |
| --- | --- | --- | --- |
| 无参数索引 | 4 / 86 ms / 2128 / 888 | 4 / 52 ms / 2144 / 888 | 索引略快，体积持平 |
| `Dim=` | 24 / 1270 ms / 1017 / 1020 | 24 / 1615 ms / 1017 / 1020 | 体积不变；IFA 图变大所以更慢 |
| `Name=Value` | 24 / 1304 ms / 3444 / 1502 | 24 / 1608 ms / 3444 / 1502 | 同上 |
| 标识符 | 58 / 39 ms / 2393 / 1571 | 58 / 66 ms / 3578 / 3515 | 定义窗：FUNCTION/METHOD 卡可到 40 行 |
| `--file --line` | 54 / 25 ms / 3715 / 5366 | 53 / 33 ms / 5130 / 5080 | 包围定义 seed 后 snippet 变长；max 反而略降 |

Cover 的 payload 字节与基线逐形态相同（合法集 JSON 没变）。墙钟上升来自 **图更大**（local_writes + `ge.graphStatus` 根与 RETURNS），不是 cover 算法改坏。

## 产物体积（重 extract 后）

| 算子 | 基线 `.uo` | after `.uo` | extract+analyze+commit |
| --- | ---: | ---: | ---: |
| FAG | 35 MB | 46 MB | 29 + 44 + 4 s |
| IFA | 79 MB | 106 MB | 110 + 150 + 8 s |
| GMM | 25 MB | 33 MB | 33 + 32 + 3 s |
| NSA | 1.9 MB | 2.4 MB | 29 + 7 + 0.3 s |

IFA 从 79 MB → 106 MB，单次 `Dim=` / `Name=Value` 最坏约 7 s（基线约 4 s）。这是契约 A/B 提取变宽的成本，不是查询回退。

## 质量抽样（after 图，原断言仍过）

| 算子 | 断言 | 基线 | after |
| --- | --- | --- | --- |
| FAG | `IsTnd=1` 命中；`Dim=IsTnd`=`[0,1]` | 通过 | 通过（38 块 / `coverage_checked`） |
| FAG | launch 不是 entry:225 | 63 / 94 / 213 | 仍是 63 / 94 / 213 |
| IFA | `HasAttenMask=true` | 122 块；图内 `0/1` | 122 块；`Dim=`=`[0,1]` |
| GMM | `Dim=TRANS_B` | `[0,1]`；`groupNum` readers=2 | `[0,1]`；readers=2 |
| NSA | `dim_names` 无 `"0"`；`pipe` @ cpp:30 | 通过 | 通过 |
| 全算子 | 索引 hint 不含死写 `IsTnd=1` | 通过 | 通过 |
| FAG | `s1Inner` readers | 仍空（图无 READS） | 仍空 |
| catalog | `LocalTensor` / `TQue` 空 | 空 | 仍空 |

## 契约增量（after 才有）

| 轴 | 结果 |
| --- | --- |
| 空 cover | `IsTnd=9` → `matching_block_count=0` 且 `completeness=coverage_checked`；`nearby` 在 `coverage` 里 |
| 定义窗 | Host `CheckShapeValid` `definition_span` 194–220，snippet 27 行（≥ span，≤ `SNIPPET_LINES=40`），`truncated` 假 |
| around | 点在该函数体内时第一 seed 是 `FUNCTION CheckShapeValid`，不是体内字段 |
| 失败码 | `GRAPH_FAILED` → `catalog=ge.graphStatus`、`role=host_refuse`；RETURNS 入边 FAG 227 / IFA 1160 / GMM 553 / NSA 42 |
| 名字同一 | 叶子名仍命中属主前缀写点（玩具图单测）；生产 `Init` 卡从 buffer.h 声明行改到定义体（FAG `:130` 等） |

失败根是 Host 拒单入口。存在 `GRAPH_FAILED` 根 ≠ 某维永不产生。

## 速度

- 索引 / 多数标识符 / around：仍是几十毫秒（NSA 索引 5 ms）。标识符 p95 升到 0.5 s，因为个别定义卡要读 40 行磁盘窗。
- FAG cover：约 1.6 s。IFA cover：约 7 s（产物 106 MB，仍是最慢形态）。不要对 IFA 无节制扫全部维。
- 墙钟 +47 s 是 **cover 扫更大宇宙** + **定义窗 I/O**，不是连接泄漏。

## 体积与硬顶风险

返回值已经按卡片裁剪。平均约 900 token，仍适合 cannbot 上下文。最大 20321 B（约 5080 token），距 24000 还有约 15%。around 平均从 3.7 KB 升到 5.1 KB——这是定义窗的预期，不是 cap 撞击。若再对超长 Host 函数放开 `SNIPPET_LINES`，around 会先顶到 24 KB。

不要把 `matching_block_count` 理解成「返回了 122 张卡」——exemplar 仍是 1 块，覆盖在 `dim_coverage`。

## 内存结论

串行查询 **不会** 把 106 MB `.uo` 解成数百 MB Python 对象（共享 1 连接 + 紧凑 legal-key）。卡死来自 **extract 多 TU libclang 重叠**，已默认关掉。评测禁止并行 `open_query`。
