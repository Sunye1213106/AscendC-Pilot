# 算子理解冷启动复测报告

实验编号：pass70-20260816-perf  
对照：pass70-20260816（同一份 70 个算子，不是新抽的）  
日期：2026-08-16  
测的是：AscendC-Pilot 里把算子源码画成代码地图的流程（uo-init）  
算子来自：CANN ops-transformer  
AscendC-Pilot 版本：`69308572471c4141acecad43d8b059379dc500c0`（`main` 领先 origin 4 个提交；开跑时工作树以当时 HEAD 为准）  
ops-transformer 版本：`4e09c2ec15a414f6e312caf5b3da16cd965af07b`

名单哈希（SHA256）：`ACDE707A1A7B1C167A91E161FA5D096538FB12757DC7A6B8487071C72C76B1A9`

---

## 1. 为了什么

同一份 70 个算子再跑一遍：还能不能画完、画对，分析阶段有没有明显变慢。  
不声称换仓库、换没见过的算子也一定行。

## 2. 实验平台（本机）

- 记录时间：2026-08-16T17:06:46+08:00
- 主机名：DESKTOP-8FM628U
- 系统：Windows 11 家庭中文版，内核 10.0.22000，64 位
- CPU：AMD Ryzen 7 6800H with Radeon Graphics，8 核 / 16 逻辑处理器
- 内存：约 15.2 GB；开跑前可用约 1.8 GB（偏低，墙钟可能受换页影响）
- 磁盘：D: Data NTFS 固定盘，约 274.7 GB / 剩余 144.7 GB；工作目录 `d:\TEST`。本机两块 SSD（Fanxiang S790C 1TB、SKHynix 512GB）
- Python：3.11.5，`E:\anaconda\python.exe`
- Clang：18.1.8（x86_64-pc-windows-msvc）
- libclang：系统 `C:\Program Files\LLVM\bin\libclang.dll`；Python clang 绑定指向 `E:\anaconda\Lib\site-packages\clang\native\libclang.dll`
- 当时是否还在跑别的重任务：是（Cursor 前台仍在；内存可用偏低；杀毒未单独关闭）

## 3. 测了哪些算子

仓里符合条件的正式算子 164 个（须有 `op_kernel/`）。按家族配额抽 70 个（Hamilton，seed=20260816）：attention 25、mc2 18、moe 12、posembedding 6、gmm 3、mhc 3、ffn 2、mamba 1。本轮原名单重跑，中途没有换成别的算子。

母体各家族可抽数量：attention 59、ffn 5、gmm 8、mamba 1、mc2 41、mhc 8、moe 28、posembedding 14。

70 个名单（rel / arch）：

| # | rel | arch | 家族 |
| ---: | --- | --- | --- |
| 1 | attention/fused_infer_attention_score | arch35 | attention |
| 2 | attention/dense_lightning_indexer_grad_kl_loss | arch35 | attention |
| 3 | attention/nsa_selected_attention_infer | arch35 | attention |
| 4 | attention/nsa_compress_attention | arch35 | attention |
| 5 | attention/scatter_pa_cache | arch35 | attention |
| 6 | attention/mla_preprocess | arch35 | attention |
| 7 | attention/gather_pa_kv_cache | arch35 | attention |
| 8 | attention/sparse_lightning_indexer_kl_loss_grad | arch35 | attention |
| 9 | attention/quant_lightning_indexer | arch35 | attention |
| 10 | attention/fused_floyd_attention | arch35 | attention |
| 11 | attention/prompt_flash_attention | arch35 | attention |
| 12 | attention/mla_prolog_v3 | arch35 | attention |
| 13 | attention/sparse_lightning_indexer_grad_kl_loss | arch35 | attention |
| 14 | attention/mixed_quant_sparse_flash_mla | arch35 | attention |
| 15 | attention/nsa_compress | arch35 | attention |
| 16 | attention/nsa_selected_attention_grad | arch35 | attention |
| 17 | attention/inplace_fused_causal_conv1d | arch35 | attention |
| 18 | attention/block_sparse_attention | arch35 | attention |
| 19 | attention/compressor | arch35 | attention |
| 20 | attention/nsa_compress_attention_infer | arch35 | attention |
| 21 | attention/flash_attention_score_grad | arch35 | attention |
| 22 | attention/chunk_gated_delta_rule | arch35 | attention |
| 23 | attention/kv_quant_sparse_flash_attention | arch35 | attention |
| 24 | attention/sparse_flash_mla | arch35 | attention |
| 25 | attention/attention_worker_combine | arch35 | attention |
| 26 | ffn/ffn_worker_batching | arch35 | ffn |
| 27 | ffn/swin_transformer_ln_qkv | arch35 | ffn |
| 28 | gmm/grouped_matmul_swiglu_quant | arch35 | gmm |
| 29 | gmm/grouped_matmul_add | arch35 | gmm |
| 30 | gmm/grouped_matmul | arch35 | gmm |
| 31 | mamba/causal_conv1d | arch35 | mamba |
| 32 | mc2/moe_distribute_dispatch_v2 | arch35 | mc2 |
| 33 | mc2/attention_to_ffn | arch22 | mc2 |
| 34 | mc2/moe_distribute_combine_setup | arch35 | mc2 |
| 35 | mc2/moe_distribute_combine_teardown | arch35 | mc2 |
| 36 | mc2/moe_ep_dispatch | arch35 | mc2 |
| 37 | mc2/moe_distribute_dispatch_teardown | arch35 | mc2 |
| 38 | mc2/matmul_all_reduce_add_rms_norm | arch22 | mc2 |
| 39 | mc2/moe_distribute_combine_v2 | arch35 | mc2 |
| 40 | mc2/matmul_reduce_scatter_v2 | arch35 | mc2 |
| 41 | mc2/quant_reduce_scatter | arch35 | mc2 |
| 42 | mc2/matmul_all_reduce | arch35 | mc2 |
| 43 | mc2/all_gather_matmul_v2 | arch35 | mc2 |
| 44 | mc2/allto_allv_quant_grouped_mat_mul | arch35 | mc2 |
| 45 | mc2/mega_moe | arch35 | mc2 |
| 46 | mc2/moe_update_expert | arch35 | mc2 |
| 47 | mc2/engram_fetch | arch35 | mc2 |
| 48 | mc2/moe_distribute_dispatch | arch35 | mc2 |
| 49 | mc2/quant_all_reduce | arch35 | mc2 |
| 50 | mhc/mhc_pre_backward | arch35 | mhc |
| 51 | mhc/mhc_post_backward | arch35 | mhc |
| 52 | mhc/mhc_sinkhorn | arch35 | mhc |
| 53 | moe/moe_gating_top_k_backward | arch35 | moe |
| 54 | moe/moe_compute_expert_tokens | arch35 | moe |
| 55 | moe/moe_token_unpermute_with_routing_map_grad | arch35 | moe |
| 56 | moe/moe_re_routing | arch35 | moe |
| 57 | moe/moe_token_unpermute_with_routing_map | arch35 | moe |
| 58 | moe/moe_gating_top_k_softmax | arch35 | moe |
| 59 | moe/moe_token_unpermute | arch35 | moe |
| 60 | moe/moe_token_unpermute_grad | arch35 | moe |
| 61 | moe/moe_init_routing_quant_v2 | arch35 | moe |
| 62 | moe/moe_token_unpermute_with_ep | arch35 | moe |
| 63 | moe/moe_init_routing_v2 | arch35 | moe |
| 64 | moe/moe_token_permute_with_ep | arch35 | moe |
| 65 | posembedding/rotary_position_embedding_grad | arch35 | posembedding |
| 66 | posembedding/rope_quant_kvcache | arch35 | posembedding |
| 67 | posembedding/norm_rope_concat_grad | arch35 | posembedding |
| 68 | posembedding/dequant_rope_quant_kvcache | arch35 | posembedding |
| 69 | posembedding/inplace_partial_rotary_mul | arch35 | posembedding |
| 70 | posembedding/inplace_partial_rotary_mul_grad | arch35 | posembedding |

