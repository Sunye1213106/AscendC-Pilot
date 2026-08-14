# FAG arch35：第三轮 UO 提取 + 两问对照（2026-08-14）

对照对象：`flash_attention_score_grad` / **arch35**。问题来自同一套跨 Host packing → Kernel 消费的考题：

1. **`queryRope`/`keyRope` 都在且 `d==d1`**：Host 的 `IsDNoEqual` / `IsRope` / `isBn2MultiBlk` 各是什么？Kernel D 轴怎么切？
2. **MutexBuffer 是什么**：Cube 侧类型、root、Lock 族。

三次作答：

| 代 | 图 | 查询引擎 | 是否读源码 |
| --- | --- | --- | --- |
| **A1** | 旧 `.uo`（~30.2MB，含 arch22） | hydrate 全图 + 子串 | 否（纯图；Kernel D 标 PARTIAL） |
| **A2** | 第一次重提取 28.44MB（清 arch22） | SQLite 索引，但排序/窗/扇出未改 | 是（snippet + 补读） |
| **A3** | 本次 28.15MB（TYPE 去重 + BRANCH 不存 1 行 span） | 名字匹配、定义优先、命中行向后窗、按 function 样例 | snippet **视为已 Read**，未 Grep 整树 |

权威产品：

`TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/uo/flash_attention_score_grad.arch35.uo`

---

## 1. 本次提取

Harness：`engines/understand-operator/tools/fag_arch35_rebuild_check.py`，`UO_INIT_PROFILE=fast`（keypath、1 kernel dtype、无 API clang）。TU cache **未抹**，所以这不是 119s 那种 true cold start，和 A2 同口径。

**verify pass。** 墙钟 **117.7s**（含 rebuild 脚本末尾的 job-fact 检查）。

| 阶段 | A2（15:49） | A3（16:27） |
| --- | ---: | ---: |
| prepare | ~14s | **13.1s** |
| extract | ~22s | **21.0s** |
| analyze | ~65s | **63.1s** |
| commit | ~15s | **12.8s** |
| verify | ~1.4s | **2.5s** |
| **合计** | **~113s** | **117.7s** |

提取速度没有为这次查询改动变慢；analyze 仍占一半以上。前两次尝试因 `_purge_root_trace_entities` 丢失、以及 collapse 后 `type_ents` 仍指向已删 `TYPE_<hash>` 而失败，修好后一次通过。

### 图规模

| 指标 | 更早旧图 | A2 | **A3** |
| --- | ---: | ---: | ---: |
| `.uo` 字节 | 30.2MB | 28.44MB（29 822 976） | **28.15MB（29 511 680）** |
| entities | 15679 | 15019 | **14820** |
| relations | — | 27860 | **27797** |
| TYPE | — | 468 | **269** |
| `TYPE_<hash>` | 270 | 270 | **71** |
| `SRCTYPE::` | — | 86 | **86** |
| BRANCH 节点 | 1620 | 1546 | **1546** |
| BRANCH `source_span` 行 | — | 1333 | **0** |
| arch22 实体 | 594 | 0 | **0** |
| MutexBuffer TYPE 条数 | 2–3 | 3（`:52` SRCTYPE + 两个 hash） | **1**（仅 `SRCTYPE` `:52`） |

TilingKey 声明 / packing / producer / root 仍是 **19/19**。`architecture_pure=true`。

TYPE 少了 199 个，几乎全是「已有 `SRCTYPE::` 的同名 `TYPE_<hash>`」。剩下 71 个 hash 是没有源码类型节点可并的 clang 产物，不是 MutexBuffer 这类包装。

BRANCH 节点数没降（仍是 clang `if constexpr`），但磁盘不再存 1 行 `if constexpr (...) {`；查询一律走命中行向后的磁盘窗。

---

## 2. 问题 1 答案（A3）

场景：`queryRope` 与 `keyRope` 都在，且 `d == d1`。

