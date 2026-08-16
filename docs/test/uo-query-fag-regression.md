# uo-query 回归测卷（FAG arch35）

上次 GLM-5.2 在 `session-ses_ffba` 上翻车的题，加上一道 **看起来像一单、其实跨好几层** 的线上故障。给 OpenCode / Cursor 主控逐题粘贴。算子：

`d:\TEST\ops-transformer\attention\flash_attention_score_grad`  
architecture：`arch35`

Wave 3 抽取（PIPE `kernel_phase`、`definition_sites`、registry PREDICATE、`fused_outer_candidates`、`mutex_policy`）要先 **重建** `.uo` 才出现在真实查询里。Wave 1–2（`template_match.dim_coverage`、`--query`、空结果 hint、禁仓级 findstr）对现有产物立刻生效。

测查询时 **不要再发 `/uo-init`**。上一场建库已完成、写锁已释放；leftover 弹窗不是卡住。直接贴题。

## 当前派发（Cursor 同构）

Cursor：若 `host_step.tasks` ≥2，**同一条消息里并行多个 Task**（编译器权威）；否则按独立证据空间启发式拆。子代理隔离上下文；全部返回后 **Primary 综合**，不发明子代理没引用的事实。

uo-query **禁止** `pilot_run`。主控必须先在当前会话说出路由，再动手。刚跑完 `/uo-init` 后 leftover 阶段不含 `uo-query` **不得**拦 `Task(agent=uo-query)`。

| 问法 | 谁查 |
| --- | --- |
| 短、一两跳 | 主控自己 `acp uo-query --mode`，不开子代理 |
| 深、一个独立证据空间 | **一个** `Task(agent=uo-query)`（主控写 FOCUS；点卡片看思考） |
| 深、多个独立证据空间 | 主控 **同一轮并行** 多个 `Task(agent=uo-query)`；全部返回后综合，禁止只转述某一个 |

不是「一个子代理串 15 个 mode」。`host_step.tasks` ≥2 时按编译器 fanout；0/1 片才用启发式。算法见 `skills/operator-analysis/capabilities/uo-query-router/METHOD.md`。

## 怎么判

- 列表型（SEL / virtual / fusedOuter / PIPE / Mutex）`completeness: first_hit` 不得 `ANSWERED`。
- 声称某维没注册必须引用 `dim_coverage` 或 `legal_key.total_matched`。
- 仓级 `findstr /S` / `grep -r` / 无路径 `rg` = 失败。
- 综合题：题面 **不会** 点名 mode / API /「请拆成三个问题」。主控应自己判断并**对人说出**要并行几个 `uo-query` Task，终答是分叉的，不是收成一个根因。
- 子代标 PARTIAL / 未闭合 / 互相矛盾时，主控必须再开一轮 Task（FOCUS=缺口），禁止问「要不要继续」就收工。Q6 三相对了但 scale 乘几次没坐实 = 未结案。
- 深问（Q6/Q18 等）主控自己连 `acp`/Read、一次都不 `Task(agent=uo-query)` = 失败。禁止「这是深问但我短问范围内查清了」。

---

## 上次翻车题（原话，可直接问）

### Q6 Pre/Main/Post

> FP16 精度不过：dq 量级差一截，FP32 同 shape 过了。是不是 POST 的 scale/cast 写错了？先画出 arch35 单 launch 的三相，并说明 FP32 / BN2 / `enablePreSfmg` 各自怎么走。

上次错：把三相讲成主循环 V1–V6。要对：`kernel_launch`，`pipeIn` Pre → Destroy → `pipeBase` Main →（非 FP32）`pipePost`；入口是 `RegbaseFAG` / `*_entry_regbase.h`，不是 `ProcessVec*`。

阅卷：题面像一单故障也必须 **同一轮并行 ≥2** 个 Task（三相=`kernel_launch` 一路；FP32/BN2/`enablePreSfmg`=`kernel_branch`/`field` 一路）。禁止「相关所以一个 agent 更连贯」。每个 Task 带 `FIRST_QUERY`。三相那路第一刀必须 `--mode kernel_launch`，不是 `--mode search ProcessVec`。结构事实可以讲；scale 乘几次没坐实 = 未结案，禁止把 POST 乘 scale 当已证实根因。

### Q7 确定性 dK 不齐

> 确定性开了，连跑 7 次 dK 对不齐，dQ 齐。先别改 VF。是 DETER_DENSE 的坐标分核没生效，还是 POST 多核写回顺序，还是 TND prefix 没带上？

上次错：`locate CalcleTNDDeterParam` 停在 `.h` 空 virtual。必须看全部 `definition_sites`（varlen `.cpp` override）。缺 `actual_seq` → `PARTIAL`，禁止「根因已定位」。

### Q8 softmaxMax / PreSfmg

> 某 case 只有 dQ 在 S 尾部炸，dK/dV 还行。怀疑 CopyInMaxSum 或 softmax-grad VF。arch35 怎么用 saved max/sum？aligned VF 什么时候上场？enablePreSfmg 会不会把 softmax-grad 挪出主循环？