arch 分布：arch35 共 68 个，arch22 共 2 个（`mc2/attention_to_ffn`、`mc2/matmul_all_reduce_add_rms_norm`）。

## 4. 怎样算对

1. 70 个都走完：准备 → 抽图 → 分析 → 落盘 → 自检
2. 产物完整，没有「说不清类型」的节点
3. 该能指到源码的，文件和行号都在
4. 源码里有 packing 的，图上能指回去；源码里没有的两个负例，图上应是 0/0
5. LLM 打开源码核对 Key / Kernel / 输入 / packing，不能只看自动分 ready

## 5. 总结果（对照上轮）

| 看什么 | 上轮 | 本轮 |
| --- | ---: | ---: |
| 算子数 | 70 | 70 |
| 五步都跑完 | 70/70 | **70/70** |
| 产物完整 | 70/70 | **70/70** |
| 自动分 ready | 70/70 | **70/70** |
| 说不清类型的节点 | 0 | **0** |
| 能指到源码 | 全部 | 70 个定位探针均能指到文件（locate_hit_rate=1.0） |
| 源码无 packing、图上也不编造 | 2 个 | **仍是这 2 个**（`0/0`） |
| LLM 复检通过 / 可解释 / 失败 | 通过为主 | **68 / 2 / 0** |
| 70 个合计耗时（秒，各算子五步合计相加） | 3408 | **3424** |

两个负例（源码没有拼 tiling key，图上 packing 为 `0/0`，与源码一致）：

- `ffn/swin_transformer_ln_qkv`
- `posembedding/rope_quant_kvcache`

对照上轮 packing 维数有变化、但本轮五步与自动分仍通过的算子：

| 算子 | 上轮 packing | 本轮 packing |
| --- | --- | --- |
| attention/mla_preprocess | 132/132 | 7/7 |
| attention/block_sparse_attention | 36/36 | 9/9 |
| posembedding/norm_rope_concat_grad | 54/54 | 4/4 |
| mc2/moe_distribute_dispatch_teardown | 16/16 | 13/13 |

## 6. 每个算子的图里有什么（70 行全表）

时间单位：秒。写点为「有 writer 的字段 / TilingField 总数」。LLM 列为打开源码核对 Key / Kernel / 输入 / packing 的结论。

