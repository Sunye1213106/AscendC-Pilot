# 算子理解冷启动复测报告（性能优化后）

实验编号：pass70-20260816-perf  
对照：pass70-20260816（同一份 70 个算子，不是新抽的）  
日期：2026-08-16  
测的是：AscendC-Pilot 里把算子源码画成代码地图的流程（uo-init）  
算子来自：CANN ops-transformer  
AscendC-Pilot 版本：`69308572471c4141acecad43d8b059379dc500c0`（`main` 领先 origin 4 个提交；开跑时工作树以当时 HEAD 为准）  
ops-transformer 版本：`4e09c2ec15a414f6e312caf5b3da16cd965af07b`  
开跑后有没有为这 70 个改代码：**无**

产物：[`artifacts/uo-init-generalization/pass70-20260816-perf/`](../../artifacts/uo-init-generalization/pass70-20260816-perf/)（`sample.json` / `results.json` / `ledger.md` / `inspect/` / `pass70-20260816-perf.csv` / `platform.md`）。

---

## 1. 为了什么

同一份 70 个算子再跑一遍：优化之后还能不能画完、画对，分析阶段有没有明显变慢。  
不声称换仓库、换没见过的算子也一定行。

## 2. 实验平台（本机）

详见 [`platform.md`](../../artifacts/uo-init-generalization/pass70-20260816-perf/platform.md)。

- 系统：Windows 11 家庭中文版，内核 10.0.22000，64 位；主机 `DESKTOP-8FM628U`
- CPU / 核数：AMD Ryzen 7 6800H，8 核 / 16 逻辑处理器
- 内存：约 15.2 GB；开跑前可用约 1.8 GB（偏紧，墙钟可能受换页影响）
- 磁盘：D: Data NTFS，约 274.7 GB / 剩余 144.7 GB；工作目录 `d:\TEST`；本机两块 SSD
- Python：3.11.5，`E:\anaconda\python.exe`
- Clang / libclang：Clang 18.1.8；系统 `C:\Program Files\LLVM\bin\libclang.dll`；Python 绑定指向 `E:\anaconda\Lib\site-packages\clang\native\libclang.dll`
- 当时是否还在跑别的重任务：是（Cursor 前台仍在；内存可用偏低）
- 开始 / 结束时间：2026-08-16 17:07:24 ～ 17:58:33（UTC+8）

## 3. 测了哪些算子

当时仓里符合条件的正式算子 164 个。上轮按家族配额抽了 70 个（attention 25、mc2 18、moe 12、posembedding 6、gmm 3、mhc 3、ffn 2、mamba 1）。本轮原名单重跑，中途没有换成别的算子。

名单哈希（SHA256）：`ACDE707A1A7B1C167A91E161FA5D096538FB12757DC7A6B8487071C72C76B1A9`

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
| 五步都跑完 | 70/70 | **65/70** |
| 产物完整 | 70/70 | 66/70（1 个准备失败无产物；3 个完整性失败） |
| 自动分 ready | 70/70 | **65/70** |
| 说不清类型的节点 | 0 | **0** |
| 能指到源码 | 全部 | 有产物的 69 个里，定位探针大多能指到文件；5 个整体复检失败 |
| 源码无 packing、图上也不编造 | 2 个 | **仍是这 2 个**（`0/0`） |
| LLM 复检通过 / 可解释 / 失败 | 上轮 inspect 以通过为主 | **63 / 2 / 5** |
| 70 个合计耗时（秒） | 3408 | **3069** |

失败算子（没有事后换样）：

| 算子 | 卡在哪 | 人话 |
| --- | --- | --- |
| `attention/fused_infer_attention_score` | 质量门禁 | Key/Kernel/输入能对上源码，但图上几乎没有 EnQue/DataCopy 等运算点（运算 13、调用 0；上轮运算约 7896）。图比上轮少了约 9000 个节点。 |
| `attention/prompt_flash_attention` | 准备 | `SCOPE_VALIDATE_BLOCKED`，后面没画图。上轮是能跑完的。 |
| `attention/mla_prolog_v3` | 自检 | packing 从上轮 `9/9` 变成 `0/9`（拼 key 的代码在兄弟算子 `mla_prolog` 的 host 里，本轮没挂上）。 |
| `attention/inplace_fused_causal_conv1d` | 自检 | Key/Kernel/输入能对上，产物完整性失败。 |
| `mc2/moe_distribute_dispatch_teardown` | 自检 | packing 从上轮 `16/16` 变成 `4/16`，完整性失败。 |

另外几个**五步仍过、但 packing 明显变少**（自动分仍是 ready，报告里必须写出来）：

- `attention/mla_preprocess`：`132/132` → `7/7`
- `attention/block_sparse_attention`：`36/36` → `9/9`
- `posembedding/norm_rope_concat_grad`：`54/54` → `4/4`

## 6. 每个算子的图里有什么

70 行全表见 [`ledger.md`](../../artifacts/uo-init-generalization/pass70-20260816-perf/ledger.md) 和 [`pass70-20260816-perf.csv`](../../artifacts/uo-init-generalization/pass70-20260816-perf/pass70-20260816-perf.csv)。

人话摘要：

- 节点最多：`attention/fused_infer_attention_score`（25580 节点 / 31868 边）。它大，是因为 host 侧 tiling、字段、分支特别多；但本轮 kernel 运算几乎没画上，所以「大」主要在 host，不能理解成「kernel 图画全了」。上轮同一算子是 34782 节点 / 55426 边。
- 节点最少：`posembedding/rope_quant_kvcache`（648 节点 / 1283 边），这个算子源码里没有拼 tiling key。
- TilingKey 最多：`attention/flash_attention_score_grad`（19 维，packing `19/19`，Buffer 405）。
- Buffer 最多：仍是 IFA（1132），数字大但和「运算点几乎为空」同时出现，说明缓冲区识别和 kernel 调用链不是一回事。
- packing 为 `0/0` 的两个：`ffn/swin_transformer_ln_qkv`、`posembedding/rope_quant_kvcache`。