| 位 | 值 | 依据（图上的 packing / snippet） |
| --- | --- | --- |
| **IsDNoEqual** | **1** | bit47。`packing_value_sites[0]`：`dNoEqual = (fBaseParams.d1 != fBaseParams.d) \|\| fBaseParams.hasRope`（`tiling_normal_regbase.cpp:1439`）。`d==d1` 时前半为假，`hasRope` 仍置 1。 |
| **IsRope** | **1** | bit48。真实写出在 `packing_value_sites[1]`：`fBaseParams.hasRope = hasQueryRope && hasKeyRope`（同文件 `:95`，`GetShapeAttrsInfo`）。`[0]` 只是头文件默认 `false`，不要停在第一项。 |
| **isBn2MultiBlk** | **false** | bit46。`SetSplitAxis` `:1597` 的完整 RHS（**788 字符，含 `!fBaseParams.hasRope`**）。有 rope 时整段为假；`:1621` / `:682` 还会再强制 `false`。 |

Kernel D 轴：**不是把 D 均分**。Rope packing 必然带上 `IS_D_NO_EQUAL`。切分是「QK 非 rope（`dSizeV`=d1）+ rope（`dRopeSize=64`）」。

- `FagConstInfo::dRopeSize = 64`（`common.h:430`，`field dRopeSize` 的 snippet 里能看到初值）。
- `SetConstInfo`：`IS_ROPE` 在 `kernel_base.h:534`。snippet 从 `:531` 起盖住整个 `*Dr` 体（`s1Dr = s1Size * dRopeSize` 等）直到 `:545`。
- `DqkvMulsAndCastFromGM`：`block_vec.h:837`。snippet 里两路 `DataCopyPad`：主段 `blockLen = dSizeV`，rope 段 `blockLen = dRopeSize`、源偏移 `dqkvCastTensor[dSize]`。`MM_IDX == DV_IDX` 只拷 `dSizeV`。

一句话：`d==d1` 加 rope，不能开 BN2 多基本块，也不能绕过 no-equal；Kernel 按「非 rope(d1) + rope(64)」两段切。

### Q1 查询轮次

`open_query` **0.056s**。下面是实际打出的轮次（含刻意多打的对照轮）。

| # | 查询 | 耗时 | payload | truncated | 有效？ | 第一页拿到了什么 |
| --- | --- | ---: | ---: | --- | --- | --- |
| 1 | `tiling_key IsDNoEqual` | 0.11s | 2.5k | 否 | **有效** | 完整 packing 式；snippet 是 TPL 声明（bit47），公式在 `facts.packing_value_sites` |
| 2 | `tiling_key IsRope` | 0.11s | 2.8k | 否 | **半有效** | `[1]` 才是 `hasQueryRope && hasKeyRope`；`[0]` 是 header `false` |
| 3 | `tiling_key IsBn2MultiBlk` | 0.12s | 4.2k | 否 | **有效（须看 [1]）** | `[1]` 788 字、以 `!hasRope` 结尾；`[0]/[2]/[3]` 都是 `false` |
| 4 | `field isBn2MultiBlk` | 0.02s | 10k | 否 | **半有效** | 主键不再误打 `blockOuter`。但 **主字段是 `:682` 强制 false**；真正 packing 在 **writers[0] `:1597`** |
| 5 | `kernel_branch IS_ROPE` | 0.19s | 12k | **是** | **目录有效 / 样例无效** | `count=39`，`functions` 目录齐全。第一击仍是 `SetRunInfo:1118`（该名出现最多），**不是 D 轴** |
| 6 | `kernel_branch IS_ROPE SetConstInfo` | 0.02s | 4.0k | 否 | **有效** | `:534` 命中行在窗内；`s1Dr` / `dRopeSize` 都在 |
| 7 | `kernel_branch IS_ROPE DqkvMulsAndCastFromGM` | 0.02s | 3.2k | 否 | **有效** | `:837` 两路 `DataCopyPad` + `dSizeV` / `dRopeSize` |
| 8 | `field dRopeSize` | 0.01s | 2.4k | 否 | **有效** | `common.h:430`，snippet 含 `= 64` |

**最少 hop（4 轮即可答完，不必 8 轮）：**

1. `tiling_key IsDNoEqual`（顺手看同 payload 习惯，再打 IsRope / IsBn2MultiBlk，或三次 tiling_key）
2. `kernel_branch IS_ROPE` → 读 `functions`，选 `SetConstInfo` / `DqkvMulsAndCastFromGM`
3. `IS_ROPE SetConstInfo`
4. `IS_ROPE DqkvMulsAndCastFromGM`（`dRopeSize=64` 已在 3 的窗里；`field dRopeSize` 可省）

第 4 轮 `field isBn2MultiBlk`、第 8 轮 `field dRopeSize` **不是必须**。第 5 轮如果只看第一条 BRANCH 会答偏（offset/runinfo），必须按目录再查。