| # | rel | arch | 准备 | 抽图 | 分析 | 落盘 | 自检 | 合计 | 完整 | 自动分 | packing | 节点 | 边 | Buffer | 写点 | LLM |
| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---: | ---: | ---: | --- | --- |
| 1 | attention/fused_infer_attention_score | arch35 | 15.4 | 100.8 | 170.2 | 5.9 | 7.9 | 300.3 | pass | ready | 12/12 | 37497 | 58250 | 2022 | 187/738 | 通过 |
| 2 | attention/dense_lightning_indexer_grad_kl_loss | arch35 | 7.7 | 10.0 | 8.0 | 0.7 | 0.8 | 27.2 | pass | ready | 5/5 | 2795 | 5546 | 167 | 31/36 | 通过 |
| 3 | attention/nsa_selected_attention_infer | arch35 | 8.8 | 9.0 | 6.9 | 0.5 | 0.3 | 25.5 | pass | ready | 2/2 | 1667 | 3452 | 64 | 36/39 | 通过 |
| 4 | attention/nsa_compress_attention | arch35 | 9.5 | 9.0 | 4.6 | 0.4 | 0.2 | 23.9 | pass | ready | 4/4 | 1405 | 2507 | 44 | 32/41 | 通过 |
| 5 | attention/scatter_pa_cache | arch35 | 20.6 | 8.4 | 9.7 | 0.5 | 0.4 | 39.8 | pass | ready | 12/12 | 2617 | 5882 | 129 | 61/40 | 通过 |
| 6 | attention/mla_preprocess | arch35 | 9.5 | 10.5 | 20.1 | 1.7 | 0.6 | 42.4 | pass | ready | 7/7 | 4014 | 7964 | 674 | 64/65 | 通过 |
| 7 | attention/gather_pa_kv_cache | arch35 | 7.1 | 7.8 | 4.7 | 0.3 | 0.2 | 20.2 | pass | ready | 8/8 | 1391 | 2812 | 76 | 43/36 | 通过 |
| 8 | attention/sparse_lightning_indexer_kl_loss_grad | arch35 | 8.7 | 11.3 | 11.3 | 0.7 | 0.4 | 32.5 | pass | ready | 6/6 | 3447 | 5723 | 141 | 39/39 | 通过 |
| 9 | attention/quant_lightning_indexer | arch35 | 10.1 | 17.3 | 11.3 | 0.7 | 1.1 | 40.5 | pass | ready | 6/6 | 3563 | 7232 | 105 | 27/13 | 通过 |
| 10 | attention/fused_floyd_attention | arch35 | 11.9 | 12.7 | 8.4 | 0.8 | 0.4 | 34.3 | pass | ready | 12/12 | 3090 | 5247 | 180 | 70/261 | 通过 |
| 11 | attention/prompt_flash_attention | arch35 | 33.0 | 91.8 | 137.4 | 15.2 | 6.2 | 283.6 | pass | ready | 11/11 | 32408 | 55527 | 1609 | 269/440 | 通过 |
| 12 | attention/mla_prolog_v3 | arch35 | 13.7 | 15.1 | 29.3 | 0.9 | 0.7 | 59.8 | pass | ready | 9/9 | 5049 | 11526 | 327 | 68/45 | 通过 |
| 13 | attention/sparse_lightning_indexer_grad_kl_loss | arch35 | 8.0 | 11.8 | 11.7 | 0.8 | 0.5 | 32.8 | pass | ready | 6/6 | 3328 | 5982 | 165 | 28/29 | 通过 |
| 14 | attention/mixed_quant_sparse_flash_mla | arch35 | 8.5 | 14.9 | 20.8 | 1.0 | 1.3 | 46.7 | pass | ready | 7/7 | 4186 | 7740 | 195 | 50/26 | 通过 |
| 15 | attention/nsa_compress | arch35 | 6.6 | 8.3 | 4.7 | 0.3 | 0.2 | 20.2 | pass | ready | 1/1 | 1030 | 1517 | 46 | 13/13 | 通过 |
| 16 | attention/nsa_selected_attention_grad | arch35 | 11.1 | 12.0 | 9.5 | 0.7 | 0.4 | 33.7 | pass | ready | 6/6 | 2446 | 5020 | 165 | 92/100 | 通过 |
| 17 | attention/inplace_fused_causal_conv1d | arch35 | 22.0 | 12.5 | 20.8 | 0.8 | 1.2 | 57.7 | pass | ready | 4/4 | 5539 | 10952 | 84 | 93/91 | 通过 |
| 18 | attention/block_sparse_attention | arch35 | 12.6 | 28.7 | 29.9 | 1.8 | 0.9 | 73.9 | pass | ready | 9/9 | 7316 | 11274 | 242 | 50/53 | 通过 |
| 19 | attention/compressor | arch35 | 10.0 | 11.8 | 15.2 | 1.2 | 0.6 | 38.8 | pass | ready | 5/5 | 4744 | 8758 | 133 | 30/35 | 通过 |
| 20 | attention/nsa_compress_attention_infer | arch35 | 8.4 | 10.7 | 4.8 | 0.4 | 0.2 | 24.5 | pass | ready | 2/2 | 1317 | 2194 | 42 | 39/42 | 通过 |
| 21 | attention/flash_attention_score_grad | arch35 | 14.7 | 22.3 | 52.7 | 3.7 | 2.2 | 95.7 | pass | ready | 19/19 | 14504 | 27463 | 405 | 197/163 | 通过 |
| 22 | attention/chunk_gated_delta_rule | arch35 | 9.9 | 12.4 | 6.7 | 0.5 | 1.5 | 31.2 | pass | ready | 2/2 | 2041 | 4584 | 265 | 6/24 | 通过 |
| 23 | attention/kv_quant_sparse_flash_attention | arch35 | 8.8 | 15.4 | 19.0 | 1.2 | 0.7 | 45.2 | pass | ready | 6/6 | 4417 | 9001 | 261 | 41/29 | 通过 |
| 24 | attention/sparse_flash_mla | arch35 | 9.0 | 20.7 | 19.6 | 1.1 | 0.7 | 51.1 | pass | ready | 6/6 | 4895 | 10543 | 228 | 69/40 | 通过 |
| 25 | attention/attention_worker_combine | arch35 | 7.0 | 9.7 | 4.3 | 0.3 | 1.5 | 23.0 | pass | ready | 6/6 | 1230 | 2720 | 101 | 17/25 | 通过 |
| 26 | ffn/ffn_worker_batching | arch35 | 19.1 | 8.2 | 15.1 | 0.8 | 0.6 | 43.9 | pass | ready | 2/2 | 3764 | 9115 | 248 | 21/146 | 通过 |
| 27 | ffn/swin_transformer_ln_qkv | arch35 | 8.4 | 10.2 | 2.3 | 0.2 | 0.1 | 21.2 | pass | ready | 0/0 | 770 | 1321 | 52 | 19/25 | 可解释 |
| 28 | gmm/grouped_matmul_swiglu_quant | arch35 | 6.6 | 9.8 | 6.2 | 0.4 | 0.3 | 23.4 | pass | ready | 3/3 | 1768 | 4173 | 166 | 17/17 | 通过 |
| 29 | gmm/grouped_matmul_add | arch35 | 8.7 | 10.8 | 11.4 | 0.6 | 0.2 | 31.9 | pass | ready | 3/3 | 1670 | 2020 | 60 | 8/60 | 通过 |
| 30 | gmm/grouped_matmul | arch35 | 9.6 | 16.9 | 33.9 | 2.5 | 1.4 | 64.3 | pass | ready | 3/3 | 9430 | 20564 | 627 | 143/117 | 通过 |
| 31 | mamba/causal_conv1d | arch35 | 7.6 | 12.5 | 4.4 | 0.3 | 0.2 | 25.2 | pass | ready | 4/4 | 1142 | 2453 | 77 | 39/17 | 通过 |
| 32 | mc2/moe_distribute_dispatch_v2 | arch35 | 29.1 | 13.3 | 37.9 | 2.4 | 3.2 | 85.9 | pass | ready | 5/5 | 8160 | 17808 | 912 | 123/366 | 通过 |
| 33 | mc2/attention_to_ffn | arch22 | 19.1 | 12.0 | 9.3 | 0.4 | 0.2 | 41.1 | pass | ready | 4/4 | 1985 | 2492 | 93 | 27/234 | 通过 |
| 34 | mc2/moe_distribute_combine_setup | arch35 | 22.5 | 9.5 | 12.2 | 0.5 | 0.3 | 45.1 | pass | ready | 1/1 | 2373 | 3329 | 97 | 97/344 | 通过 |
| 35 | mc2/moe_distribute_combine_teardown | arch35 | 22.5 | 10.4 | 13.0 | 0.5 | 0.3 | 46.8 | pass | ready | 1/1 | 2352 | 3191 | 68 | 96/336 | 通过 |
| 36 | mc2/moe_ep_dispatch | arch35 | 23.3 | 13.2 | 12.2 | 0.5 | 0.4 | 49.7 | pass | ready | 5/5 | 2681 | 3642 | 72 | 100/346 | 通过 |
| 37 | mc2/moe_distribute_dispatch_teardown | arch35 | 19.4 | 10.0 | 12.8 | 0.5 | 0.3 | 43.1 | pass | ready | 13/13 | 2654 | 3849 | 70 | 93/340 | 通过 |
| 38 | mc2/matmul_all_reduce_add_rms_norm | arch22 | 25.5 | 12.9 | 38.8 | 1.4 | 0.8 | 79.5 | pass | ready | 17/17 | 5358 | 10029 | 382 | 37/403 | 通过 |
| 39 | mc2/moe_distribute_combine_v2 | arch35 | 30.4 | 12.0 | 28.1 | 1.5 | 0.9 | 72.9 | pass | ready | 3/3 | 5756 | 11017 | 457 | 117/365 | 通过 |
| 40 | mc2/matmul_reduce_scatter_v2 | arch35 | 35.2 | 16.4 | 30.5 | 1.1 | 0.6 | 83.9 | pass | ready | 8/8 | 4346 | 6461 | 83 | 157/372 | 通过 |
| 41 | mc2/quant_reduce_scatter | arch35 | 23.3 | 10.0 | 11.0 | 0.4 | 0.3 | 45.1 | pass | ready | 1/1 | 2371 | 2884 | 38 | 79/327 | 通过 |
| 42 | mc2/matmul_all_reduce | arch35 | 31.6 | 18.6 | 39.1 | 1.4 | 0.8 | 91.5 | pass | ready | 14/14 | 5895 | 11222 | 271 | 134/498 | 通过 |
| 43 | mc2/all_gather_matmul_v2 | arch35 | 35.6 | 14.5 | 28.1 | 0.9 | 0.5 | 79.7 | pass | ready | 6/6 | 4408 | 6455 | 85 | 164/498 | 通过 |
| 44 | mc2/allto_allv_quant_grouped_mat_mul | arch35 | 25.9 | 12.2 | 19.3 | 0.6 | 0.4 | 58.4 | pass | ready | 3/3 | 3699 | 4710 | 52 | 150/441 | 通过 |
| 45 | mc2/mega_moe | arch35 | 19.8 | 14.0 | 16.7 | 1.1 | 0.6 | 52.4 | pass | ready | 5/5 | 4213 | 7630 | 177 | 114/357 | 通过 |
| 46 | mc2/moe_update_expert | arch35 | 7.6 | 9.5 | 3.1 | 0.3 | 0.2 | 20.7 | pass | ready | 2/2 | 1193 | 1786 | 60 | 15/139 | 通过 |
| 47 | mc2/engram_fetch | arch35 | 8.4 | 12.5 | 3.1 | 0.3 | 0.2 | 24.5 | pass | ready | 1/1 | 1080 | 1596 | 62 | 12/140 | 通过 |
| 48 | mc2/moe_distribute_dispatch | arch35 | 23.6 | 10.4 | 15.4 | 0.6 | 0.4 | 50.5 | pass | ready | 5/5 | 2832 | 4061 | 165 | 94/341 | 通过 |
| 49 | mc2/quant_all_reduce | arch35 | 22.8 | 10.0 | 11.2 | 0.4 | 0.3 | 44.8 | pass | ready | 1/1 | 2229 | 2545 | 37 | 79/327 | 通过 |
| 50 | mhc/mhc_pre_backward | arch35 | 10.2 | 11.2 | 5.3 | 0.6 | 0.3 | 27.6 | pass | ready | 1/1 | 1590 | 3250 | 141 | 8/10 | 通过 |
| 51 | mhc/mhc_post_backward | arch35 | 10.3 | 9.2 | 6.1 | 0.3 | 0.2 | 26.2 | pass | ready | 1/1 | 903 | 1787 | 74 | 15/16 | 通过 |
| 52 | mhc/mhc_sinkhorn | arch35 | 8.3 | 9.5 | 4.3 | 0.3 | 0.2 | 22.7 | pass | ready | 1/1 | 914 | 2000 | 45 | 11/11 | 通过 |
| 53 | moe/moe_gating_top_k_backward | arch35 | 5.9 | 8.7 | 4.3 | 0.2 | 0.2 | 19.4 | pass | ready | 1/1 | 800 | 1580 | 41 | 16/16 | 通过 |
| 54 | moe/moe_compute_expert_tokens | arch35 | 5.6 | 10.5 | 4.2 | 0.3 | 0.2 | 20.9 | pass | ready | 3/3 | 1213 | 2417 | 57 | 38/36 | 通过 |
| 55 | moe/moe_token_unpermute_with_routing_map_grad | arch35 | 5.6 | 6.3 | 4.8 | 0.4 | 0.2 | 17.4 | pass | ready | 6/6 | 1301 | 2831 | 88 | 27/21 | 通过 |
| 56 | moe/moe_re_routing | arch35 | 7.6 | 9.9 | 7.7 | 0.3 | 0.2 | 25.7 | pass | ready | 6/6 | 1101 | 2042 | 77 | 35/28 | 通过 |
| 57 | moe/moe_token_unpermute_with_routing_map | arch35 | 7.0 | 6.7 | 4.4 | 0.3 | 0.2 | 18.8 | pass | ready | 3/3 | 1458 | 2843 | 115 | 67/41 | 通过 |
| 58 | moe/moe_gating_top_k_softmax | arch35 | 9.4 | 9.3 | 10.4 | 0.4 | 0.3 | 30.0 | pass | ready | 6/6 | 1762 | 4003 | 159 | 83/88 | 通过 |
| 59 | moe/moe_token_unpermute | arch35 | 7.1 | 8.6 | 2.7 | 0.2 | 0.1 | 18.8 | pass | ready | 12/12 | 650 | 1159 | 23 | 25/12 | 通过 |
| 60 | moe/moe_token_unpermute_grad | arch35 | 5.5 | 6.0 | 2.7 | 0.2 | 0.1 | 14.5 | pass | ready | 4/4 | 701 | 1272 | 32 | 21/17 | 通过 |
| 61 | moe/moe_init_routing_quant_v2 | arch35 | 90.6 | 11.4 | 15.4 | 1.2 | 1.0 | 119.7 | pass | ready | 8/8 | 4783 | 13068 | 456 | 53/58 | 通过 |
| 62 | moe/moe_token_unpermute_with_ep | arch35 | 7.1 | 10.4 | 3.1 | 0.2 | 0.2 | 21.1 | pass | ready | 4/4 | 787 | 1492 | 31 | 30/15 | 通过 |
| 63 | moe/moe_init_routing_v2 | arch35 | 25.9 | 14.9 | 11.1 | 0.8 | 0.6 | 53.5 | pass | ready | 9/9 | 2814 | 6747 | 230 | 27/41 | 通过 |
| 64 | moe/moe_token_permute_with_ep | arch35 | 7.5 | 9.4 | 10.1 | 0.4 | 0.4 | 27.9 | pass | ready | 8/8 | 1898 | 3760 | 95 | 66/74 | 通过 |
| 65 | posembedding/rotary_position_embedding_grad | arch35 | 25.7 | 14.1 | 17.6 | 0.7 | 3.1 | 61.3 | pass | ready | 6/6 | 3222 | 7259 | 173 | 96/97 | 通过 |
| 66 | posembedding/rope_quant_kvcache | arch35 | 5.8 | 6.0 | 2.6 | 0.2 | 0.1 | 14.8 | pass | ready | 0/0 | 648 | 1283 | 67 | 7/7 | 可解释 |
| 67 | posembedding/norm_rope_concat_grad | arch35 | 6.4 | 13.9 | 6.1 | 0.4 | 0.3 | 27.2 | pass | ready | 4/4 | 1636 | 3248 | 119 | 22/22 | 通过 |
| 68 | posembedding/dequant_rope_quant_kvcache | arch35 | 5.8 | 6.5 | 6.6 | 0.3 | 0.3 | 19.6 | pass | ready | 4/4 | 1262 | 2602 | 142 | 38/22 | 通过 |
| 69 | posembedding/inplace_partial_rotary_mul | arch35 | 8.8 | 10.4 | 15.7 | 1.0 | 0.9 | 36.9 | pass | ready | 18/18 | 5261 | 12469 | 427 | 63/61 | 通过 |
| 70 | posembedding/inplace_partial_rotary_mul_grad | arch35 | 8.1 | 11.9 | 8.8 | 0.4 | 0.3 | 29.6 | pass | ready | 7/7 | 1556 | 3054 | 75 | 38/38 | 通过 |

