# FAG arch35 13 条不可达引理：冷启动 uo-init + uo-query 评测

对照 `tilingkey-closure-report.md` 的 13 组 Host 引理。本轮**不复用旧 `.uo`**：先 abort 卡住的 run、删掉 `.ascendc-pilot/arch35`，再冷编译 CodeMap，然后只用 `uo-query` 四种形态查图（无参数索引 / 标识符 / `Dim=`·`Name=Value` / 从卡片复制的 `--file --line`）。

目标不是把引理升级进排除集，而是看 **uo-query 返回值是否正确、噪声低、够不够关上证明义务**。

## 0. 算子与产物

| 项 | 值 |
| --- | --- |
| 算子目录 | `d:\TEST\ops-transformer\attention\flash_attention_score_grad` |
| architecture | `arch35` |
| 产品 | `.ascendc-pilot/arch35/uo/FlashAttentionScoreGrad.arch35.uo` |
| 声明 Key 数（`legal_key_count`） | **8705**（与闭合报告 `\|D\|` 一致） |
| 实体 / 边 | 19225 / 35407 |
| TilingKey 维 | 19/19 声明、packing、host producer、root 覆盖 |
| verify | `pass` |

## 1. 冷启动 uo-init 耗时

`true-cold`：wipe `arch35` 后 `prepare → extract → analyze → commit → verify`。墙钟来自 `full_init_timing_report.json`。

| 阶段 | 结果 | 耗时 |
| --- | ---: | ---: |
| prepare | ok | **18.395 s** |
| extract | ok | **15.406 s** |
| analyze | ok（`semantic_completeness=complete`，gap_count=11） | **44.491 s** |
| commit | ok | **3.345 s** |
| verify | pass | **2.889 s** |
| **合计** | 全部 ok | **84.527 s** |

analyze 内 `kernel_root_trace` 单独 **15.214 s**。extract 的 TU cache 全 miss（`hit=0, miss=11`），确认没有吃到上一份产物。

历史契约 after 口径（FAG extract 29 + analyze 44 + commit 4）与本次同量级；本次把 prepare/verify 也算进墙钟，所以总时长约 **85 s**。

## 2. uo-query 怎么跑

同一条 `.uo` 连接、**串行** 99 次 `agent_query`（禁止并行 `open_query`），约 **102 s**。

| 形态 | 次数 | 延迟 | 体积 |
| --- | ---: | --- | --- |
| 无参数索引 | 1 | 52 ms | 2.4 KB |
| `Dim=<维>` | 14 | ~1.5 s | 0.7–0.8 KB |
| `Name=Value` 组合 | 47 | ~1.5–1.8 s | 空集 ~1 KB；命中 ~2.2–2.6 KB |
| 标识符 | 18 | 51–112 ms | 1.8–9.2 KB |
| `--file --line`（从上一张卡复制） | 19 | 32–63 ms | 2.4–24 KB（未撞 24 KB 硬顶） |

原始卡片：`uoquery-lemma-cards.json`。`Dim=` 的 `declared_coverage` / `product_coverage`：`_dim_coverage.json`。

## 3. 总评：uo-query 能不能用来证这 13 条

**分层是对的，定位是准的，单独一张 cover 卡不能证 Host「不可达」。**

- 声明集里本来就没有的取值/组合（闭合报告「单独排除=0」）：`matching_block_count=0` 且 `completeness=coverage_checked`，**模板层可证**。
- 声明集里有、Host 写不出来的组合：cover **有命中**（2–26 块），这只说明 **模板接纳**，必须转 Host 标识符。这与 source-proof 口径一致，不是回归。
- 标识符打到的 `file:line` 与闭合报告引用几乎同一窗口（常见偏差 0–2 行，来自当前源码 vs 报告当时行号）。
- 噪声主要在**第一张卡的 kind**：`IsRope` / `isBn2MultiBlk` / `keepProb` 会先落到 `TILING_KEY` 或 `TILING_DATA`，Host 赋值在后面几张或 `next` 里。技能已警告；评测里复现了。

