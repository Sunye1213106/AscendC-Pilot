# 算子理解冷启动：补 30 个 arch22

实验编号：pass30-arch22-20260816  
对照：pass70-20260816-perf（已测过的 70 个算子，本轮不重跑、不改那份产物）  
日期：2026-08-16  
测的是：AscendC-Pilot 里把算子源码画成代码地图的流程（uo-init）  
算子来自：CANN ops-transformer  
AscendC-Pilot 版本：`08839883f45bdd3328ddca1bfbdd8491ff800853`（工作树另有与本实验无关的本地改动；开跑前 `ownership.py` 缺闭合花括号，补上后才能启动）  
ops-transformer 版本：`4e09c2ec15a414f6e312caf5b3da16cd965af07b`

本轮名单哈希（SHA256）：`38475FB4F465FD1A57D902AF7FDE4A094536B9AC69F82490FC09D53AEFEA8A91`  
70 名单哈希（SHA256）：`ACDE707A1A7B1C167A91E161FA5D096538FB12757DC7A6B8487071C72C76B1A9`（与本轮 30 条 `rel` 交集为空）

---

## 1. 为了什么

70 个样本里只有 2 个 arch22。把实验补到 100 个算子：剩下 30 个全部强制跑 arch22，且不能和那 70 个算子重复。  
不重跑那 70 个，不覆盖 `pass70-20260816/`。

## 2. 实验平台（本机）

- 记录时间：2026-08-16T22:02+08:00 开跑，墙钟 1454.7s（约 24.2 分钟）
- 主机名：DESKTOP-8FM628U
- 系统：Windows 11 家庭中文版，内核 10.0.22000，64 位
- CPU：AMD Ryzen 7 6800H with Radeon Graphics，8 核 / 16 逻辑处理器
- 内存：约 15.2 GB
- 磁盘：D: Data NTFS 固定盘；工作目录 `d:\TEST`
- Python：3.11.5，`E:\anaconda\python.exe`
- Clang：18.1.8（x86_64-pc-windows-msvc）
- 当时是否还在跑别的重任务：是（Cursor 前台仍在）

## 3. 这 30 个怎么来的

仓里正式算子须有 `op_kernel/`。带 arch22 的判定：

- 直系：`op_host/arch22` 或 `op_kernel/arch22`
- 嵌套：仅 `op_host/op_tiling/arch22`（discover 默认看不见，本轮写死 `arch=arch22`）

满足上述、且 `rel` 不在冻结 70 里的，一共正好 30 个，全部入选，没有再抽样。家族：attention 11、mc2 17、mhc 2。  
其中 4 个只有 tiling 子目录里的 arch22：`mc2/all_gather_matmul`、`mc2/allto_allv_grouped_mat_mul`、`mc2/grouped_mat_mul_allto_allv`、`mc2/matmul_reduce_scatter`。这 4 个本轮五步都过了。

discover 在同时有 arch35 时会优先 arch35，所以本轮用 `UO_GEN_CASES_FILE` 把 30 条全部写成 `"arch": "arch22"`。

30 个名单（rel / arch，全部 arch22）：

| # | rel | arch | 家族 |
| ---: | --- | --- | --- |
| 1 | attention/block_sparse_attention_grad | arch22 | attention |
| 2 | attention/flash_attention_score | arch22 | attention |
| 3 | attention/incre_flash_attention | arch22 | attention |
| 4 | attention/lightning_indexer | arch22 | attention |
| 5 | attention/lightning_indexer_v2 | arch22 | attention |
| 6 | attention/mla_prolog | arch22 | attention |
| 7 | attention/quant_lightning_indexer_v2 | arch22 | attention |
| 8 | attention/recurrent_gated_delta_rule | arch22 | attention |
| 9 | attention/sparse_flash_attention | arch22 | attention |
| 10 | attention/sparse_flash_attention_grad | arch22 | attention |
| 11 | attention/sparse_flash_mla_grad | arch22 | attention |
| 12 | mc2/all_gather_matmul | arch22 | mc2 |
| 13 | mc2/allto_all_all_gather_batch_mat_mul | arch22 | mc2 |
| 14 | mc2/allto_all_matmul | arch22 | mc2 |
| 15 | mc2/allto_allv_grouped_mat_mul | arch22 | mc2 |
| 16 | mc2/batch_mat_mul_reduce_scatter_allto_all | arch22 | mc2 |
| 17 | mc2/distribute_barrier | arch22 | mc2 |
| 18 | mc2/ffn_to_attention | arch22 | mc2 |
| 19 | mc2/grouped_mat_mul_all_reduce | arch22 | mc2 |
| 20 | mc2/grouped_mat_mul_allto_allv | arch22 | mc2 |
| 21 | mc2/inplace_matmul_all_reduce_add_rms_norm | arch22 | mc2 |
| 22 | mc2/matmul_allto_all | arch22 | mc2 |
| 23 | mc2/matmul_reduce_scatter | arch22 | mc2 |
| 24 | mc2/moe_distribute_combine | arch22 | mc2 |
| 25 | mc2/moe_distribute_combine_add_rms_norm | arch22 | mc2 |
| 26 | mc2/moe_distribute_combine_v3 | arch22 | mc2 |
| 27 | mc2/moe_distribute_dispatch_setup | arch22 | mc2 |
| 28 | mc2/moe_distribute_dispatch_v3 | arch22 | mc2 |
| 29 | mhc/mhc_post | arch22 | mhc |
| 30 | mhc/mhc_pre_sinkhorn_backward | arch22 | mhc |