自然语言摘要：

- 节点最多：`attention/fused_infer_attention_score`（37497 节点 / 58250 边；运算 7928；图上 EnQue 106、DataCopy 219、SetFlag 322，均带行号）。上轮同一算子 34782 节点 / 55426 边。
- 节点次多：`attention/prompt_flash_attention`（32408 节点 / 55527 边；运算 6011；packing 11/11）。
- 节点最少：`posembedding/rope_quant_kvcache`（648 节点 / 1283 边），这个算子源码里没有拼 tiling key。
- TilingKey 最多：`attention/flash_attention_score_grad`（19 维，packing `19/19`，Buffer 405）。
- Buffer 最多：IFA（2022）。
- packing 为 `0/0` 的两个：`ffn/swin_transformer_ln_qkv`、`posembedding/rope_quant_kvcache`。

各家族各举一个（均 LLM 通过，负例家族用可解释的那个）：

| 家族 | 算子 | 节点 | 边 | TilingKey / packing | Buffer | 写点 |
| --- | --- | ---: | ---: | --- | ---: | --- |
| attention | flash_attention_score_grad | 14504 | 27463 | 19 / 19/19 | 405 | 197/163 |
| ffn | ffn_worker_batching | 3764 | 9115 | 2 / 2/2 | 248 | 21/146 |
| gmm | grouped_matmul | 9430 | 20564 | 3 / 3/3 | 627 | 143/117 |
| mamba | causal_conv1d | 1142 | 2453 | 4 / 4/4 | 77 | 39/17 |
| mc2 | attention_to_ffn（arch22） | 1985 | 2492 | 4 / 4/4 | 93 | 27/234 |
| mhc | mhc_sinkhorn | 914 | 2000 | 1 / 1/1 | 45 | 11/11 |
| moe | moe_init_routing_v2 | 2814 | 6747 | 9 / 9/9 | 230 | 27/41 |
| posembedding | rope_quant_kvcache | 648 | 1283 | 0 / 0/0 | 67 | 7/7 |