对照组合（含可达控制组）**没有一张 cover 扫错层**：该空的空，该命中的命中。

## 4. 逐条引理

每条先给 **cover 层**，再给 **Host 窗口**。`PROVED` 只在该层义务能关上时使用。

### 引理组一：FP8 / HIFLOAT8 在 tiling 前被拒

| 查询 | matching | completeness | 层 |
| --- | ---: | --- | --- |
| `InputDType=4/5/6` | 0 | coverage_checked | template 空集 |
| `S1TemplateNum=512` | 0 | coverage_checked | template 空集 |
| `S2TemplateNum=256/512` | 0 | coverage_checked | template 空集 |

`Dim=InputDType`：`declared_coverage=[0..6]`，`product_coverage=[0..3]`。  
`Dim=S1TemplateNum`：declared 含 512，product 只有 `0/64/128`。  
`Dim=S2TemplateNum`：declared 含 256/512，product 只有 `0/128`。

这比闭合报告「内核没声明」更细：值在 **DECL 域**里，不在 **SEL product** 里。cover 用 `product` 而不是第一块 ARGS_SEL，正确。

Host：`ProcessQuantInfo` → `common_regbase.cpp:1145`（报告 1143），snippet 含 `DT_FLOAT8_*` / `HIFLOAT8`；`next` 含 `GRAPH_FAILED`、`DetermineMode`。`DetermineMode` @ 1651 写出 `inputDtype`。`GetS1S2TemplateType` @ 812 第一个分支就是 fp32 大 D（组十），512 分支在后续。

- template：`PROVED`（宇宙扫完的空集）
- host 拒单：`PROVED` 到 `ProcessQuantInfo` 入口；`GRAPH_FAILED` 根是 catalog=`ge.graphStatus` / `role=host_refuse`（RETURNS=227），不能单独写成「某维永不产生」——本条有站点覆盖，不靠根节点。

### 引理组二：rope 强制 D 模板 192

| 查询 | matching | 备注 |
| --- | ---: | --- |
| `IsRope=1,DTemplateNum=64/128/256/768` | **4** | 模板接纳 → 必须走 Host |
| `IsRope=1,DTemplateNum=192`（控制） | **18** | 可达侧命中更多块 |

Host：`GetDTemplateType` @ `common_regbase.cpp:847`，snippet 第一句 `if (hasRope) { dTemplateType = NUM192; return 192; }`。与报告 845–850 同窗。

- template：不能证不可达（cover>0）
- host：`PROVED`（入口第一行分流已见）

`IsRope` 第一张是 `TILING_FIELD isRope`（tiling_data_regbase.h:45），第二张才是 `TILING_KEY` bit 48。`hasRope` 第一张才是 Host 赋值 `normal_regbase.cpp:95`。查错名字会偏到 Kernel 字段。

### 引理组三：rope 强制 dNoEqual 置位

`IsRope=1,IsDNoEqual=0` matching=**4**（模板接纳）。控制 `=1` matching=**18**。

Host：`GetTilingKey` @ `normal_regbase.cpp:1435`，snippet 含  
`dNoEqual = (d1 != d) || hasRope`（报告 1438）。

- host：`PROVED`

### 引理组四 / 五：BN2MultiBlk 合取与 TND 互斥

| 查询 | matching |
| --- | ---: |
| `IsBn2MultiBlk=1,IsRope=1` | 4 |
| `IsBn2MultiBlk=1,IsDNoEqual=1` | 4 |
| `IsTnd=1,IsBn2MultiBlk=1` | 2 |

模板都接纳。Host 原赋值在 `SetSplitAxis` @ `common_regbase.cpp:1581`（报告 1592 合取式）。`--file --line 1581` 的 around 第一 seed 就是该函数；snippet 从 `isBn2 = ... queryType != FLOAT` 开始，40 行窗可以接到 `isBn2MultiBlk` / `!hasRope` / `layoutType != TND`。

