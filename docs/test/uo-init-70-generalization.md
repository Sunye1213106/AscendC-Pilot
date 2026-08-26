# uo-init 70 算子泛化（pass70-20260816）

从 `ops-transformer` 主仓 8 家族按家族密度（Hamilton）抽 70 个算子，逐个 wipe 冷启动 `prepare → extract → analyze → commit → verify`，证明提取脚本可泛化。

质量口径：[`high-quality-codemap.md`](high-quality-codemap.md) + 当前 `codemap_quality()`。不引用历史 pass 名单。`grade: ready` 不能代替抽检。

产物：`artifacts/uo-init-generalization/pass70-20260816/`（`sample.json` / `results.json` / `ledger.md` / `inspect/`），只在跑测机器上，不入仓。

## 抽样（冻结）

- 母体：主仓 8 家族，不含 `experimental/`
- eligible=164：家族下一层且必须有 `op_kernel/`；排除 common/3rd/tests；AICPU-only / host-only 不入池
- Hamilton n=70 seed=**20260816**
- 配额：attention 25 / mc2 18 / moe 12 / posembedding 6 / gmm 3 / mhc 3 / ffn 2 / mamba 1
- 架构：优先 arch35，否则最新 `arch*`

## 结果

| 项 | 值 |
| --- | --- |
| 流水线 | **70/70 pass**（prepare 未挡、packing 未挡、verify pass） |
| 墙钟 | 3408s |
| grade | 70/70 `ready` |
| OTHER | 0 |
| locate_hit_rate | 1.0 |
| packing | 68 个满覆盖；2 个 **0/0**（源码无 `TILING_KEY_IS` / `GET_TILINGKEY`，诚实空 catalog） |
| IFA analyze | 239.9s vs 上一 sweep 201.8s（**+18.9%**，未同时达到 +20%） |
| IFA packing / 实体 | 12/12，entity=34782（与上一 sweep 一致） |
| FAG packing | 19/19 |

70 行清单见该产物目录下的 `ledger.md`。

## 本轮通用修复（无算子名特化）

失败只改 AscendC 惯用法，禁止 `spec/operators/<op>.yaml`。

1. **裸 `GET_TILINGKEY(` + `TILING_KEY_IS(...UL)`** — `source_contract.py`
2. **兄弟算子 host tiling** — kernel 相对 include 指向同家族、有 `op_host` 的兄弟时并入 tiling TU
3. **`TILING_KEY_IS(IDENT)` 名字过滤** — catalog 捕获的 ident 不再要求名字里带 `TILING_KEY`
4. **函数宏形参上的 `TILING_KEY_IS`** — catalog 取调用实参，不取宏形参名
5. **`tilingKey_ +=` 也是 packing** — `host_tiling_key.py`
6. **PFA probe** — `clang_scope_status==complete` 且 host 无错时，kernel `declarations_only` 残留不再把 `probe_clean` 打 false
7. **兄弟 host 并入闸门** — 仅当**本地 host 还没有 packing 站点**（register/dispatch 壳）时才 union 兄弟。IFA kernel include PFA/incre，但本地已有 `GET_TPL_TILING_KEY`；无条件并入曾把 IFA analyze 拉到 301s、entity 48668。闸门恢复 entity 34782。

## 抽检（不能用 ready 代替）

每算子核对：异常零值、源码有图上无（`precision_gaps`）、locate 的 `file:line` 是否指向该符号。

- 70 个 `precision_gaps=[]`，OTHER=0。
- Kernel / INPUT / 具名 TILING_KEY 的 sample 行含该符号（或 `TILING_KEY_IS(N…UL)` 整型后缀，`\b` 卡在 `UL` 上是检查器假阴性）。
- `pack_arg_*`：host `GET_TILINGKEY` / `GET_TPL_TILING_KEY` 实参是表达式，与 nsa_compress / fused_floyd 同类，记 **explained**。
- 整数 Key 名 `0` 的 LIKE 首击可能落到无关的 `if (0)`（mla_preprocess）；同算子 `TILING_KEY_IS(4)` / `(8)` 已对准 kernel。
- `source_api` 本目录为 0、图上 n>0：调用在家族 `common/` include 闭包，记 **explained_zero**（IFA/PFA LoadAlign）。

先前流水线失败、本轮已过的 5 个：

| rel | 上一轮 | 本轮 packing | 根因 |
| --- | --- | --- | --- |
| attention/prompt_flash_attention | prepare 挡 | 11/11 | probe residual vs complete clang scope |
| attention/mla_prolog_v3 | 0/1 | 9/9 | 本地仅 register，packing 在兄弟 `mla_prolog` |
| attention/inplace_fused_causal_conv1d | 0/4 | 4/4 | 本地 dispatch，GetTilingKey 在兄弟 `fused_causal_conv1d` |
| attention/attention_worker_combine | 3/6 | 6/6 | `tilingKey_ += 1` 未识别 |
| posembedding/norm_rope_concat_grad | 0/54 | 54/54 | wrapper 宏 `Impl(tilingKey)` + host `+=` |

## 结论

同一套 uo-init（无 per-op yaml）在 8 家族 70 样本上全部冷启动过线；packing 相对上一 sweep 无回退；IFA analyze 未触发「同时 +20% 且 +5s」。