## 7. 图规模与 API 明细（70 行）

列说明：OTHER=说不清类型的节点数；Kernel/输入/输出/运算为图上实体数；调用为图上 CALLS 边数（IFA/PFA/mla_prolog_v3/inplace/teardown 用产物 `relations_by_kind.CALLS`；其余沿用本轮流水线导出值）。

| # | rel | OTHER | TilingKey | packing | Kernel | 输入 | 输出 | 运算 | 调用 | 流水线 |
| ---: | --- | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | attention/fused_infer_attention_score | 0 | 12 | 12/12 | 1 | 47 | 2 | 7928 | 21498 | 过 |
| 2 | attention/dense_lightning_indexer_grad_kl_loss | 0 | 5 | 5/5 | 1 | 19 | 4 | 843 | 515 | 过 |
| 3 | attention/nsa_selected_attention_infer | 0 | 2 | 2/2 | 1 | 16 | 1 | 357 | 216 | 过 |
| 4 | attention/nsa_compress_attention | 0 | 4 | 4/4 | 1 | 16 | 4 | 314 | 150 | 过 |
| 5 | attention/scatter_pa_cache | 0 | 12 | 12/12 | 1 | 7 | 1 | 505 | 269 | 过 |
| 6 | attention/mla_preprocess | 0 | 7 | 7/7 | 1 | 37 | 4 | 1259 | 567 | 过 |
| 7 | attention/gather_pa_kv_cache | 0 | 8 | 8/8 | 1 | 9 | 2 | 279 | 155 | 过 |
| 8 | attention/sparse_lightning_indexer_kl_loss_grad | 0 | 6 | 6/6 | 1 | 16 | 4 | 854 | 186 | 过 |
| 9 | attention/quant_lightning_indexer | 0 | 6 | 6/6 | 1 | 18 | 1 | 1365 | 579 | 过 |
| 10 | attention/fused_floyd_attention | 0 | 12 | 12/12 | 1 | 7 | 3 | 748 | 344 | 过 |
| 11 | attention/prompt_flash_attention | 0 | 11 | 11/11 | 2 | 20 | 1 | 6011 | 17851 | 过 |
| 12 | attention/mla_prolog_v3 | 0 | 9 | 9/9 | 1 | 33 | 7 | 1650 | 3110 | 过 |
| 13 | attention/sparse_lightning_indexer_grad_kl_loss | 0 | 6 | 6/6 | 1 | 18 | 4 | 915 | 234 | 过 |
| 14 | attention/mixed_quant_sparse_flash_mla | 0 | 7 | 7/7 | 1 | 30 | 2 | 794 | 281 | 过 |
| 15 | attention/nsa_compress | 0 | 1 | 1/1 | 1 | 7 | 1 | 114 | 36 | 过 |
| 16 | attention/nsa_selected_attention_grad | 0 | 6 | 6/6 | 1 | 17 | 3 | 743 | 423 | 过 |
| 17 | attention/inplace_fused_causal_conv1d | 0 | 4 | 4/4 | 1 | 19 | 2 | 3069 | 4131 | 过 |
| 18 | attention/block_sparse_attention | 0 | 9 | 9/9 | 4 | 22 | 2 | 1815 | 856 | 过 |
| 19 | attention/compressor | 0 | 5 | 5/5 | 1 | 13 | 2 | 1826 | 682 | 过 |
| 20 | attention/nsa_compress_attention_infer | 0 | 2 | 2/2 | 1 | 19 | 2 | 239 | 180 | 过 |
| 21 | attention/flash_attention_score_grad | 0 | 19 | 19/19 | 1 | 41 | 7 | 4073 | 1251 | 过 |
| 22 | attention/chunk_gated_delta_rule | 0 | 2 | 2/2 | 1 | 8 | 2 | 728 | 283 | 过 |
| 23 | attention/kv_quant_sparse_flash_attention | 0 | 6 | 6/6 | 1 | 22 | 1 | 825 | 315 | 过 |
| 24 | attention/sparse_flash_mla | 0 | 6 | 6/6 | 1 | 28 | 2 | 767 | 261 | 过 |
| 25 | attention/attention_worker_combine | 0 | 6 | 6/6 | 1 | 6 | 2 | 453 | 193 | 过 |
| 26 | ffn/ffn_worker_batching | 0 | 2 | 2/2 | 1 | 6 | 8 | 1788 | 586 | 过 |
| 27 | ffn/swin_transformer_ln_qkv | 0 | 0 | 0/0 | 1 | 10 | 3 | 165 | 71 | 过 |
| 28 | gmm/grouped_matmul_swiglu_quant | 0 | 3 | 3/3 | 1 | 8 | 2 | 682 | 374 | 过 |
| 29 | gmm/grouped_matmul_add | 0 | 3 | 3/3 | 1 | 8 | 1 | 173 | 11 | 过 |
| 30 | gmm/grouped_matmul | 0 | 3 | 3/3 | 1 | 17 | 1 | 2808 | 1290 | 过 |
| 31 | mamba/causal_conv1d | 0 | 4 | 4/4 | 1 | 10 | 2 | 168 | 85 | 过 |
| 32 | mc2/moe_distribute_dispatch_v2 | 0 | 5 | 5/5 | 1 | 25 | 7 | 2580 | 924 | 过 |
| 33 | mc2/attention_to_ffn | 0 | 4 | 4/4 | 1 | 17 | 0 | 223 | 95 | 过 |
| 34 | mc2/moe_distribute_combine_setup | 0 | 1 | 1/1 | 1 | 14 | 2 | 226 | 86 | 过 |
| 35 | mc2/moe_distribute_combine_teardown | 0 | 1 | 1/1 | 1 | 19 | 2 | 217 | 94 | 过 |
| 36 | mc2/moe_ep_dispatch | 0 | 5 | 5/5 | 1 | 14 | 3 | 324 | 119 | 过 |
| 37 | mc2/moe_distribute_dispatch_teardown | 0 | 13 | 13/13 | 1 | 16 | 4 | 328 | 1094 | 过 |
| 38 | mc2/matmul_all_reduce_add_rms_norm | 0 | 17 | 17/17 | 1 | 15 | 2 | 1519 | 612 | 过 |
| 39 | mc2/moe_distribute_combine_v2 | 0 | 3 | 3/3 | 1 | 36 | 1 | 1425 | 500 | 过 |
| 40 | mc2/matmul_reduce_scatter_v2 | 0 | 8 | 8/8 | 1 | 17 | 2 | 579 | 327 | 过 |
| 41 | mc2/quant_reduce_scatter | 0 | 1 | 1/1 | 1 | 6 | 1 | 193 | 93 | 过 |
| 42 | mc2/matmul_all_reduce | 0 | 14 | 14/14 | 4 | 20 | 1 | 874 | 356 | 过 |
| 43 | mc2/all_gather_matmul_v2 | 0 | 6 | 6/6 | 1 | 18 | 3 | 491 | 290 | 过 |
| 44 | mc2/allto_allv_quant_grouped_mat_mul | 0 | 3 | 3/3 | 1 | 25 | 3 | 149 | 50 | 过 |
| 45 | mc2/mega_moe | 0 | 5 | 5/5 | 1 | 36 | 2 | 1382 | 446 | 过 |
| 46 | mc2/moe_update_expert | 0 | 2 | 2/2 | 1 | 8 | 2 | 143 | 58 | 过 |
| 47 | mc2/engram_fetch | 0 | 1 | 1/1 | 1 | 8 | 6 | 135 | 48 | 过 |
| 48 | mc2/moe_distribute_dispatch | 0 | 5 | 5/5 | 1 | 18 | 7 | 322 | 126 | 过 |
| 49 | mc2/quant_all_reduce | 0 | 1 | 1/1 | 1 | 6 | 1 | 195 | 95 | 过 |
| 50 | mhc/mhc_pre_backward | 0 | 1 | 1/1 | 1 | 13 | 5 | 470 | 148 | 过 |
| 51 | mhc/mhc_post_backward | 0 | 1 | 1/1 | 1 | 5 | 4 | 189 | 95 | 过 |
| 52 | mhc/mhc_sinkhorn | 0 | 1 | 1/1 | 1 | 4 | 3 | 282 | 139 | 过 |
| 53 | moe/moe_gating_top_k_backward | 0 | 1 | 1/1 | 1 | 7 | 1 | 195 | 53 | 过 |
| 54 | moe/moe_compute_expert_tokens | 0 | 3 | 3/3 | 1 | 2 | 1 | 324 | 127 | 过 |
| 55 | moe/moe_token_unpermute_with_routing_map_grad | 0 | 6 | 6/6 | 1 | 8 | 2 | 427 | 263 | 过 |
| 56 | moe/moe_re_routing | 0 | 6 | 6/6 | 1 | 5 | 4 | 149 | 79 | 过 |
| 57 | moe/moe_token_unpermute_with_routing_map | 0 | 3 | 3/3 | 1 | 6 | 4 | 365 | 111 | 过 |
| 58 | moe/moe_gating_top_k_softmax | 0 | 6 | 6/6 | 1 | 3 | 3 | 567 | 217 | 过 |
| 59 | moe/moe_token_unpermute | 0 | 12 | 12/12 | 1 | 5 | 1 | 117 | 46 | 过 |
| 60 | moe/moe_token_unpermute_grad | 0 | 4 | 4/4 | 1 | 6 | 2 | 169 | 125 | 过 |
| 61 | moe/moe_init_routing_quant_v2 | 0 | 8 | 8/8 | 1 | 11 | 5 | 2149 | 917 | 过 |
| 62 | moe/moe_token_unpermute_with_ep | 0 | 4 | 4/4 | 1 | 7 | 1 | 195 | 100 | 过 |
| 63 | moe/moe_init_routing_v2 | 0 | 9 | 9/9 | 1 | 8 | 4 | 882 | 323 | 过 |
| 64 | moe/moe_token_permute_with_ep | 0 | 8 | 8/8 | 1 | 6 | 3 | 481 | 160 | 过 |
| 65 | posembedding/rotary_position_embedding_grad | 0 | 6 | 6/6 | 1 | 5 | 3 | 999 | 360 | 过 |
| 66 | posembedding/rope_quant_kvcache | 0 | 0 | 0/0 | 1 | 11 | 5 | 214 | 101 | 过 |
| 67 | posembedding/norm_rope_concat_grad | 0 | 4 | 4/4 | 1 | 25 | 14 | 462 | 158 | 过 |
| 68 | posembedding/dequant_rope_quant_kvcache | 0 | 4 | 4/4 | 1 | 18 | 5 | 371 | 146 | 过 |
| 69 | posembedding/inplace_partial_rotary_mul | 0 | 18 | 18/18 | 1 | 5 | 1 | 1715 | 729 | 过 |
| 70 | posembedding/inplace_partial_rotary_mul_grad | 0 | 7 | 7/7 | 1 | 5 | 1 | 216 | 88 | 过 |