Q1 查询合计（8 轮 + open）**~0.64s**，远小于 A1 的「13 次 × 10s」。

---

## 3. 问题 2 答案（A3）

Cube 侧带互斥 ID 的 **LocalTensor 包装**（`storage_wrapper_type`，`root=AscendC::LocalTensor`），用来在 L0C/L1 等共享缓冲上做生产/消费互斥，不是 `TQue`/`BUFFER` 节点。

- 类型定义：`op_kernel/arch35/cube_api/mutex_buffer.h:52`。snippet 从类声明起，能看到 `LocalTensor<uint8_t>`、构造、`mutexId_`。
- 图上 **只剩一条** `SRCTYPE::…::MutexBuffer`，没有 `:146` 的 `TYPE_<hash>`。
- API（`search METHOD MutexBuffer` 前 8 条）：`MutexBuffer` / `Init` / `UnInit` / `Lock` / `Unlock` / `LockProd` / `UnlockProd`… 都在 `mutex_buffer.h`，**不再把 `block_cube.h:470` 裸名调用点排第一**。

`--mode buffer MutexBuffer` 同样打到这条 TYPE（1 条，未截断）。

### Q2 查询轮次

| # | 查询 | 耗时 | payload | truncated | 有效？ |
| --- | --- | ---: | ---: | --- | --- |
| 1 | `search TYPE MutexBuffer` | 0.03s | 3.4k | 否 | **有效，一页就能答类型** |
| 2 | `buffer MutexBuffer` | 0.01s | 3.7k | 否 | 有效但是重复 |
| 3 | `search METHOD MutexBuffer` | 0.21s | 20.5k | 否 | **有效（API 列表）**；第一击是构造函数 `:61`，不是 `LockProd`。夹进一条 `MutexBuffer::size_`（成员被标成 METHOD） |

最少 hop：**1 轮 TYPE** 足够回答「是什么」；要 Lock 族再加 1 轮 METHOD。

---

## 4. 三次答案对比

结论（三个 packing 位 + 两段 D 切分 + MutexBuffer 是 LocalTensor 包装）**三次都对**。差在：第一页够不够、要不要补读、会不会被噪声带偏。

| 要点 | A1 旧图纯 UO | A2 第一次重提取 | **A3 本次** |
| --- | --- | --- | --- |
| IsDNoEqual=1 / IsRope=1 / isBn2MultiBlk=false | 对 | 对 | **对**，IsDNoEqual 公式在第一击 packing |
| `dRopeSize=64` | 图上无初值 → PARTIAL | snippet 已有 | **field / SetConstInfo 窗都有** |
| `*Dr` stride | 只有 BRANCH 行号 | 仍要补读 `:523-545` | **`IS_ROPE SetConstInfo` 窗已盖住 body** |
| Vec 两段 copy | 靠 impact args | BRANCH snippet 已覆盖 | **`IS_ROPE Dqkv…` 窗含两路 DataCopyPad** |
| `field isBn2MultiBlk` | tiling_field_not_found | **误命中 `blockOuter`** | 命中同名 FIELD；主行仍是 `:682` 不是 `:1597` |
| `tiling_key` 长 RHS | 常被 400 字裁掉 | `!hasRope` 被裁 | **788 字完整，含 `!hasRope`** |
| `kernel_branch IS_ROPE` | count 1083 + overview | 39 处但第一击 Cube Init，12k 裁成 1 条 | **`functions` 目录 + 每函数一条**；第一击仍是 SetRunInfo，**要第二 ident** |
| `buffer MutexBuffer` | **0 条** | 能命中，但双 TYPE + truncated | **1 条 SRCTYPE，未截断** |
| `search TYPE MutexBuffer` | Info/Manager/hash 抢第一 | 精确名 + 仍有 `:146` hash | **只有定义点 `:52`** |
| `search METHOD MutexBuffer` | 调用点在前 | 调用点 `:470` 在前 | **`MutexBuffer::…` 定义在前** |
| 查询时延 | 10–15s/次，串 13 次 ~1min | open 0.05s，mode 亚秒 | **open 0.06s；Q1 必要 hop ~0.4s；Q2 一页 0.03s** |
| 异 arch | 594 条 arch22 | 0 | **0** |

