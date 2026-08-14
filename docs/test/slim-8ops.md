# 瘦身 UO：wipe 前 8 算子基准 + 实验

> 抽检记录。权威产品仍是各算子 `.ascendc-pilot/<arch>/uo/*.uo`。
>
> 机器可读基准：`artifacts/uo-init-generalization/slim-8ops-baseline/pre_wipe.json`
> 本次冷启动收据：`artifacts/uo-init-generalization/slim-8ops/`

对照对象是用户 2026-08-14 下午瘦身过的 UO（TYPE 去重、BRANCH 不落 1 行 span、长 rhs 进磁盘）。FAG arch35 已用该引擎重抽过（A3，28.15MB / 14820 实体）；其余算子磁盘上仍是瘦身前的产物。本页先记下 **wipe 前** 数字，8 算子冷启动结束后补「现在」列。

未设 `UO_TEST_ALLOW_UNVERIFIED_SCOPE`。未 wipe FAG arch22。

8 算子：

1. `attention/flash_attention_score_grad` arch35
2. `attention/incre_flash_attention` arch22
3. `attention/fused_causal_conv1d` arch35
4. `gmm/grouped_matmul` arch35
5. `mc2/moe_distribute_dispatch` arch22
6. `mc2/matmul_reduce_scatter_v2` arch22
7. `moe/moe_gating_top_k` arch35
8. `posembedding/rotary_position_embedding_grad` arch35

---

## Wipe 前（磁盘上已有产物）

| 算子 | 体积 | 实体 | TYPE | grade | packing | dep | OTHER | EnQue | 挡门 |
| --- | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | --- |
| FAG arch35 | 28.15MB | 14820 | 269 | **ready** | 19/19 | 12/19 | 0 | 61 | — |
| IFA arch22 | 21.79MB | 12803 | 271 | **ready** | 12/12 | 6/12 | 0 | 60 | 尚未用瘦身引擎重抽 |
| fused_causal_conv1d | 3.19MB | 2005 | 83 | usable | 4/4 | 0/4 | 56 | 13 | locate_blocking 56（`set_*` owner 歧义） |
| grouped_matmul | — | — | — | 无产物 | — | — | — | — | 上次 prepare 卡 `DTYPE_X` |
| moe_distribute_dispatch | 3.14MB | 2113 | 127 | not_ready | 5/5 | 0/5 | 0 | 0 | producer 缺 ARCH_TAG；INPUT→Key 断 |
| mrs-v2 | 11.10MB | 6459 | 341 | **ready** | 5/5 | 2/5 | 0 | 0 | Kernel API 空（走查没解开） |
| moe_gating_top_k | 2.49MB | 1494 | 96 | not_ready | **0/5** | 5/5 | 0 | 14 | packing 0 |
| rope_grad | 3.13MB | 2012 | 148 | not_ready | 6/6 | 5/6 | 0 | 0 | producer 5/6 缺 |

FAG 相对瘦身前 host-recv-narrow（15679 实体 / TYPE 468 / FUNCTION 1053）：实体 −859，TYPE −199，FUNCTION 1053→714，`.uo` 29.82MB 量级 → 28.15MB。packing 19/19、dependency 12/19、EnQue 61 没掉。这是「能跑过」的质量锚。

---

## 瘦身后再抽（8 算子冷启动）

收据：`artifacts/uo-init-generalization/slim-8ops/results.json`。墙钟 **807.5s**（~13.5 min）。Harness 退出码 1：8 个里 4 个 verify fail。

| 算子 | verify | grade | packing | dep | OTHER | EnQue | 实体 | 体积 | 相对 wipe 前 |
| --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| FAG | **pass** | **ready** | 19/19 | 12/19 | 0 | 61 | 14820 | 28.11MB | 质量锚未掉；体积 28.15→28.11MB |
| IFA | **pass** | **ready** | 12/12 | 6/12 | 0 | 60 | 12792 | 21.50MB | 瘦身生效（12803→12792，21.79→21.50MB） |
| fused_causal | **pass** | usable | 4/4 | **4/4** | 56 | 13 | 4585 | 7.21MB | dep 0/4→4/4；OPERATION 245→1815；仍 56 条 `set_*` owner 歧义 |
| grouped_matmul | **fail** | not_ready | **0/14** | 14/14 | 0 | 0 | 5222 | 7.32MB | **prepare 首次过**（原先无产物）；Key 基数 14/3，packing 未绑 |
| moe_dispatch | **fail** | not_ready | 5/5 | 1/5 | 0 | 0 | 3909 | 6.81MB | OPERATION 10→1171；仍缺 ARCH_TAG producer + INPUT→Key |
| mrs-v2 | **pass** | **ready** | 5/5 | **5/5** | 0 | 0 | 11122 | 19.10MB | dep 2/5→5/5；OPERATION 12→2920（Kernel 走查开了）；EnQue 仍 0，InitBuffer 4 |
| moe_gating | **fail** | not_ready | **0/5** | 5/5 | 0 | 14 | 1514 | 2.50MB | packing 仍 0；Kernel API 还在 |
| rope_grad | **fail** | not_ready | 6/6 | 5/6 | 0 | 0 | 2238 | 3.52MB | producer 仍 1/6；InitBuffer 10 |

### 怎么读

- **能当 cannbot 底座（ready + verify pass）**：FAG、IFA、mrs-v2。三条路径都通，locate 1.0。
- **verify pass 但 usable**：fused_causal。packing/路径齐，`locate_blocking=56` 挡 ready。
- **图能出、integrity 不过**：grouped_matmul / moe_dispatch / moe_gating / rope_grad。挡门仍是 Host packing/producer，不是瘦身把 FAG 打坏。
- **瘦身本身**：FAG/IFA 实体和 `.uo` 略降，packing / EnQue / 12/19 没退。mrs-v2 / fused_causal / moe_dispatch 实体变大，是 Kernel TU 解开，不是 TYPE 膨胀。

FAG 本轮 160s（wipe 后冷一些）；IFA 185s。grouped_matmul extract 74s 最慢。