IFA 图上 kernel API（均 with_span = n，precision_gaps 为空）：

| API | 图上 n | 源码计数 |
| --- | ---: | ---: |
| EnQue | 106 | 37 |
| DeQue | 109 | 43 |
| InitBuffer | 397 | 78 |
| DataCopyPad | 102 | 67 |
| DataCopy | 219 | 196 |
| Copy | 6 | 2 |
| Cast | 91 | 45 |
| SetFlag | 322 | 181 |
| WaitFlag | 322 | 191 |
| SetGlobalBuffer | 153 | 70 |
| LoadAlign | 616 | 0（调用在 `attention/common/op_kernel/arch35/vf/`，本目录无 `LoadAlign`） |
| LoadData | 14 | 14 |

PFA 图上：运算 6011；EnQue 47；packing 11/11；host_check 1146/1146。  
mla_prolog_v3：运算 1650；packing 9/9；host_check 71/71。  
inplace_fused_causal_conv1d：运算 3069；EnQue 13；packing 4/4；host_check 105/105。  
moe_distribute_dispatch_teardown：运算 328；packing 13/13；host_check 118/118。

## 8. LLM 复检（图和源码一不一致）

- 覆盖：70/70
- 通过 / 可解释 / 失败：**68 / 2 / 0**
- 可解释点名：`ffn/swin_transformer_ln_qkv`、`posembedding/rope_quant_kvcache`（源码没有 packing，图上也不该有）