## 4. 怎样算对

1. 30 个都走完：准备 → 抽图 → 分析 → 落盘 → 自检
2. 产物完整，没有「说不清类型」的节点
3. 该能指到源码的，文件和行号都在
4. 源码里有 packing 的，图上能指回去；源码里没有的，图上应是 0/0
5. 本轮自动分 ready 与定位探针为准（没有再做 70 轮那种逐算子打开源码的 LLM 复检）。6 个未过的对照了 scope / host 源码。

## 5. 总结果

| 看什么 | 70 轮（已测） | 本轮 30 | 合计 100 |
| --- | ---: | ---: | ---: |
| 算子数 | 70 | 30 | 100（`rel` 不重复） |
| arch | arch35×68，arch22×2 | **arch22×30** | arch35×68，arch22×32 |
| 五步都跑完 | 70/70 | **24/30** | 94/100 |
| 产物完整 | 70/70 | **27/30**（3 个准备阶段拦住，没有图） | 97/100 |
| 自动分 ready | 70/70 | **24/30** | 94/100 |
| 说不清类型的节点 | 0 | **0**（画出的 27 个） | 0 |
| 墙钟（秒） | — | **1454.7** | — |
| 各算子五步合计相加（秒） | 3424 | **1435** | — |

家族：attention 9/11，mc2 14/17，mhc 1/2。

6 个未过：

| 算子 | 停在 | 现象 |
| --- | --- | --- |
| `mc2/allto_all_matmul` | 准备 | `SCOPE_VALIDATE_BLOCKED`。Clang 闭包是 complete、probe 干净，但 scope 记了 `kernel_entry_not_found: no op_kernel/*.cpp`（`op_kernel/arch22/` 只有头文件，没有 `.cpp`） |
| `mc2/matmul_allto_all` | 准备 | 同上，`kernel_entry_not_found: no op_kernel/*.cpp` |
| `mc2/moe_distribute_dispatch_setup` | 准备 | `SCOPE_VALIDATE_BLOCKED`。`kernel_entry_other_arch: moe_distribute_dispatch_setup.cpp builds arch35`；另有 `tiling_key_header_not_found` |
| `attention/mla_prolog` | 自检 | 图画完，packing `0/8`，`INCOMPLETE_HOST_TILINGKEY_PACKING` / `MISSING_HOST_TILINGKEY_PRODUCERS` / `UNROOTED_TILING_KEYS`。host 有 `context_->tilingKey = GET_TPL_TILING_KEY(...)`，kernel 侧没有 `TILING_KEY_IS` |
| `attention/sparse_flash_attention_grad` | 自检 | packing `32/39`，另有 `TILING_KEY_CARDINALITY_MISMATCH`。`GET_TPL_TILING_KEY` 在 `op_host/arch35/`，`op_host/arch22/` 里没有 |
| `mhc/mhc_pre_sinkhorn_backward` | 自检 | packing `0/1`。arch22 tiling 里是一条丢弃返回值的 `GET_TPL_TILING_KEY(isDeterministic);`，没有赋给 `tilingKey` / `SetTilingKey` |

负例（源码没有拼 tiling key，图上 packing `0/0`，本轮仍算过）：

- `mc2/distribute_barrier`（目录里没有 `GET_TPL_TILING_KEY` / `TILING_KEY_IS`）

## 6. 每个算子的图里有什么（30 行全表）

时间单位：秒。Buffer 本轮是定位探针里带源码 span 的 BUFFER 节点数。写点为「有 writer 的字段 / TilingField 总数」。结论列：自动 ready / 可解释 / 失败。