噪声：查 `isBn2MultiBlk` 第一张是 `TILING_KEY` 声明；Host 写点先打到 `normal_regbase.cpp:682`（DoSparse **事后清掉**），不是 SetSplitAxis 的合取式。义务「写点全集」要跟 `SetSplitAxis` 的 `next`（`bn2S2RouteLimit` 等），不能停在第一张。

- 层判断：正确（必须 Host）
- 合取式本身：around 后 **PROVED**；若只信 `isBn2MultiBlk` 第一张 → **INSUFFICIENT**（写点不全）

### 引理组六：BN2MultiBlk 关闭确定性

`IsBn2MultiBlk=1,DeterType=1..4` matching=**0** / coverage_checked。  
控制 `DeterType=0` matching=**4**。

与报告「声明集内无此组合」一致。Host 旁证：`GetDeterSparseTilingKey` @ 790 第一句 `!isDeterministic → NO_DETER`。

- template：`PROVED`
- host：定位到 deter 函数，与 cover 空集互证

### 引理组七 / 八 / 九：BN2S2 / BN2 压低 D

全是三元约束，cover **全部命中**（模板不编码 `d<=128`）：

| 查询 | matching |
| --- | ---: |
| `SplitAxis=5,IsDrop=1,DTemplateNum=192/256/768` | 8 |
| 控制 `DTemplateNum=128` | 8（同数，模板分不出） |
| `SplitAxis=5,IsTnd=0,DTemplateNum=192/256/768` | 2 |
| `SplitAxis=1,IsTnd=1,DTemplateNum=192/256/768` | 2 |
| 控制 `SplitAxis=1,IsTnd=1,DTemplateNum=128` | 2（同数） |

Host：

- `bn2S2RouteLimit` @ 1631、`bn2S2NotTndLimit` @ 1625（`d <= BN2S2_WRITE_UB_D`）
- `SetSplitAxis` around 覆盖 BN2S2=5 与 layout 析取
- `keepProb` 第一张是 TilingData 字段，**不是** `GetTilingKey` 里 `keepProb<1`（报告 1440）。IsDrop 要用 `GetTilingKey` / `Dim=IsDrop`，不要停在 `keepProb`

组七/八/九是「先读源码再被三元挖掘复现」的典型：**cover 命中 ≠ Host 可达**。uo-query 正确拒绝用 cover 结案。

- template：不得证不可达
- host：窗口齐则 **PROVED**；`keepProb` 第一张噪声，IsDrop 义务要改查 `GetTilingKey`

### 引理组十：fp32 大 D 固定 S1=64

`InputDType=1,DTemplateNum=768,S1TemplateNum=128` matching=**7**  
控制 `S1TemplateNum=64` matching=**7**（模板同样接纳）

Host：`GetS1S2TemplateType` @ 812 第一个分支  
`queryType==DT_FLOAT && d>NUM256 → s1=64, s2=128`。与报告 810–816 同窗。

- host：`PROVED`（第一行分流）

### 引理组十一：nEqual 依赖 deter 类型

`IsNEqual=1,DeterType=0/1` matching=**0** / coverage_checked  
控制 `DeterType=2` matching=**26**

Host：`isDeterNEqual` @ `GetTilingKey` 1444，snippet 即  
`deterSparseType != DETER_OLD && != NO_DETER && g==1`。

- template：`PROVED`（声明集无此组合）
- host：公式窗口 **PROVED**

### 引理组十二：无 mask 时 DeterType 不能是 3/4

| 查询 | matching | 含义 |
| --- | ---: | --- |
| `IsAttenMask=0,DeterType=4` | **26** | 模板接纳，Host 才拒 |
| `IsAttenMask=0,DeterType=3` | **24** | 同上 |
| 控制 `DeterType=0/1/2` | 27 / **12** / 26 | 1 仍命中 → 对应 PREFIX 例外，**没有**被误扫成空 |

这是质量最好的一条：**控制组 `DeterType=1` 仍有 12 块**，不会重演「无 mask 只能 0/2」那种假证。

Host：`GetDeterSparseTilingKey` @ 790（`!isSparse` 早退 2）；`SetSparseParams` @ 1538 **第一句就是 PREFIX 例外**（报告强调必须读进去）。函数卡 `truncated=true`，EMPTY_TENSOR→false 要 around 续窗。