抽查加细（图给的行 vs 源码实际那一行）：

| 算子 | 核对 | 结果 |
| --- | --- | --- |
| IFA | TilingKey `InOutLayoutType` 在 `fused_infer_attention_score/op_kernel/fused_infer_attention_score_template_tiling_key.h:48` 的 `ASCENDC_TPL_UINT_DECL`；Kernel `fused_infer_attention_score` 在 `..._apt.cpp:42` 的 `__global__`；Input `query` 在 `..._def.cpp:26` 的 `this->Input("query")`；TilingField `inputParamsRegbase` 在 `common/op_kernel/arch35/flash_attention_score_tiling_regbase.h:1066` | 这几项对上。图上 EnQue/DataCopy/SetFlag 均有运算点且带行号，precision_gaps 为空。 |
| PFA | packing 11/11；Kernel 2 个；运算 6011 | 通过 |
| FAG | Kernel / Input / Key 对上；packing `19/19` | 通过 |
| mla_prolog_v3 | packing 9/9；Kernel 1；输入 33 | 通过 |
| inplace_fused_causal_conv1d | packing 4/4；Kernel `inplace_fused_causal_conv1d`；输入 19 | 通过 |
| teardown | packing 13/13；Kernel 1；输入 16 | 通过 |
| mla_preprocess | Key `inDtype`、Kernel、Input `input` 对上 | 通过；packing 为 7/7 |
| 两个 0/0 | Kernel `__global__` 和 Input 在 proto 里能看到；没有 TilingKey 探针 | 可解释 |
| arch22 `attention_to_ffn` | Key `TILINGKEY_QUANT`、Kernel 在 `op_kernel/arch22/...cpp:30` | 通过 |
| arch22 `matmul_all_reduce_add_rms_norm` | Kernel 在 arch22 cpp:41 | 通过 |
| `rotary_position_embedding_grad` | Key 名叫 `IsContiguous`，定位行是 `REDUCE_TPL_KEY_DECL()` 宏，名字在公共 reduce 头里展开 | 通过（宏展开，不是写错图） |