| # | rel | 准备 | 抽图 | 分析 | 落盘 | 自检 | 合计 | 完整 | 自动分 | packing | 节点 | 边 | Buffer | 写点 | 结论 |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | attention/block_sparse_attention_grad | 21.8 | 15.4 | 33.8 | 1.8 | 0.9 | 73.9 | pass | ready | 2/2 | 5394 | 8168 | 401 | 31/54 | 自动 ready |
| 2 | attention/flash_attention_score | 7.8 | 19.8 | 44.8 | 5.0 | 2.6 | 80.0 | pass | ready | 20/20 | 9548 | 17868 | 467 | 113/269 | 自动 ready |
| 3 | attention/incre_flash_attention | 11.2 | 36.6 | 101.3 | 7.1 | 4.4 | 160.7 | pass | ready | 12/12 | 17355 | 41550 | 1689 | 156/479 | 自动 ready |
| 4 | attention/lightning_indexer | 7.6 | 15.5 | 6.7 | 0.5 | 0.4 | 30.7 | pass | ready | 7/7 | 1956 | 4530 | 99 | 28/13 | 自动 ready |
| 5 | attention/lightning_indexer_v2 | 5.5 | 14.4 | 7.4 | 0.6 | 0.4 | 28.5 | pass | ready | 7/7 | 2006 | 5085 | 98 | 32/17 | 自动 ready |
| 6 | attention/mla_prolog | 6.1 | 11.1 | 14.9 | 1.1 | 1.2 | 34.5 | pass | not_ready | 0/8 | 3689 | 8839 | 358 | 68/45 | 失败 |
| 7 | attention/quant_lightning_indexer_v2 | 5.1 | 13.6 | 6.3 | 1.0 | 0.3 | 26.4 | pass | ready | 6/6 | 2101 | 5429 | 84 | 34/16 | 自动 ready |
| 8 | attention/recurrent_gated_delta_rule | 5.7 | 9.1 | 2.9 | 0.2 | 0.2 | 18.2 | pass | ready | 2/2 | 765 | 1542 | 69 | 10/17 | 自动 ready |
| 9 | attention/sparse_flash_attention | 5.6 | 15.8 | 10.6 | 0.9 | 0.5 | 33.6 | pass | ready | 6/6 | 3157 | 7231 | 145 | 51/32 | 自动 ready |
| 10 | attention/sparse_flash_attention_grad | 7.8 | 10.9 | 10.2 | 0.7 | 0.5 | 30.2 | pass | not_ready | 32/39 | 3110 | 7169 | 166 | 79/96 | 失败 |
| 11 | attention/sparse_flash_mla_grad | 8.1 | 9.9 | 9.5 | 0.6 | 0.5 | 28.7 | pass | ready | 2/2 | 2474 | 4758 | 137 | 65/54 | 自动 ready |
| 12 | mc2/all_gather_matmul | 50.5 | 10.4 | 12.0 | 0.4 | 0.2 | 73.5 | pass | ready | 3/3 | 2027 | 2302 | 25 | 61/222 | 自动 ready |
| 13 | mc2/allto_all_all_gather_batch_mat_mul | 14.0 | 16.9 | 21.6 | 0.7 | 1.3 | 54.6 | pass | ready | 5/5 | 4330 | 6853 | 236 | 58/260 | 自动 ready |
| 14 | mc2/allto_all_matmul | 15.2 | — | — | — | — | 15.3 | 未画出 | — | — | — | — | — | — | 失败 |
| 15 | mc2/allto_allv_grouped_mat_mul | 17.8 | 12.0 | 18.6 | 0.6 | 0.3 | 49.4 | pass | ready | 3/3 | 2810 | 3075 | 33 | 57/332 | 自动 ready |
| 16 | mc2/batch_mat_mul_reduce_scatter_allto_all | 14.6 | 15.5 | 24.0 | 0.9 | 1.7 | 56.7 | pass | ready | 4/4 | 4150 | 6426 | 175 | 57/246 | 自动 ready |
| 17 | mc2/distribute_barrier | 14.2 | 10.6 | 8.5 | 0.5 | 0.2 | 34.1 | pass | ready | 0/0 | 1566 | 1544 | 50 | 9/220 | 可解释 |
| 18 | mc2/ffn_to_attention | 17.6 | 11.8 | 9.2 | 0.5 | 0.2 | 39.3 | pass | ready | 2/2 | 1523 | 1311 | 30 | 12/223 | 自动 ready |
| 19 | mc2/grouped_mat_mul_all_reduce | 19.1 | 13.9 | 11.8 | 0.7 | 0.3 | 45.9 | pass | ready | 1/1 | 1670 | 1750 | 34 | 52/226 | 自动 ready |
| 20 | mc2/grouped_mat_mul_allto_allv | 19.2 | 16.1 | 17.3 | 0.5 | 0.3 | 53.5 | pass | ready | 4/4 | 2198 | 2250 | 33 | 3/290 | 自动 ready |
| 21 | mc2/inplace_matmul_all_reduce_add_rms_norm | 28.0 | 21.5 | 54.3 | 3.6 | 1.7 | 109.1 | pass | ready | 17/17 | 6251 | 15189 | 209 | 42/403 | 自动 ready |
| 22 | mc2/matmul_allto_all | 28.9 | — | — | — | — | 29.0 | 未画出 | — | — | — | — | — | — | 失败 |
| 23 | mc2/matmul_reduce_scatter | 22.7 | 29.5 | 13.6 | 0.5 | 0.3 | 66.7 | pass | ready | 3/3 | 2753 | 3756 | 69 | 59/225 | 自动 ready |
| 24 | mc2/moe_distribute_combine | 17.8 | 9.1 | 16.5 | 0.7 | 1.7 | 45.8 | pass | ready | 3/3 | 3744 | 7027 | 314 | 19/230 | 自动 ready |
| 25 | mc2/moe_distribute_combine_add_rms_norm | 18.1 | 12.8 | 18.9 | 0.7 | 0.4 | 51.1 | pass | ready | 3/3 | 3604 | 6018 | 140 | 47/256 | 自动 ready |
| 26 | mc2/moe_distribute_combine_v3 | 18.6 | 12.2 | 19.9 | 0.8 | 0.4 | 52.0 | pass | ready | 3/3 | 3616 | 6163 | 140 | 47/256 | 自动 ready |
| 27 | mc2/moe_distribute_dispatch_setup | 11.7 | — | — | — | — | 11.8 | 未画出 | — | — | — | — | — | — | 失败 |
| 28 | mc2/moe_distribute_dispatch_v3 | 15.9 | 12.4 | 30.2 | 1.1 | 0.7 | 60.5 | pass | ready | 5/5 | 4991 | 10313 | 327 | 48/257 | 自动 ready |
| 29 | mhc/mhc_post | 4.8 | 11.0 | 2.6 | 0.3 | 0.2 | 19.0 | pass | ready | 1/1 | 647 | 1229 | 32 | 12/12 | 自动 ready |
| 30 | mhc/mhc_pre_sinkhorn_backward | 7.5 | 7.6 | 6.6 | 0.4 | 0.2 | 22.4 | pass | not_ready | 0/1 | 1199 | 2504 | 96 | 15/16 | 失败 |