各家族各举一个（均 LLM 通过）：

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

## 7. LLM 复检（图和源码一不一致）

- 覆盖：70/70（每份见 [`inspect/`](../../artifacts/uo-init-generalization/pass70-20260816-perf/inspect/)）
- 通过 / 可解释 / 失败：**63 / 2 / 5**
- 失败点名：`fused_infer_attention_score`、`prompt_flash_attention`、`mla_prolog_v3`、`inplace_fused_causal_conv1d`、`moe_distribute_dispatch_teardown`
- 可解释点名：`ffn/swin_transformer_ln_qkv`、`posembedding/rope_quant_kvcache`（源码没有 packing，图上也不该有）

抽查加细（图给的行 vs 源码实际那一行）：

| 算子 | 核对 | 结果 |
| --- | --- | --- |
| IFA | TilingKey `InOutLayoutType` 在 `..._template_tiling_key.h:48` 的 `ASCENDC_TPL_UINT_DECL`；Kernel `fused_infer_attention_score` 在 `..._apt.cpp:42`；Input `query` 在 `..._def.cpp:26` | 这三项对上。失败原因是源码里大量 EnQue/DataCopy/SetFlag，图上运算点几乎为 0。 |
| FAG | Kernel / Input / Key 对上；packing `19/19` | 通过 |
| mla_preprocess | Key `inDtype`、Kernel、Input `input` 对上 | 通过；但 packing 从 132 维掉到 7 维，图比上轮瘦一圈 |
| 两个 0/0 | Kernel `__global__` 和 Input 在 proto 里能看到；没有 TilingKey 探针 | 可解释 |
| arch22 `attention_to_ffn` | Key `TILINGKEY_QUANT`、Kernel 在 `op_kernel/arch22/...cpp:30` | 通过 |
| arch22 `matmul_all_reduce_add_rms_norm` | Kernel 在 arch22 cpp:41 | 通过 |
| `rotary_position_embedding_grad` | Key 名叫 `IsContiguous`，定位行是 `REDUCE_TPL_KEY_DECL()` 宏，名字在公共 reduce 头里展开 | 通过（宏展开，不是写错图） |

**70 个自动分 ready 但 LLM 有失败，总体仍算质量没过。** 本轮连自动分都没有 70/70，质量结论是**相对上轮回退**。

## 8. 耗时

最重的 IFA（fused_infer_attention_score）分析阶段：

| 哪一轮 | 秒 |
| --- | ---: |
| 更早一次 | 201.8 |
| 上轮 70 实验 | 239.9 |
| 本轮 | **137.0** |

相对 201.8s 变慢：**-32.1%**（变快）  
相对 239.9s 变慢：**-42.9%**（变快）  
门禁：变慢不到 20% 算过。若只看秒数，相对两条对照都过。  
**不能当成优化成功**：变快的同时 IFA 图画残了（运算点丢失），属于用更小的图换时间，和「同样的图更快」不是一回事。

分析最慢的 5 个算子（上轮 vs 本轮）：

| 算子 | 上轮分析 s | 本轮分析 s |
| --- | ---: | ---: |
| fused_infer_attention_score | 239.9 | 137.0 |
| flash_attention_score_grad | 64.8 | 52.7 |
| matmul_all_reduce | 38.6 | 39.1 |
| matmul_all_reduce_add_rms_norm | 38.2 | 38.8 |
| moe_distribute_dispatch_v2 | 39.1 | 37.9 |

70 个合计：3408s → 3069s（约 -10%）。其中 `prompt_flash_attention` 上轮分析 193s，本轮在准备阶段就停了，合计墙钟变少也有「没跑完」的成分。

## 9. 结论（一段话）

这 70 个算子在性能优化后**没有**维持上轮的质量：五步 65/70，自动分 65/70，LLM 复检 63 通过、2 可解释、5 失败。两个「源码本来就没有 packing」的负例仍然是 `0/0`，这一点没编造。IFA 分析阶段从 240s 降到 137s，全样本也略快，但 IFA 的 kernel 运算点几乎没画上，还有 PFA 准备被挡、若干算子 packing 维数明显变少。限制：只在这一个仓、这一份已经见过的名单上；多数是 arch35；LLM 复检是抽 Key/Kernel/输入/packing 对源，不是逐节点人工审。下一步应先修「图变瘦/packing 掉维/PFA 准备挡」再谈性能数字。

## 附录 A. CSV

路径：[`artifacts/uo-init-generalization/pass70-20260816-perf/pass70-20260816-perf.csv`](../../artifacts/uo-init-generalization/pass70-20260816-perf/pass70-20260816-perf.csv)

## 附录 B. 怎么复现

- AscendC-Pilot commit：`69308572471c4141acecad43d8b059379dc500c0`
- ops-transformer commit：`4e09c2ec15a414f6e312caf5b3da16cd965af07b`
- 名单：复用 `pass70-20260816/sample.json`
- sample.json SHA256：`ACDE707A1A7B1C167A91E161FA5D096538FB12757DC7A6B8487071C72C76B1A9`
- results.json SHA256：`58AA0C384D28C8DA3C807C7150306A1501301AC131E42BDE1DAA758D5FFE1893`
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
- 开始 / 结束：2026-08-16 17:07:24 ～ 17:58:33（UTC+8）