- template：不得证不可达
- host：PREFIX 例外可见 → 引理「不是 3/4」**PROVED**；「只能 0/1/2」与 cover 控制组一致

### 引理组十三：TND swizzle 与确定性互斥

`IsTndSwizzle=1,DeterType=2/3/4` matching=**8**  
控制 `DeterType=0` matching=**2**

Host：`templateSupportCond` @ `normal_regbase.cpp:453`；`isTndSwizzle` 赋值 @ 461。第一页 snippet 从 450 行注释切入，`&& false` 在后续几行，around 才能关「确定性析取恒假」。

- host：定位正确；字面量 `false` 不在 12 行 head 里 → 义务要 around 后续。around 后可 **PROVED**

## 5. 噪声与易错（产品问题，不是这次算子特例）

| 现象 | 影响 | 判 |
| --- | --- | --- |
| `Dim=X` 的 `matching_block_count=0` 且 `count=product 基数` | 容易看成「没覆盖」 | `cover_kind=dim_list`；看 `declared_coverage`/`product_coverage` |
| 组合 cover>0 | 容易写成 Host 不可达 | 只证明模板接纳 |
| `IsRope` 第一张 TilingData | 证错层 | 看全部 kind；Host 用 `hasRope` / `GetDTemplateType` |
| `isBn2MultiBlk` 先 KEY、再 DoSparse:682 | 漏掉 SetSplitAxis 合取 | 跟 `SetSplitAxis` |
| `keepProb` 先 TilingData packing | 证不成 IsDrop | 用 `GetTilingKey` 的 `keepProb<1` |
| 无 file 的 VARIABLE 卡 | 噪声 | 忽略，跟有 span 的卡 |
| around 形状是 `seeds/hits/neighbors`，不是 `cards` | 探针对 `cards` 会看成空 | 形态不同，payload 本身有（本轮 around 16 seeds，第一 seed 常是对的 FUNCTION） |
| `GRAPH_FAILED` 无 file、catalog 根 | 不能当「该维永不产生」 | 只证明存在拒单入口 |

## 6. 结论（针对「测 uo-query」）

**正确性**：13 组在「该走 template 还是 host」上与闭合报告 **13/13 一致**。空集三条（组一取值、组六、组十一）cover 空且 `coverage_checked`；其余 Host 引理 cover 均命中；组十二控制组保留了 `DeterType=1`（PREFIX），没有假空集。

**质量**：Host 函数标识符（`ProcessQuantInfo` / `GetDTemplateType` / `GetTilingKey` / `GetS1S2TemplateType` / `GetDeterSparseTilingKey` / `SetSparseParams` / `SetSplitAxis`）打到报告同一批窗口，snippet 含关键 guard。这够作为证明入口。

**噪声**：中等、可预期。主要是同名跨 kind、第一张 packing/KEY、以及 around 不用 `cards`。按技能「看全部 kind / 跟 next / 截断续窗」可以滤掉；若 Agent 只读第一张，组四/七会证错。

**uo-query 不能单独闭合的**：任何 cover>0 的「Host 不可达」命题。它能分层、能给窗口，关上「只能 / 从不」仍要读完赋值函数（含后续覆盖 682 行那种）。这与 `skills/source-proof` 一致，评测里被 13 条引理复现。

## 7. 产物

| 文件 | 内容 |
| --- | --- |
| `ops-transformer/.../.ascendc-pilot/arch35/uo/ir/full_init_timing_report.json` | 本次冷启动分阶段耗时 |
| `docs/history/fag_test/uoquery-lemma-cards.json` | 99 次查询压缩卡 |
| `docs/history/fag_test/_dim_coverage.json` | 14 维 declared/product |
| `docs/history/fag_test/_uoquery_lemma_probe.py` | 可复现探针 |
| `docs/history/fag_test/uoquery-kernel-eval.md` | Kernel 侧 TPipe/TQue/Mutex/同步对照 |