人话摘要：

- 节点最多：`attention/incre_flash_attention`（17355 节点 / 41550 边；运算 5001；分析 101.3s）。
- 合计最慢：同一个 IFA，160.7s。其次 `mc2/inplace_matmul_all_reduce_add_rms_norm` 109.1s。
- packing 维数最多且过了：`attention/flash_attention_score`（20/20）。
- 4 个「只有 op_tiling/arch22」的 mc2 全部过了。
- 3 个准备阶段没画出图；3 个图画完但 tiling key packing 对不上。

## 7. 结论

补进的 30 个 arch22 与冻结 70 不重复。24/30 五步通过、自动分 ready；3 个卡在准备（kernel 入口对不上 arch22），3 个卡在 packing。连同已测的 70 个，100 个不重复算子里 94 个五步通过；arch22 从 2 个变成 32 个。限制：只在这一个仓；本轮 30 个没有做 70 轮那种逐算子 LLM 对源；3 个准备失败没有产物可审。

## 附录 A. 怎么复现

- AscendC-Pilot commit：`08839883f45bdd3328ddca1bfbdd8491ff800853`
- ops-transformer commit：`4e09c2ec15a414f6e312caf5b3da16cd965af07b`
- 名单：`artifacts/uo-init-generalization/pass30-arch22-20260816/sample.json`
- sample.json SHA256：`38475FB4F465FD1A57D902AF7FDE4A094536B9AC69F82490FC09D53AEFEA8A91`
- 命令：

```powershell
cd d:\TEST\AscendC-Pilot
$env:UO_OPS_ROOT = "d:\TEST\ops-transformer"
$env:UO_GEN_OUT = "d:\TEST\AscendC-Pilot\artifacts\uo-init-generalization\pass30-arch22-20260816"
$env:UO_GEN_CASES_FILE = "d:\TEST\AscendC-Pilot\artifacts\uo-init-generalization\pass30-arch22-20260816\sample.json"
$env:PYTHONUNBUFFERED = "1"
python engines/understand-operator/tools/uo_init_generalization.py
```

- 本机环境：见第 2 节
- 测量日期：2026-08-16（UTC+8）
- 不要设 `UO_KERNEL_ROOT_TRACE_BUDGET_S` / `UO_COLD_BUDGET_S`；不要用 `UO_GEN_ONLY`（会走 discover，arch 会被选成 arch35）