## 9. 耗时

最重的 IFA（fused_infer_attention_score）分析阶段：

| 哪一轮 | 秒 |
| --- | ---: |
| 更早一次 | 201.8 |
| 上轮 70 实验 | 239.9 |
| 本轮 | **170.2** |

相对 201.8s：−15.7%（变快）  
相对 239.9s：−29.1%（变快）  
门禁：变慢不到 20% 算过。相对两条对照都过。本轮 IFA 运算点 7928，图完整。

分析最慢的 5 个算子（上轮 vs 本轮）：

| 算子 | 上轮分析 s | 本轮分析 s |
| --- | ---: | ---: |
| fused_infer_attention_score | 239.9 | 170.2 |
| prompt_flash_attention | 193.3 | 137.4 |
| flash_attention_score_grad | 64.8 | 52.7 |
| matmul_all_reduce | 38.6 | 39.1 |
| matmul_all_reduce_add_rms_norm | 38.2 | 38.8 |

70 个合计（各算子五步合计相加）：3408s → 3424s。  
准备最慢：`moe/moe_init_routing_quant_v2` 90.6s。  
合计最慢：IFA 300.3s，其次 PFA 283.6s。  
合计最快：`moe/moe_token_unpermute_grad` 14.5s。

## 10. 结论

这 70 个算子五步 70/70，产物完整 70/70，自动分 ready 70/70，说不清类型的节点 0，LLM 复检 68 通过、2 可解释、0 失败。两个「源码本来就没有 packing」的负例仍然是 `0/0`，没有编造。IFA 分析 170.2s（上轮 239.9s），运算点 7928；PFA 分析 137.4s，运算点 6011。限制：只在这一个仓、这一份已经见过的名单上；68 个 arch35、2 个 arch22；LLM 复检是抽 Key/Kernel/输入/packing 对源，不是逐节点人工审。`mla_preprocess` / `block_sparse_attention` / `norm_rope_concat_grad` 的 packing 维数相对上轮变少，但本轮仍完整通过。

## 附录 A. 怎么复现

- AscendC-Pilot commit：`69308572471c4141acecad43d8b059379dc500c0`
- ops-transformer commit：`4e09c2ec15a414f6e312caf5b3da16cd965af07b`
- 名单：复用 pass70-20260816 冻结的 70 条（seed=20260816）
- sample.json SHA256：`ACDE707A1A7B1C167A91E161FA5D096538FB12757DC7A6B8487071C72C76B1A9`
- 命令：

```powershell
cd d:\TEST\AscendC-Pilot
$env:UO_OPS_ROOT = "d:\TEST\ops-transformer"
$env:UO_GEN_OUT = "d:\TEST\AscendC-Pilot\artifacts\uo-init-generalization\pass70-20260816-perf"
$env:UO_GEN_CASES_FILE = "d:\TEST\AscendC-Pilot\artifacts\uo-init-generalization\pass70-20260816\sample.json"
$env:PYTHONUNBUFFERED = "1"
python engines/understand-operator/tools/uo_init_generalization.py
```

- 本机环境：见第 2 节
- 测量日期：2026-08-16（UTC+8）