### Q9 561003 / SEL

> 950 上某 FP16、D=80、带 dropout 的 case 报 kernel 找不到。host 算出的 TilingKey 在 ASCENDC_TPL_SEL 里一定有吗？ORIG_DTYPE_QUERY 和 IsDNoEqual / IsNzOut 怎么把组合砍掉

上次错：第一块 `ARGS_SEL` 没有 D=128 就说没注册。必须 `template_match` `DTemplateNum=128,DeterType=0,InputDType=3`，看 `dim_coverage`。

### Q10 TilingData offset

> 开确定性 + TND 后 tiling 成功，kernel 一进来 coreNum/s1/s2 就是垃圾。空 tensor 正常。从 REGISTER_TILING_DEFAULT 和 RegbaseFAG 的 offset 解释。

上次错：`locate` 多 token AND 成空，改走 findstr。应对 `locate` OR 多标识符，看 registry PREDICATE 的 priority（Varlen 900 / Normal 950）。

### Q11 hang / SyncALLCores

> 偶发 hang，plog 停在 Pre 末尾 SyncALLCores。有人说 BufferID 没配对。arch35 为什么 PostTiling 要 SetScheduleMode(1)？哪条路径故意不设？AIC/AIV dummy 和 CrossCore flag 怎么配？

### Q12 flag 复用

> D=64、确定性、小 shape 卡死。common.h 里 SYNC_DETER_FIX_FLAG=10 和 SYNC_V2_TO_C1_FLAG[2]={10,11} 看起来重叠。这是不是实 bug？什么条件下会撞？

### Q13 分核 / fusedOuter

> B=1,N=4,S=2048 只有 4 个 AIC 在干活，vendor 几乎打满。是核内 VF 慢，还是分核轴错了？fusedOuter 在 BN2GS1S2 / BN2 / BN2S2 里分别乘了什么？超 L2 的 swizzle 救的是核间还是 L2？

上次错：`search FUNCTION fusedOuter` 空，只看一条公式。应 `field blockOuter`，看全部 `candidates` / `fused_outer_candidates`。

### Q14 Mutex policy

> msprof 显示 AIC 等 AIV 的 L1 dS。MutexBuffersPolicySingleBuffer/DB/3buff/4buff 谁决定？FAG 主循环 P 和 dS 各用哪套？把 3buff 改 4buff 要动 tiling 还是只动 kernel？

上次错：regex `\|` 查 TYPE 空结果后 findstr。应 `buffer`，看 `mutex_policy` / `conditional_flag`。

### Q16 D=320

> 业务要 D=320。现在 D 模板是 64/128/192/256/768。只改 DTemplateNum 的 ASCENDC_TPL_UINT_SEL 够不够？host GetDTemplateType、VF aligned768、L0/L1、IsDNoEqual、NzOut 还要动哪些？

### Q17 UT 静默错

> tests/ut/op_host/arch35/test_flash_attention_score_grad_tiling.cpp 要补“一改就静默错”的 case。列 5 个，每个说期望的 splitAxis / deterSparseType / enablePreSfmg / isTndSwizzle / isNzOut，以及断言哪个 TilingData 子结构存在。

---

## Q18 综合题（测 fan-out）

下面这段 **原样粘贴**。不要先告诉模型「这是三道题」或该用哪个 mode。好的主控会自己觉得这单走不完一层，同一轮开多个 `uo-query`。

> 950 上一个 FP16 dropout 的 case，D=80，B=1 N=4 S=2048。host 算出 TilingKey 了，板上却报找不到 kernel。同一份 shape 打开确定性 TND 之后能编过、tiling 也成功，可是一进核 coreNum/s1/s2 就是垃圾，连跑下来 dK 对不齐、dQ 齐。把确定性关掉又能跑完，但核占不满，只有四个 AIC 在动，msprof 里 AIC 堵着等 AIV 的 L1。先别改 VF，按 CodeMap 把这条路径说清楚；缺实际 seq 或分核轴就说还缺什么，不要先认定是同一处 bug。

**阅卷（不要贴进问题）**

- 题面没有 ①②③、没有点名 SEL / virtual / fusedOuter / PIPE / Mutex。应仍看到 **≥2 个并行** `uo-query` Task。
- 「找不到 kernel」→ `template_match` + `dim_coverage`，不能拿第一块 `ARGS_SEL` 否定全集。
- 「能 tiling、进核字段垃圾、确定性 TND、dK 不齐」→ `locate` 全部 `definition_sites` + registry 900 vs 950；空 virtual ≠ 没实现。
- 「四个 AIC、等 AIV 的 L1」→ `field blockOuter` 的 fusedOuter 候选 + `buffer` 的 `mutex_policy`。不要把主循环 V1–V6 当成单 launch 三相。
- 终答：编不过、进核垃圾、占不满/等 L1 **不是** 同一根因。缺 `actual_seq` / `splitAxis` → `PARTIAL`。综合时不得丢掉切片，不得发明子代理没引用的行号。

建议先单题 Q6/Q7/Q9/Q13/Q14，再丢 Q18。