A1 的 PARTIAL（D 轴赋值）在 A2 已能用 snippet 补上；A3 把「还要再 Read 那 20 行」和「第一击答偏」两件事压掉了大部分。还没压掉的见下一节。

---

## 5. 查询排序再测（同日稍后，未重提取）

针对上一节「会答偏」只改了 `uo-query`（`sql.py` / `evidence.py`），**没有重跑 extract**。第一页一次给 **最多 3 条候选**，准确优先。

| 原先会答偏 | 再测 |
| --- | --- |
| `packing_value_sites[0]` 是 header `false` | **已消。** `IsRope[0]=hasQueryRope && hasKeyRope`（`:95`）；`IsBn2MultiBlk[0]=SetSplitAxis` 长式（含 `!hasRope`）；`IsDNoEqual[0]` 仍是 `(d1!=d)\|\|hasRope`。snippet 对着写出点。 |
| `field isBn2MultiBlk` 停在 `:682` | **已消。** 主键 `:1597`，snippet 含 `!hasRope`。`candidates` 指向 `SetSplitAxis`。 |
| 裸 `IS_ROPE` 第一击是 `SetRunInfo` offset | **已消。** 第一页 3 条：`DqkvMulsAndCastFromGM:837`（两路 `DataCopyPad` + `dRopeSize`）、`IterateMmQK:667`（`ROPE_D_128`+`ROPE_D_64`）、`ProcessDqkv:255`（post 128+64）。都是 D 轴两段切。`functions` 目录仍全。 |
| `IS_ROPE SetConstInfo` 不是 `*Dr` | **已消。** 3 条里 **第一条** 就是 `:534`（`s1Dr` / `dRopeSize` / 外层 `IS_D_NO_EQUAL`）。`:641`/`:672` 的 mmK 缩放排后面。 |
| BRANCH 窗看不到外层 `if constexpr` | **已消。** `SetConstInfo:534` 窗扩到 `:523` 的 `IS_D_NO_EQUAL`。 |

`open_query` 0.12s。Q1 必要 hop 仍是 tiling_key ×3 + 裸 `IS_ROPE`（0.35+0.35+0.37+0.55s ≈ **1.6s** 含磁盘修 packing）；再加 `IS_ROPE SetConstInfo` 0.05s 可抄 stride。比 A3 的 0.4s 慢，是因为每个 packing site 回源补 RHS、BRANCH 先开窗再按条件体排序。Q2 不变：TYPE 0.10s 一页。

裸 `IS_ROPE` **不再 truncated**（3×40 行 ≈ 9.5k）。`field isBn2MultiBlk` 仍标 `truncated`（先丢掉 `edges` 才压进 12k），但命中行和 `hasRope` 都在窗内，不必二次查。

---

## 6. 还在的噪声（答错风险已低）

按「会不会让 agent 答错」排序。

1. **裸 `IS_ROPE` 第一页没有 `SetConstInfo`。** 3 条都是搬运/两段 copy，够答「D 怎么切」；`*Dr` stride 要看 `functions` 再查 `IS_ROPE SetConstInfo`，或读第一条窗里的 `dRopeSize`。不 hop 也不会把 packing 位说错。
2. **`tiling_key.line_start` 仍是 TPL 声明行**，snippet 已是 packing 窗，所以 `covers` 对声明行可能是 false。看 snippet / `packing_value_sites[0]`，不要用声明行当 packing 行。
3. **`search METHOD MutexBuffer` 仍把 `size_` 收成 METHOD**（浪费一条，不改类型结论）。
4. 提取侧 `TYPE_<hash>` 71、BRANCH 1546：瘦图，不挡这两问。

不必做：kernel 赋值边、`SYNC` kind、hydrate 全图、全局 `SNIPPET_BEFORE=12`。

---

## 7. 建议的 agent hop

```text
packing 三位     → tiling_key <Name>     （[0] 已是真实写出，[1][2] 是次候选）
                 field 现在也能打到 packing 行，但仍以 tiling_key 为准
Kernel 同名 IS_* → kernel_branch IS_ROPE
                 先看返回的 2–3 条（copy / 嵌套 constexpr）
                 要 stride 再查 IS_ROPE SetConstInfo
类型是什么       → search --kind TYPE <Name>
```

再测：Q1 **tiling_key ×3 + 裸 IS_ROPE 即可答 packing + D 轴切分**；stride 多 1 跳。Q2 **1 跳 TYPE**。
