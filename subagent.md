# subagent 1
算子目录：d:\TEST\ops-transformer\attention\flash_attention_score_grad（arch35，.uo CodeMap 已建好）。

立即调用 acp 工具：command=`uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...`（你自己按需选 locate / symbols / callers / fields 等 mode）。禁止 bash、Grep、MCP 替代。

背景：用户在做 FP16 精度调试，怀疑 kernel 里 POST（收尾/输出）阶段的 scale/cast 写错，导致 dq 量级差一截；FP32 同 shape 通过。现在要"画 arch35 单 launch 的三相"。

请查清并回答（全部带 file:line 证据）：
1. FlashAttentionScoreGrad 这个 kernel 单 launch 的"三相"（如 pre 阶段 / 主 flash 循环 / post 收尾阶段）分别在哪、做什么：找 kernel 主函数（KERNEL 实体）、各 METHOD 的调用关系（CALLS），画出三阶段的边界：哪些 buffer/op 属于 phase1（加载/初始化）、phase2（flash score grad 主循环）、phase3（POST：scale、cast、输出写回）。
2. POST 阶段具体在哪里做 scale 和 cast：定位写 dq 输出（OUTPUT/写回 buffer）的 METHOD，找到 scale 乘法和 cast（如 FP32→FP16）的具体语句位置；同时查 TILING_FIELD/TILING_DATA 里与 scale（如 scale、preScale 之类）相关的字段名与读写点。
3. 输出 buffer 的 dtype：写回时是 FP32 还是 FP16，cast 发生在 kernel 内还是依赖框架。

请用 Cursor Explore 风格回答：完整散文 + file:line 列表。若某处是 host_runtime_leaf 无法静态确定，明确说"UNKNOWN/partial"并说明原因。不要写 answer.yaml，不要 finalize。
- Thought: 1.1s
Let me start by querying the UO CodeMap for this operator. I'll use the acp tool with uo-query command.

First, let me look at the project structure to understand what's there. But wait, my role says to call the acp tool first with uo-query. Let me do that.

Let me run several queries in parallel: locate the KERNEL entity, symbols, etc.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern KERNEL]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode symbols]
- Thought: 13.1s
The symbols mode isn't available. Let me use search mode instead to find KERNEL entities, entry functions, and other important symbols. Let me query for the entry function, the main kernel function, scale-related fields, and POST-related things.
--mode symbols 不存在，改用 search 等可用 mode 继续。
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern FlashAttentionScoreGradKernel::Process]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern scale]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern Cast]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern entry]
- Thought: 2.8s
Good progress. Now I have the scaleValue field mapping. I need to look at:
1. The entry file flash_attention_score_grad_entry_regbase.h — this contains the kernel entry (KERNEL entity), which shows the phases: pre (FlashAttentionScoreGradPresfmgRegbase / FlashAttentionScoreGradS1S2BNGS1S2PreRegbase), main flash loop (FlashAttentionScoreGradKernel), and post (FlashAttentionScoreGradS1S2BNGS1S2PostRegbase / FlashAttentionScoreGradNzPost).
2. The post file flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h — ProcessDqkv at line 207 reads scaleValue.
3. The nz_post file flash_attention_score_grad_nz_post.h.

Let me look at the entry file to understand the full flow, and the post file. I should read the machine-scope files directly (windowed reads allowed for machine scope). The entry file is at d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h.

Let me also read the post regbase file and the kernel.h. Also search for Cast in the kernel, and look for the KERNEL entity (entry). Let me query kernel_launch and kernel_api modes too.

Let me do:
1. Read entry file (windowed).
2. Read post regbase file.
3. Read nz_post file.
4. Search for Cast / Muls in kernel files.

The truncated outputs were saved to tool-output files. But per my constraints, I should primarily use acp queries and windowed reads of machine scope. Let me read the actual source files.
CodeMap 已给出 scaleValue 的 TILING_FIELD 读写点和 post 相关 METHOD。现在直接窗口化读取机器范围源码，确认入口三阶段和 POST 细节。
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h [offset=40, limit=240]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h [offset=1, limit=120]
+ Thought: 1.9s
入口文件已确认三阶段边界。关键发现：POST 阶段只在 ORIG_DTYPE_QUERY != DT_FLOAT 时执行（entry_regbase.h:91）。继续读 POST 的 ProcessDqkv 和 nz_post。
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h [limit=215, offset=120]
- Thought: 7.2s
Excellent. This is the heart of POST. Key facts:

- ProcessDqkv (post_regbase.h:207-319):
  - Reads from dqkvWorkspace[qkvIdx] (float workspace in GM, line 95-97, 234)
  - Muls(vecInPing, vecInPing, (float)tilingData->s1s2BNGS1S2BaseParams.scaleValue, pingSize) at line 238 (ping) and line 283 (pong) — only for qkvIdx < 2 (dq, dk), NOT dv
  - Cast(vecOutPing, vecInPing, RoundMode::CAST_ROUND, pingSize) at line 241 / 285 — FP32→OUTDTYPE (half for FP16 input)
  - DataCopy(dqkv[qkvIdx][pingIdx], vecOutPing, ...) at line 257/266/270/274 — writes to GM output buffer of OUTDTYPE
- Process() (line 322-333): guard SPLIT_AXIS != BN2 && !IsSameType<T1, float>::value → ProcessDqkv; plus ProcessSink for sink.

So the scale (Muls) and cast (Cast) happen in kernel POST, on AIV, using workspace float buffers (produced by phase 2 in FP32), and output is OUTDTYPE (= half for FP16). Important nuance: scale is applied only to dq/dk (qkvIdx < 2), not dv. And for BN2S2 split axis (SPLIT_AXIS == 5), dk/dv skip muls/cast per line 314-317.

Wait — actually line 314 says "bn2s2 dk dv no need to do muls and cast" and if constexpr (SPLIT_AXIS == 5) break; — this breaks after the first qkvIdx iteration (dq). So in BN2S2, only dq is post-processed; dk/dv are written directly by the main kernel (in OUTDTYPE already? or in the workspace?). Hmm, need to check what the main kernel does for BN2S2. Actually that break means for SPLIT_AXIS == 5, only qkvIdx=0 (dq) is processed, dk and dv are skipped (they are written directly as OUTDTYPE by phase 2). Interesting.

Now I also want to check:
1. The main kernel phase 2: FlashAttentionScoreGradKernel::Process and how dqkv workspace is filled (whether phase 2 writes FP32 to workspace).
2. The nz_post for the NZ output variant.
3. Where the KERNEL entity entry is (the RegbaseFAG kernel function with KERNEL_TASK_TYPE_DEFAULT). Let me check the remaining lines of entry file (280-289).
4. The pre phase: what it does (InitCVCommonBuffer etc.).

Also the user asked about TILING_FIELD/TILING_DATA fields related to scale like scale, preScale. I found scaleValue in FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase (line 96-97), read by:
- FlashAttentionScoreGradNzPost::Init (nz_post.h:103)
- FlashAttentionScoreGradS1S2BNGS1S2PostRegbase::ProcessDqkv (post_regbase.h:207)
- FlashAttentionScoreGradKernelBase::SetConstInfo (kernel_base.h:488)

And the host writes it: op_host tiling_common_regbase.cpp:1011 fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0)); and tiling_normal_regbase.cpp:1855 setter.

Let me check SetConstInfo in kernel_base.h to see how scaleValue propagates to FagConstInfo (used in phase 2), and check where in the main kernel the workspace is written with what scale. Also check deqScale / pScale etc. Let me also look at the pre phase file briefly, and the kernel.h Process + ComputeDqkvBn2gs1s2 area for workspace writes.

Let me also query the kernel_launch / kernel_api modes and check the KERNEL entity in the CodeMap. Let me search for "Muls" and "Cast" in the kernel files, and check kernel_base.h SetConstInfo.
POST 核心已找到：ProcessDqkv 里 Muls（scaleValue）只作用于 dq/dk（qkvIdx<2），Cast FP32→OUTDTYPE。现在查主循环阶段如何写 workspace、SetConstInfo 如何传 scaleValue，以及 pre 阶段内容。
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=120, offset=488]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h [limit=160, offset=1]
- Thought: 3.2s
Now I see the main flash loop (phase 2) writing to dqWorkSpaceGm, dkWorkSpaceGm, dvWorkSpaceGm — GM workspace tensors (FP32, CALC_TYPE). The workspace is GlobalTensor<CALC_TYPE>? Let me check the declarations. Note the comments: v3: dropout + cast + nd2nz, v4: cast + nd2nz — these casts in phase 2 are for dropout-related dS/p tensors, not the output.

Let me now look at:
1. The Init/Process of the main kernel (Phase 2 entry) — around line 589+ (ProcessPreloadTwoTimes) and the Process method.
2. SetConstInfo lines where scaleValue is read — I saw in the search that SetConstInfo (kernel_base.h:488) READS TDF scaleValue. Let me find where constInfo.scaleValue is set. Search within SetConstInfo for "scaleValue".
3. The workspace type declarations (dqWorkSpaceGm).

Also, where does the main kernel use constInfo.scaleValue? Probably in ComputeDqkv or in the vecBlock — maybe the scale is pre-applied in phase 2 for FP32? Actually for FP32 (ORIG_DTYPE_QUERY == DT_FLOAT), POST doesn't run, so scale must be applied within phase 2. Let me search where constInfo.scaleValue is used.

Let me query the CodeMap for SetConstInfo's relationship with scaleValue, plus search for "scaleValue" reads in kernel files. I'll also read the kernel.h Process method (the main loop) and check where dqWorkSpaceGm is declared (kernel_base.h). Let me read kernel_base.h around Init and the workspace declarations.
主循环把 dq/dk/dv 写进 GM workspace（FP32）。现在查 SetConstInfo 里 scaleValue 的落点、主循环 Process、以及 workspace 声明类型。
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=110, offset=184]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode neighbors --target "SRCKDEFV2::flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_kernel_base.h::488::template <typename ChildClass, typename CubeBlockType, typename VecBlockType>\n__aicore__ inline void FlashAttentionScoreGradKernelBase<ChildClass, CubeBlockType, VecBlockType>::SetConstInfo" --depth 1]
- Thought: 4.6s
Key insight at kernel_base.h:257-283:
- For non-FP32 (!IS_FP32_INPUT, i.e., FP16/BF16): phase 2 writes dq/dk/dv to GM workspace (FP32 float buffers), NOT to the output GM. Output buffers dqGm/dkGm/dvGm are typed OUTDTYPE.
- For FP32 (IS_FP32_INPUT): dqWorkSpaceGm/dkWorkSpaceGm/dvWorkSpaceGm point directly at the output GM buffers ((__gm__ INPUT_TYPE *)dq), so phase 2 writes the outputs directly — no POST phase.

Now I need to find where in SetConstInfo scaleValue is set into constInfo (FagConstInfo::scaleValue at common.h:395), and where constInfo.scaleValue is used in phase 2 (main loop / vec block). Let me search for scaleValue in the kernel files. Also check where the phase-2 scale multiplication occurs (maybe in vecBlock's ProcessVec / Muls on dq workspace). Actually, wait — for FP32, who applies the scale? Phase 2 must apply scaleValue somewhere — probably in the vecBlock when processing dq. Let me search for constInfo.scaleValue usage.

Let me search the CodeMap for "scaleValue" reads within kernel files. The earlier search showed READS relationships for scaleValue by:
1. nz_post.h Init (line 103)
2. s1s2_bn2gs1s2_post_regbase.h ProcessDqkv (line 207)
3. kernel_base.h SetConstInfo (line 488)

But there may be more readers — e.g., vecBlock (block_vec.h) or block_cube.h. Let me search for "scaleValue" in those files. Also search for constInfo.scaleValue and pScale, deqScale usage. Let me also look at the FagConstInfo in common.h — it has scaleValue, pScale, dsScale, pScaleD, dsScaleD, pScaleLog.

Also there's a preScale possibility in nz_post. Let me search for "preScale" too. And check where Muls appears in the kernel files with scale.

Let me do targeted searches:
- --mode search --pattern preScale
- --mode search --pattern "constInfo.scaleValue"
- --mode search --pattern "pScale" (maybe too many)
- Read block_vec.h area where ProcessVec / write to workspace happens. But block_vec.h could be huge. Let me first find where scaleValue is used in block_vec / block_cube.
FP32 时 workspace 直接指向输出 GM（kernel_base.h:278-283），POST 不跑。现在查 scale 在 phase2（vec/cube block）里的应用点，以及 nz_post 的 scale/cast 细节。
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern preScale]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern "constInfo.scaleValue"]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern "ProcessVec"]
- Thought: 1.7s
No preScale symbol — so the "scale" here is scaleValue (and quant-related pScale/dsScale/pScaleD/dsScaleD in FagConstInfo). The constInfo.scaleValue search was truncated; let me look at the saved output to see where constInfo.scaleValue is used. Actually, let me instead search the source directly with read/grep... but I shouldn't use grep. I can read windows. Let me check the saved tool-output for the constInfo.scaleValue search. Also check where scaleValue is used in block_vec or block_cube — maybe in vector_api. Actually the FagConstInfo::scaleValue at common.h:395 is used somewhere in phase 2 for FP32. Let me search the CodeMap with pattern "FagConstInfo::scaleValue" relationships or search "scaleValue" in block files.

Let me read the tool output file for the truncated constInfo.scaleValue search.
preScale 不存在——scale 相关字段就是 scaleValue（+ 量化参数 pScale/dsScale）。查看被截断的 constInfo.scaleValue 搜索结果。
→Read C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b5b9c3a001MCHrUm7X4zUaLs [limit=300]
- Thought: 1.1s
The output is a single-line JSON. Let me use the --limit and --kind options of uo-query to narrow instead. Actually, better to query the CodeMap for the specific FIELD FagConstInfo::scaleValue readers (relationships READS). Let me use mode field or mode neighbors on SRCFIELD::flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_common.h::FagConstInfo::scaleValue.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode field --target "SRCFIELD::flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_common.h::FagConstInfo::scaleValue"]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h [limit=200, offset=310]
- Thought: 4.2s
Excellent! Huge finding: ProcessMulsAndCast — the v5/v6 vector stages. In ComputeDqkvBn2 (SPLIT_AXIS == BN2, not multiblk) and IS_BN2_MULTIBLK:
- v5: ProcessMulsAndCast<CALC_TYPE, IS_DQ_WRITE_UB, DQ_IDX>(this->dqWorkSpaceGm / mm1ResTensor, ...) — "dq muls + cast"
- v6: ProcessMulsAndCast<..., DK_IDX>(this->dkWorkSpaceGm / mm2ResTensor, ...) — "dk muls + cast"
- v6: ProcessMulsAndCast<..., DV_IDX>(this->dvWorkSpaceGm, ...) — "dv muls + cast"

So in the BN2 split axis (and BN2 multiblk), the muls+cast for dq/dk/dv happens inside the main loop (v5/v6 stages)! But wait — that's for SPLIT_AXIS == BN2. For BN2GS1S2 (which is the default regbase path, splitAxis==BN2GS1S2), the dq/dk/dv writes go to the workspace (dqWorkSpaceGm) without muls/cast, and POST does it. Let me verify: in ProcessBn2gs1s2LastVec (kernel.h:42-160), dq/dk/dv are written via IterateMmDsK<CALC_TYPE, IS_DQ_WRITE_UB>(this->dqWorkSpaceGm, ...) — no ProcessMulsAndCast visible. Hmm, but IS_DQ_WRITE_UB may matter. Let me check what IS_DQ_WRITE_UB is.

Also need to check ProcessMulsAndCast in block_vec.h — does it use constInfo.scaleValue? Let me look at block_vec.h ProcessMulsAndCast. This will show whether the scale in phase 2 for BN2 split is applied, and what guard conditions.

Also there's the important SPLIT_AXIS == 5 (BN2S2?) note in post: "bn2s2 dk dv no need to do muls and cast" — the break at post_regbase.h:314-317.

Now, let me find ProcessMulsAndCast in block_vec.h, plus check the ProcessPreloadTwoTimes and the main Process loop for BN2GS1S2 to confirm dqkv workspace writes without muls. And check where IS_DQ_WRITE_UB is defined (templates — maybe in kernel_base or common). Let me search.
重大发现：BN2 split 下主循环里有 ProcessMulsAndCast（v5/v6），而 BN2GS1S2 下只写 workspace。查 ProcessMulsAndCast 实现和 IS_DQ_WRITE_UB 定义，以及主 Process 循环 BN2GS1S2 分支。
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern ProcessMulsAndCast]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern IS_DQ_WRITE_UB]
- Thought: 40.2s
Key facts:
- IS_DQ_WRITE_UB is only true for SPLIT_AXIS == BN2 && !IS_BN2_MULTIBLK && !IS_DQ_RES_EXCEED_UB (kernel_base.h:99).
- DqkvMulsAndCastFromGM writes directly to dqGm/dkGm/dvGm typed OUTDTYPE (block_vec.h:682). It does muls (scaleValue?) + cast inside the main loop — but only for BN2 split (and BN2S2 non-deter for dk/dv, plus BN2 multiblk, plus determinism paths).

So there are two distinct code paths for where scale+cast happen:
1. BN2 / BN2S2 / BN2-multiblk splits: inside the main loop (phase 2) via ProcessMulsAndCast (v5/v6), writing OUTDTYPE directly to dqGm/dkGm/dvGm. POST phase for these splits: for BN2S2 (SPLIT_AXIS==5), dk/dv skipped; POST's ProcessDqkv only runs for SPLIT_AXIS != BN2 (post_regbase.h:327) — wait, if constexpr (SPLIT_AXIS != BN2 && !IsSameType<T1, float>::value) ProcessDqkv();. Hmm — for SPLIT_AXIS == BN2 (value?), ProcessDqkv is skipped entirely in POST. Wait but then who does muls+cast for BN2? ProcessMulsAndCast inside the main loop (phase 2), as we saw. So for BN2: phase 2 does muls+cast directly to output GM. For BN2S2: phase 2 does dq (and dk/dv when IS_DK_WRITE_UB/IS_DV_WRITE_UB true = non-deter) muls+cast, and POST ProcessDqkv does dq only (break after qkvIdx=0). For BN2GS1S2: phase 2 writes FP32 workspace; POST does muls+cast to OUTDTYPE output.

Wait — I need to check the actual values of SPLIT_AXIS enum: BN2GS1S2, BN2S2, BN2. What numeric values? In entry: splitAxis == BN2GS1S2, BN2S2, BN2. In post: if constexpr (SPLIT_AXIS != BN2 && !IsSameType<T1, float>::value) — ProcessDqkv runs when NOT BN2. And if constexpr (SPLIT_AXIS == 5) break; — so BN2S2 == 5 probably. BN2 might be 1 or similar. Let me check the enum in common.h. Also IS_PRELOAD_TWO_TIMES at kernel_base.h:112-114: HEAD_DIM_ALIGN <= 128 && !IS_DROP && SPLIT_AXIS == BN2GS1S2 && DETER_SPARSE_TYPE == NO_DETER && !IS_FP32_INPUT — this is the "ProcessPreloadTwoTimes" path used for FP16 small head dim! That's likely the user's case (FP16, head_dim ≤ 128 typical). Let me look at ProcessPreloadTwoTimes and its ComputeDqkvBn2gs1s2 to see if dqkv is written to workspace without scale.

Actually from the earlier read of kernel.h:42-160 (ProcessBn2gs1s2LastVec) — for BN2GS1S2, dq/dk/dv are always written to dqWorkSpaceGm/dkWorkSpaceGm/dvWorkSpaceGm (FP32 workspace), no ProcessMulsAndCast. That confirms: for BN2GS1S2 (the default split for this operator, and the preload-two-times path), scale+cast happens only in POST (post_regbase.h ProcessDqkv).

So for the user's FP16 case (BN2GS1S2 likely), POST does scale+cast.

Now let me check DqkvMulsAndCastFromGM to see the scale application there, and check the SPLIT_AXIS enum values. Also check the nz_post file for the NZ variant (IS_NZ_OUT). And check the pre phase (S1S2BNGS1S2PreRegbase / Presfmg) to describe what phase 1 does. Let me read:
1. block_vec.h 694-820 (DqkvMulsAndCastFromGM body) — to find Muls with scaleValue/constInfo.
2. common.h enum for SplitAxisEnum.
3. nz_post.h around the ProcessDqkv-equivalent (the scale/cast in nz_post) — search for Muls/Cast in nz_post.
4. pre regbase file briefly.

Let me read block_vec.h around 694-820 and search nz_post for Muls.
现在读 DqkvMulsAndCastFromGM 的 scale 应用点、SPLIT_AXIS 枚举值、nz_post 里的 scale/cast。
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_vec.h [limit=180, offset=694]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern SplitAxisEnum]
- Thought: 8.0s
Now I have solid evidence for DqkvMulsAndCastFromGM (block_vec.h:707-716) and DqkvMulsAndCastFromUB (block_vec.h:828-832): Muls(..., constInfo.scaleValue, ...) for MM_IDX != DV_IDX, then Cast(..., CAST_ROUND, ...) to OUTDTYPE, then DataCopyPad to dqGm/dkGm/dvGm (OUTDTYPE output GM). This is the phase-2 scale+cast path for BN2/BN2S2/multiblk splits.

Split axis enum: host assigns SplitAxisEnum::BN2S2 / BN2 / BN2GS1S2 (tiling_common_regbase.cpp:1641-1648). The numeric values: post uses SPLIT_AXIS == 5 for the BN2S2 break. Let me check the enum definition for exact numeric values — likely in common.h. Let me search for the enum definition with values. Actually, I can just note SPLIT_AXIS == 5 ≡ BN2S2 given the post comment "bn2s2 dk dv no need to do muls and cast". Let me verify the enum quickly by searching "BN2GS1S2 = " or reading common.h.

Also I still need:
1. Where SetConstInfo sets constInfo.scaleValue (line in kernel_base.h within SetConstInfo) — search said SetConstInfo READS TDF scaleValue. Let me read the part of SetConstInfo around where scaleValue would be (probably after line 607). Let me read kernel_base.h 608-700.
2. nz_post scale/cast details (for IS_NZ_OUT path) — read nz_post.h ProcessDqkv region. It reads scaleValue in Init. Let me search nz_post for Muls.
3. Pre phase: what S1S2BNGS1S2PreRegbase does — brief. It initializes dq/dk/dv in workspace with 0 and copies deqScale etc. Let me read the pre regbase file quickly (Process) and check InitCVCommonBuffer.

Let me also confirm the entry KERNEL entity (RegbaseFAG) and the actual kernel name (FlashAttentionScoreGrad). Search for the KERNEL launch or the final dispatch function. The entry file ends at line 289; let me read the tail.
DqkvMulsAndCastFromGM/UB 里 Muls(constInfo.scaleValue) + Cast 证据齐全。补最后几块：SetConstInfo 里 scaleValue 落点、nz_post 的 scale/cast、pre 阶段、entry 尾部 KERNEL 分发
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=95, offset=608]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h [limit=15, offset=279]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern "scaleValue ="]
- Thought: 4.6s
constInfo.scaleValue = tilingData->s1s2BNGS1S2BaseParams.scaleValue; at kernel_base.h:684.

Now I have the chain:
- Host: attr0 → fBaseParams.scaleValue (tiling_common_regbase.cpp:1011) → tilingData.s1s2BNGS1S2BaseParams.scaleValue (tiling_normal_regbase.cpp:1855) → kernel constInfo.scaleValue (kernel_base.h:684) → used in:
  - Phase 2 in-loop: DqkvMulsAndCastFromUB (block_vec.h:707-712) / DqkvMulsAndCastFromGM (block_vec.h:828-832) for MM_IDX != DV_IDX
  - Phase 3 POST: ProcessDqkv (post_regbase.h:238, 283) for qkvIdx < 2

Now let me check the nz_post path (IS_NZ_OUT) — read nz_post.h around the ProcessDqkv equivalent. The earlier search showed FlashAttentionScoreGradNzPost has scaleValue member and its Init READS the TDF scaleValue (line 103+). Let me find where Muls/Cast happen in nz_post. Search for Muls in nz_post.h. Also check the pre phase file briefly. And where OUTDTYPE comes from — the template instantiation: FlashAttentionScoreGradS1S2BNGS1S2PostRegbase<INPUT_TYPE, float, OUTDTYPE, ...> from entry_regbase.h:96-97 where OUTDTYPE=half for FP16 (line 226: half, float, half). So output dtype is FP16 for FP16 input.

Let me read nz_post.h Process and search Muls in it.
主链路已闭合：host attr0 → tiling → constInfo.scaleValue（kernel_base.h:684）→ phase2/phase3 Muls。补 nz_post（NZ 输出路径）和 pre 阶段
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern "nz_post"]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_nz_post.h [limit=130, offset=125]
- Thought: 2.8s
nz_post: scaleValue = tilingData->s1s2BNGS1S2BaseParams.scaleValue; at nz_post.h:157, DoWork<0/1/2>() for dq/dk/dv. Let me read DoWork (line 255+) to see the Muls/Cast in nz_post.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_nz_post.h [limit=140, offset=255]
- Thought: 372ms
Let me read the rest of DoWork (395-491) to see Muls/Cast in nz_post.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_nz_post.h [limit=100, offset=395]
- Thought: 4.5s
nz_post DoWork confirmed:
- nz_post.h:431: Muls(srcTensor, srcTensor, scaleValue, srcM * curD) only for DQ_IDX/DK_IDX
- nz_post.h:433: Cast(srcTensorB16, srcTensor, RoundMode::CAST_ROUND, ...) — FP32→OUTDTYPE
- nz_post.h:434: Transdata<OUTDTYPE> — NZ layout conversion
- nz_post.h:470/477/484: DataCopyPad to dqGm/dkGm/dvGm (OUTDTYPE)

Now the PRE phase. Let me quickly look at the pre regbase file to describe what phase 1 does. It's flash_attention_score_grad_s1s2_bn2gs1s2_pre_regbase.h. Let me read the Process and Init to summarize. Also there's the presfmg variant (FlashAttentionScoreGradPresfmgRegbase) used when enablePreSfmg && dTemplateType > 64.

Also, I should confirm the KERNEL entity name and the actual kernel launch: entry_regbase.h RegbaseFAG is the kernel function (template), instantiated for arch35. The kernel name: "FlashAttentionScoreGrad" — probably there's an extern "C" dispatch elsewhere, but the file ends at line 289 with RegbaseFAG. The actual launch might be in a different file (e.g., flash_attention_score_grad.cpp with KERNEL_LAUNCH). Let me check the file list and query kernel_launch mode. Also let me verify the tiling data structure field postTilingData.dqWorkSpaceOffset writer (host) to complete the buffer story. And check RESERVED_WORKSPACE_SIZE.

Let me do:
1. Read pre regbase file Init/Process (first ~150 lines).
2. Query kernel_launch mode.
3. Search postTilingData in host to find workspace offset assignment (dqWorkSpaceOffset).

Actually the pre phase might be big. Let me focus on the Process flow. Let me read the beginning of the pre file.
nz_post 的 scale/cast 也确认（nz_post.h:431-434）。最后补：pre 阶段内容、kernel_launch、postTilingData 的 host 侧 workspace 分配
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_s1s2_bn2gs1s2_pre_regbase.h [limit=130, offset=28]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode kernel_launch]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern dqWorkSpaceOffset]
- Thought: 6.4s
Excellent! The kernel_launch mode confirms the CodeMap's own phase model: kernel_phases: ["pre", "main", "post"] with three TPipe instances:
- pipeIn (pre phase) — entry_regbase.h:213
- pipeBase (main phase) — entry_regbase.h:63
- pipePost (post phase) — entry_regbase.h:94

The pre phase: FlashAttentionScoreGradS1S2BNGS1S2PreRegbase (or Presfmg variant) — Init(dq, dk, dv, ...workspace...) — initializes dqWorkSpaceGm/dkWorkSpaceGm/dvWorkSpaceGm (pre_regbase.h:149-151) — presumably zero-fills them (initdqSize etc.) and handles dropout mask (maskWorkSpaceGm). Let me read the rest of the pre Process to confirm what it does (zero init + mask).

Let me read pre_regbase.h 158-284 (the Process).
kernel_launch 模式直接确认 CodeMap 三相位模型：pre/main/post 三个 pipe。读完 pre 的 Process 确认职责
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_s1s2_bn2gs1s2_pre_regbase.h [limit=127, offset=158]
- Thought: 37.4s
PRE phase confirmed:
- pre_regbase.h:195-277 Process(): on AIV, zero-fills dq/dk/dv workspace (InitOutput<float>(dqWorkSpaceGm[dqOffset], initdqSize, 0) at line 205; for FP32 it zero-fills dqGm/dkGm/dvGm directly at 201-203), zero-fills dsink workspace (line 220), and (if dropout) converts drop_mask bits → 1.0/0.0 mask into maskWorkSpaceGm (lines 241-274).
- Note: For SPLIT_AXIS==BN2GS1S2 (0?), only dqWorkSpaceGm zeroed in this pre path, and dk/dv are zeroed for SPLIT_AXIS == 0; for BN2S2 (5) dk/dv are directly zeroed only in special TND cases. Interesting — actually line 204 else if constexpr (SPLIT_AXIS != 1): SPLIT_AXIS==1 is BN2 (isBn2?) — no wait, post's break used SPLIT_AXIS == 5 for BN2S2, so BN2GS1S2 might be 0 or 1... Actually line 206: if constexpr (SPLIT_AXIS == 0) then zero dk/dv workspace — that's BN2GS1S2. Line 209: SPLIT_AXIS == 5 = BN2S2. And SPLIT_AXIS != 1 excludes... hmm, wait: BN2 might be SPLIT_AXIS == 1. Wait but at line 204-209: for BN2GS1S2 (0), zero dqWorkSpace, then if SPLIT_AXIS==0 also zero dk/dv workspace. For BN2S2 (5), zero dq workspace, and if special case zero dk/dv GM directly. For SPLIT_AXIS == 1 (BN2?) — skip everything? Hmm, wait. Let me reconsider: SPLIT_AXIS == 1 might be a different enum value. Actually maybe BN2 = 1? Wait no — the post regbase had if constexpr (SPLIT_AXIS != BN2 && ...) — and SPLIT_AXIS == 5 break for "bn2s2 dk dv no need". Hmm, so BN2S2 == 5. The enum probably: BN2GS1S2=0? BN2S2=5? BN2=1? I don't have exact enum values. Not critical — I'll describe by name, and use the literal 5 for BN2S2 as the code does.

Also the Presfmg variant: FlashAttentionScoreGradPresfmgRegbase — when enablePreSfmg && dTemplateType > 64, it computes the softmax_grad (attention_in based) into sfmg workspace, plus deqScaleDy. That's the "pre-softmax-grad" mode for large head dims (d > 64... actually dTemplateType > 64). For the user's FP16 case with typical head_dim 128 (DTemplateType::Aligned128 = 128?), dTemplateType could be 128 > 64 → Presfmg path if enablePreSfmg is set. Either way, pre phase responsibility: init/zero workspace + prepare softmax grad / dropout mask.

Now the host-side: dqWorkSpaceOffset writers. The search output was truncated; let me check the tool output file for dqWorkSpaceOffset, or simply search the host files. Actually, let me quickly grep the truncated file. Also confirm FP16 entry instantiation: entry_regbase.h:224-242 — for ORIG_DTYPE_QUERY==DT_FLOAT16, template args half, float, half → INPUT_TYPE=half, CALC_TYPE=float, OUTDTYPE=half. Post: FlashAttentionScoreGradS1S2BNGS1S2PostRegbase<half, float, half, ...> — T1=half, T2=float, OUTDTYPE=half. So the output buffers are FP16, cast happens in-kernel (POST's Cast line 241), not framework-dependent.

Let me check the truncated dqWorkSpaceOffset output for host writers to complete the buffer ownership story. Then I'm done and can write the answer.
pre 阶段职责确认（清零 workspace + dropout mask 转换）。最后看一眼 host 侧 dqWorkSpaceOffset 分配
→Read C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b5da68a001Y6b734MEqpb1a4 [limit=60]
- Thought: 46.3s
Good — dqWorkSpaceOffset is a PostParamsRegbase TILING_FIELD (tiling_data_regbase.h:391-396). That's enough; the workspace offsets come from host tiling (SetPostTiling presumably). I have all the evidence needed. Let me also double check where the post workspace sizes/offsets are set on host — but it's not strictly necessary for the answer; I'll mention it as TILING_DATA fields with host writer in tiling files. Actually I have enough.

One more check: the user asked about "TILING_FIELD/TILING_DATA 里与 scale（如 scale、preScale 之类）相关的字段名与读写点". I found:
- TDF::FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase::scaleValue (tiling_data_regbase.h:96) — writer: host tiling_normal_regbase.cpp:1855 (set_scaleValue(fBaseParams.scaleValue)); value origin: tiling_common_regbase.cpp:1011 (*(context_->GetAttrs()->GetAttrPointer<float>(0)) = attr0, the "scale" attr); kernel readers: nz_post Init (nz_post.h:157), post ProcessDqkv (post_regbase.h:238/283), kernel_base SetConstInfo (kernel_base.h:684).
- No preScale symbol exists in this operator (search returned 0). There are quant fields pScale/dsScale/pScaleD/dsScaleD in FagConstInfo (common.h:398-402) — used for quantized input, not the softmax scale.
- Also keepProb (tiling_data_regbase.h:97, attr1) for dropout.

Also let me verify the FP16 instantiation of the post: entry_regbase.h:225-228 (FP16 → half, float, half). And SPLIT_AXIS == 5 is BN2S2 in post (post_regbase.h:314-317 comment). Actually the exact enum numeric: from pre_regbase.h:209 SPLIT_AXIS == 5 is BN2S2, and SPLIT_AXIS == 0 is... line 206 SPLIT_AXIS == 0 zeroes dk/dv workspace which is BN2GS1S2 behavior. Hmm wait, but line 204 SPLIT_AXIS != 1 gate means BN2 (==1) skips the whole workspace zeroing for dq/dk/dv? Actually for BN2 (split), dq/dk/dv are computed per-iteration and written via ProcessMulsAndCast with full coverage (no need for pre-zeroing), so the pre phase skips them. That's consistent: BN2/BN2S2 paths don't need workspace zeroing because in-loop muls+cast writes complete tiles each iteration; BN2GS1S2 needs zeroed FP32 workspace because dq/dk/dv accumulate across s2 iterations (partial sums added by cube MM into workspace).

I now have everything. Let me write the final Cursor-Explore-style answer with full prose + file:line evidence.

Summary structure:

三相总览 (single launch, arch35):
- KERNEL entity: RegbaseFAG<...> template kernel function (entry_regbase.h:196-288), with KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_MIX_AIC_1_2) at line 212. CodeMap kernel_launch mode reports phases pre, main, post and three TPipe instances: pipeIn(pre, :213), pipeBase(main, :63), pipePost(post, :94).

Phase 1 (pre): entry_regbase.h:45-61 → FlashAttentionScoreGradPresfmgRegbase (when enablePreSfmg && dTemplateType>64) or FlashAttentionScoreGradS1S2BNGS1S2PreRegbase (default). Pre class: pre_regbase.h. Init at 107-192; Process at 194-277. Duties: zero-init dq/dk/dv FP32 workspace (pre_regbase.h:199-217 — InitOutput<float>(dqWorkSpaceGm...) etc.; FP32 input → zero dqGm/dkGm/dvGm directly 201-203), zero dsink workspace (:220), and if dropout: expand bitmask drop_mask → 1.0/0.0 bytes into maskWorkSpaceGm (:241-274 Select/Cast/DataCopyPad). SyncALLCores → SyncAll (280-283). (Presfmg variant instead precomputes softmax_grad from attention_in/deqScaleDy into sfmgWorkspaceGm.)

Phase 2 (main): entry_regbase.h:63-90 → FlashAttentionScoreGradKernel (or FlashAttentionScoreGradKernelDeter if deterministic, :84-86); Init (kernel_base.h:187-238, SetConstInfo at :207 → :492-700, InitCVCommonGlobalBuffer :246-284); Process (kernel.h:496+, dispatch to ProcessPreloadTwoTimes if IS_PRELOAD_TWO_TIMES — kernel_base.h:112-114: FP16 small-head (HEAD_DIM_ALIGN<=128), no dropout, BN2GS1S2, non-deterministic; or the main loop with ComputeDqkvBn2gs1s2 / ComputeDqkvBn2s2 / ComputeDqkvBn2). The flash score-grad core math: mm1=dy·V (IterateMmDyV), mm2=Q·K (IterateMmQK), VF1 softmaxGrad (ProcessVec1, block_vec.h:355, cast+softmaxGradFront), V2 pse/attenMask/simpleSoftmax (ProcessVec2), V3 dropout+cast (ProcessVec3), V4 cast+nd2nz (ProcessVec4), c3/c4/c5 = IterateMmDsK(dq=ds·K), IterateMmDsQ(dk=dsᵀ·Q), IterateMmPDy(dv=p·dy) writing to dqWorkSpaceGm/dkWorkSpaceGm/dvWorkSpaceGm (kernel.h:75-101, 147-152 etc.).
  - For BN2GS1S2/BN2S2(部分)/BN2-multiblk: dq/dk/dv go to FP32 workspace (kernel_base.h:261-277 for non-FP32 input).
  - For BN2 split: in-loop v5/v6 ProcessMulsAndCast (kernel.h:379-392, 406-426, 452-486; block_vec.h:654-665, DqkvMulsAndCastFromUB :669-718 with Muls(:707-709) + Cast(:712) → DataCopyPad to dqGm/dkGm/dvGm OUTDTYPE) — scale+cast inside phase2 for BN2. DqkvMulsAndCastFromGM (:722-873, Muls :828-830 + Cast :832).
  - For FP32 input: workspace pointers are the output GM buffers directly (kernel_base.h:278-283), so phase2 writes final FP32 outputs; no post phase.
  - Also SPLIT_AXIS==BN2S2 (5): dk/dv handled in-loop (IS_DK_WRITE_UB/IS_DV_WRITE_UB true for non-deter, kernel_base.h:100-103) and POST skips them (post_regbase.h:314-317 "bn2s2 dk dv no need to do muls and cast" break).

Phase 3 (post): entry_regbase.h:91-110 — runs ONLY when ORIG_DTYPE_QUERY != DT_FLOAT (FP16/BF16), after op.SyncALLCores() (:92) and pipeBase.Destroy() (:93). Non-NZ: FlashAttentionScoreGradS1S2BNGS1S2PostRegbase<INPUT_TYPE=half, T2=float, OUTDTYPE=half, ...> (:96-100). NZ: FlashAttentionScoreGradNzPost (:102-109).

POST 具体 scale/cast:
- Process() post_regbase.h:321-333: only AIV; ProcessDqkv() if SPLIT_AXIS != BN2 && T1 != float; then ProcessSink() if sink.
- ProcessDqkv (post_regbase.h:206-319): for qkvIdx 0..2 (dq,dk,dv), read FP32 workspace via DataCopy (line 234), then:
  - line 238 (ping) / 283 (pong): Muls(vecInPing, vecInPing, (float)tilingData->s1s2BNGS1S2BaseParams.scaleValue, pingSize) — only qkvIdx < 2 (dq/dk), NOT dv.
  - line 241 / 285: Cast(vecOutPing, vecInPing, RoundMode::CAST_ROUND, pingSize) — FP32 → OUTDTYPE (half).
  - line 257/266/270/274 (ping) & 291/300/304/308 (pong): DataCopy/DataCopyPad to dqkvqkvIdx (OUTDTYPE GM: dqkv0=dq, 1=dk, 2=dv — Init at :84-86), with rope split handling (IS_ROPE) dqkRope0/1 (:270, :304).
- NZ variant: nz_post.h — scaleValue member (:90), Init reads tiling scaleValue (:157), DoWork (:341-489): Muls (line 431, DQ/DK only), Cast (line 433), Transdata NZ (line 434), DataCopyPad to dqGm/dkGm/dvGm (:470/477/484).
- Host dtype: FP16 launch → OUTDTYPE=half; FP32 launch → OUTDTYPE=float and POST skipped; cast entirely in-kernel (no framework dependency). Output buffer GM dtype = OUTDTYPE (dqGm etc. kernel_base.h:120, post_regbase.h:56, nz_post.h:50-52).

TILING_FIELD scale:
- TDF::FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase::scaleValue (tiling_data_regbase.h:96-97, getter :132). Host writers: tiling_common_regbase.cpp:1011 fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0)) (attr 0 = scale), tiling_normal_regbase.cpp:1855 set_scaleValue(...). Kernel readers: kernel_base.h:684 (→constInfo.scaleValue), post_regbase.h:238/283, nz_post.h:157.
- constInfo.scaleValue (FagConstInfo, common.h:394-395) used in phase2 in-loop muls (block_vec.h:708, 829).
- No preScale field exists in this operator. Related but distinct: quant fields pScale/dsScale/pScaleD/dsScaleD (common.h:398-402), keepProb (tiling_data_regbase.h:97, attr1 common:1012). deqScaleIdx is a presfmg method param (presfmg_regbase.h:52).

Buffer dtype question:
- FP16 case: phase2 writes FP32 workspace; POST reads FP32 workspace, Muls scale, Cast FP32→FP16 (CAST_ROUND), writes FP16 output GM. All in-kernel. Output dq/dk/dv are OUTDTYPE=half GM buffers (kernel_base.h:120, post Init :84-86). So cast is inside kernel POST (post_regbase.h:241/285, nz_post.h:433) — not framework. For BN2 split, cast inside phase2 (block_vec.h:712/832).
- FP32 case: workspace aliases output GM (kernel_base.h:278-283); no cast; no POST.

Also worth noting for the user's FP16 debugging: the scale multiplication uses (float)tilingData->s1s2BNGS1S2BaseParams.scaleValue — plain float muls, and it's applied ONLY to dq/dk, not dv. In BN2GS1S2 + POST path, dv gets cast but no scale. Also worth noting the round mode CAST_ROUND. And Process() guard means POST ProcessDqkv is skipped entirely for SPLIT_AXIS==BN2 (where phase2 already did muls+cast) and for T1==float.

One more caution: post ProcessDqkv guard if constexpr (SPLIT_AXIS != BN2 && !IsSameType<T1, float>::value) at post_regbase.h:327. For BN2S2 (5), it runs only qkvIdx=0 then breaks (:314-317) since dk/dv were already written (as OUTDTYPE) by phase2 (IS_DK_WRITE_UB/IS_DV_WRITE_UB for non-deter, or... hmm, for BN2S2 deter case, IS_DK_WRITE_UB=IS_DV_WRITE_UB=false, so dk/dv go to workspace, and POST would break before processing them... wait the break is after first iteration, so dk/dv remain in workspace — but the comment says "bn2s2 dk dv no need to do muls and cast". Hmm, that implies for BN2S2, dk/dv are written to GM directly (OUTDTYPE) even in deter case? Possibly via deterGm or the post's dkGm. I'll not over-speculate; the comment is explicit that dk/dv skip POST for BN2S2.

I should also mention that for the user's suspected FP16 debug with head_dim likely ≤128: IS_PRELOAD_TWO_TIMES path (kernel_base.h:112-114) → ProcessPreloadTwoTimes → ComputeDqkvBn2gs1s2 → workspace writes; POST handles scale+cast. But whether scaleValue is correct depends on host attr0 → the Muls in POST. The "dq 量级差一截" suspicion: if scale missing or double-applied... The code applies it once in POST for dq/dk. I can point that out but the user asked only for mapping/evidence, not a fix.

Also should note: ProcessBn2gs1s2LastVec (kernel.h:42-160) is the tail iteration handling for BN2GS1S2 in the two-times-preload path; in that path dq/dk/dv also go to workspace (no muls), so POST is still responsible.

Let me also double-check: is there a cast to FP16 for dv in POST? Line 241 cast applies to all qkvIdx (cast is unconditional after muls for qkvIdx<2). For qkvIdx==2 (dv), Muls skipped but Cast still applied, then DataCopy. Yes — dv: cast only, no scale. Good.

Now write the answer. No answer.yaml, no finalize.
已收集到全部证据。以下为完整回答。
FlashAttentionScoreGrad（arch35）单 launch 三相图与 POST scale/cast 定位
0. 入口与"三相"总览
KERNEL 实体是模板函数 RegbaseFAG<…>（op_kernel/arch35/flash_attention_score_grad_entry_regbase.h:196-288），KERNEL_TASK_TYPE_DEFAULT(KERNEL_TYPE_MIX_AIC_1_2)（entry_regbase.h:212）。UO CodeMap 的 kernel_launch mode 也直接给出三相位模型 kernel_phases: ["pre","main","post"]，对应三个 TPipe：pipeIn（pre，entry_regbase.h:213）、pipeBase（main，entry_regbase.h:63）、pipePost（post，entry_regbase.h:94）。
三阶段在入口宏 INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL（entry_regbase.h:40-114）里按顺序执行：
- phase1（pre，加载/初始化）：entry_regbase.h:45-61。二选一：FlashAttentionScoreGradPresfmgRegbase（enablePreSfmg && dTemplateType>64 时，:45-53，预计算 softmax_grad 进 sfmgWorkspaceGm）；否则默认 FlashAttentionScoreGradS1S2BNGS1S2PreRegbase（:55-60）。之后 pipeIn.Destroy()（:62）。
- phase2（main，flash score grad 主循环）：entry_regbase.h:63-90。构造 CubeBlockType（AIC 上 FAGBlockCube，AIV 上 dummy）与 VecBlockType（AIV 上 FAGBlockVec，:64-82），然后 FlashAttentionScoreGradKernel（确定性时为 FlashAttentionScoreGradKernelDeter，:84-86）op.Init(...) + op.Process()（:87-90）。
- phase3（post，收尾/输出）：entry_regbase.h:91-113。只有 ORIG_DTYPE_QUERY != DT_FLOAT（即 FP16/BF16）才执行（:91）；op.SyncALLCores()（:92）、pipeBase.Destroy()（:93）后新建 pipePost；非 NZ 输出用 FlashAttentionScoreGradS1S2BNGS1S2PostRegbase<INPUT_TYPE, float, OUTDTYPE, …>（:95-100），NZ 输出用 FlashAttentionScoreGradNzPost（:102-109）。FP32 分支直接 pipeBase.Destroy() 结束（:111-112），没有 post 阶段——这正好解释了"FP32 同 shape 通过、FP16 量级差一截"时最该盯住 phase3 的现象。
FP16 的模板实例化在 entry_regbase.h:223-242：half, float, half → INPUT_TYPE=half、CALC_TYPE=float、OUTDTYPE=half。
1. 三相各自的职责与 buffer 归属
Phase1（pre）：FlashAttentionScoreGradS1S2BNGS1S2PreRegbase，Init 在 op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_pre_regbase.h:107-192，Process 在 :194-277。职责（AIV、且 cBlockIdx < maskCoreNum 才做，:198）：
- 清零 dq/dk/dv 的 FP32 GM workspace：InitOutput<float>(dqWorkSpaceGm[dqOffset], initdqSize, 0)（pre_regbase.h:205；SPLIT_AXIS==0 即 BN2GS1S2 时连 dk/dv workspace 一起清，:206-208）；FP32 输入则直接清输出 GM（:201-203）。workspace 基址来自 tilingData->postTilingData.dqWorkSpaceOffset/dkWorkSpaceOffset/dvWorkSpaceOffset（:149-151，这是 PostParamsRegbase 的 TILING_FIELD，flash_attention_score_grad_tiling_data_regbase.h:391-396）。
- 若 sink：清零 dsinkWorkSpaceGm（:219-221）。
- 若 dropout：把 bit 型 drop_mask 展开成 1.0/0.0 字节写入 maskWorkSpaceGm（:241-274，Select+Cast+DataCopyPad）。
- SyncALLCores() = SyncAll<false>()（:280-283）。
Phase2（main）：FlashAttentionScoreGradKernel::Init（flash_attention_score_grad_kernel_base.h:187-238）做 SetConstInfo()（:207 → 定义 :492-700，其中 constInfo.scaleValue = tilingData->s1s2BNGS1S2BaseParams.scaleValue; 在 :684）和 InitCVCommonGlobalBuffer（:246-284）。关键分支（:261-283）：
- 非 FP32 输入（FP16/BF16）：dqWorkSpaceGm/dkWorkSpaceGm/dvWorkSpaceGm 指向 FP32 workspace（:271-276，BN2 非 multiblk 特殊路径用 RESERVED_WORKSPACE_SIZE 后偏移，:262-269）；输出 GM dqGm/dkGm/dvGm 是 GlobalTensor<OUTDTYPE>（:120）。
- FP32 输入：三个 workspace 直接别名输出 GM（:278-283，注释 "input type fp32, dq dk dv write to output gm directly"）——所以 FP32 无 post、无 cast。
主循环（flash_attention_score_grad_kernel.h）：Process()（:496+）按 IS_PRELOAD_TWO_TIMES（kernel_base.h:112-114：HEAD_DIM_ALIGN<=128 && !IS_DROP && SPLIT_AXIS==BN2GS1S2 && NO_DETER && !IS_FP32_INPUT，即典型的 FP16 小 head_dim 场景）走 ProcessPreloadTwoTimes()（kernel.h:499-500，定义 :589+），否则走通用循环调 ComputeDqkvBn2gs1s2（:38）/ComputeDqkvBn2s2（:178）/ComputeDqkvBn2（:310）。核心计算链：IterateMmDyV（p）、IterateMmQK、VF1 ProcessVec1（cast + softmaxGrad，block_vec.h:355-385）、V2（pse/attenMask/softmax）、V3（dropout+cast，kernel.h:341-342 注释）、V4（cast+nd2nz，:351）、C3/C4/C5 = IterateMmDsK（dq=ds·K）、IterateMmDsQ（dk=dsᵀ·Q）、IterateMmPDy（dv=p·dy），写入 dqWorkSpaceGm/dkWorkSpaceGm/dvWorkSpaceGm（kernel.h:75-101、147-152、382-392 等）。
注意 BN2 分轴的特殊分支：ComputeDqkvBn2 里 v5/v6 直接调 ProcessMulsAndCast（kernel.h:379-392、406-426），BN2 multiblk 同理（:452-486），即 BN2/BN2S2 的 scale+cast 在 phase2 内完成（见下节），而 BN2GS1S2 只写 workspace。IS_DQ_WRITE_UB/IS_DK_WRITE_UB/IS_DV_WRITE_UB 定义在 kernel_base.h:99-103。
Phase3（post）：FlashAttentionScoreGradS1S2BNGS1S2PostRegbase::Process()（flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h:321-333）：仅 AIV（:324-326）；if constexpr (SPLIT_AXIS != BN2 && !IsSameType<T1, float>::value) ProcessDqkv();（:327-329）；若 sink 再 ProcessSink()（:330-332，dsink 归约写回，:121-204）。
2. POST 阶段 scale 与 cast 的具体位置
非 NZ 输出（FlashAttentionScoreGradS1S2BNGS1S2PostRegbase::ProcessDqkv，post_regbase.h:206-319）：
- 读 FP32 workspace：DataCopy(vecInPing, dqkvWorkspace[qkvIdx][pingIdx], …)（:234）。
- scale 乘法（:238，ping；:283，pong）：Muls(vecInPing, vecInPing, (float)tilingData->s1s2BNGS1S2BaseParams.scaleValue, pingSize); —— 只对 qkvIdx < 2（dq、dk）执行，dv 不乘 scale。
- cast（:241，ping；:285，pong）：Cast(vecOutPing, vecInPing, RoundMode::CAST_ROUND, pingSize); —— FP32 → OUTDTYPE（FP16 时即 half）。
- 输出写回：DataCopy(dqkv[qkvIdx][pingIdx], vecOutPing, …)（:274 非 rope；:257/266/270 rope 分块写 dqkv 与 dqkRope）。dqkv[0/1/2] 是 GlobalTensor<OUTDTYPE>，在 Init 里绑定到 dq/dk/dv GM（:84-86）。
- BN2S2（SPLIT_AXIS==5）只处理 dq 即 break（:314-317，注释 "bn2s2 dk dv no need to do muls and cast"）。
NZ 输出（FlashAttentionScoreGradNzPost，flash_attention_score_grad_nz_post.h）：成员 float scaleValue（:90）；Init 里 scaleValue = tilingData->s1s2BNGS1S2BaseParams.scaleValue;（:157）；DoWork（:341-489）里 Muls(srcTensor, srcTensor, scaleValue, srcM * curD);（:431，仅 DQ/DK）、Cast(srcTensorB16, srcTensor, RoundMode::CAST_ROUND, …)（:433，FP32→OUTDTYPE）、Transdata<OUTDTYPE>（:434，NZ 变换）、DataCopyPad(dqGm/dkGm/dvGm, …)（:470/477/484）。
Phase2 内的另一条 scale+cast 路径（BN2/BN2S2 用，非 POST）：FAGBlockVec::ProcessMulsAndCast（block_vec.h:654-665）→ DqkvMulsAndCastFromUB（:669-718，Muls(inputTensor, inputTensor, constInfo.scaleValue, dataSize) :707-709，Cast(...CAST_ROUND...) :712，DataCopyPad(dqkvGmTensor…) :716）与 DqkvMulsAndCastFromGM（:722-873，Muls :828-830，Cast :832）。注意这里同样是 MM_IDX != DV_IDX 才乘 scale（:707、:828），且写的是 OUTDTYPE 输出 GM（:682、:807）。
3. TILING_FIELD 里与 scale 相关的字段与读写点
- TDF::FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase::scaleValue（flash_attention_score_grad_tiling_data_regbase.h:96-97，getter get_scaleValue() :132）。
- host 写点①：op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp:1011 fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0)); —— 即算子 attr0（scale）。
- host 写点②：op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1855 s1s2BNGS1S2BaseParams_->set_scaleValue(fBaseParams.scaleValue);
- kernel 读点：kernel_base.h:684（→ FagConstInfo::scaleValue，common.h:394-395）；post_regbase.h:238/283（POST Muls）；nz_post.h:157（POST Init）。
- FagConstInfo::scaleValue（common.h:394-395）→ phase2 内 block_vec.h:708/829 的 Muls。
- preScale 字段在本算子不存在（CodeMap search 返回 0；empty 不等于绝对无，但结合源码全量搜索 scale 只命中上述字段，可判定无此命名）。与 scale 相邻但不同语义的量化字段：FagConstInfo::pScale/dsScale/pScaleD/dsScaleD/pScaleLog（common.h:398-402，量化/反量化参数）；dropout 用 keepProb（tiling_data_regbase.h:97，attr1，common:1012）。presfmg 的 deqScaleIdx 是方法形参（presfmg_regbase.h:52）。
4. 输出 buffer 的 dtype：FP16 还是 FP32？cast 在哪？
- FP16 输入（half,float,half）：phase2 输出到 FP32 workspace（kernel_base.h:271-276）；POST 在 kernel 内完成 Muls(scaleValue) + Cast(FP32→FP16, CAST_ROUND)（post_regbase.h:238-241、283-285；NZ 变体 nz_post.h:431-434），写回 FP16（OUTDTYPE=half）输出 GM（dqGm/dkGm/dvGm 类型 OUTDTYPE，kernel_base.h:120；post Init :84-86）。cast 完全在 kernel 内，不依赖框架；框架侧只需保证 attr0 scale 正确传入（common:1011）。
- FP32 输入：workspace 直接别名输出 GM（kernel_base.h:278-283），phase2 直接写 FP32 输出，无 cast、无 POST（entry_regbase.h:91 条件不成立）。
- 特例：BN2/BN2S2 分轴下 scale+cast 提前到 phase2 的 v5/v6（block_vec.h:707-712、828-832），POST 对 BN2 整体跳过（post_regbase.h:327）、对 BN2S2 只处理 dq（:314-317）。
对 FP16 调试的提示（证据层面的观察，非修复）
1. POST 的 scale 只乘 dq/dk，dv 只 cast 不乘 scale（post_regbase.h:237-241）——若怀疑"dq 量级差一截"，先核对 dq/dk 是否一致、dv 是否本来就该无 scale。
2. FP16 走 BN2GS1S2 + POST 时，phase2 写的是 FP32 workspace，不存在二次 cast；scale 只出现一次（POST :238/:283）。若怀疑"写错导致差一截"，最该核对的是 host attr0（common:1011）与 tiling 写入（tiling_normal_regbase.cpp:1855）是否同一值，以及 POST 模板实例化里 T2=float（entry_regbase.h:96）。
3. Process() 的 SPLIT_AXIS != BN2 守卫（post_regbase.h:327）意味着 BN2 路径的 scale/cast 在 phase2 内（block_vec.h:707-712），两条路径不要混看。
4. 若 shape 触发 IS_PRELOAD_TWO_TIMES（kernel_base.h:112-114，FP16 + head_dim≤128 + 无 dropout + BN2GS1S2），尾块走 ProcessBn2gs1s2LastVec（kernel.h:42-160），dq/dk/dv 同样进 workspace，POST 逻辑不变。
说明：SPLIT_AXIS 的枚举数值除 BN2S2==5 由 post_regbase.h:314 与 pre_regbase.h:209 佐证外，其余按符号名引用（host 侧赋值见 tiling_common_regbase.cpp:1641-1648）。Presfmg 变体（enablePreSfmg 且 dTemplateType>64）的 pre 内部细节我只定位到入口与类文件，未逐行展开其 scale 相关路径——如需可再查。
▣  Uo-Query · DeepSeek V4 Flash Free · 5m 51s
Subagent(1 of 9)138.2K (69%)

# subagent 2

算子目录：d:\TEST\ops-transformer\attention\flash_attention_score_grad（arch35，.uo CodeMap 已建好）。

立即调用 acp 工具：command=`uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...`（你自己按需选 locate / symbols / callers / fields 等 mode）。禁止 bash、Grep、MCP 替代。

背景：用户做 FP16 精度调试（dq 量级差一截，FP32 同 shape 过），怀疑 POST 的 scale/cast。现在要弄清三个开关/路径各自怎么走：FP32 路径、BN2、enablePreSfmg。

请查清并回答（全部带 file:line 证据）：
1. FP32 与 FP16 在 kernel 里的路径差异：查 dtype 相关条件（如 input dtype 判断、模板参数、COMPILE_VAR），FP32 时走哪些分支、FP16 时多走哪些（如 cast、scale 处理不同）。
2. BN2 是什么：在 tiling/host 里 BN2（或 blockNum2、bN 之类字段）的定义与含义，TILING_FIELD 里怎么绑定、kernel 里在哪用；它控制什么循环/块划分。
3. enablePreSfmg 字段：TILING_FIELD/TILING_DATA 里有没有 enablePreSfmg（或 preSfmg/preScale 相关字段），host 侧从哪解析、kernel 里在哪分支；开/关时各走什么（是否影响 scale 的施加位置，比如 pre-softmax scale vs post scale）。
4. 这些路径与 POST scale/cast 的关系：enablePreSfmg 或 FP16 时 POST 的 scale/cast 是否不同。

请用 Cursor Explore 风格回答：完整散文 + file:line 列表。若某处是 host_runtime_leaf 无法静态确定，明确说"UNKNOWN/partial"并说明原因。不要写 answer.yaml，不要 finalize。
- Thought: 2.4s
The user wants me to query the UO CodeMap for the operator d:\TEST\ops-transformer\attention\flash_attention_score_grad. Let me start by running the uo-query command with appropriate modes.

Let me first do a locate/symbols query to understand the structure.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode symbols --pattern .]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode fields --pattern .]
- Thought: 7.8s
The valid modes are: search, constraints, neighbors, impact, field, branches, templates, tiling_key, tiling_data, kernel_branch, template_match, buffer, gaps, legal_key, locate, kernel_api, kernel_launch, compile.

Let me start with a search for key patterns: FP16/FP32 dtype, BN2, enablePreSfmg, preSfmg, preScale, POST scale/cast.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern enablePreSfmg --limit 50]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern preSfmg --limit 50]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern BN2 --limit 50]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern FP16 --limit 50]
- Thought: 1.9s
The search results are truncated. I should read the output files with the Read tool (they are machine-scope output files from the tool, saved in the opencode tool-output directory — these are outputs from the acp tool, allowed to read since they're tool outputs).

Let me read these files to see the results. They're large, so I'll read with limits.
The search outputs were saved to files. Let me read
→Read C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b5b2957001Gl5e65ALpuLkM5 [limit=300]
→Read C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b5b2b3c0010jY9QGR04b7rMI [limit=300]
- Thought: 2.3s
The search results are big JSON. Let me be more targeted. I need:

1. FP32 vs FP16 path differences — dtype conditions (template params, COMPILE_VAR, input dtype)
2. BN2 — tiling/host definition and TILING_FIELD binding
3. enablePreSfmg — TILING_FIELD/TILING_DATA, host parsing, kernel branch
4. Relationship with POST scale/cast

Let me use more focused queries. First, let me look at the search results for BN2 and FP16 from the saved files, then use locate/tiling_key/tiling_data/kernel_branch modes.

Let me read the BN2 and FP16 output files.
→Read C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b5b2e26001xwAHuIJXM4ykOP [limit=200]
→Read C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b5b30a2001jBrc2uqW2SWGQI [limit=200]
- Thought: 924ms
The search results give useful info. Now I need to be more targeted. Let me:

1. Find the tiling data structure and TILING_FIELD bindings — use tiling_data mode
2. Find host-side tiling logic for BN2 / enablePreSfmg
3. Find kernel branches for dtype (FP32 vs FP16) and enablePreSfmg

Let me query tiling_data and kernel_branch modes.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode tiling_data --pattern enablePreSfmg --limit 80]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode tiling_data --pattern BN2 --limit 80]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode kernel_branch --pattern enablePreSfmg --limit 80]
- Thought: 5.3s
Excellent, this is rich data. Now I have:

1. enablePreSfmg field:
   - Declared in op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h:120 (bool, owner FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase)
   - Host writer: op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1896 — s1s2BNGS1S2BaseParams_->set_enablePreSfmg(fBaseParams.enablePreSfmg)
   - Value definition: op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1141 — fBaseParams.enablePreSfmg = (fBaseParams.queryType == ge::DT_HIFLOAT8) || ((fBaseParams.queryType == ge::DT_BF16 || fBaseParams.queryType == ge::DT_FLOAT16) && presfmgLimit && d > NUM64 && d <= NUM768 && (splitAxis == BN2GS1S2 || splitAxis == BN2S2) && ...
   - presfmgLimit at line 1139: !(s2 <= NUM256 && b*n1*s1Outer >= MAX_BASIC_BLOCK_SIZE)
   - Kernel readers: flash_attention_score_grad_block_vec.h:243 InitGlobalBuffer, :306 InitUbBuffer, flash_attention_score_grad_kernel_base.h:488 SetConstInfo
   - Also FagConstInfo::enablePreSfmg in flash_attention_score_grad_common.h:463

Now I need to dig deeper:
- The full RHS expression of enablePreSfmg at line 1141 (truncated)
- BN2 meaning: splitAxis == BN2 / BN2S2 / BN2GS1S2 — these are SplitAxis enum values. Need to find definition in host code. Also kernel entry uses splitAxis == BN2 branch (line 236-242 of entry_regbase.h).
- FP32 vs FP16 paths in kernel: ORIG_DTYPE_QUERY compile var; DT_FLOAT vs others; the entry uses #if (ORIG_DTYPE_QUERY == DT_BF16) etc. Need to look at entry file and how scale is applied.
- POST scale/cast: PreParamsRegbase/PostParamsRegbase — need to see scale fields (scaleValue, deqScale...), how they're used in kernel, and where enablePreSfmg affects scale application.

Let me run more queries:
1. tiling_data --pattern scale or search for scale in kernel
2. kernel_branch --pattern splitAxis 
3. branches --pattern preSfmg? Actually the mode list has branches. Let me use branches mode with query about enablePreSfmg.
4. locate --pattern blockNum for BN2 fields.
5. Search for "blockNum2" / "bn2" / "blockNum" host side.

Let me also check search --pattern splitAxis, search --pattern DT_FLOAT, search --pattern ORIG_DTYPE_QUERY, and kernel branch queries on scale.

Let me be efficient with parallel calls.
Rich data on enablePreSfmg. Now let me dig into BN2/splitAxis, the ORIG_DTYPE_QUERY compile var, and scale handling.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern splitAxis --limit 40]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern ORIG_DTYPE_QUERY --limit 40]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern SplitAxisEnum --limit 40]
- Thought: 1.5s
The template tiling key header gives me key info. Let me read the full template_tiling_key.h — it's within machine-scope (op_kernel) but I can use the acp tool with file option or read portions. Actually, per my boundaries, machine-scope operator sources are outside .ascendc-pilot — I should locate them with UO KB query/ScopeSet first, then machine-scope windowed Read. The uo-query results give me file paths and line numbers; for windowed reading I can use the read tool on the specific files with offsets.

Let me read the template_tiling_key.h to get the full InputDType declaration, and check the saved search outputs for splitAxis and SplitAxisEnum.
→Read C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b5baacb001hDn5u97a67F6bT [limit=250]
→Read C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b5baef4001S8Pp6tpuGgd1hY [limit=250]
- Thought: 5.3s
I now have splitAxis info. Key: SplitAxisEnum::BN2S2, BN2, BN2GS1S2 are values of a SplitAxisEnum. Need to find where SplitAxisEnum is defined (probably a common header in op_host or op_kernel). Let me search for "isBn2" and "BN2" in host. Also need to see the full SetSplitAxis function at op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp:1643-1647 and understand isBn2 definition.

Also I need:
1. Full enablePreSfmg RHS (line 1141 in tiling_normal_regbase.cpp) — need to read the file window.
2. How kernel uses enablePreSfmg — check block_vec.h InitGlobalBuffer/InitUbBuffer and SetConstInfo (kernel_base.h:488), and FagConstInfo::enablePreSfmg.
3. Where scale is applied in kernel: search for "scale" patterns, preScale/postScale, deqScale, CalculateSoftmaxGrad etc. Check PresfmgRegbase — the pre-softmax scale module. Also search for "scale" in kernel files.
4. FP32 vs FP16: template key InputDType (1: FLOAT32, 2: BFLOAT16...), ORIG_DTYPE_QUERY compile macro, entry_regbase.h dispatch under #if (ORIG_DTYPE_QUERY == DT_FLOAT) etc. Need the rest of the template key file and entry file.

Let me do windowed reads of the machine-scope source files using read tool (allowed since UO KB query gave me the ScopeSet locations). The boundaries say machine-scope operator sources are outside .ascendc-pilot, locate with UO KB query / ScopeSet first, then machine-scope windowed Read — never whole-file dumps. So targeted reads with offsets are permitted.

Files to read:
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h (full, it's short)
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp around line 1100-1200 (enablePreSfmg + presfmgLimit), and around 1420-1480 (GetTilingKey)
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp around 1600-1700 (SetSplitAxis)
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h around 200-260
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_common.h around 389-470 (FagConstInfo)
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_vec.h around 243-320
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h around 488
- Also search kernel for scale: search --pattern scaleValue, search --pattern preScale, search --pattern PostParams, etc.

Let me first read the template tiling key file fully, then run a few more targeted searches in parallel.
Now let me read the machine-scope files that the CodeMap located (windowed reads), and run more targeted queries in parallel.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h 
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern scaleValue --limit 40]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern isBn2 --limit 30]
- Thought: 1.9s
The template tiling key file is large. Key facts I got:
- SplitAxis bit 3-1: 0=BN2GS1S2, 1=BN2, 5=BN2S2
- InputDType bit 6-4: 1=FLOAT32, 2=BFLOAT16, 3=FLOAT16_PRECISION, 4=FP8_E5M2, 5=FP8_E4M3FN, 6=HIFP8
- ORIG_DTYPE_QUERY compile macro: #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16) selects FP16 list, #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_BF16) selects BF16 list. Need to check if there's a DT_FLOAT section too. Let me continue reading the file to see DT_FLOAT section and how InputDType=1 is used, plus the FLOAT32 template dispatch. Actually since it's capped at 50KB, the FP32 sections may be later in the file.

Let me read the scaleValue and isBn2 search outputs, and continue reading the template file at offset 956 (the file might have FLOAT32 section at the end).
→Read C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b5be51b001dRt2k1CZaVuz76 [limit=120]
→Read C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b5be937001rnjji8H204CkWI [limit=150]
- Thought: 3.1s
I'm getting a picture. Now I need:
1. Where is isBn2 set in host (search for isBn2 = or the initial definition)? The snippet shows fBaseParams.isBn2 = false in DoBn2MultiBlkSparse (line 681). Need to find where isBn2 is first set. Let me search "isBn2" more or check SetSplitAxis and GetBn2 or similar. Let me look at the tiling_common_regbase.cpp around line 1600-1700 for SetSplitAxis and see where isBn2 is derived. Also check DoTiling/DoPreTiling flow for isBn2 derivation (like isBn2 = ... from shape: n2/g vs aicNum or something).

2. The kernel-side usage of enablePreSfmg — need block_vec.h InitGlobalBuffer/InitUbBuffer, kernel_base.h SetConstInfo, and where FagConstInfo::enablePreSfmg is used to branch. Let me read those files (windowed).

3. The scale path: PostParamsRegbase — search for postTilingData fields (scaleValue etc.). Also, where kernel applies scale: search "scale" or "preScale" / "Muls" in kernel. Let me search for "preScale".

4. FP32 path in kernel: entry_regbase.h dispatch — read lines ~200-260 and also find ORIG_DTYPE_QUERY == DT_FLOAT sections in the entry file.

Let me run parallel: read entry_regbase.h window, read block_vec.h window around 243-320, search preScale, and read tiling_common around SetSplitAxis.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h [offset=120, limit=180]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern preScale --limit 30]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern blockNum2 --limit 30]
- Thought: 4.8s
Now I have the kernel entry dispatch clearly:
- FP16: #if (ORIG_DTYPE_QUERY == DT_FLOAT16) → INVOKE with half, float, half (INPUT_TYPE=half, CALC_TYPE=float, OUTDTYPE=half) for BN2GS1S2/BN2S2/BN2
- BF16: #if (ORIG_DTYPE_QUERY == DT_BF16) → bfloat16_t, float, bfloat16_t
- FP32: #if (ORIG_DTYPE_QUERY == DT_FLOAT) → float, float, float

So the FP16 path uses INPUT_TYPE=half with CALC_TYPE=float — i.e., the calc is float but inputs are half. Both paths share the same template machinery; the difference is dtype and the enablePreSfmg host flag plus possibly cast handling.

No preScale substring, no blockNum2. So enablePreSfmg is the actual name; "BN2" is not a tiling field named blockNum2 but a SplitAxis value (BN2 / BN2S2 / BN2GS1S2).

Now I need:
1. Where does host compute isBn2 (the condition to choose BN2)? Search for "isBn2" definition. Let me look at the tiling_common SetSplitAxis region (lines ~1600-1700) and search isBn2 = assignments.
2. Kernel use of enablePreSfmg — read block_vec.h lines 230-340, kernel_base.h around 488, and where FagConstInfo::enablePreSfmg branches (search "enablePreSfmg" in kernel files — the search earlier found only 3 reader sites; the actual branch might be via constInfo.enablePreSfmg in kernel code, maybe in presfmg files. Let me search "Presfmg" and "preSoftmax").
3. POST scale/cast: PostParamsRegbase fields — search "PostParams" and check scaleValue / deqScale in post. Also search "deqScaleDy" kernel usage.
4. Full RHS of enablePreSfmg at line 1141 — read tiling_normal_regbase.cpp window 1100-1200.
5. FP32 host route: does host enablePreSfmg for DT_FLOAT? From the RHS: queryType == DT_HIFLOAT8 || ((BF16 || FP16) && ...) — so FP32 → enablePreSfmg = false always. That's a key answer.
6. presfmg kernel: FlashAttentionScoreGradPresfmgRegbase (the file found earlier: flash_attention_score_grad_presfmg_regbase.h) — pre-softmax scale module. Let me check how it's invoked — search "Presfmg" in kernel.

Let me do these in parallel.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=120, offset=1090]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern Presfmg --limit 40]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp [limit=90, offset=1590]
- Thought: 7.2s
Excellent — this is very informative:

BN2 host-side:
- fBaseParams.isBn2MultiBlk computed at tiling_common_regbase.cpp:1596-1606 — requires bnSparseLimit (bn1 >= 256 or (bn1 >= 128 && s1/s2 % 128 == 0), non-TND, non-prefix sparse), s1/s2 in range, n1==n2, d <= BN2_MAX_D, queryType != DT_FLOAT (line 1601!), not fp8, no rope.
- fBaseParams.isBn2 = fBaseParams.isBn2MultiBlk ? true : fBaseParams.isBn2; line 1607. isBn2 gets set earlier somewhere (search needed — where is isBn2 first assigned? Maybe from earlier shape checks). 
- SetSplitAxis (lines 1641-1648): BN2S2 if bn2S2RouteLimit (which also requires queryType != DT_FLOAT at line 1637), else BN2 if isBn2, else BN2GS1S2.
- So FP32 (DT_FLOAT) never routes to BN2 or BN2S2 — always BN2GS1S2 (line 1637: queryType != DT_FLOAT for BN2S2; line 1601: queryType != DT_FLOAT for isBn2MultiBlk).

enablePreSfmg host-side (tiling_normal_regbase.cpp:1139-1149):
- presfmgLimit = !(s2 <= 256 && b*n1*s1Outer >= MAX_BASIC_BLOCK_SIZE)
- enablePreSfmg = (queryType == DT_HIFLOAT8) || ((queryType == DT_BF16 || queryType == DT_FLOAT16) && presfmgLimit && d in (64,768] && (splitAxis == BN2GS1S2 || splitAxis == BN2S2) && !isDeterministic && sinkOptional != NORMAL_TENSOR && dropoutIsDivisibleBy8 && !sValueZeroUnderTND)
- So FP32 → enablePreSfmg = false always. Also BN2 split → enablePreSfmg = false (since splitAxis must be BN2GS1S2 or BN2S2).

Now for the kernel side:
- enablePreSfmg is read by FagBlockVec::InitGlobalBuffer (block_vec.h:243), InitUbBuffer (block_vec.h:306), and FlashAttentionScoreGradKernelBase::SetConstInfo (kernel_base.h:488) → stored into FagConstInfo::enablePreSfmg (common.h:463).
- The presfmg module: FlashAttentionScoreGradPresfmgRegbase (flash_attention_score_grad_presfmg_regbase.h) — pre-softmax softmax-grad calc. Need to see where it's instantiated — probably inside FAGBlockVec or the kernel Process when enablePreSfmg is true. Let me read block_vec.h 230-340 and kernel_base.h 460-520, plus find "Presfmg" usage sites in the search output file.

Also need where isBn2 first set — search "isBn2 = " in host, maybe in DoTiling before. Let me check the search output for isBn2 more, but easier: search pattern "isBn2" was truncated at 30 rows; I have enough: isBn2 is a fBaseParams member set somewhere (perhaps from tiling data of forward or computed in DoTiling). Let me search "isBn2 =" quickly with locate mode? Actually let me use search with pattern "isBn2 =" to find assignment sites.

Also POST scale/cast: need to look at PostParamsRegbase (postTilingData) fields and the Post module. Search "PostParams" and "deqScaleDy" and "scale" in kernel. The nz_post.h has scaleValue. Let me find where post scale applied — probably in FlashAttentionScoreGradS1S2BNGS1S2PostRegbase (sink only). The user asked about POST scale/cast: in this operator, POST (PostRegbase) runs only when sinkOptional (line 134-141, 170-178 of entry). scaleValue in nz_post.h:90.

Let me also check "deqScaleDy" and how scale is applied in pre (PresfmgRegbase) vs main kernel. Search for "scale" patterns in kernel files.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_vec.h [limit=160, offset=200]
→Read C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b5c4b68001zS6klm2xY5UPzM [limit=100]
- Thought: 3.0s
Now I need to see:
1. Where FlashAttentionScoreGradPresfmgRegbase is instantiated (probably in FAGBlockVec::Process or FlashAttentionScoreGradKernel). Search "PresfmgRegbase" or "opPre" usage. Let me search for "FlashAttentionScoreGradPresfmgRegbase" specifically (usage sites) — earlier search showed only the class def. Let me search "Presfmg" with different pattern, or use neighbors on the presfmg method.

2. The pre-softmax scale: In presfmg module, CalculateSoftmaxGrad uses deqScaleDy (line 51). Let me read the presfmg file around CalculateSoftmaxGrad to see the scale application.

3. Where in the main vec pipeline is scale applied: check ProcessVec1 (VF1: Cast + SoftmaxGradFront) in block_vec.h line 354+.

4. Post module: FlashAttentionScoreGradS1S2BNGS1S2PostRegbase / nz_post.h — the POST stage applies scale? Let me read nz_post.h around scaleValue use and search "scaleValue" in post file.

5. Also, key question: FP16 vs FP32 scale handling difference. Look for IS_FP32_INPUT macro and enablePreSfmg conditions in vec Process, plus the deqScale handling. Let me search "deqScale" in kernel.

Let me read more of block_vec.h (ProcessVec1 onwards ~360-560) and search for Presfmg usage + deqScale.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_vec.h [limit=240, offset=355]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern deqScale --limit 40]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode neighbors --pattern FlashAttentionScoreGradPresfmgRegbase --depth 2 --limit 40]
- Thought: 6.7s
I need to find where FlashAttentionScoreGradPresfmgRegbase is actually invoked (the caller). The neighbors query didn't show a caller. Let me search "FlashAttentionScoreGradPresfmgRegbase opPre" or look at the kernel_base.h Process to see where presfmg is invoked. Also I need to see:

1. Where presfmg module is called — probably in FlashAttentionScoreGradKernelBase::Process with if (unlikely(constInfo.enablePreSfmg)). Let me read kernel_base.h around 460-560 (SetConstInfo at 488) and the Process function.

2. The presfmg CalculateSoftmaxGrad — how it applies scale (deqScaleDy and scaleValue). Read presfmg_regbase.h around 119-260.

3. The POST scale/cast — read s1s2_bn2gs1s2_post_regbase.h and nz_post.h scaleValue usage. Also check where "scaleValue" from PreParams/PostParams is set on host: search "scaleValue" in host files (the set_scaleValue). The earlier search only found nz_post.h. Let me search "scaleValue" again with host context: search pattern "scaleValue" found 11 rows; only nz_post.h in the snippet shown (truncated). Let me search specifically for "set_scaleValue" or "scaleValue" in host.

4. Also need CalculateCastSoftmaxGrad / CalculatePseMulsSelSimpleSoftMax — where scale is applied in the vec path: the "muls" is applied to the QK^T result (mm2ResTensor) via constInfo.commonConstInfo.scale or similar. Let me search for "scale" in kernel — search pattern "scale" might be too broad. Let me look at "commonConstInfo.scale" or the RunInfo scale. Search "scaleValue" in common.h — FagConstInfo fields. Let me search pattern "scale" with limit 50 and see what comes. Actually the earlier scaleValue search listed only 11 rows; let me look at the rest of that file (it was 1 line, truncated). Let me read more carefully — it only showed 1 row because the line was truncated at 2000 chars. I should re-run with a narrower pattern: "set_scaleValue" / "scaleValue" in host. Let me use locate mode? The modes: locate — locate symbols. Let me use locate --pattern scaleValue.

Actually, let me do targeted reads and searches:
- Read kernel_base.h 440-540 (SetConstInfo) 
- Read kernel_base.h Process (search "enablePreSfmg" in kernel_base) — the reader site is at 488 SetConstInfo. Let me read that.
- Search "PresfmgRegbase opPre" or "EnablePreSfmg" capital. Search pattern "PreSfmg" (capital S) might find caller. Earlier search "Presfmg" found 26 rows but the output was truncated at the top 100 lines. The file had rows sorted; the caller may be in flash_attention_score_grad_kernel_base.h. Let me search specifically "FlashAttentionScoreGradPresfmgRegbase" usage with locate.

Let me do:
1. uo-query --mode search --pattern "PresfmgRegbase opPre" — hmm search may not handle spaces well. Better: search --pattern opPre.
2. Read kernel_base.h around 440-560.
3. Read presfmg_regbase.h around 119-300.
4. Search "scaleValue" in host: search --pattern set_scaleValue.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern opPre --limit 20]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=130, offset=440]
- Thought: 13.6s
The opPre usage is in the entry macro (INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL at line 40-61), and the entry snippet at line 40-61 shows:
- If tilingData->s1s2BNGS1S2BaseParams.enablePreSfmg (probably line 48-53 region; the snippet is at 50-53 showing opPre.Init(dq, dk, dv, dy, attention_in, deqScaleDy, actual_seq_qlen, user, tilingData, &pipeIn) — that's the FlashAttentionScoreGradPresfmgRegbase opPre (init with dy, attention_in, deqScaleDy).
- else: FlashAttentionScoreGradS1S2BNGS1S2PreRegbase opPre (init with dq, dk, dv, actual_seq_kvlen, drop_mask...).

Let me read the beginning of entry_regbase.h lines 1-120 to see the full macro with the enablePreSfmg condition.

Also I should:
1. Read presfmg_regbase.h CalculateSoftmaxGrad (lines ~200-300) to see scale application (deqScaleDy + scaleValue).
2. Find where scaleValue is set on host: search "scaleValue" in host tiling files. Let me search "scaleValue" with kinds HOSTDEF/TDWRITE. Search returned 11 rows, but truncated. Let me use a targeted query: search --pattern "set_scaleValue".
3. Find the pre scale: PreParamsRegbase — read tiling_data_regbase.h around PreParamsRegbase (search "PreParamsRegbase" or read lines 380-460). Also where host sets scaleValue: in tiling_normal or tiling_common. Search "scaleValue" in the tiling files.
4. Also check where CalculateCastSoftmaxGrad / "muls" applies scale — the VF2 uses constInfo maybe with scaleValue. Search "Muls" or "MulsParam" — search pattern "Muls".

Let me continue.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h [limit=120, offset=1]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern set_scaleValue --limit 20]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern PreParamsRegbase --limit 20]
- Thought: 18.9s
Now I have the crucial POST-path info from entry_regbase.h:40-114:
- The main kernel pipeline: op.Process() at line 90.
- Crucially, line 91: if (ORIG_DTYPE_QUERY != DT_FLOAT) — the POST stage (FlashAttentionScoreGradS1S2BNGS1S2PostRegbase / FlashAttentionScoreGradNzPost) only runs for non-FP32! For FP32, pipeBase.Destroy() and no post processing (line 111-113).

So FP32: no Post stage at all — dq/dk/dv written directly by the main kernel (no cast-back needed since calc is already float and output is float). FP16/BF16: main kernel computes in float (workspace), then Post stage casts float workspace → OUTDTYPE (half) and writes to dq/dk/dv.

Wait — actually there are two different macro versions. The earlier snippet from search --pattern BN2 (lines 233-242 of entry) showed a version where post runs if (tilingData->s1s2BNGS1S2BaseParams.sinkOptional) — that was from a different macro region? Actually no — that was from the KBR branch snippet which shows lines 233-242 in the entry file. Hmm, but I just read lines 1-120 which is INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL (for BN2GS1S2/BN2S2 splitAxis) and line 91 says if (ORIG_DTYPE_QUERY != DT_FLOAT). The other macro INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL (lines 129-182) uses if (tilingData->s1s2BNGS1S2BaseParams.sinkOptional) for post — that's for the BN2 splitAxis template, a different (older?) path. Let me re-read: lines 129-182 define INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL, which has if (tilingData->s1s2BNGS1S2BaseParams.sinkOptional) { ... opPost ... } else { pipeBase.Destroy(); } — interesting, so the BN2 splitAxis path runs post only if sinkOptional.

But the BN2GS1S2 path (used for both BN2GS1S2 and BN2S2 in the dispatch at lines 224-242) runs post when ORIG_DTYPE_QUERY != DT_FLOAT. This is the important FP16 vs FP32 difference: the FP16/BF16 path always runs a Post stage (cast workspace float → half output), while FP32 skips it entirely.

Actually wait — let me double check that the earlier "search BN2" snippet (lines 233-242) was from the file version I read. The search snippet showed:
233:            isRope, isNzOut, isTndSwizzle, BN2S2, S1TemplateType(s1TemplateType), S2TemplateType(s2TemplateType),
234:            DTemplateType(dTemplateType));
235:        return;
236:    } else if constexpr (splitAxis == BN2) {
237:        INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL_FP16(half, float, half, ...
That matches my read: lines 224-242 are within RegbaseFAG dispatch for FP16.

OK. Now let me confirm:
1. Where in host the scaleValue is set — SaveToTilingData at tiling_normal_regbase.cpp:1837 calls set_scaleValue. Let me read the SaveToTilingData region (lines ~1830-1949) to see how fBaseParams.scaleValue / set_scaleValue is bound, plus where scaleValue is computed (probably DoPreTiling earlier: fBaseParams.scaleValue = ...). Search "scaleValue =" in host. Let me read the SaveToTilingData window and search "scaleValue" assignments in host.

2. Kernel usage of scale: where the muls applies scale. In vec VF2 (CalculatePseMulsSelSimpleSoftMax) — muls the QK^T by scale. Let me find where scaleValue is read in kernel: search "scaleValue" in kernel files — earlier search showed only nz_post.h scaleValue field (kernel). Let me search "scaleValue" in flash_attention_score_grad_common.h FagConstInfo or commonConstInfo. Search returned 11 rows for scaleValue but truncated. Let me search "commonConstInfo.scale" or "ScaleValue" in kernel. Use search pattern "scaleValue" with kernel files — but it only showed nz_post.h. Hmm, but there must be scale usage in CalculatePseMulsSelSimpleSoftMax (maybe in a shared template header). Search pattern "Muls" might find the template. Let me search "CalculatePseMulsSelSimpleSoftMax" and "scale".

3. The presfmg module: read presfmg_regbase.h CalculateSoftmaxGrad body to see how it applies deqScaleDy and scaleValue (pre-softmax scale). Lines ~200-300.

4. Also read the PreParamsRegbase search output (saved file) for pre scale fields: scaleValue is in s1s2BNGS1S2BaseParams (set_scaleValue at line 165 of tiling_data_regbase.h). So scaleValue lives in the base params, not Pre/Post.

Let me now:
- Read SaveToTilingData region (1830-1949) of tiling_normal_regbase.cpp.
- Read presfmg_regbase.h lines 119-320 (Init + CalculateSoftmaxGrad).
- Read the PreParamsRegbase search output file.
- Search "CalculatePseMulsSelSimpleSoftMax" or "Muls" to find scale application in the QK^T muls.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=130, offset=1820]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_presfmg_regbase.h [limit=210, offset=115]
- Thought: 2.7s
Now let me read the presfmg CalculateSoftmaxGrad body (lines ~325-578) to see how scale is applied (deqScaleDy and possibly scaleValue / pre-softmax scale). Also I need to check where scaleValue is used in kernel: the FagConstInfo probably has commonConstInfo.scaleValue or similar. Let me look at common.h FagConstInfo around line 389-465 and search kernel usage of scaleValue — the earlier scaleValue search found only nz_post.h; but likely the vec template uses constInfo.commonConstInfo.scaleValue. Let me read common.h lines 380-465 and search "scaleValue" in kernel files with the field mode. Let me also read the presfmg body.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_presfmg_regbase.h [limit=160, offset=325]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_common.h [limit=100, offset=385]
- Thought: 20.0s
Good progress. Key facts so far:

FagConstInfo (common.h:389-463):
- float scaleValue; (line 394)
- float pScale, dsScale, pScaleD, dsScaleD, pScaleLog; (lines 398-402) — quant params
- bool enablePreSfmg = false; (line 462)

PresfmgRegbase::CalculateSoftmaxGrad (presfmg_regbase.h:382-417):
- It computes MySoftmaxGradFrontCast<T1, T2, ...>(output1Buf, yInTensor, dxInTensor, ...) — the pre-softmax softmax-grad front part. Notably, deqScaleIdx parameter is declared but... the body I read does NOT use deqScaleIdx or deqScaleDyGm — wait, it uses yInTensor = input1Que (y) and dxInTensor = input2Que (dx = dy input "dx"?) — actually in the entry, opPre.Init(dq, dk, dv, dy, attention_in, deqScaleDy, ...) so dx=dy, y=attention_in (y). So the presfmg computes softmax grad front (dy*... ) and writes float result into sfmgWorkspaceGm. The deqScaleDy is initialized but where used? Maybe in DoSoftmaxGrad tail (lines 485-578). Let me read the rest (485-578) — it probably applies deqScaleDy value via scalar in the loop. Actually MySoftmaxGradFrontCast doesn't take deqScale. Let me read the remaining lines to see if deqScaleDyGm is used. Also the "dq/dk/dv workspace init" part (zeros) — that's the workspace initialization that the presfmg does instead of the main kernel writing dqkv — i.e., the pre-stage zeroes the float workspaces and computes the softmax-grad-front term, so the main kernel only does the rest.

Now where is scaleValue used in the kernel? FagConstInfo::scaleValue (common.h:394). The main kernel applies scale in the "muls" — in CalculatePseMulsSelSimpleSoftMax which takes constInfo. But that function is in a shared template file (probably in the ascendc common API or a local template header). Let me search for "scaleValue" usages in kernel — search returned only nz_post.h row earlier. Let me search "constInfo.scaleValue" or "scaleValue" with mode search again and look for kernel files. Actually earlier search for "scaleValue" (11 rows) got truncated — the visible first row was nz_post.h. Let me re-run a targeted search with pattern "scaleValue" and limit to see all 11 rows.

Also need to verify: the user asked "enablePreSfmg 或 FP16 时 POST 的 scale/cast 是否不同". Key answer: POST stage (PostRegbase) runs only when ORIG_DTYPE_QUERY != DT_FLOAT (entry_regbase.h:91) — i.e., FP16/BF16 always run the Post stage which casts float workspace → OUTDTYPE (half) and applies scaleValue (let me verify in the post file). FP32 skips post (no cast, no post scale). Also BN2-splitAxis path (INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL at lines 129-182) runs post only when sinkOptional — but BN2 never triggers for FP32 anyway.

Wait — there's a subtlety: the BN2 macro (lines 129-182) vs BN2GS1S2 macro (lines 40-114). The BN2GS1S2 macro at line 91 says if (ORIG_DTYPE_QUERY != DT_FLOAT) → run post. But the earlier search snippet at lines 233-242 (from search BN2) showed line 236-242 in the file which matched the RegbaseFAG function dispatch, using INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL_FP16 for splitAxis == BN2. Hmm wait — that snippet is lines 233-242 of the file, and my read shows lines 236-242 dispatch to INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL_FP16. And line 230-235 dispatch BN2S2 → INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL_FP16. So:
- BN2GS1S2 & BN2S2 → INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL (macro at line 40): post runs if ORIG_DTYPE_QUERY != DT_FLOAT (line 91) — regardless of sinkOptional! Actually wait, it doesn't check sinkOptional. Hmm — so for non-FP32, the post stage ALWAYS runs (cast from float workspace to half output), and additionally inside post it may handle sink.
- BN2 → INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL (macro at line 129): post runs only if sinkOptional (line 134/170). 

Interesting. But wait — is that right? For BN2 template (non-deterministic, no sink), how does dq/dk/dv get written? Maybe in the BN2 macro the main kernel writes directly. This is the older BN2 path. Let me re-check lines 129-182: if (tilingData->s1s2BNGS1S2BaseParams.sinkOptional) { ... opPre (S1S2BNGS1S2PreRegbase)... op.Process(); ... opPost } else { pipeBase.Destroy(); }. So for BN2 without sink, main kernel handles everything (no post). For BN2 with sink, pre+post run.

Hmm wait, but this contradicts "FP16 always runs post" for the BN2 path. Actually for the BN2 splitAxis path there's no post unless sink — but the codebase's BN2 path may write dqkv directly in float→? Let me not over-analyze; I'll present what the code shows, noting both macro variants.

Actually, let me look at the s1s2_bn2gs1s2_post_regbase.h to see what the Post stage does (scale + cast). Read that file. Also the nz_post.h (scaleValue member at line 90). And check the FP16 main kernel output path: if constexpr (!IS_FP32_INPUT) in block_vec.h:343-351 — non-FP32 uses separate dSOutQue/pOutQue buffers sized by OUTDTYPE, FP32 reuses dSOutQue. That's an UB layout difference.

Also need: where does kernel write dq/dk/dv? In non-FP32 (FP16/BF16), the main kernel writes float results into workspace (dqWorkSpaceGm etc.), then Post stage casts to half and writes to dq/dk/dv GM. Let me verify in block_vec / kernel: search "dqWorkSpaceGm" usage in vec. Also check "CopyDqkvToGm" in vec (the vec writes to workspace for non-fp32 or directly to dq for fp32). Let me search "dqWorkSpace" in block_vec.h.

Also verify the post stage applies scale: read s1s2_bn2gs1s2_post_regbase.h around Init/Process.

Also host side: fBaseParams.scaleValue — where is it computed? Search "scaleValue =" in host. Let me search pattern "scaleValue =" or read around DoPreTiling beginning. Search "scaleValue" in tiling_normal file — let me just search "scaleValue =" with limit.

Let me also read the remaining part of presfmg (485-578) to see deqScaleDy usage.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_presfmg_regbase.h [limit=100, offset=484]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h [limit=220, offset=40]
- Thought: 13.9s
This is the key POST evidence:

PostRegbase::ProcessDqkv (s1s2_bn2gs1s2_post_regbase.h:207-259):
- Reads float workspace dqkvWorkspace[qkvIdx] (line 234: DataCopy)
- Line 237-239: if (qkvIdx < 2) { Muls(vecInPing, vecInPing, (float)tilingData->s1s2BNGS1S2BaseParams.scaleValue, pingSize); } — the POST stage applies scaleValue (Muls) to dq and dk (qkvIdx 0,1), but NOT dv (qkvIdx 2)!
- Line 240-241: Cast(vecOutPing, vecInPing, RoundMode::CAST_ROUND, pingSize); — POST casts float → OUTDTYPE (half for FP16) with CAST_ROUND.

So the POST scale/cast is: for FP16/BF16, dq/dk/dv are produced as float in workspace by the main kernel; the post stage multiplies dq/dk by scaleValue and casts to OUTDTYPE. dv is NOT scaled (only cast). FP32 skips post entirely — main kernel writes float directly (dq/dk/dv are float) — presumably scale applied differently or... wait, where does FP32 apply the scale? Actually for FP32 the main kernel presumably applies scaleValue inside the vec pipeline (muls of QK^T uses scaleValue? no — the attention scale is applied pre-softmax on QK^T; that's not the same scaleValue). Hmm.

Wait, what is scaleValue here? In flash attention score grad, the forward y = softmax(QK^T * scale + ...) * V. The gradient dq/dk involve the scale. The scale is applied to QK^T before softmax. In this op, the mm1 result (QK^T) is multiplied by scale in the "muls" step (CalculatePseMulsSelSimpleSoftMax). Then in the backward, dq/dk must also carry the scale factor: dP = dy_softmax_grad * scale, etc. Actually the classic formulation: dQ = dP * K * scale, dK = dP^T * Q * scale, dV = P^T * dY (no scale). So dq/dk need the scale, dv doesn't. That matches the Post Muls: qkvIdx<2 → scale dq/dk, not dv.

So the FP16 path applies scale on dq/dk at POST (after computing float dqkv in main kernel), while FP32 applies scale where? In FP32, there's no post stage... So where does FP32 apply the scale to dq/dk? Maybe in the main kernel's vec output: e.g., if constexpr (IS_FP32_INPUT) Muls(vecOutBuffer, vecOutBuffer, scale) in ProcessVec3/4? Or maybe the main kernel applies the scale inside "BroadcastSubMul" or the dq/dk accumulation... Let me check block_vec.h ProcessVec3/4 for FP32-specific scale handling. Actually the scale on dq/dk might be applied during the sub/mul step or in the vec output stage — search "scaleValue" usage in block_vec.h. Let me search in kernel: search --pattern scaleValue gave 11 rows; the visible rows were only nz_post.h. Let me look at the full 11-row list by searching with a pattern restricted to kernel files. Actually the output was truncated at 2000 chars per line. I'll run search with pattern "scaleValue" again and read the saved file — but it saved the whole output. Actually earlier scaleValue search output file was tool_00b5be51b001dRt2k1CZaVuz76 which I read only partially (120 lines, 1 JSON line). I need to re-run and read more of it... The JSON is one line, so reading more won't help. Instead, let me use field mode on the TILING_FIELD scaleValue to get kernel readers, like I did for enablePreSfmg.

Let me run:
- uo-query --mode tiling_data --pattern scaleValue — gets TILING_FIELD readers/writers for scaleValue.
- Also read block_vec.h ProcessVec3 remainder + vec4 (lines 595-750) to find where FP32 writes dqkv and where scale is applied, plus search "dqWorkSpaceGm" in block_vec.h. Actually simpler: read block_vec.h lines 595-760 (ProcessVec3 continuation, ProcessVec4, etc.) and look for scaleValue / IS_FP32_INPUT branches.

Also need where host computes scaleValue: search "scaleValue" in host — fBaseParams.scaleValue = assignment. Let me search "scaleValue =" pattern.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode tiling_data --pattern scaleValue --limit 60]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern "scaleValue =" --limit 20]
- Thought: 16.5s
Now I have the scaleValue chain:
- Host: fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0)) — tiling_common_regbase.cpp:1011 (ProcessOptionalInput) — the first attr (scale_value) directly from attrs.
- TilingData writer: s1s2BNGS1S2BaseParams_->set_scaleValue(fBaseParams.scaleValue) — tiling_normal_regbase.cpp:1855.
- Kernel readers: 
  - FlashAttentionScoreGradKernelBase::SetConstInfo (kernel_base.h:488) → constInfo.scaleValue
  - FlashAttentionScoreGradS1S2BNGS1S2PostRegbase::ProcessDqkv (post_regbase.h:207) → Muls dq/dk by scaleValue (line 238)
  - FlashAttentionScoreGradNzPost::Init (nz_post.h:103) → scaleValue member (line 90)

Now I need to find where the main kernel (vec pipeline) uses constInfo.scaleValue — i.e., the pre-softmax scale application in CalculatePseMulsSelSimpleSoftMax and where FP32 applies scale to dq/dk output. Let me check the SetConstInfo region around line 488 where scaleValue is read (lines 570-650 probably), and search "constInfo.scaleValue" in kernel. Search pattern "scaleValue" got 11 rows but truncated. Let me search "scaleValue" in the kernel files with a query on kernel reader... Actually the tiling_data query gave readers. The vec uses constInfo.scaleValue — where? Let me search "constInfo.scaleValue" — but the search engine may treat that. Let me instead read kernel_base.h lines 570-660 (rest of SetConstInfo).

Also check where the vec pipeline applies scale to dq/dk for FP32. In the FP32 path, there is no post; the vec must write dq/dk/dv directly. Look at block_vec.h ProcessVec3/Vec4 remainder — the dq/dk are computed from mm3/mm4 and the scale might be applied via Muls at the end or inside "BroadcastSubMul". Actually, wait — the scale in flash-attn-grad is applied to dP (softmax grad * scale) BEFORE the mm3/mm4 matmuls: dS = dP * scale where dP = (dy⊙y - rowsum) etc. Actually the standard: dS = P ⊙ (dP - rowsum(dP·P)); and dQ = dS · K · scale, dK = dS^T · Q · scale, dV = P^T · dY. Hmm, but this operator applies scale where? Let me check CalculatePseMulsSelSimpleSoftMax — the "muls" in VF2 muls mm2ResTensor (QK^T) by scale — but wait, that's the FORWARD-like path... no, this is the grad op. In the grad op, mm1 = Q^T? Hmm, mm1 (QK^T) — actually in this op, mm1 computes S = Q·K^T? No — this is flash_attention_score_grad: mm1 computes the score matrix from q,k (like forward), then softmax grad from dy,y, then dS = softmax_grad - ... then mm3/mm4 compute dq,dk,dv. The scale on the score matrix matters for the softmax-grad path (since y = softmax(scale·S), dy/dS involves scale).

The key question from the user: "enablePreSfmg 或 FP16 时 POST 的 scale/cast 是否不同". The evidence:
1. FP16/BF16 → Post stage runs (ORIG_DTYPE_QUERY != DT_FLOAT at entry:91), where dq/dk get Muls by scaleValue (post:238) and Cast to OUTDTYPE (post:241). dv only cast.
2. FP32 → no post stage (entry:111-113), so scaleValue must be applied elsewhere in the main kernel — the vec pipeline. Need to confirm where. Let me check the vec dq/dk output path for FP32: search for "IS_FP32_INPUT" usage and "scaleValue" in block_vec.h. The nz_post also uses scaleValue (nz_post.h) for NZ output path.

Let me read:
- kernel_base.h 570-680 (rest of SetConstInfo, includes scaleValue read + enablePreSfmg read into constInfo)
- block_vec.h ProcessVec3 tail + ProcessVec4 (lines 595-780) to find where dq/dk/dv write and scale applied.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=120, offset=570]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_vec.h [limit=190, offset=595]
- Thought: 34.9s
Very important discovery:

kernel_base.h:684-686 (SetConstInfo):
- constInfo.scaleValue = tilingData->s1s2BNGS1S2BaseParams.scaleValue; (line 684)
- constInfo.enablePreSfmg = ((uint32_t)dTemplateType > 64) && tilingData->s1s2BNGS1S2BaseParams.enablePreSfmg; (line 686) — kernel double-checks dTemplateType > 64.

block_vec.h:618-621 (ProcessVec3):
// input type fp32, no post, mov muls here
if constexpr (IS_FP32_INPUT) {
    Muls(mm1ResTensor, mm1ResTensor, constInfo.scaleValue, VECTOR_BASEM * VECTOR_BASEN);
}
So for FP32 (IS_FP32_INPUT), the dq/dk path applies Muls by scaleValue right in the vec pipeline (comment literally says "input type fp32, no post, mov muls here"). For non-FP32, the scale is NOT applied in the main kernel — it's deferred to the Post stage.

block_vec.h:707-709 (DqkvMulsAndCastFromUB):
if constexpr (MM_IDX != DV_IDX) {
    Muls(inputTensor, inputTensor, constInfo.scaleValue, dataSize);
}
Hmm — this is another place where dq/dk get Muls by scaleValue and Cast to OUTDTYPE. This one writes directly to dqkvGmTensor (dqGm/dkGm/dvGm). Wait — this is DqkvMulsAndCastFromUB which writes to dqkv GM directly with OUTDTYPE! This would be used for... hmm. So there are two output paths in the vec:
1. DqkvMulsAndCastFromUB: reads CALC_TYPE (float) from UB, Muls scale (if not DV), Cast to OUTDTYPE, writes to dq/dk/dv GM directly (line 682, 716).
2. DqkvMulsAndCastFromGM: reads from GM (float workspace), ... need to see the rest.

But wait — if the vec pipeline already Muls+Cast+write to dqkv GM directly, why does the Post stage do the same thing? Because for non-FP32, the vec pipeline writes float results to workspace (dqWorkSpaceGm), and the Post stage (which runs after op.Process()) reads the workspace, Muls scale, Cast, and writes dqkv GM. While DqkvMulsAndCastFromUB/GM might be used in specific paths (like BN2 template without post, or the sink path). I need to understand which path is used when. Let me look at how ProcessMulsAndCast is invoked — search "ProcessMulsAndCast" in block_vec.h / kernel. And also check where dqkv GM is written in the FP32 case vs workspace in the non-FP32 case.

Actually, from block_vec.h:343-351 (InitUbBuffer):
if constexpr (!IS_FP32_INPUT) {
    pipe->InitBuffer(dSOutQue, 1, (VECTOR_BASEM + 1) * VECTOR_BASEN * sizeof(OUTDTYPE));
    pipe->InitBuffer(pOutQue, 1, (VECTOR_BASEM + 1) * VECTOR_BASEN * sizeof(OUTDTYPE));
} else {
    // input type fp32, exceed ub size so need to reuse dSOutQue
    pipe->InitBuffer(dSOutQue, 1, VECTOR_BASEM * VECTOR_BASEN * sizeof(INPUT_TYPE) + VECTOR_BASEN * sizeof(INPUT_TYPE));
    pOutQue = dSOutQue;
}
So for non-FP32, dSOutQue holds OUTDTYPE-sized buffers... The dqkv result buffer: for non-FP32 the vec output buffer is dSOutQue (OUTDTYPE = half sized)... Hmm wait, but the dqkv results are computed in float (mm3/mm4 results are CALC_TYPE float). Let me look at where mm3/mm4 results get written — ProcessVec5 or similar (VF5/VF6). Let me read block_vec.h 785-1100 to see DqkvMulsAndCastFromGM continuation and the dqkv write flow. Also search "ProcessMulsAndCast" callers.

Also, I should check how FP32 writes dqkv GM — maybe via DqkvMulsAndCastFromUB with IS_WRITE_UB=true path where the mm result is in UB (CALC_TYPE float), Muls by scale, Cast to OUTDTYPE(float), write to dqGm directly. But then for FP32 the scale would be applied twice (once at ProcessVec3 line 620, once at line 708)?! Hmm, no — maybe for FP32 the vec output path does NOT use DqkvMulsAndCast* (scale already applied in ProcessVec3), but writes via CastTransdataDeconflict + CopyUB2L1Vec3 (lines 623-626). Actually line 619-626 in ProcessVec3 shows for FP32: Muls by scaleValue, then CastTransdataDeconflict<INPUT_TYPE, CALC_TYPE, VECTOR_BASEN>(vecOutBuffer, mm1ResTensor, ...) then CopyUB2L1Vec3 — this writes the dq result into L1 buffer (dstBuffer) for the next cube mm? Wait, mm1ResTensor is the dq/dk result from mm3 (or the dS result?)...

Hmm, I need to be careful about the pipeline structure. Let me look at the kernel Process to understand the phases: In FlashAttentionScoreGradKernel, the vec/cube collaboration:
- VF1 (ProcessVec1): cast + softmaxgrad front
- VF2 (ProcessVec2): pse + attenMask + muls + simpleSoftmax (mm2ResTensor is QK^T? scaled by "muls")
- VF3 (ProcessVec3): sub + mul (compute dS), then CastTransdataDeconflict → CopyUB2L1Vec3 (dS→L1 for mm3/mm4)
- VF4 (ProcessVec4): cast + nd2nz (P → L1 for mm1?)
- Then mm3/mm4 compute dq,dk,dv in L0C/UB
- Then ProcessMulsAndCast (VF5/VF6): Muls scale + Cast + write dqkv

So for FP32, scale is applied in ProcessVec3 (line 619-621) because dS = P⊙(dP - rowsum) needs scale BEFORE mm3/mm4: dQ = dS·K·scale. Wait no — if scale applied to mm1ResTensor (which is dS) before writing to L1, then mm3 = dS_scaled · K gives dQ directly with scale. Then dv = P^T·dY (no scale). For FP32, that's the "mov muls here" comment.

For FP16/BF16: dS is NOT scaled in ProcessVec3; instead the main kernel computes unscaled dq/dk float, writes to workspace; the Post stage then Muls scale + Cast. This means dq/dk float in workspace are unscaled for FP16 — the scale application is deferred to POST. Wait but that changes the numeric path: for FP16, mm3 computes dQ_unscaled = dS·K, then post multiplies by scale. Mathematically identical (linear), but in FP16 the order is: float dS → mm → float dQ_unscaled → Muls by scale (float) → Cast to half. For FP32: float dS → Muls scale → mm → float dQ → Cast to float (identity). Numerically equivalent in exact arithmetic; but the workspace float for FP16 is unscaled — interesting.

Hmm wait — actually, is that right? Let me double check the DqkvMulsAndCastFromUB path. Maybe for FP16 the main kernel DOES apply scale in DqkvMulsAndCast and writes dqkv GM directly, and the Post stage is only for sink reduction? But the entry says Post runs for all non-FP32 (line 91: if (ORIG_DTYPE_QUERY != DT_FLOAT)), and Post ProcessDqkv reads dqkvWorkspace (float workspace) and writes dqkv GM. So the main kernel for non-FP32 must be writing to workspace, not dqkv GM. Let me verify where the main kernel writes dqkv results: search "dqWorkSpaceGm" in block_vec.h, or read the vec ProcessVec5/6 that calls ProcessMulsAndCast with IS_WRITE_UB=false (from GM — workspace). The DqkvMulsAndCastFromGM reads GlobalTensor<CALC_TYPE> inputTensor — that's the workspace float GM. So for non-FP32, dqkv results are written to workspace via CopyOutDqkv or similar, then Post stage handles the final write. And DqkvMulsAndCastFromUB might be used for the BN2 template path (which doesn't run post unless sink). Let me read block_vec.h 785-1100 to see the rest of DqkvMulsAndCastFromGM (which likely has the "if IS_FP32_INPUT ... Muls; else ... no Muls" logic) and find CopyOutDqkv etc.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_vec.h [limit=230, offset=785]
+ Thought: 19.5s
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern ProcessMulsAndCast --limit 20]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern dqWorkSpaceGm --limit 30]
- Thought: 18.4s
I have a lot now. Key remaining question: how do the write flags (IS_DQ_WRITE_UB, IS_DK_WRITE_UB, IS_DV_WRITE_UB) get set — i.e., when does the vec write dqkv directly to GM (via ProcessMulsAndCast) vs when the Post stage does it? Let me look at kernel_base.h where IS_DQ_WRITE_UB etc. are computed (search "IS_DQ_WRITE_UB" / "WRITE_UB"). Also, in ComputeDqkvBn2s2 (kernel.h:178) — which is the BN2S2 template path — the vec does ProcessMulsAndCast with this->dkWorkSpaceGm (GM path) — meaning for BN2S2 the main kernel itself writes dqkv GM (Muls+Cast), and then... but the entry says BN2S2 (non-FP32) also runs Post? Wait — BN2S2 dispatch uses INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL (line 230-235), which at line 91 if (ORIG_DTYPE_QUERY != DT_FLOAT) runs Post. Hmm, so for BN2S2 non-FP32, both the main kernel (ComputeDqkvBn2s2 → ProcessMulsAndCast writes dqkv GM) AND the Post run? That would double-write... unless in the BN2S2 path, IS_DK_WRITE_UB etc. are false when post will run, and the mm results go to workspace instead.

Actually wait — ComputeDqkvBn2s2 passes this->dkWorkSpaceGm as the inputTensor to ProcessMulsAndCast with BaseClass::IS_DK_WRITE_UB. ProcessMulsAndCast<CALC_TYPE, IS_WRITE_UB, DK_IDX>: if IS_WRITE_UB is false → DqkvMulsAndCastFromGM: reads from dkWorkSpaceGm (float workspace GM), Muls scale, Cast to OUTDTYPE, writes to dkGm GM directly (line 807, 844/860). So in the BN2S2 path, the main kernel DOES write dqkv GM directly with Muls+Cast — even for FP16!

Hmm — so then what does Post do for BN2S2? The entry macro runs Post for non-FP32 unconditionally... Wait, unless the flags IS_DQ_WRITE_UB/IS_DK_WRITE_UB/IS_DV_WRITE_UB differ per template. Let me check how these flags are computed. Search "IS_DQ_WRITE_UB" in kernel_base.h. Let me read kernel_base.h where the template args / flags are defined (probably lines 40-120 or in the class template declaration).

Also there's a key distinction: maybe the flags depend on IS_FP32_INPUT: e.g., for FP16/BF16 (non-FP32), IS_DK_WRITE_UB = false, and the vec writes mm results to workspace; then Post does the Muls+Cast+GM write. For FP32, IS_DK_WRITE_UB = true, vec writes dqkv GM directly... but FP32 doesn't run post, and the FP32 scale is applied in ProcessVec3 (line 619-621). But DqkvMulsAndCastFromUB also applies Muls (line 707-709) — would double-scale for FP32... unless for FP32, the vec uses a different write path without Muls. Hmm, but DqkvMulsAndCast always Muls for MM_IDX != DV_IDX. So for FP32 the ProcessVec3 scale + DqkvMulsAndCast scale would double-apply. Unless the FP32 path's dS is NOT scaled in ProcessVec3... wait, line 619-621: if constexpr (IS_FP32_INPUT) { Muls(mm1ResTensor, ...) } — that's in ProcessVec3 where mm1ResTensor is the dS result. So for FP32 dS IS scaled. And then dq/dk = dS_scaled · K... and if DqkvMulsAndCast also Muls by scale → double scale → wrong. So for FP32, the dqkv write path must NOT go through DqkvMulsAndCast. The flags IS_*_WRITE_UB probably encode this: for FP32, the vec writes dqkv directly without muls (maybe via a different function), OR for FP32 the dqkv write doesn't happen in vec at all and the L0C results are copied to dq GM directly by the cube with no scale (already scaled in dS).

I need to find the flag definitions. Let me search "IS_DK_WRITE_UB" and read the kernel_base.h template header region.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern IS_DK_WRITE_UB --limit 20]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=120, offset=30]
- Thought: 13.4s
Now I understand the WRITE_UB flags:
- IS_DQ_WRITE_UB = SPLIT_AXIS == BN2 && !IS_BN2_MULTIBLK && !IS_DQ_RES_EXCEED_UB (kernel_base.h:99)
- IS_DK_WRITE_UB = ((BN2 && !multiBlk) || (BN2S2 && NO_DETER)) && !IS_DKV_RES_EXCEED_UB (100-101)
- IS_DV_WRITE_UB = (BN2S2 && NO_DETER) && !IS_DKV_RES_EXCEED_UB (102-103)

So:
- BN2GS1S2 (the default/primary path, and the only FP32 path): IS_DQ/DK/DV_WRITE_UB are ALL false → the cube writes mm results to workspace GM (dqWorkSpaceGm / dkWorkSpaceGm / dvWorkSpaceGm — see kernel.h:254 IterateMmDsQ(this->dkWorkSpaceGm, ...)), and ProcessMulsAndCast reads from GM workspace. Then for non-FP32, the Post stage reads the workspace and does the final Muls+Cast+GM write. For FP32 there's no post — but wait, for FP32 in BN2GS1S2, the vec still calls ProcessMulsAndCast (with IS_DK_WRITE_UB=false → DqkvMulsAndCastFromGM) which does Muls + Cast + write to dqkv GM! So for FP32, scale is applied TWICE? No wait — for FP32, ProcessVec3 line 619-621 applies Muls to dS (mm1ResTensor) — that's the dS tensor (softmax grad result), NOT the dq/dk result. Then dq = dS_scaled · K via mm3/mm4. Then DqkvMulsAndCastFromGM does Muls by scaleValue on dq — that WOULD double-apply for FP32...

Hmm, unless for FP32 the write path used by ComputeDqkv* is different. Let me reconsider: For FP32 in BN2GS1S2 — which ComputeDqkv function is used? The kernel.h has ComputeDqkvBn2s2 (line 178), ComputeDqkvBn2 (line 395 area), and probably ComputeDqkvBn2gs1s2 (the default). Let me check the Process in kernel.h to see which compute function runs for BN2GS1S2 and whether it uses ProcessMulsAndCast or a different write path (maybe "ProcessDqkvNoMuls"? or the write is done via a separate CopyOutDqkvToGm without Muls).

Actually, I realize the FP32 "mov muls here" comment at block_vec.h:619 says the Muls in ProcessVec3 IS the FP32's scale application, implying the write path for FP32 does NOT apply scale. But DqkvMulsAndCastFromGM/UB always Muls for MM_IDX != DV_IDX... These functions are only reached in ComputeDqkvBn2s2/ComputeDqkvBn2 (BN2S2 and BN2 paths). For BN2GS1S2 (the FP32 route — FP32 can never be BN2/BN2S2), the dqkv write must use a different path. Let me look at ComputeDqkvBn2gs1s2 in kernel.h (probably the default compute for BN2GS1S2). Let me read kernel.h around the Process/Compute functions — search "ComputeDqkv" names, and read kernel.h Process.

Also need to confirm the FP32 dqkv write path for BN2GS1S2 — maybe it's via CopyOutDqkvToGm or via ProcessDqkvWithScale etc. Let me read kernel.h around 30-180 (Process) to see the overall structure.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h [limit=185, offset=30]
- Thought: 1m 27s
Let me analyze this conversation and produce the required structured summary.

The user is debugging FP16 precision in flash_attention_score_grad (arch35) and wants to understand:
1. FP32 vs FP16 kernel path differences (dtype conditions)
2. BN2 meaning (tiling/host definition, TILING_FIELD binding, kernel usage)
3. enablePreSfmg field (TILING_FIELD/TILING_DATA, host parsing, kernel branch)
4. Relationship with POST scale/cast

The agent has gathered substantial evidence through uo-query (acp tool) and windowed file reads. I need to preserve all the file:line evidence found.

Key findings so far:

enablePreSfmg:
- TILING_FIELD: op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h:120 (bool, owner FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase)
- Host writer: op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1896 — s1s2BNGS1S2BaseParams_->set_enablePreSfmg(fBaseParams.enablePreSfmg) (line 1896 setter)
- Value definition: op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1141 — fBaseParams.enablePreSfmg = (fBaseParams.queryType == ge::DT_HIFLOAT8) || ((fBaseParams.queryType == ge::DT_BF16 || fBaseParams.queryType == ge::DT_FLOAT16) && presfmgLimit && d > NUM64 && d <= NUM768 && (splitAxis == BN2GS1S2 || splitAxis == BN2S2) && ...) (truncated — need to verify rest: !isDeterministic, sinkOptional != NORMAL_TENSOR, dropoutIsDivisibleBy8, !sValueZeroUnderTND — this was inferred from the agent's reasoning but the exact remaining conditions weren't fully read. The agent's reasoning says: "presfmgLimit = !(s2 <= 256 && bn1s1Outer >= MAX_BASIC_BLOCK_SIZE)" and the full condition included !isDeterministic && sinkOptional != NORMAL_TENSOR && dropoutIsDivisibleBy8 && !sValueZeroUnderTND — but I should be careful: the agent's summary of these extra conditions was in its reasoning, not fully confirmed from the file read. The tiling_data query output for enablePreSfmg was truncated at the RHS. Actually the tiling_data query output showed: "rhs":"(fBaseParams.queryType == ge::DT_HIFLOAT8) ||\n        ((fBaseParams.queryType == ge::DT_BF16 || fBaseParams.queryType == ge::DT_FLOAT16) &&\n         presfmgLimit &&\n         fBaseParams.d > static_cast<uint32_t>(ConstAxisTemplateNum::NUM64) &&\n         fBaseParams.d <= static_cast<uint32_t>(ConstAxisTemplateNum::NUM768) &&\n         (fBaseParams.splitAxis == SplitAxisEnum::BN2GS1S2 || fBaseParams.s" — truncated at "fBaseParams.s" (likely BN2S2). So the confirmed part is: queryType == DT_HIFLOAT8 OR (dtype FP16/BF16 && presfmgLimit && 64 < d <= 768 && (splitAxis == BN2GS1S2 || splitAxis == BN2S2 ...)). The rest is unconfirmed. presfmgLimit is defined at line 1139 per the tiling_data output ("presfmgLimit", "function":"DoPreTiling") — the agent inferred its definition !(s2 <= 256 && b*n1*s1Outer >= MAX_BASIC_BLOCK_SIZE) from its reasoning but that wasn't directly shown in tool results — actually in the agent's reasoning it said "presfmgLimit at line 1139: !(s2 <= NUM256 && bn1s1Outer >= MAX_BASIC_BLOCK_SIZE)" — hmm, that came from the tiling_data output which was truncated but included "presfmgLimit" in fused_outer_candidates with line 1139. The exact RHS was in the agent's reasoning. I should note it as partial.
- Kernel readers (from tiling_data query): flash_attention_score_grad_block_vec.h:243 InitGlobalBuffer, :306 InitUbBuffer, flash_attention_score_grad_kernel_base.h:488 SetConstInfo; also FagConstInfo::enablePreSfmg in flash_attention_score_grad_common.h:463
- kernel_base.h:686: constInfo.enablePreSfmg = ((uint32_t)dTemplateType > 64) && tilingData->s1s2BNGS1S2BaseParams.enablePreSfmg; — kernel double-checks dTemplateType > 64
- block_vec.h:605: if (unlikely(constInfo.enablePreSfmg)) { maxSumQue[...].FreeTensor(softmaxGradResTensor); }

FP32 vs FP16 kernel path:
- ORIG_DTYPE_QUERY macro: op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h:22-24 — #define ORIG_DTYPE_QUERY (-1) default; comment: "kernel通过宏定义隔离dtype编译tilingkey"
- Entry dispatch in op_kernel/arch35/flash_attention_score_grad_entry_regbase.h:
  - Macros: INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL_FP16(...) if (ORIG_DTYPE_QUERY == DT_FLOAT16), _BF16(...) if (ORIG_DTYPE_QUERY == DT_BF16), _FP32(...) if (ORIG_DTYPE_QUERY == DT_FLOAT) (lines 116-126)
  - FP16 template args: half, float, half (INPUT_TYPE=half, CALC_TYPE=float, OUTDTYPE=half)
  - BF16: bfloat16_t, float, bfloat16_t
  - FP32: float, float, float (line 124-126 macro)
  - BN2GS1S2/BN2S2 → INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL; BN2 → INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL (lines 224-242)
  - Macro INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL (lines 40-114): line 91 if (ORIG_DTYPE_QUERY != DT_FLOAT) → runs Post stage (FlashAttentionScoreGradS1S2BNGS1S2PostRegbase / FlashAttentionScoreGradNzPost); FP32 → no post, pipeBase.Destroy() (lines 111-113)
  - Macro INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL (lines 129-182): post runs only if sinkOptional (line 134)
- InputDType template key (template_tiling_key.h): bit 6-4, 1=FLOAT32, 2=BFLOAT16, 3=FLOAT16_PRECISION (from agent reasoning — the actual file content was truncated but the agent recorded this)
- SplitAxis bit 3-1: 0=BN2GS1S2, 1=BN2, 5=BN2S2

BN2:
- BN2 is a SplitAxis enum value (SplitAxisEnum::BN2), not a tiling field named blockNum2. No blockNum2 substring in code (search returned 0). No preScale substring either.
- Host: op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp:1590-1608:
  - bnLimit (line 1590-1591): bn1 >= 256 || (bn1 >= 128 && s1%128==0 && s2%128==0)
  - isBn2MultiBlk (line 1596-1606): bnSparseLimit && s1 > BN2_MAX_S || s2 > BN2_MAX_S ... && n1==n2 && d <= BN2_MAX_D && queryType != DT_FLOAT (line 1601) && d==d1 && !fp8 && !hasRope
  - line 1607: fBaseParams.isBn2 = fBaseParams.isBn2MultiBlk ? true : fBaseParams.isBn2;
- SetSplitAxis (tiling_common_regbase.cpp:1641-1648): BN2S2 if !isBn2 && bn2S2RouteLimit (line 1643, and line 1637 requires queryType != DT_FLOAT for BN2S2), BN2 if isBn2 (line 1645), else BN2GS1S2 (line 1647)
- tiling_normal_regbase.cpp:674-691: DoBn2MultiBlkSparse — if invalid col/row: isBn2=false, isBn2MultiBlk=false, splitAxis=BN2GS1S2 (line 681-684); line 691: splitAxis = isBn2 ? BN2 : BN2GS1S2
- Kernel entry: else if constexpr (splitAxis == BN2) → INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL (entry_regbase.h:236-242)
- BN2_MULTIBLK constants: BN2_MULTIBLK_BN256, BN2_MULTIBLK_BN128, BN2_MAX_S, BN2_MULTIBLK_SEQ, BN2_MAX_D (tiling_common_regbase.cpp:1590-1606)
- isBn2 first assignment not yet located (partial) — the agent searched "isBn2" and got assignments; where isBn2 is first set wasn't confirmed

POST scale/cast:
- scaleValue TILING_FIELD: op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h:96
- Host: op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp:1011 — fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0)) (ProcessOptionalInput, attr 0 = scale_value)
- Tiling writer: op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1855 — s1s2BNGS1S2BaseParams_->set_scaleValue(fBaseParams.scaleValue)
- Kernel readers: post_regbase.h:207 ProcessDqkv (Muls at line 238), nz_post.h:103 Init (scaleValue member line 90), kernel_base.h:488 SetConstInfo → constInfo.scaleValue at line 684
- PostRegbase::ProcessDqkv (s1s2_bn2gs1s2_post_regbase.h, lines 207-259): reads float workspace dqkvWorkspace, lines 237-239: if (qkvIdx < 2) Muls(...scaleValue...) — scale applied to dq/dk only, not dv; line 240-241: Cast(vecOutPing, vecInPing, RoundMode::CAST_ROUND, pingSize) — cast float → OUTDTYPE
- block_vec.h:618-621 (ProcessVec3): // input type fp32, no post, mov muls here; if constexpr (IS_FP32_INPUT) { Muls(mm1ResTensor, mm1ResTensor, constInfo.scaleValue, VECTOR_BASEM * VECTOR_BASEN); } — FP32 applies scale in-kernel (on dS before mm3/mm4); non-FP32 defers to Post
- block_vec.h:707-709 (DqkvMulsAndCastFromUB): if constexpr (MM_IDX != DV_IDX) { Muls(inputTensor, inputTensor, constInfo.scaleValue, dataSize); } — dq/dk scaled, dv not
- block_vec.h:343-351 InitUbBuffer: non-FP32 allocates separate dSOutQue/pOutQue sized by OUTDTYPE; FP32 reuses dSOutQue (UB size comment)
- FagConstInfo (common.h:389+): scaleValue line 394, pScale/dsScale/pScaleD/dsScaleD/pScaleLog lines 398-402, enablePreSfmg line 462/463

Presfmg module:
- op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h — class FlashAttentionScoreGradPresfmgRegbase (line 37 constructor; Init line 130; CalculateSoftmaxGrad line ~382-417; DoSoftmaxGrad)
- Instantiated via entry macro: opPre.Init(dq, dk, dv, dy, attention_in, deqScaleDy, actual_seq_qlen, user, tilingData, &pipeIn) (entry_regbase.h:50) when enablePreSfmg; else FlashAttentionScoreGradS1S2BNGS1S2PreRegbase (line 55-58)
- Presfmg uses preTilingData fields (qPreBlockFactor etc., presfmg_regbase.h:143-151), deqScaleDyGm, sfmgWorkspaceGm; computes softmax-grad-front into float workspace; MySoftmaxGradFrontCast (line ~382+)
- Host preSfmg tiling: DoPreSfmgTiling in tiling_normal_regbase.cpp (~line 1040-1113): sfmgUsedCoreNum = blockOuter * AICV_RATIO_DEFAULT, singleLoopNBurstNum computed for FP16/BF16 (line 1096-1098)
- PreParamsRegbase = preTilingData fields

Tiling data structure:
- FlashAttentionScoreGradTilingDataUs1s2Bbn2gs1s2Regbase (tiling_data_regbase.h:610-623): s1s2BNGS1S2BaseParams + SplitCoreParams + BlockNumList + preTilingData + postTilingData + conditional deter/tnd/tndSwizzle params
- Tiling key types in template_tiling_key.h:32-46: FagTilingWithTemplateFFFF/FFTT/FFTF/TFFF/TFTF/TTTF/TTTT

Unknowns / partial:
- Full RHS of enablePreSfmg at tiling_normal_regbase.cpp:1141 (truncated after "splitAxis == SplitAxisEnum::BN2GS1S2 || fBaseParams.s") — remaining conditions not fully confirmed (agent inferred !isDeterministic && sinkOptional != NORMAL_TENSOR && dropoutIsDivisibleBy8 && !sValueZeroUnderTND from its reasoning; mark as partial)
- presfmgLimit exact definition at line 1139 (partial)
- Where isBn2 is first assigned in host (partial)
- The DqkvMulsAndCastFromGM rest (lines 828-830 also apply Muls MM_IDX != DV_IDX per agent reading at 828-830? Actually the agent's read at 785-1014 showed line 807-808 dqkvGmTensor assignment and workspace offset; the Muls at 828-830 was mentioned in agent reasoning as "DqkvMulsAndCastFromUB/GM both apply Muls scale (MM_IDX != DV_IDX) and Cast to OUTDTYPE" — line 707-709 confirmed for FromUB; FromGM not fully confirmed)
- How FP16 main kernel writes dqkv to workspace vs GM (the dqWorkSpaceGm search showed it's declared in pre_regbase.h:53 and presfmg_regbase.h:60; whether the vec writes workspace for non-FP32 not fully confirmed)
- presfmg DoSoftmaxGrad tail / deqScaleDy actual use (lines 485-578 partially read; deqScaleIdx param declared but not seen used in the read portion)
- exact INITVOKE macro lines 40-114 details: line 48-53 region shows opPre branch (presfmg), line 54-61 else S1S2BNGS1S2PreRegbase; the if (ORIG_DTYPE_QUERY != DT_FLOAT) at line 91 and pipeBase.Destroy() at 111-113 were in agent reasoning (partially confirmed — the read showed lines 1-120 but only the first ~40 lines were visible; lines 91, 111-113 were from the agent's reasoning/earlier search snippet. Actually the read output for entry_regbase.h 1-120 was truncated in the displayed content — the agent's reasoning says "line 91: if (ORIG_DTYPE_QUERY != DT_FLOAT) — POST stage only runs for non-FP32" and "line 111-113: pipeBase.Destroy()". These came from reading lines 1-120 which displayed up to line 40. Hmm, actually the read tool result showed content only through line 40 ("#define INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL(INPUT_TYPE, CALC_TYPE, OUTDTYPE, IS_ATTEN_MA" then truncated). The line 91/111-113 facts were in the agent's reasoning — likely from the same read but not visible in the transcript. I'll mark them as reported but note the macro region 40-114.

Actually, wait — re-reading the conversation: after reading entry_regbase.h offset 1 limit 120, the agent's reasoning says "Now I have the crucial POST-path info from entry_regbase.h:40-114... line 91: if (ORIG_DTYPE_QUERY != DT_FLOAT)... lines 111-113 pipeBase.Destroy()". The read output was truncated at line 40 in what's shown, but the tool result may have had more content that got cut in display. The agent's reasoning confirms lines 40-114 content including line 91 and 111-113. I'll include those with a note.

Also:
- DoPreSfmgTiling region lines 1090-1113 read: singleLoopNBurstNum for FP16/BF16 computed at line 1096-1098 (if (queryType == DT_FLOAT16 || DT_BF16) { singleLoopNBurstNum = sfmgDyBufferLen / inputSize / valueDAlign; })
- The search --pattern enablePreSfmg earlier returned 11 rows including kernel reader sites: block_vec.h:243 InitGlobalBuffer, :306 InitUbBuffer, kernel_base.h:488 SetConstInfo, FagConstInfo::enablePreSfmg common.h:463
- tiling_data query for enablePreSfmg confirmed: host_writer_sites tiling_normal_regbase.cpp:1896; value_defining_sites line 1141 (DoPreTiling function); presfmgLimit at line 1139 in DoPreTiling (from fused_outer_candidates list)
- FP16_C0_SIZE COMPILE_VAR: tiling_normal_regbase.cpp:444 — used in isNzOut calc; isNzOut excludes DT_FLOAT etc. (line 448-449)
- Note: enablePreSfmg kernel readers at block_vec.h:243/306 were mentioned in the tiling_data output "kernel readers" — actually the tiling_data output for enablePreSfmg didn't explicitly list kernel reader sites in the truncated view, but the first search (11 rows) did include the kernel reader rows (agent reasoning states: "Kernel readers: flash_attention_score_grad_block_vec.h:243 InitGlobalBuffer, :306 InitUbBuffer, flash_attention_score_grad_kernel_base.h:488 SetConstInfo"). Good.

Tools/commands used:
- acp tool: uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode <search|tiling_data|kernel_branch|neighbors> — valid modes: search, constraints, neighbors, impact, field, branches, templates, tiling_key, tiling_data, kernel_branch, template_match, buffer, gaps, legal_key, locate, kernel_api, kernel_launch, compile (symbols/fields/locate are NOT valid modes — that error was hit)
- Search outputs >50KB saved to C:\Users\SunYe\.local\share\opencode\tool-output\*.json — read via read tool
- Windowed reads of machine-scope files are allowed after UO KB/CodeMap location

User's debug context:
- FP16 precision debugging: dq magnitude off by a factor (dq 量级差一截), FP32 same shape passes
- Suspects POST scale/cast
- Wants answer in Cursor Explore style: prose + file:line lists; mark UNKNOWN/partial for host_runtime_leaf statically undeterminable
- Explicitly: do not write answer.yaml, do not finalize

The output must be in the same language as the conversation — the user prompt is in Chinese (with some English). The summary template instructions are in English. The conversation is mixed Chinese/English. The rule says "Respond in the same language as the conversation." The conversation is predominantly Chinese (user) with English tool output. I'll write the summary in Chinese with English technical terms preserved, since the user's message is in Chinese. Actually, the summary format headings are fixed in English (Objective, Important Details, etc.). I'll keep the headings as specified and write content in Chinese (matching the user's language), keeping code identifiers in English.

Hmm — the instruction says "Respond in the same language as the conversation." The conversation includes both, but the primary user language is Chinese. I'll write in Chinese for the content, keeping headings exactly as the template specifies (they're part of the output structure).

Now, the "Work State" sections:
- Completed: all the verified facts with file:line
- Active: investigation state — remaining unknowns to confirm (full enablePreSfmg RHS, presfmg deqScale usage, where FP16 vec writes workspace, where isBn2 first set, FP32 dqkv write path)
- Blocked: none really — the aicore tool mode errors (symbols/fields not valid) were resolved

Next Move: 
1. Read tiling_normal_regbase.cpp around 1135-1150 to get full enablePreSfmg RHS + presfmgLimit definition
2. Confirm where vec writes dqkv for non-FP32 (workspace) — read block_vec.h ProcessVec5/6 or search CopyOutDqkv / dqkv workspace writes; confirm DqkvMulsAndCastFromGM Muls at 828-830
3. Confirm isBn2 first assignment in host (search isBn2 in DoTiling/DoPreTiling)
4. Check presfmg DoSoftmaxGrad for deqScaleDy usage (lines 516-578)
5. Compose final answer (prose + file:line) — do NOT write answer.yaml/finalize

Relevant files: list the key files.

Let me write this out concisely but completely.
Objective
- 查清 d:\TEST\ops-transformer\attention\flash_attention_score_grad（arch35，CodeMap 已建）中三个开关/路径的走向：FP32 路径、BN2、enablePreSfmg，以及它们与 POST scale/cast 的关系（用户在做 FP16 精度调试，dq 量级差一截，FP32 同 shape 过，怀疑 POST 的 scale/cast）。要求全部带 file:line 证据，Cursor Explore 风格（散文 + 列表），host_runtime_leaf 无法静态确定的写 "UNKNOWN/partial"。不写 answer.yaml、不 finalize。
Important Details
- 工具约束：只能用 acp 工具 uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...；禁止 bash/Grep/MCP 替代。合法 mode 只有：search, constraints, neighbors, impact, field, branches, templates, tiling_key, tiling_data, kernel_branch, template_match, buffer, gaps, legal_key, locate, kernel_api, kernel_launch, compile（symbols/fields 是非法 mode，已踩过报错）。
- search 输出 >50KB 时被截断，会存到 C:\Users\SunYe\.local\share\opencode\tool-output\tool_*.json，用 read 工具按 offset/limit 读取（已确认可行）。
- 机器作用域源文件（op_kernel/op_host 下）已由 uo-query 定位到 ScopeSet，可做窗口化 read（禁止整文件 dump）。
- 用户语言为中文；最终回答须中文散文 + file:line 列表。
- 已知关键结论骨架（待最终成文）：enablePreSfmg 仅 FP16/BF16/HIFP8 生效，FP32 恒 false 且不走 POST；BN2 是 SplitAxisEnum 枚举值（BN2/BN2S2/BN2GS1S2），FP32 永不走 BN2/BN2S2；POST 阶段（非 FP32）对 dq/dk 做 scaleValue 的 Muls + Cast（round），dv 只 cast 不 scale；FP32 在主核内 ProcessVec3 提前 Muls scale。
- 无 blockNum2 / preScale 相关字段（search 均 0 命中）——"BN2" 不是 tiling 字段名。
Work State
Completed
- enablePreSfmg 字段链：
- TILING_FIELD 声明：op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h:120（bool，owner FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase）。
- host 写入：op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1896（set_enablePreSfmg(fBaseParams.enablePreSfmg)，SaveToTilingData）。
- host 取值（DoPreTiling）：同文件 :1141，RHS 开头已确认：(queryType == DT_HIFLOAT8) || ((queryType == DT_BF16 || queryType == DT_FLOAT16) && presfmgLimit && d > NUM64 && d <= NUM768 && (splitAxis == BN2GS1S2 || splitAxis == BN2S2 ...)；presfmgLimit 在同函数 :1139。RHS 后半段被截断（UNKNOWN/partial，见 Active）。
- kernel 读点：flash_attention_score_grad_block_vec.h:243（InitGlobalBuffer）、:306（InitUbBuffer）、flash_attention_score_grad_kernel_base.h:488（SetConstInfo）；FagConstInfo::enablePreSfmg 在 flash_attention_score_grad_common.h:463。
- kernel_base.h:686：constInfo.enablePreSfmg = ((uint32_t)dTemplateType > 64) && tilingData->s1s2BNGS1S2BaseParams.enablePreSfmg;（kernel 侧二次校验 d>64）。
- block_vec.h:605：if (unlikely(constInfo.enablePreSfmg)) 释放 maxSumQue 的 softmaxGradResTensor。
- FP32 vs FP16 kernel 路径：
- op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h:22-24：ORIG_DTYPE_QUERY 宏默认 (-1)，注释"kernel通过宏定义隔离dtype编译tilingkey"。
- entry 宏：op_kernel/arch35/flash_attention_score_grad_entry_regbase.h:116-126 — ..._FP16 宏 if (ORIG_DTYPE_QUERY == DT_FLOAT16)、_BF16 宏 DT_BF16、_FP32 宏 DT_FLOAT；FP16 模板实参 half, float, half（INPUT=half, CALC=float, OUT=half），BF16 bfloat16_t, float, bfloat16_t，FP32 float, float, float。
- 分发（entry_regbase.h:224-242）：splitAxis==BN2S2 与 BN2GS1S2 → INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL_*；splitAxis==BN2 → INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL_*。
- POST 是否执行：BN2GS1S2 宏（entry:40-114）中 if (ORIG_DTYPE_QUERY != DT_FLOAT) 才跑 Post（S1S2BNGS1S2PostRegbase / NzPost），FP32 直接 pipeBase.Destroy()（约 entry:91、111-113，见 Active 备注）；BN2 宏（entry:129-182）仅在 sinkOptional 时跑 post。
- 模板 key：SplitAxis bit 3-1（0=BN2GS1S2, 1=BN2, 5=BN2S2）；InputDType bit 6-4（1=FLOAT32, 2=BFLOAT16, 3=FLOAT16_PRECISION...）（template_tiling_key.h:49-56 区域）。
- UB 差异：block_vec.h:343-351 — 非 FP32 用独立 dSOutQue/pOutQue（OUTDTYPE 大小），FP32 复用 dSOutQue（UB 超限注释）。
- BN2（SplitAxisEnum，非 tiling 字段）：
- host 定义/条件：op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp:1590-1608：bnLimit（:1590-1591，b*n1>=256 或 (>=128 且 s1/s2 均%128==0)）；isBn2MultiBlk（:1596-1606）含 queryType != DT_FLOAT（:1601）、非 TND/prefix sparse、s1/s2 范围、n1==n2、d<=BN2_MAX_D、非 fp8、无 rope；:1607 isBn2 = isBn2MultiBlk ? true : isBn2。
- SetSplitAxis（:1641-1648）：!isBn2 && bn2S2RouteLimit → BN2S2（BN2S2 也要求 queryType != DT_FLOAT，:1637）；isBn2 → BN2；否则 BN2GS1S2。
- tiling_normal_regbase.cpp:674-691（DoBn2MultiBlkSparse）：invalid col/row 时 isBn2=false; splitAxis=BN2GS1S2（:681-684）；:691 splitAxis = isBn2 ? BN2 : BN2GS1S2。
- kernel：entry_regbase.h:236-242 else if constexpr (splitAxis == BN2) → BN2 专用宏（BN2 路径 post 仅 sinkOptional 时跑）。
- isBn2 首次赋值点未定位（partial）。
- POST scale/cast：
- scaleValue 链路：声明 tiling_data_regbase.h:96；host 赋值 tiling_common_regbase.cpp:1011 fBaseParams.scaleValue = *(GetAttrPointer<float>(0))（attr 0）；写 tiling tiling_normal_regbase.cpp:1855 set_scaleValue；kernel 读：post_regbase.h:207 ProcessDqkv、nz_post.h:103 Init（成员 :90）、kernel_base.h:488→684 constInfo.scaleValue。
- PostRegbase::ProcessDqkv（s1s2_bn2gs1s2_post_regbase.h:207-259）：从 float workspace 读 dqkv；:237-239 if (qkvIdx < 2) Muls(...scaleValue...)（dq/dk 乘 scale，dv 不乘）；:240-241 Cast(vecOutPing, vecInPing, RoundMode::CAST_ROUND, ...) float→OUTDTYPE。
- FP32 提前 scale：block_vec.h:618-621 // input type fp32, no post, mov muls here; if constexpr (IS_FP32_INPUT) Muls(mm1ResTensor, ..., constInfo.scaleValue, ...)（在写 L1 供 mm3/mm4 前）。
- DqkvMulsAndCastFromUB（block_vec.h:707-709）：if constexpr (MM_IDX != DV_IDX) Muls(inputTensor, ..., constInfo.scaleValue, ...) + Cast OUTDTYPE 写 dqkv GM（ProcessMulsAndCast 定义 :654-665）。
- FagConstInfo：common.h:394 scaleValue；:398-402 pScale/dsScale/pScaleD/dsScaleD/pScaleLog（量化）。
- Presfmg 模块：op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h（类 :28 起，Init :130，CalculateSoftmaxGrad ~:382-417，DoSoftmaxGrad :485+）；由 entry 宏实例化（entry_regbase.h:50 opPre.Init(dq, dk, dv, dy, attention_in, deqScaleDy, ...)）；依赖 preTilingData（presfmg_regbase.h:143-151）；host 侧 DoPreSfmgTiling（tiling_normal_regbase.cpp:1040-1113，:1096-1098 仅 FP16/BF16 算 singleLoopNBurstNum）。
- Tiling 数据结构：FlashAttentionScoreGradTilingDataUs1s2Bbn2gs1s2Regbase（tiling_data_regbase.h:610-623）：s1s2BNGS1S2BaseParams + SplitCoreParams + BlockNumList + preTilingData(PreParamsRegbase) + postTilingData(PostParamsRegbase) + 条件性 deter/tnd/tndSwizzle。
- FP16_C0_SIZE COMPILE_VAR：tiling_normal_regbase.cpp:444（isNzOut 计算，:448-449 排除 DT_FLOAT 等）。
Active
- 未确认（UNKNOWN/partial）项，需补齐后成文：
1. enablePreSfmg 完整 RHS（tiling_normal_regbase.cpp:1141 后半段）与 presfmgLimit 定义（:1139）——当前仅确认到 (splitAxis == BN2GS1S2 || fBaseParams.s...（推测还有 BN2S2、!isDeterministic、sinkOptional 等，未实证）。
2. entry_regbase.h:91（if (ORIG_DTYPE_QUERY != DT_FLOAT)）与 :111-113（pipeBase.Destroy()）来自 agent 对 40-114 行的解读，需再核对一次原文（此前 read 输出显示到 :40 截断）。
3. 非 FP32 主核把 dqkv 写 float workspace 的具体位置（DqkvMulsAndCastFromGM 的 Muls 段 :828-830 未完整读；dqWorkSpaceGm 仅确认声明于 pre_regbase.h:53、presfmg_regbase.h:60）。
4. isBn2 首次赋值点（host 早期 shape 判断）。
5. presfmg DoSoftmaxGrad 尾部对 deqScaleDyGm 的实际使用（:516-578 未读完；deqScaleIdx 参数已声明 :51）。
6. NzPost 中 scaleValue 用法（nz_post.h:90 声明，:103 Init 读取，使用点未读）。
Blocked
- (none)
Next Move
1. 读 op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1130-1150（enablePreSfmg 完整 RHS + presfmgLimit）。
2. 读 op_kernel/arch35/flash_attention_score_grad_entry_regbase.h:85-115 复核 POST 条件与 FP32 destroy 分支。
3. 读 op_kernel/arch35/flash_attention_score_grad_block_vec.h:678-760（DqkvMulsAndCastFromUB/GM 完整 Muls+Cast）及 ProcessVec5/6 调用点，确认非 FP32 写 workspace、FP32 写 dqkv GM 的分流。
4. uo-query search --pattern "isBn2 ="（或读 tiling_common DoTiling 前段）定位 isBn2 首次赋值。
5. 读 presfmg_regbase.h:516-578 确认 deqScaleDy 用法。
6. 汇总成中文散文 + file:line 答案；host_runtime_leaf 处标注 UNKNOWN/partial；不写 answer.yaml、不 finalize。
Relevant Files
- op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h: ORIG_DTYPE_QUERY 宏、tiling key 位定义（SplitAxis/InputDType）、FagTilingWithTemplate* 别名
- op_kernel/arch35/flash_attention_score_grad_entry_regbase.h: dtype/splitAxis 分发宏与 POST 条件
- op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h: TILING_FIELD（enablePreSfmg:120、scaleValue:96）、TilingData 结构 :610-623
- op_kernel/arch35/flash_attention_score_grad_common.h: FagConstInfo（scaleValue:394、enablePreSfmg:463、量化参数 :398-402）
- op_kernel/arch35/flash_attention_score_grad_kernel_base.h: SetConstInfo :488、:684-686
- op_kernel/arch35/flash_attention_score_grad_block_vec.h: enablePreSfmg :243/:306/:605、FP32 muls :618-621、UB 分配 :343-351、ProcessMulsAndCast :654-665、DqkvMulsAndCastFromUB :669-709
- op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h: ProcessDqkv :207-259（scale :237-239、cast :240-241）
- op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h: Presfmg 模块（Init :130、CalculateSoftmaxGrad、DoSoftmaxGrad）
- op_kernel/arch35/flash_attention_score_grad_nz_post.h: NzPost scaleValue :90/:103
- op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp: enablePreSfmg :1141/:1896、scaleValue setter :1855、DoPreSfmgTiling :1040-1113、DoBn2MultiBlkSparse :674-691
- op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp: BN2 条件 :1590-1608、SetSplitAxis :1641-1648、scaleValue :1011
- 工具输出缓存目录：C:\Users\SunYe\.local\share\opencode\tool-output\tool_*.json（截断的 search 结果）
▣  Compaction · DeepSeek V4 Flash Free · 2m 13s
- Thought: 20.5s
I've now confirmed the key picture. Let me trace the remaining question: for BN2GS1S2 (the FP32 path and the default non-FP32 path), IS_DQ_WRITE_UB/IS_DK_WRITE_UB/IS_DV_WRITE_UB are ALL false (kernel_base.h:99-103 — those flags are only true for BN2 (non-multiblk) and BN2S2 (NO_DETER) paths). So in ProcessBn2gs1s2LastVec (kernel.h:75-101, 137-153), the cube IterateMmDsK/IterateMmDsQ/IterateMmPDy write mm results to workspace GM (dqWorkSpaceGm/dkWorkSpaceGm/dvWorkSpaceGm), and there's NO ProcessMulsAndCast call in the BN2GS1S2 vec flow at all. The vec only does ProcessVec3/ProcessVec4 (dropout/cast/nd2nz on dS and p).

So for BN2GS1S2:
- non-FP32: cube writes dqkv as float to workspace GM; then the Post stage (ProcessDqkv in s1s2_bn2gs1s2_post_regbase.h:207-259) reads workspace, does Muls scale for dq/dk (qkvIdx<2), Cast round to OUTDTYPE, writes final dqkv GM.
- FP32: cube writes dqkv to workspace GM too; no Post (entry: if (ORIG_DTYPE_QUERY != DT_FLOAT)), and scale applied earlier at ProcessVec3 (block_vec.h:618-621: if constexpr (IS_FP32_INPUT) Muls(mm1ResTensor, mm1ResTensor, constInfo.scaleValue, ...) — dS scaled before dq/dk computed). Then the FP32 workspace is just the final output? Wait — but where does the FP32 path copy dqkv from workspace GM to dqGm? Hmm. The IterateMmDsK writes to dqWorkSpaceGm — for FP32 with no post, someone must copy workspace → dqGm. Let me check the Post stage / entry for FP32: maybe there's a "CopyOutDqkvFromWorkspace" in the kernel base or in the post for FP32? Actually the entry macro at line 91 if (ORIG_DTYPE_QUERY != DT_FLOAT) runs Post — else pipeBase.Destroy() at 111-113 — meaning for FP32, NO post stage runs at all. So who writes dqkv GM for FP32?

Hmm — for FP32, maybe the workspace IS the output: the host may set dqGm/dkGm/dvGm = workspace addresses for FP32? Or InitCVCommonGlobalBuffer sets dqGm from workspace? Actually, wait — for FP32 the output dtype is float, and the workspace is also float. It's plausible the kernel's IterateMmDsK with IS_DQ_WRITE_UB=false writes directly to dqGm (not workspace) — the template arg IS_DQ_WRITE_UB=false might control whether output goes to UB (mm1ResBuf) vs GM directly. In kernel.h:75 IterateMmDsK<CALC_TYPE, BaseClass::IS_DQ_WRITE_UB>(this->dqWorkSpaceGm, dSL1Buffer, ...) — the first GM arg is dqWorkSpaceGm. But for FP32 maybe dqWorkSpaceGm is aliased to dqGm. Let me check InitCVCommonGlobalBuffer in kernel_base.h (line 35 declaration; implementation likely in flash_attention_score_grad_kernel_base.cpp or .h). Search for where dqGm/dqWorkSpaceGm get assigned.

Actually — I should check how InitCVCommonGlobalBuffer assigns the workspace and dqGm. Let me search "InitCVCommonGlobalBuffer" and read that region of kernel_base.h. Also check whether the FP32 case sets dqWorkSpaceGm = dqGm (i.e., alias output workspace to final output). That would answer the FP32 path completely: cube writes float dqkv directly to final dq/dk/dv GM (aliased workspace), no Post, scale applied in ProcessVec3 on dS.

Hmm wait, but there's a subtlety: for FP32 the scale is applied to dS in ProcessVec3. Then dq = dS_scaled · K. Then the output workspace contains already-scaled dq/dk. And dv = P · dy (no scale). That matches the Post behavior (dq/dk scaled, dv not).

But hold on — for FP32, does the FP32 path apply scale in ProcessVec3 BEFORE mm3/mm4 (dq= dS·K, dk = dS·Q)? Yes — line 619-621 Muls on mm1ResTensor (the dS), then mm3/mm4 use dSL1Buffer which contains the scaled dS. Correct.

But then for FP32, if IterateMmDsK writes to dqWorkSpaceGm, and dqWorkSpaceGm aliases dqGm, output is complete. Let me verify InitCVCommonGlobalBuffer. Search it.

Also I should double check entry_regbase.h lines 40-114 to confirm the post condition and FP32 Destroy, and lines 116-126 for the dtype macros. I read only up to line 40 earlier. Let me now:

1. uo-query search "InitCVCommonGlobalBuffer" to find where dqWorkSpaceGm/dqGm are assigned.
2. read entry_regbase.h:40-130 to confirm the post/destroy branch and dtype macros.
3. read kernel_base.h SetConstInfo region (lines 480-700) — I already know :488 and :684-686 from tiling_data output.
4. read tiling_normal_regbase.cpp:1130-1150 for the full enablePreSfmg RHS + presfmgLimit.

Let me do 1, 2, 4 in parallel; 3 optional later.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern InitCVCommonGlobalBuffer --limit 10]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h [limit=90, offset=40]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=45, offset=1110]
- Thought: 17.9s
Excellent — now I have the full picture. Key new confirmations:

1. InitCVCommonGlobalBuffer (kernel_base.h:246-282):
   - FP32 (!IS_FP32_INPUT false branch, lines 278-282): // input type fp32, dq dk dv write to output gm directly — dqWorkSpaceGm/dkWorkSpaceGm/dvWorkSpaceGm are aliased to the output GM dq/dk/dv. So the cube writes float results DIRECTLY to the final output GM. No Post needed; scale applied in ProcessVec3.
   - Non-FP32 (lines 261-277): dqkv workspaces point into the workspace buffer at postTilingData.dq/dk/dvWorkSpaceOffset (except BN2 non-multiblk which uses RESERVED_WORKSPACE_SIZE + per-core blocks). The cube writes float dqkv to workspace; then Post stage reads workspace → Muls(scale, dq/dk only) → Cast → writes final dqkv GM.

2. entry_regbase.h:91-113 confirmed: 
   - line 91: if (ORIG_DTYPE_QUERY != DT_FLOAT) → SyncALLCores, destroy pipeBase, run Post (S1S2BNGS1S2PostRegbase if !IS_NZ_OUT, else NzPost); 
   - lines 111-113: FP32 → pipeBase.Destroy() — no Post at all.
   - Also lines 45-61: enablePreSfmg branch → Presfmg pre-stage runs instead of the regular Pre; dTemplateType > 64 constexpr guard at line 46.
   - FP16/BF16/FP32 macros at 116-126 confirmed.

3. enablePreSfmg full RHS (tiling_normal_regbase.cpp:1141-1149):
   = (queryType == DT_HIFLOAT8) || ((queryType == DT_BF16 || queryType == DT_FLOAT16) && presfmgLimit && d > NUM64 && d <= NUM768 && (splitAxis == BN2GS1S2 || splitAxis == BN2S2) && !isDeterministic && sinkOptional != NORMAL_TENSOR && dropoutIsDivisibleBy8 && !sValueZeroUnderTND)
   - presfmgLimit (1139-1140): !(s2 <= NUM256 && b*n1*s1Outer >= MAX_BASIC_BLOCK_SIZE)
   - Note: BN2 (splitAxis == BN2) is EXCLUDED from enablePreSfmg (only BN2GS1S2 or BN2S2).
   - FP32 never (queryType check), and d>64 requirement, d<=768.

Note: for BN2S2, enablePreSfmg CAN be true, and the entry macro for BN2S2... wait — the BN2S2 dispatch at lines 224-235 uses INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL — so BN2S2 non-FP32 with enablePreSfmg runs presfmg too. But earlier I saw ComputeDqkvBn2s2 in kernel.h uses ProcessMulsAndCast writing dkWorkSpaceGm→dkGm directly (IS_DK_WRITE_UB=false → DqkvMulsAndCastFromGM which does Muls+Cast+GM write). Hmm — but for BN2S2, entry runs Post for non-FP32 (line 91). So there would be DOUBLE processing for BN2S2: vec writes dqkv GM with Muls+Cast, and then Post ALSO reads workspace and writes dqkv GM? That can't be right.

Wait, let me re-read. ComputeDqkvBn2s2 at kernel.h:238-267: if IS_DK_WRITE_UB (true when BN2S2 && NO_DETER && !exceed) → mm result in UB → ProcessMulsAndCast(mm1ResTensor, ...) — writes dk GM directly (DK_IDX). If false → cube writes to dkWorkSpaceGm → ProcessMulsAndCast(dkWorkSpaceGm, ...) → reads workspace, muls+cast → writes dkGm directly. So in BN2S2 path the vec ALWAYS writes final dk/dv GM directly (no Post needed for dqkv?).

But entry line 91: BN2S2 non-FP32 → Post runs (S1S2BNGS1S2PostRegbase / NzPost with SPLIT_AXIS=BN2S2). Hmm. Is that a contradiction? Let me look at the BN2S2 dispatch again: entry_regbase.h:224-242. I haven't actually seen the exact dispatch code (lines 129-242). Let me check — maybe BN2S2 goes through the BN2_REGBASE macro (which only runs post if (sinkOptional))... Actually the earlier summary said: "BN2S2 → INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL (lines 224-242)". Let me verify by reading entry_regbase.h:129-242. If BN2S2 uses the BN2GS1S2 macro, Post would run for BN2S2 non-FP32... but then what does Post do — maybe Post for BN2S2 just handles dqRope/dkRope/dsink (rope outputs / sink), not dqkv? Let me check PostRegbase::Process for BN2S2 — maybe it processes only rope/sink GM and skips dqkv when SPLIT_AXIS==BN2S2. The ProcessDqkv in post is at s1s2_bn2gs1s2_post_regbase.h:207. Let me read the post Process to see the dqkv handling per split axis.

Actually, hold on. Let me reconsider — is it possible the vec's DqkvMulsAndCastFromGM only writes to GM when IS_WRITE_UB == false AND the Post is skipped for BN2S2? No — the entry macro controls Post.

I need to read:
1. entry_regbase.h:129-242 (BN2 macro + dispatch for BN2S2/BN2/BN2GS1S2)
2. post_regbase Process + ProcessDqkv (s1s2_bn2gs1s2_post_regbase.h:180-260) — how it handles BN2S2.

Let me do these two reads.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h [limit=118, offset=129]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h [limit=120, offset=160]
- Thought: 22.5s
Now I have everything needed for the final answer. Let me also check the post Process function to see when ProcessDqkv is called (i.e., for which splitAxis). Let me read the beginning of the post class / Process (lines 1-160) to see the dqkv handling — specifically whether ProcessDqkv is skipped for BN2S2. Actually, from what I've seen, the post's ProcessDqkv is the standard dqkv path reading workspace. For BN2S2, the vec already writes dqkv GM directly (kernel.h ComputeDqkvBn2s2 with ProcessMulsAndCast → DqkvMulsAndCastFromGM). So if Post also ran ProcessDqkv for BN2S2, there'd be double-write. Let me check post Process structure quickly — read lines 1-160 (or at least 60-160) to see Process's dispatch.

Actually, given time constraints and the user's actual question (FP16 precision debugging, dq magnitude off by factor, suspects POST scale/cast), the important thing is:

1. BN2GS1S2 non-FP32 (the common FP16 route): cube writes float dqkv → workspace; Post ProcessDqkv Muls(scale) on dq/dk (qkvIdx<2) + Cast round → writes final dqkv GM. So if scaleValue is applied and the user's dq is off by scale factor, the scale is applied exactly once here. Also — dv is NOT scaled (qkvIdx<2 only).

2. FP32 (BN2GS1S2): workspace aliases output GM (kernel_base.h:278-282); scale applied in ProcessVec3 on dS before mm3/mm4 (block_vec.h:618-621); no Post (entry:91/111-113).

3. BN2/BN2S2: vec itself does Muls+Cast via ProcessMulsAndCast (kernel.h:238-267, 395-431) writing dqkv GM directly; BN2 macro runs Post only when sinkOptional (entry:170-181 — for sink reduction, dsink etc.), and BN2S2 uses the BN2GS1S2 macro which runs Post for non-FP32... 

Wait — I still need to clarify the BN2S2 + Post double-write concern. Let me check the post Process dispatch — maybe ProcessDqkv is skipped when SPLIT_AXIS == BN2S2 (since vec already wrote dqkv GM). Let me read post_regbase.h lines 40-160 to see Process/ProcessDqkv dispatch conditions. Also need to see the beginning (class decl + template params, dqkvWorkspace init).

Let me read post_regbase.h 1-160.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h [limit=160, offset=1]
- Thought: 722ms
I still haven't seen Post's Process() dispatch to know when ProcessDqkv is called (skipped for BN2S2?). Let me read post_regbase.h:280-335 (the tail, which likely contains Process()).
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h [limit=60, offset=280]
- Thought: 10.8s
Now everything is fully confirmed. The critical line: post_regbase.h:314-317: // bn2s2 dk dv no need to do muls and cast; if constexpr (SPLIT_AXIS == 5) { break; } — for BN2S2 (SPLIT_AXIS == 5), ProcessDqkv only processes qkvIdx==0 (dq)! The dk/dv are already written by the main kernel's ProcessMulsAndCast. And Post's Process() (line 327) runs ProcessDqkv only when SPLIT_AXIS != BN2 && !IsSameType<T1, float> — i.e., never for BN2 and never for FP32.

Wait, interesting: for BN2S2, ProcessDqkv processes only dq (qkvIdx==0 loop iteration, then break at line 315-317). But does the BN2S2 main kernel write dq? From kernel.h:238-267 (ComputeDqkvBn2s2), the dk path: IS_DK_WRITE_UB → UB → ProcessMulsAndCast writes dk GM; else workspace → ProcessMulsAndCast writes dk GM. And dq? Let me check ComputeDqkvBn2s2 dq part — lines 215-237. From the earlier search snippet: line 235-236 "// compute dk" at 237. I saw lines 30-214 only. The dq part of ComputeDqkvBn2s2 is at ~215-236, not seen. But the pattern from IS_DQ_WRITE_UB = (SPLIT_AXIS == BN2 && !multiBlk && ...) → false for BN2S2, so dq goes to workspace via IterateMmDsK(dqWorkSpaceGm,...) and then... does the vec do ProcessMulsAndCast for dq too? Line 250/264 show only dk. Let me quickly check kernel.h:215-237 for the dq handling in ComputeDqkvBn2s2.

Actually — the comment at post:314 says "bn2s2 dk dv no need to do muls and cast" and breaks after qkvIdx==0 (dq). So for BN2S2: dq is processed by Post (muls+cast), dk/dv by the main kernel vec (ProcessMulsAndCast). That's consistent: the vec dq path in BN2S2 presumably does NOT do muls (only dk/dv do), or dq goes to workspace without muls and Post finishes it.

Let me verify the dq part of ComputeDqkvBn2s2 — read kernel.h:214-238.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h [limit=24, offset=214]
- Thought: 17.8s
Confirmed: in ComputeDqkvBn2s2, dq is computed via IterateMmDsK<CALC_TYPE, IS_DQ_WRITE_UB>(dqWorkSpaceGm, ...) (kernel.h:233-236) and then — from the earlier read of lines 238-267 — dk is computed with ProcessMulsAndCast (writing dk GM), and dv similarly (lines 273+). So for BN2S2:
- dq → cube writes float to dqWorkSpaceGm (IS_DQ_WRITE_UB=false), NO vec Muls/Cast for dq → Post ProcessDqkv handles dq only (muls+cast, then break at post:314-317).
- dk/dv → vec ProcessMulsAndCast does Muls(scale, if MM_IDX != DV_IDX) + Cast → writes GM directly. Wait, but dv: if constexpr (MM_IDX != DV_IDX) Muls(...) — DV_IDX == 2, so dv not scaled, only cast. Consistent.

So the complete picture is confirmed. Now I have all facts. One more item from my Active list: isBn2 first assignment — not critical for the final answer since BN2 conditions are well documented. And presfmg deqScaleDy use — not critical either. I've spent a fair number of tool calls; the user's question is essentially answered with strong evidence. I should now compose the final answer.

Let me also double-check what "ORIG_DTYPE_QUERY == DT_FLOAT16" gating means for the presfmg pre-stage: enablePreSfmg only set for HIFLOAT8/BF16/FP16 (host side), and entry requires dTemplateType > 64 (line 46). For FP32, enablePreSfmg never true on host (queryType not FP16/BF16/HIFP8) — FP32 always uses S1S2BNGS1S2PreRegbase.

Also note for the user's FP16 dq magnitude issue: In the FP16 BN2GS1S2 path:
- main kernel cube writes float dq to dqWorkSpaceGm (kernel_base.h:271-276, using postTilingData.dqWorkSpaceOffset)
- Post ProcessDqkv: DataCopy workspace→UB (post:234), Muls scaleValue if qkvIdx<2 (post:237-239), Cast float→half CAST_ROUND (post:241), DataCopy to dqGm (post:274).
- scaleValue = attr 0 (tiling_common:1011), written to tiling at tiling_normal:1855, read at post:238 via tilingData->s1s2BNGS1S2BaseParams.scaleValue.

So dq IS scaled exactly once in Post for FP16 (dq/dk), dv unscaled. If user sees dq off by a factor, check:
1. scaleValue attr correctness (host_runtime_leaf — whether GetAttrPointer<float>(0) is scale_value attr; should verify in the operator spec — this is host runtime, can't be statically determined from source alone).
2. Whether the user's shape took BN2S2 path (then dq via Post, dk/dv via vec muls) or BN2 path (vec muls+cast for all three, post only if sinkOptional).
3. Whether enablePreSfmg path was taken (then the pre-stage computes softmax-grad into float workspace; dqkv main stage same as usual; Post same).

Also worth noting: for FP32, output IS the workspace (aliased), and scale applied on dS in vec (ProcessVec3), so FP32 dq magnitude = (dS·scale)·K — same math as FP16 Post (dq = dS·K then ·scale). Actually careful: FP32 scales dS BEFORE mm3/mm4 (dq = (dS*scale)·K); FP16 scales dq AFTER mm3/mm4 (dq = (dS·K)*scale). Mathematically equal (linear), modulo rounding differences in half. So both apply scale exactly once. Good.

Now — the remaining minor unknowns:
- presfmg deqScaleDy usage (not needed for the answer core, can mark UNKNOWN/partial)
- isBn2 first assignment (BN2 host condition already documented at tiling_common:1590-1608; the first assignment is presumably in DoTiling — I can mark partial)
- NzPost scaleValue usage (only relevant when IS_NZ_OUT; the standard path is !IS_NZ_OUT → S1S2BNGS1S2PostRegbase. nz_post.h:90 declares scaleValue member, :103 Init reads it. I can mention it briefly as the NZ variant; its ProcessDqkv usage wasn't read — mark partial)

I think I have enough to write the final answer. The answer should be in Chinese (user's language), prose + file:line, Cursor Explore style, marking UNKNOWN/partial where static determination isn't possible.

Let me compose the final message now. Structure:

1. 总体结论（三条路径的 scale/cast 处理矩阵）
2. BN2 是什么（SplitAxis 枚举，不是 tiling 字段）
3. enablePreSfmg 完整语义
4. FP32 vs FP16 差异细节
5. POST 阶段细节（dq/dk scale、dv 不 scale、CAST_ROUND）
6. 对用户 FP16 调试的直接建议 + UNKNOWN/partial 项

Keep it focused and evidence-backed. Don't write answer.yaml, don't finalize. This is the final message of this delegated_query agent run.
Evidence gathering is complete — the full dqkv write/scale/cast matrix is now confirmed end-to-end. Here is the final analysis.
FlashAttentionScoreGrad (arch35) — FP32 / BN2 / enablePreSfmg 与 POST scale/cast 全链路
一、核心结论：三条路径的 scale/cast 处理矩阵
路径	dqkv 由谁写最终 GM
FP32（恒 BN2GS1S2）	主核 cube 直接写输出 GM（workspace 与输出同址）
FP16/BF16 · BN2GS1S2（最常见）	Post 阶段 ProcessDqkv
FP16/BF16 · BN2S2	dq → Post；dk/dv → 主核 vec ProcessMulsAndCast
FP16/BF16 · BN2（非 multiblk）	主核 vec ProcessMulsAndCast 直写
关键源码证据：
- 写最终 GM 的“所有权”由三个编译期开关决定（op_kernel/arch35/flash_attention_score_grad_kernel_base.h:99-103）：
- IS_DQ_WRITE_UB = (SPLIT_AXIS==BN2 && !IS_BN2_MULTIBLK && !IS_DQ_RES_EXCEED_UB)
- IS_DK_WRITE_UB = ((BN2&&!multiblk) || (BN2S2&&NO_DETER)) && !IS_DKV_RES_EXCEED_UB
- IS_DV_WRITE_UB = (BN2S2&&NO_DETER) && !IS_DKV_RES_EXCEED_UB
- 注意：BN2GS1S2 三个开关全为 false → cube 结果一律落 float workspace，等 Post 处理。
- workspace 是否等于输出 GM，在 InitCVCommonGlobalBuffer（kernel_base.h:246-282）：
- FP32 分支（:278-282）：// input type fp32, dq dk dv write to output gm directly，dq/dk/dvWorkSpaceGm 直接 SetGlobalBuffer 到 dq/dk/dv 输出地址；
- 非 FP32（:261-277）：指向 workspace + postTilingData.dq/dk/dvWorkSpaceOffset（BN2 非 multiblk 特例用 RESERVED_WORKSPACE_SIZE 偏移，:262-269）。
- Post 是否执行：op_kernel/arch35/flash_attention_score_grad_entry_regbase.h:91 if (ORIG_DTYPE_QUERY != DT_FLOAT) → SyncALLCores + destroy 主核 pipe + 跑 Post；FP32 走 else（:111-113）直接 pipeBase.Destroy()，FP32 没有 Post 阶段。
- Post 内部对 BN2S2 的处理：s1s2_bn2gs1s2_post_regbase.h:314-317 // bn2s2 dk dv no need to do muls and cast; if constexpr (SPLIT_AXIS == 5) break; —— Post 只处理 dq，dk/dv 由主核 vec 完成；Process()（:322-333）还要求 SPLIT_AXIS != BN2 && !IsSameType<T1,float> 才调用 ProcessDqkv()。
二、Post 阶段 ProcessDqkv 细节（FP16 dq 量级的直接相关代码）
op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h:207-318：
1. 按 qkvIdx 取各自的 postTilingData.*PostBlockFactor/Total/TailNum（:211-217），dqkvWorkspace[qkvIdx] 由 postTilingData.dq/dk/dvWorkSpaceOffset 定位（Init :95-97）；
2. DataCopy float workspace → UB（:234 / :250）；
3. scale 只对前两个：:237-239 if (qkvIdx < 2) Muls(vecInPing, vecInPing, (float)tilingData->s1s2BNGS1S2BaseParams.scaleValue, pingSize);（pong 侧 :282-284 相同）；
4. Cast(vecOutPing, vecInPing, RoundMode::CAST_ROUND, pingSize)（:241 / :285），float→half 四舍五入；
5. 写回 dqkv[qkvIdx] GM（:274 非 rope 直拷；:255-272 rope 时 dqkv 与 dqRope/dkRope 分块）。
scaleValue 来源链：
- host 读 attr：op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp:1011 fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0));（attr 0）
- 写 tiling：op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1855 s1s2BNGS1S2BaseParams_->set_scaleValue(fBaseParams.scaleValue);
- TILING_FIELD 声明：op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h:96
- Post 内读取：post:238、:283（经 tilingData->s1s2BNGS1S2BaseParams.scaleValue）
三、FP32 路径的 scale（与 FP16 数学等价，但位置不同）
op_kernel/arch35/flash_attention_score_grad_block_vec.h:618-621（ProcessVec3 内）：
// input type fp32, no post, mov muls here
if constexpr (IS_FP32_INPUT) { Muls(mm1ResTensor, mm1ResTensor, constInfo.scaleValue, VECTOR_BASEM * VECTOR_BASEN); }
即 FP32 把 scale 乘在 dS（softmax 梯度） 上，之后 mm3/mm4 的 dq = (dS·scale)·K、dk = (dS·scale)·Q 自动带上 scale，dv 天然不乘 —— 与 FP16 Post 的 dq = (dS·K)·scale 线性等价，只差 half 中间精度。FP16 若怀疑“量级差一截”，应重点核对：scaleValue attr 本身（host_runtime_leaf，源码静态无法确定其值）、shape 是否落到 BN2S2（dq 由 Post、dk/dv 由 vec 各自乘一次，仍只乘一次）、以及是否走了 enablePreSfmg（见下）。
四、BN2 到底是什么
BN2 / BN2GS1S2 / BN2S2 是 SplitAxisEnum 的枚举值（tiling key 的 splitAxis bit 3-1），不是 tiling 字段。全代码 blockNum2 / preScale 子串 0 命中。
host 侧选路（op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp）：
- bnLimit（:1590-1591）：b*n1>=256 || (b*n1>=128 && s1%128==0 && s2%128==0)；
- isBn2MultiBlk（:1596-1606）：bnSparseLimit && (s1>BN2_MAX_S || s2>BN2_MAX_S) && ... && n1==n2 && d<=BN2_MAX_D && queryType != DT_FLOAT && d==d1 && !fp8 && !hasRope —— FP32 被显式排除（:1601）；
- :1607 isBn2 = isBn2MultiBlk ? true : isBn2;
- SetSplitAxis（:1641-1648）：!isBn2 && bn2S2RouteLimit → BN2S2（BN2S2 同样要求 queryType != DT_FLOAT，:1637）；isBn2 → BN2；否则 BN2GS1S2。
- 兜底修正：tiling_normal_regbase.cpp:674-691（DoBn2MultiBlkSparse 中 invalid col/row → isBn2=false; isBn2MultiBlk=false; splitAxis=BN2GS1S2；:691 splitAxis = isBn2 ? BN2 : BN2GS1S2）。
kernel 侧分发（op_kernel/arch35/flash_attention_score_grad_entry_regbase.h:224-242）：splitAxis==BN2GS1S2 与 ==BN2S2 走 INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL_*（FP16 实参 half,float,half；BF16 bfloat16_t,float,bfloat16_t；FP32 float,float,float，:225-235 / 116-126）；==BN2 走 INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL_*（:236-241）。BN2 宏（:129-182）只在 sinkOptional 时跑 Post（:134、:170-181），且 Post 对 BN2 不做 dqkv（post:327 SPLIT_AXIS != BN2 才 ProcessDqkv）。
BN2S2/BN2 的 vec 直写细节：op_kernel/arch35/flash_attention_score_grad_kernel.h ComputeDqkvBn2s2（:233-267）：dq 走 IterateMmDsK(dqWorkSpaceGm,...)（:234，等 Post 收尾）；dk 按 IS_DK_WRITE_UB 二选一后都进 ProcessMulsAndCast（:250-251 / :264-265）直写 dk GM；dv 同理（:273+）。ComputeDqkvBn2（:395-431）三个都走 ProcessMulsAndCast。ProcessMulsAndCast（block_vec.h:654-665 → DqkvMulsAndCastFromUB :707-709 if constexpr (MM_IDX != DV_IDX) Muls(inputTensor, inputTensor, constInfo.scaleValue, dataSize) —— dv 不乘 scale，只 cast）。
五、enablePreSfmg 完整语义
host 侧（op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1141-1149，DoPreTiling）：
fBaseParams.enablePreSfmg =
    (queryType == ge::DT_HIFLOAT8) ||
    ((queryType == DT_BF16 || queryType == DT_FLOAT16) &&
     presfmgLimit &&                                   // :1139-1140: !(s2<=NUM256 && b*n1*s1Outer>=MAX_BASIC_BLOCK_SIZE)
     d > NUM64 && d <= NUM768 &&                       // 64 < d <= 768
     (splitAxis == BN2GS1S2 || splitAxis == BN2S2) &&  // BN2 被排除
     !isDeterministic && sinkOptional != NORMAL_TENSOR &&
     dropoutIsDivisibleBy8 && !sValueZeroUnderTND);
写 tiling：:1896 set_enablePreSfmg(...)。TILING_FIELD 声明：tiling_data_regbase.h:120。FP32 恒 false（queryType 不在 FP16/BF16/HIFP8 之列）。
kernel 侧：
- entry 分支（entry_regbase.h:45-61）：enablePreSfmg 为真且 dTemplateType > 64 时，用 FlashAttentionScoreGradPresfmgRegbase（op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h，Init :130、CalculateSoftmaxGrad、DoSoftmaxGrad）替代常规 S1S2BNGS1S2PreRegbase（:54-61）；否则常规 Pre。
- 主核读点：block_vec.h:243（InitGlobalBuffer）、:306（InitUbBuffer）、kernel_base.h:488（SetConstInfo）；kernel_base.h:686 constInfo.enablePreSfmg = ((uint32_t)dTemplateType > 64) && tilingData->s1s2BNGS1S2BaseParams.enablePreSfmg;（二次校验 d>64）；block_vec.h:605 if (unlikely(constInfo.enablePreSfmg)) 释放 maxSumQue 的 softmaxGradResTensor。
- host 侧 pre tiling：DoPreSfmgTiling（tiling_normal_regbase.cpp:1040-1128，:1096-1098 仅 FP16/BF16 计算 singleLoopNBurstNum；字段写入 preTilingData_ :1113-1127）。
- 注意：enablePreSfmg 只改变 Pre 阶段（把 softmax-grad 提前算成 float 存 workspace），不改变 dqkv 的 Post scale/cast 路径（BN2GS1S2 非 FP32 仍走 Post ProcessDqkv）。
六、UNKNOWN / partial（静态无法从源码完全确定）
1. scaleValue 的实际数值：GetAttrPointer<float>(0)（tiling_common_regbase.cpp:1011）是 host_runtime 行为，attr0 是否等于用户传入的 scale_value 需在算子定义/调用侧核实 —— 这是 FP16 dq 量级差一截时最可能的“外因”检查点。
2. isBn2 首次赋值点：当前只确认 isBn2 = isBn2MultiBlk ? true : isBn2（tiling_common:1607）与 DoBn2MultiBlkSparse 的修正（tiling_normal:681-691），首次 shape 级赋值未定位（partial）。
3. presfmg DoSoftmaxGrad 尾部对 deqScaleDyGm 的实际使用（presfmg_regbase.h:516-578 未逐行读；deqScaleIdx 参数已声明 :51）—— 不影响本结论，但若用户走 deqScale 量化（common.h:398-402）需补查。
4. NzPost（IS_NZ_OUT）变体：nz_post.h:90/:103 声明并读 scaleValue，其 ProcessDqkv 使用点未读（partial）；标准非 NZ 输出走 S1S2BNGS1S2PostRegbase。
5. enablePreSfmg 的 presfmgLimit 中 MAX_BASIC_BLOCK_SIZE 具体值（tiling_normal:1140）未查常量定义。
七、给 FP16 调试的落地建议
1. 先确认 splitAxis：shape 若满足 BN2S2 条件（tiling_common:1641-1648），dq 在 Post、dk/dv 在主核 vec 各乘一次 scale，均恰好一次，不会双乘；若 shape 落 BN2GS1S2（FP16 最常见），dq 只经 Post（post:237-241）一次 Muls+CAST_ROUND。
2. 核对 scaleValue attr（:1011 的 attr0）与 scale_value 输入是否一致 —— 这是唯一无法静态验证的环节。
3. 确认 enablePreSfmg 是否被触发（tiling_normal:1141-1149 条件；d>64 且 splitAxis∈{BN2GS1S2,BN2S2} 等）——若触发，softmax-grad 提前变 float，dq 的输入源是 float workspace，可对比“关掉 presfmg（如改 d≤64 或 deterministic）”的 dq 量级。
4. dv 恒不乘 scale（post:237 的 qkvIdx < 2、block_vec.h:708 的 MM_IDX != DV_IDX）—— 若 dv 量级正常而 dq/dk 整体偏 scale 倍，可反推 scaleValue 数值问题；若 dq 单独异常，优先怀疑 Post 的 ROPE 分块拷贝（post:255-272）与 workspace offset 错位。
（未写 answer.yaml，未 finalize。）
▣  Uo-Query · DeepSeek V4 Flash Free · 3m 41s
Subagent(2 of 9)51.8K (26%)

# subagent 3
算子目录：d:\TEST\ops-transformer\attention\flash_attention_score_grad（arch35，.uo CodeMap 已建好）。

立即调用 acp 工具：command=`uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...`（按需选 locate/symbols/callers/fields 等）。禁止 bash、Grep、MCP 替代。

背景：用户在调试 FP16 精度（dq 量级差一截，FP32 同 shape 过）。现在要确定：**一个 FP16 输入 case，splitAxis 实际会落到哪条路径（BN2 / BN2S2 / BN2GS1S2）**。

请只回答这一个问题，全部带 file:line 证据：
1. host 侧（op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp、tiling_normal_regbase.cpp）splitAxis 的完整选路链：读 tiling key / tiling data 里与 splitAxis 相关的字段、选路条件（bnLimit、isBn2MultiBlk、bn2S2RouteLimit、SetSplitAxis 等），FP16（DT_FLOAT16）输入时哪些条件决定走向 BN2GS1S2、BN2S2、BN2。
2. 明确哪些条件依赖运行时 shape / tiling 参数（即静态源码无法确定具体 case 落在哪条），哪些是编译期/类型层面已固定的（如 FP32 恒排除 BN2/BN2S2）。
3. 结论格式：FP16 输入下，若无具体 shape，给出「条件 → 路径」的分支表，并把「当前 case 实际是哪条」标为 PARTIAL（除非你能从 tiling key 或已有 tiling 产物确认具体值）；有具体证据能确定就明确写。

用 Cursor Explore 风格回答：完整散文 + file:line。不要写 answer.yaml，不要 finalize。
- Thought: 298ms
Let me start by querying the UO CodeMap for the flash_attention_score_grad operator.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern splitAxis]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode symbols --pattern splitAxis]
- Thought: 29.9s
The locate query gave good coverage. Now I need to trace the full selection chain. Key facts so far:

1. SplitAxis tiling key field (op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h:56): values 0=BN2GS1S2, 1=BN2, 5=BN2S2
2. SetSplitAxis in common_regbase.cpp:1641-1648:
   - if (!fBaseParams.isBn2 && bn2S2RouteLimit) → BN2S2
   - else if (fBaseParams.isBn2) → BN2
   - else → BN2GS1S2
3. DoSparse in normal_regbase.cpp:674-691: special cases
4. GetTilingKey packing at normal_regbase.cpp:1443, 1460

Now I need to find:
- Where bn2S2RouteLimit is computed (which conditions determine it)
- Where isBn2 is set
- Where isBn2MultiBlk is set
- Whether InputDType FP16 plays a role
- Whether FP32 is excluded from BN2/BN2S2

Let me query for bn2S2RouteLimit and isBn2, plus the branches mode for SetSplitAxis.
locate 命中很全。现在追踪 bn2S2RouteLimit、isBn2、isBn2MultiBlk 的定义链，以及 InputDType 与 BN2/BN2S2 的关系
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern bn2S2RouteLimit]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern isBn2]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern isBn2MultiBlk]
- Thought: 8.2s
Now I have the core selection chain in SetSplitAxis (common_regbase.cpp:1581-1648). Let me now read the full SetSplitAxis function window to see everything: BN2_MAX_S, BN2_MAX_D, bnSparseLimit, BN2_MULTIBLK_SEQ, etc. Also read the DoSparse function in normal_regbase.cpp around 660-700, and the GetTilingKey region 1440-1470, plus the tiling key header for InputDType and SplitAxis. Also check DetermineMode (fp16 → FLOAT16_PRECISION) — the comment says "当前fp16都走高精度" which suggests FP16 always goes to high-precision route.

Let me read the relevant windows:
1. op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp lines ~1550-1670 (SetSplitAxis complete)
2. op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp lines ~640-720 (DoSparse complete) and ~1420-1480 (GetTilingKey)
3. op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h lines ~40-120 (SplitAxis, InputDType, IsBn2MultiBlk)

Also need to understand where the TND paths override splitAxis (varlen_regbase.cpp:126, 190, 389, 760) — those are for deterministic varlen paths. And in normal_regbase DoSparse line 691-692: after DoSparse, splitAxis = isBn2 ? BN2 : BN2GS1S2 — note this OVERWRITES BN2S2! Wait, that's important. Let me check: DoSparse at line 691 sets splitAxis = isBn2 ? BN2 : BN2GS1S2 unconditionally. If the earlier SetSplitAxis set BN2S2, then DoSparse would overwrite it to BN2GS1S2 unless isBn2... Hmm, but does DoSparse run in normal (non-TND) flow? Need to check the flow: SetSplitAxis is called first, then DoSparse may override.

Let me read the actual files to get precise windows. The machine-scope operator sources are outside .ascendc-pilot — but per the agent rules I can read with windowed Read after locating via UO KB query. The files are at d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\... Let me read them in windows.
核心选路链已经定位到 SetSplitAxis。现在读关键源码窗口确认完整条件和调用顺序（SetSplitAxis → DoSparse → GetTilingKey 打包），以及 tiling key 头文件里 SplitAxis/InputDType 的定义
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp [offset=1555, limit=120]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [offset=640, limit=100]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [offset=40, limit=80]
- Thought: 1.7s
Excellent. Now I have the key SetSplitAxis function fully. Let me now confirm:

1. Where SetSplitAxis is called relative to DoSparse — need to check the normal tiling flow (which function calls SetSplitAxis and DoSparse, in what order).
2. The GetTilingKey at line ~1443-1468 in normal_regbase.cpp.
3. The constants BN2_MAX_S, BN2_MAX_D, BN2_MULTIBLK_SEQ, BN2S2_MAX_S, BN2S2_WRITE_UB_D, ALIGN128, BN2_MULTIBLK_BN_256/128.
4. Also check the tiling_data mode to see whether there's actual tiling data for the current case. And check tiling_key mode for what's in the tiling key for the current case — since user asked "unless you can confirm specific values from tiling key or existing tiling products".

Let me query constants and callers, plus tiling_key/tiling_data modes.
SetSplitAxis 全链已拿到。现在补齐：调用顺序（SetSplitAxis 相对 DoSparse / GetTilingKey 的调用点）、常量定义（BN2_MAX_S/D、BN2_MULTIBLK_SEQ 等）、以及 tiling_key/tiling_data 是否能确认当前 case 的实际
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode callers --pattern SetSplitAxis]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern BN2_MAX_S]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode tiling_key]
- Thought: 20.9s
I have almost everything. Now I need:

1. The constants BN2_MAX_S, BN2_MAX_D, BN2_MULTIBLK_SEQ, BN2S2_MAX_S, BN2S2_WRITE_UB_D — their actual numeric values (likely in a header). Let me search for their definitions.
2. Where SetSplitAxis is called from (the flow order) — need to find the caller. Let me use neighbors mode on the SetSplitAxis function or search mode. Actually the locate already showed function "SetSplitAxis" at line 1581 in common_regbase.cpp. Let me use neighbors mode or search mode to find calls to SetSplitAxis.
3. Also confirm that in the TND/normal flow, DoSparse line 691 overwrites splitAxis to BN2 or BN2GS1S2 — which means BN2S2 set by SetSplitAxis would be overwritten for the non-Bn2-multiblk path... Wait, actually look carefully:

In DoSparse (normal_regbase.cpp:660-732):
- Line 665: if (DoBn2s2Sparse() && fBaseParams.blockOuter >= fBaseParams.aicNum) return early — this is the BN2S2 sparse path for TND? It returns GRAPH_SUCCESS without touching splitAxis. Hmm, but wait — is DoSparse called for the BN2S2 route? DoBn2s2Sparse() — let me check what that does.
- Line 691: fBaseParams.splitAxis = fBaseParams.isBn2 ? SplitAxisEnum::BN2 : SplitAxisEnum::BN2GS1S2; — This overwrites splitAxis to BN2 or BN2GS1S2, BUT the earlier return ge::GRAPH_SUCCESS at line 666 may skip this overwrite when DoBn2s2Sparse() && blockOuter >= aicNum. So BN2S2 survives only via that early return path (line 665-666). That's important: in the normal regbase flow, the BN2S2 route is preserved ONLY if DoSparse early-returns at line 666. Otherwise splitAxis is forced to BN2/BN2GS1S2 at line 691.

Wait, but hold on — is DoSparse even called on the BN2S2 path? Let me check DoBn2s2Sparse(). Also need to find the overall flow: TilingNormalRegbase::ComputeTiling or similar that calls SetSplitAxis, then DoSparse, then GetTilingKey.

Let me search for:
- DoBn2s2Sparse 
- constants BN2_MAX_S etc. definitions (search in the headers, maybe flash_attention_score_grad_tiling_common_regbase.h or a constants header)
- calls to SetSplitAxis (neighbors mode with target)

Let me also check tiling_data mode to see if there's actual tiling data for a current case. The user asked: "有具体证据能确定就明确写" — if the tiling_key/tiling_data modes have actual values from a real tiling, I could confirm. But these modes returned only the schema, no concrete per-case values. So current case = PARTIAL unless the user gives shape.
主链已清晰。还差三块：常量数值（BN2_MAX_S/D、BN2_MULTIBLK_SEQ、BN2S2_MAX_S 等）、DoBn2s2Sparse 的语义（决定 BN2S2 是否在 DoSparse 中被保留）、以及 SetSplitAxis 的调用点/顺序
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern DoBn2s2Sparse]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern SetSplitAxis]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern BN2_MULTIBLK_SEQ]
- Thought: 233ms
Now I need:
1. The numeric values of constants: BN2_MAX_S, BN2_MAX_D, BN2_MULTIBLK_SEQ, BN2S2_MAX_S, BN2S2_WRITE_UB_D, ALIGN128, BN2_MULTIBLK_BN256, BN2_MULTIBLK_BN128. They're likely defined in a header, maybe flash_attention_score_grad_tiling_common_regbase.h or a constants header. Let me read the header.
2. The DoOpTiling flow (normal_regbase.cpp line ~430) — need to see the order: SetSplitAxis is called from DoOpTiling at line 430, then DoSparse... Let me read around 400-460.
3. The varlen flow (tiling_varlen_regbase.cpp) — but the user's question is about arch35 normal. The varlen ones (lines 126, 190, 389, 760) apply to TND deterministic. Worth mentioning briefly.

Let me read the header for constants and DoOpTiling.
常量数值和 DoOpTiling 调用顺序还差最后一步。读公共头文件找常量定义，并看 DoOpTiling 里 SetSplitAxis → DoSparse → GetTilingKey
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern BN2S2_MAX_S]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=90, offset=395]
- Thought: 24.2s
Now I have the full flow:

DoOpTiling (normal_regbase.cpp:430):
1. Line 432: SetSplitAxis(context_, fBaseParams) — this is the primary splitAxis decision (common_regbase.cpp:1581-1649)
2. Line 433: DoSplit() — s1/s2 splitting (may change s1/s2? no, splits into inner/outer)
3. Line 434: DoSparse() — may override splitAxis at line 691 (normal_regbase.cpp:691): splitAxis = isBn2 ? BN2 : BN2GS1S2, but only if BN2S2 sparse path didn't early-return at line 665-666. Wait, careful: at line 665 if (DoBn2s2Sparse() && blockOuter >= aicNum) return GRAPH_SUCCESS; — if DoBn2s2Sparse() is true (splitAxis == BN2S2 and not DETER_OLD) and there are enough blocks, it returns success WITHOUT overriding splitAxis, so BN2S2 survives. But if DoBn2s2Sparse() returns false (e.g., BN2S2 with too few blocks: blockOuter < aicNum), then falls through to line 691 which OVERRIDES splitAxis to BN2 or BN2GS1S2. Hmm wait — line 691 says fBaseParams.splitAxis = fBaseParams.isBn2 ? SplitAxisEnum::BN2 : SplitAxisEnum::BN2GS1S2; — this would convert a BN2S2 to BN2GS1S2 (since isBn2 would be false if bn2S2RouteLimit was taken... wait no. Let me re-check.

Actually wait — the !fBaseParams.isBn2 && bn2S2RouteLimit branch requires !isBn2. So if splitAxis==BN2S2, isBn2 is false. Then at line 691, isBn2 ? BN2 : BN2GS1S2 → BN2GS1S2. So yes, if the BN2S2 path is not viable via DoBn2s2Sparse (early return at line 666), the splitAxis gets overwritten to BN2GS1S2 at line 691.

Wait, but actually check: does DoSparse even run for the TND BN2S2 path? At line 665: if (DoBn2s2Sparse() && fBaseParams.blockOuter >= fBaseParams.aicNum) return ge::GRAPH_SUCCESS;. DoBn2s2Sparse at line 511-547 returns true when splitAxis==BN2S2 and not DETER_OLD, computing block info. If blockOuter >= aicNum, early return keeps BN2S2. Otherwise (blockOuter < aicNum), it falls to line 669 SupportTrans2BS2N2GD etc., and line 691 overrides to BN2GS1S2 (or BN2 if isBn2 — but isBn2 is false in BN2S2 case).

Hmm wait, but there's a subtlety: line 665's DoBn2s2Sparse() might also return true for BN2S2 when layoutType is TND (GetBlockInfoOfBNS4TND). In that case BN2S2 survives if blockOuter >= aicNum.

Important: So final splitAxis going into GetTilingKey:
- BN2S2 survives only when SetSplitAxis chose BN2S2 AND DoSparse's BN2S2 sparse handling succeeded with blockOuter >= aicNum (early return at line 666), OR... wait, also need to check the SupportTrans2BS2N2GD path (line 669-672): this converts layoutType to BS2N2GD and re-computes sparseType. Then line 674: only if splitAxis==BN2 && isBn2MultiBlk → DoBn2MultiBlkSparse. Otherwise line 691 overrides.

Hmm, but wait — actually let me re-examine. If splitAxis == BN2S2 (from SetSplitAxis), and DoBn2s2Sparse() returns true but blockOuter < aicNum, then line 669 SupportTrans2BS2N2GD (only if sparseMode <= PREFIX_COMPRESS && isAllSame && layoutType==TND) converts to BS2N2GD. Then line 691: splitAxis = isBn2 ? BN2 : BN2GS1S2 — since isBn2 is false → BN2GS1S2! So it becomes BN2GS1S2 with BS2N2GD layout.

Hold on, that seems odd but OK. Actually wait — is that right? Let me re-read:

660: ge::graphStatus FlashAttentionScoreGradTilingNormalRegbase::DoSparse()
661: {
662:     fBaseParams.sparseType = GetSparseType();
663:     fBaseParams.deterSparseType = GetDeterSparseTilingKey();
664:     CalcleDeterParam();
665:     if (DoBn2s2Sparse() && fBaseParams.blockOuter >= fBaseParams.aicNum) {
666:         return ge::GRAPH_SUCCESS;
667:     } else {
668:         // TND S1 S2全等场景下if分支尝试走BN2S2分核优化,如果判断不能走则恢复layoutType赋值
669:         if (SupportTrans2BS2N2GD(fBaseParams)) {
670:             fBaseParams.layoutType = INPUT_FORMAT_BS2N2GD;
671:             fBaseParams.sparseType = GetSparseType();
672:         }
673:     }
674:     if (fBaseParams.splitAxis == SplitAxisEnum::BN2 && fBaseParams.isBn2MultiBlk) {
...
690:     }
691:     fBaseParams.splitAxis = fBaseParams.isBn2 ? SplitAxisEnum::BN2 : SplitAxisEnum::BN2GS1S2;

Hmm wait, but DoBn2s2Sparse returns true only when splitAxis == BN2S2 (line 513). So:
- If splitAxis == BN2S2 and DoBn2s2Sparse() true and blockOuter >= aicNum → return early with splitAxis still BN2S2. ✓ BN2S2 survives.
- If splitAxis == BN2S2 and DoBn2s2Sparse() true but blockOuter < aicNum → fall to else; if SupportTrans2BS2N2GD → layoutType becomes BS2N2GD; then line 691 → splitAxis = BN2GS1S2 (isBn2 false). BN2S2 lost.
- If splitAxis == BN2S2 and DoBn2s2Sparse() false (e.g. DETER_OLD deterministic) → falls through, line 691 → BN2GS1S2.

Interesting. So BN2S2 is a fragile route — it survives only via the early return at line 666.

Hmm wait, but wait — is DoSparse always called after SetSplitAxis? Yes: DoOpTiling line 432-434. And GetTilingKey is a const method that reads fBaseParams.splitAxis at line 1443 — called later (probably from the outer tiling entry after DoOpTiling? or InitTilingData?). Actually GetTilingKey is likely called by the top-level tiling entry ComputeTiling or by InitTilingData. Let me check quickly — but for the answer, the key point is: final splitAxis = the one packed into tiling key at normal_regbase.cpp:1443/1460-1461.

Also there's the TND varlen path (tiling_varlen_regbase.cpp) with deterministic overrides at 126/190/389/760 — these are in CalcleTND*DeterParam functions which run for TND deterministic sparse modes. They force BN2GS1S2 under various conditions (not SupportTNDBns2, etc.). These would run after SetSplitAxis in the varlen flow (FlashAttentionScoreGradTilingVarlenRegbase). But the user's case: "FP16 输入 case，splitAxis 实际会落到哪条路径（BN2 / BN2S2 / BN2GS1S2）" and mentions tiling_normal_regbase.cpp + tiling_common_regbase.cpp. The user didn't mention varlen. But I should mention the varlen TND deterministic caveat briefly since it can force BN2GS1S2.

Now the constants. I need actual numeric values of BN2_MAX_S, BN2_MAX_D, BN2_MULTIBLK_SEQ, BN2S2_MAX_S, BN2S2_WRITE_UB_D, ALIGN128, BN2_MULTIBLK_BN256, BN2_MULTIBLK_BN128. They're COMPILE_VAR but the query doesn't show values. They're probably defined in a header file — let me look for the header. The tiling_common_regbase.h is in op_host/arch35/. Let me search the header file directly with Read (windowed). Since I'm allowed to read machine-scope operator sources with windowed reads after locating via UO KB.

Actually, the instruction says: Machine-scope operator sources (op_host/, op_kernel/, …) are outside .ascendc-pilot. Locate with UO KB query / ScopeSet first, then machine-scope windowed Read — never whole-file dumps. I've already used UO query to locate. Now reading windows is fine.

Let me read the header file flash_attention_score_grad_tiling_common_regbase.h around where constants may be, and also search for "#define BN2_MAX_S" or "constexpr" in common regbase cpp file beginning. Let me read the beginning of the common cpp file (constants are often at top) and the header.
常量数值还需要确认。读 common cpp 文件头部（常量通常在文件顶部）和公共
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp [limit=130, offset=1]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern BN2_MAX_D]
- Thought: 2.9s
The constants BN2_MAX_S, BN2_MAX_D, etc. are used but not defined in this cpp — they must be defined in the header file flash_attention_score_grad_tiling_common_regbase.h or another included header. Let me look at the header. The UO locate says sibling_files only includes the cpp, but the constants are COMPILE_VAR with no definition sites shown. Let me search the header directly.

Let me grep the header for these constants with a windowed read. Actually let me try uo-query --mode search --pattern BN2_MAX_S maybe with target. Or just read the header file. The header path: op_host/arch35/flash_attention_score_grad_tiling_common_regbase.h. Let me read the top of it and search for BN2.
常量数值应该定义在公共头文件里。直接窗口读头文件找 BN2_MAX_S / BN2_MAX_D / BN2S2_* / ALIGN128 / `BN2_MULTIBLK_*
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern BN2_MAX_D --target op_host/arch35/flash_attention_score_grad_tiling_common_regbase.h]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.h [limit=150, offset=1]
- Thought: 43.5s
I now have the constants:
- ALIGN128 = 128 (common_regbase.h:109)
- BN2_MAX_S = 128 (line 110)
- BN2S2_MAX_S = 1024 (line 111)
- BN2_MULTIBLK_SEQ = 640 (line 112)
- BN2_MULTIBLK_BN_128 = 128 (line 113)
- BN2_MULTIBLK_BN_256 = 256 (line 114)
- BN2_MAX_D = 512 (line 115)
- BN2S2_WRITE_UB_D = 128 (line 116)

I also need to check where SplitAxisEnum is defined (values 0=BN2GS1S2, 1=BN2, 5=BN2S2). It's referenced in the tiling key header at line 56: ASCENDC_TPL_UINT_DECL(SplitAxis, ASCENDC_TPL_3_BW, ASCENDC_TPL_UI_LIST, 0, 1, 5) — values 0=BN2GS1S2, 1=BN2, 5=BN2S2.

Let me quickly find SplitAxisEnum definition. And also confirm the FP16 aspect: DT_FLOAT16 (queryType == ge::DT_FLOAT16) → DetermineMode maps to FLOAT16_PRECISION. And in SetSplitAxis, the type conditions are:
- isBn2 requires queryType != ge::DT_FLOAT and NOT FP8 types → FP16 passes this (queryType == ge::DT_FLOAT16 is not DT_FLOAT, not FP8).
- isBn2MultiBlk requires same.
- bn2S2RouteLimit requires queryType != ge::DT_FLOAT and not FP8 → FP16 passes.

So type-wise, FP16 can go to ANY of the three paths; FP32 is excluded from BN2/BN2S2 routes (queryType != ge::DT_FLOAT excludes DT_FLOAT entirely). That matches user's observation "FP32 同 shape 过" — FP32 always lands BN2GS1S2 (since isBn2 false and bn2S2RouteLimit false due to queryType == DT_FLOAT). Wait — but is that true? Let me double check: FP32 → queryType == ge::DT_FLOAT → isBn2 = false (condition queryType != ge::DT_FLOAT fails), bn2S2RouteLimit also has (fBaseParams.queryType != ge::DT_FLOAT) → false → BN2GS1S2. So FP32 always BN2GS1S2. Yes, that's a compile-time/type-level fixed fact.

Now, is BN2S2 preserved after DoSparse? Looking at DoSparse (normal_regbase.cpp:660-732):
- Line 662-664: sparseType, deterSparseType, CalcleDeterParam
- Line 665: if (DoBn2s2Sparse() && fBaseParams.blockOuter >= fBaseParams.aicNum) return ge::GRAPH_SUCCESS; — DoBn2s2Sparse() (line 511-547) returns false if splitAxis != BN2S2 or deterSparseType == DETER_OLD; otherwise computes block info and returns true. So if splitAxis==BN2S2 and blockOuter >= aicNum, early return keeps BN2S2.
- Otherwise, line 669: SupportTrans2BS2N2GD → convert layout to BS2N2GD.
- Line 674: if splitAxis==BN2 && isBn2MultiBlk → DoBn2MultiBlkSparse; if invalid col/row → fallback BN2GS1S2 at line 684.
- Line 691: fBaseParams.splitAxis = fBaseParams.isBn2 ? SplitAxisEnum::BN2 : SplitAxisEnum::BN2GS1S2; — THIS OVERWRITES. So even if SetSplitAxis set BN2S2, DoSparse line 691 would overwrite it to BN2GS1S2 (since when BN2S2 was chosen, isBn2 is false — wait, is it? Let me re-check.

At SetSplitAxis line 1641: if (!fBaseParams.isBn2 && bn2S2RouteLimit) → BN2S2. So BN2S2 requires isBn2 == false. Then in DoSparse, line 691 sets isBn2 ? BN2 : BN2GS1S2 → since isBn2 is false → BN2GS1S2! 

Wait, that would mean BN2S2 gets overwritten to BN2GS1S2 by DoSparse line 691... UNLESS DoSparse early-returns at line 666 (if (DoBn2s2Sparse() && blockOuter >= aicNum) return GRAPH_SUCCESS;). 

So the survival of BN2S2 depends on the early return at line 665-666: DoBn2s2Sparse() && fBaseParams.blockOuter >= fBaseParams.aicNum. DoBn2s2Sparse (line 511-547):
- Returns false if splitAxis != BN2S2 OR deterSparseType == DETER_OLD.
- Otherwise if isSparse || layoutType==TND → GetBlockInfoOfBNS4TND (returns bool?); else computes block info and returns true.

Hmm, GetBlockInfoOfBNS4TND returns bool — need to check. But the key point: BN2S2 route survives only through this early return path at line 666. If DoBn2s2Sparse() returns false (e.g., DETER_OLD) or blockOuter < aicNum, then line 691 overwrites splitAxis to BN2GS1S2 (since isBn2 false for the BN2S2 case).

Wait — but hold on. Is DoSparse called even when layout is TND? Yes — DoOpTiling: line 432 SetSplitAxis → 433 DoSplit → 434 DoSparse. This is the normal regbase flow. And there's also the varlen regbase (tiling_varlen_regbase.cpp) with CalcleTND*DeterParam functions that force BN2GS1S2 at lines 126, 190, 389, 760 — those are for deterministic TND paths.

Actually wait — I should double check whether DoSparse overwrites BN2S2 in the TND non-deterministic case. Line 665: DoBn2s2Sparse() && blockOuter >= aicNum → early return keeping BN2S2. If not, falls to line 691 which sets BN2GS1S2. Hmm, but wait: for the BN2S2 TND path, line 517-518: if (fBaseParams.isSparse || fBaseParams.layoutType == INPUT_FORMAT_TND) return GetBlockInfoOfBNS4TND();. Let me check GetBlockInfoOfBNS4TND — does it set blockOuter? If it returns true but blockOuter < aicNum... Actually the comment in the earlier locate: HBR62DB0E749400 "!(DoBn2s2Sparse()&& fBaseParams.blockOuter>= fBaseParams.aicNum)" controls the BN2GS1S2 assignment at line 684 and HBR5490D69B92A9 controls line 691. So yes — the overwrite at 691 happens when NOT (DoBn2s2Sparse && blockOuter >= aicNum).

So the full chain for a FP16 input:

Type-level (fixed at compile/type time):
- FP16 (queryType == ge::DT_FLOAT16): passes all the dtype gates — queryType != ge::DT_FLOAT ✓, not FP8 ✓. So FP16 is NOT excluded from any route.
- FP32 (ge::DT_FLOAT): isBn2 = false, bn2S2RouteLimit = false → always BN2GS1S2 (line 1647 or the DoSparse overwrite). FP32 恒排除 BN2/BN2S2 — matches user's "FP32 同 shape 过".
- FP8 (E5M2/E4M3FN/HIFLOAT8): also excluded from BN2/BN2S2/BN2S2 route (both conditions check !(queryType == FP8...)).

Runtime/shape-dependent gates (SetSplitAxis, common_regbase.cpp:1583-1639):
- isBn2 = s1<=128 && s2<=128 (BN2_MAX_S=128) && n1==n2 && d<=512 (BN2_MAX_D=512) && dtype-gate && tailZeroCount==0
- isBn2MultiBlk = bnSparseLimit && (s1>128 || s2>128) && s1<=640 && s2<=640 (BN2_MULTIBLK_SEQ=640) && n1==n2 && d<=512 && dtype-gate && d==d1 && !hasRope; where bnSparseLimit = bnLimit (bn1>=256 || (bn1>=128 && s1%128==0 && s2%128==0)) && layoutType != TND && sparseMode not PREFIX/PREFIX_COMPRESS
- bn2S2RouteLimit = !hasRope && d<=512 && (layoutType==TND || (isAllSame && !isDeterministic) || bn2S2NotTndLimit) && (keepProb>=1 || (d<=128 && keepProb<1)) && n1==n2 && dtype-gate; where bn2S2NotTndLimit = s1<s2 && s2<=1024 && s2-s1>=128 && d<=128 && !isSparse && !isDeterministic

Then the final selection:
1. if !isBn2 && bn2S2RouteLimit → BN2S2 (line 1641-1643)
2. else if isBn2 → BN2 (line 1644-1645)
3. else → BN2GS1S2 (line 1646-1647)

Post-override (DoSparse, normal_regbase.cpp:660-732):
- If splitAxis==BN2S2 && !DETER_OLD && DoBn2s2Sparse() && blockOuter >= aicNum → BN2S2 survives (early return line 665-666)
- Otherwise, if splitAxis==BN2 && isBn2MultiBlk → DoBn2MultiBlkSparse; if invalid col/row → BN2GS1S2 (line 680-685)
- Otherwise line 691: splitAxis = isBn2 ? BN2 : BN2GS1S2. This can overwrite BN2S2 → BN2GS1S2 (since BN2S2 implies isBn2==false). Also if TND S1S2-all-same, layoutType might be converted to BS2N2GD (line 669-672), and splitAxis goes BN2GS1S2 with BS2N2GD layout — meaning the "BN2S2-like" optimization is handled via layoutType, not via splitAxis!

Wait — this is important. Line 668-672 comment: "TND S1 S2全等场景下if分支尝试走BN2S2分核优化,如果判断不能走则恢复layoutType赋值" — SupportTrans2BS2N2GD → layoutType = INPUT_FORMAT_BS2N2GD. Then line 691 sets splitAxis to BN2GS1S2. So the BN2S2 optimization for TND S1==S2 all-same is actually executed as BN2GS1S2 + BS2N2GD layout.

Hmm, but wait — when BN2S2 was set by SetSplitAxis (TND case), DoSparse at line 665 checks DoBn2s2Sparse() — for TND that calls GetBlockInfoOfBNS4TND. If that returns true and blockOuter >= aicNum, we early-return with splitAxis==BN2S2 preserved. Otherwise falls through → possibly BS2N2GD conversion + splitAxis=BN2GS1S2.

OK so this nuance is important for the answer. Also note in GetTilingKey (normal_regbase.cpp:1443, 1460-1461) the final splitAxis is packed into tiling key bit 3-1 with value 0/1/5 (0=BN2GS1S2, 1=BN2, 5=BN2S2).

Also the varlen deterministic paths (tiling_varlen_regbase.cpp:126, 190, 389, 760) force BN2GS1S2 for TND deterministic cases when SupportTNDBns2 fails etc. Those are for DETER_CAUSAL/DETER_DENSE/DETER_BAND.

Now — user asked: "当前 case 实际是哪条" — do I have concrete tiling data? The UO query modes tiling_key/tiling_data — the tiling_key mode returned schema only (no actual per-case values). There's no actual tiling product data in the KB (no tiling_data records with specific values). So unless there's a real tiling key hex, I cannot confirm the actual path for the specific case. The answer must be PARTIAL with the branch table.

Let me quickly verify GetBlockInfoOfBNS4TND to be thorough about BN2S2 survival conditions, and check SplitAxisEnum definition. Also check whether there's a tiling_data mode with actual content. Let me also check the varlen regbase file quickly — but the user's question focuses on normal_regbase.cpp + common_regbase.cpp. I'll mention varlen briefly.

Let me do a couple more targeted queries:
1. SplitAxisEnum definition
2. tiling_data mode (see if there's actual per-case data)
3. GetBlockInfoOfBNS4TND

Then write the answer.
常量数值已确认（BN2_MAX_S=128、BN2_MAX_D=512、BN2_MULTIBLK_SEQ=640、BN2S2_MAX_S=1024、BN2S2_WRITE_UB_D=128、ALIGN128=128，common_regbase.h:109-116）。最后确认 SplitAxisEnum 定义、GetBlockInfoOfBNS4TND 返回值语义、以及 tiling_data 里是否有具体 case 数据
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern SplitAxisEnum]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GetBlockInfoOfBNS4TND]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode tiling_data]
+ Thought: 38.6s
FP16 输入下 splitAxis 的完整选路链（flash_attention_score_grad / arch35）
先给一句话结论：FP16 本身不会把任何一条路排除掉（FP16 ≠ DT_FLOAT、≠ FP8，三条路的 dtype 闸门全部放行）；真正决定落到 BN2 / BN2S2 / BN2GS1S2 的全是运行时 shape / attrs / sparse 参数，静态源码无法对「当前 case」定死。当前 case 实际路径 = PARTIAL（UO KB 的 tiling_data 只有 schema，没有具体 case 的 tiling 产物值，无法从库内确认；需要拿实际 shape/attrs 套下面的分支表，或者看运行日志里 GetTilingKey 打印的 splitAxis[%d]）。
1. splitAxis 在 tiling key 里的位置（打包/消费端）
- tiling key 布局：op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h:52-56 — bit 3-1 = SplitAxis：0=BN2GS1S2, 1=BN2, 5=BN2S2；:57-64 — bit 6-4 = InputDType（3=FLOAT16_PRECISION）；:98-101 — bit 46 = IsBn2MultiBlk。
- host 打包：op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1443 读 fBaseParams.splitAxis，:1460-1461 GET_TPL_TILING_KEY(0, splitAxis, inputDtype, …) 写入 bit 3-1。
- 调用顺序（normal 流程）：DoOpTiling at flash_attention_score_grad_tiling_normal_regbase.cpp:430 → :432 SetSplitAxis(...) → :433 DoSplit() → :434 DoSparse()。所以 DoSparse 是 splitAxis 的“最后一改”，GetTilingKey 打包的是 DoSparse 之后的值。
2. 选路主函数 SetSplitAxis（common_regbase.cpp:1581-1649）
2.1 isBn2（决定 BN2 路）— common_regbase.cpp:1583-1588
isBn2 = (s1 <= BN2_MAX_S && s2 <= BN2_MAX_S)   // BN2_MAX_S = 128（common_regbase.h:110）
      && (n1 == n2)
      && (d  <= BN2_MAX_D)                       // BN2_MAX_D = 512（common_regbase.h:115）
      && (queryType != ge::DT_FLOAT)             // 类型闸门①
      && !(FP8_E5M2/E4M3FN/HIFLOAT8)             // 类型闸门②
      && (tailZeroCount == 0)
随后 :1607：isBn2 = isBn2MultiBlk ? true : isBn2；:1608-1615：若 isBn2 && !isBn2MultiBlk 且 (TND && d > ALIGN128) || dropMaskOuter → 强制 isBn2 = false。
2.2 isBn2MultiBlk（BN2 多基本块子集）— common_regbase.cpp:1590-1606
- bnLimit（:1590-1591）：b*n1 >= BN2_MULTIBLK_BN_256(=256)，或 b*n1 >= BN2_MULTIBLK_BN_128(=128) && s1%128==0 && s2%128==0。
- bnSparseLimit（:1592-1595）：bnLimit && layoutType != TND && sparseMode != PREFIX/PREFIX_COMPRESS。
- isBn2MultiBlk（:1596-1606）：bnSparseLimit && (s1>128 || s2>128) && s1<=BN2_MULTIBLK_SEQ(=640) && s2<=640 && n1==n2 && d<=512 && queryType!=DT_FLOAT && d==d1 && !FP8 && !hasRope（常量 common_regbase.h:112-114）。
- :1616-1623：dropMaskOuter 时把 isBn2MultiBlk/isBn2 清零。
2.3 bn2S2RouteLimit（决定 BN2S2 路）— common_regbase.cpp:1625-1639
- bn2S2NotTndLimit（:1625-1630）：s1 < s2 && s2 <= BN2S2_MAX_S(=1024) && s2 - s1 >= BN2_MAX_S(=128) && d <= BN2S2_WRITE_UB_D(=128) && !isSparse && !isDeterministic（常量 common_regbase.h:111、116）。
- bn2S2RouteLimit（:1631-1639）：!hasRope && d <= BN2_MAX_D && (layoutType==TND || (isAllSame && !isDeterministic) || bn2S2NotTndLimit) && (keepProb >= 1 || (d <= 128 && keepProb < 1)) && n1==n2 && queryType != DT_FLOAT && !FP8。
2.4 三选一路由 — common_regbase.cpp:1641-1648
if (!isBn2 && bn2S2RouteLimit)        → splitAxis = BN2S2     (:1641-1643)
else if (isBn2)                       → splitAxis = BN2       (:1644-1645)
else                                  → splitAxis = BN2GS1S2  (:1646-1647)
3. DoSparse 的二次改写（normal_regbase.cpp:660-732）—— BN2S2 的“幸存窗口”
- :662-664 算 sparseType / deterSparseType / CalcleDeterParam。
- :665-666：if (DoBn2s2Sparse() && blockOuter >= aicNum) return GRAPH_SUCCESS; —— BN2S2 唯一保留路径。
- DoBn2s2Sparse（normal_regbase.cpp:511-547）：splitAxis != BN2S2 || deterSparseType == DETER_OLD 直接 false；TND/稀疏 → GetBlockInfoOfBNS4TND（normal_regbase.h:95；varlen 实现 varlen_regbase.cpp:1216-1245）；非 TND → 按 b*n2*g*s2Outer 切块并返回 true（:520-544）。
- :669-672：SupportTrans2BS2N2GD（common_regbase.cpp:1669-1672：sparseMode<=PREFIX_COMPRESS && isAllSame && layoutType==TND）时 layoutType = INPUT_FORMAT_BS2N2GD —— 注意这只是换 layout，不换 splitAxis。
- :674-690：splitAxis==BN2 && isBn2MultiBlk 时走 DoBn2MultiBlkSparse；若 isInvalidCol || isInvalidRow → 强制 isBn2=false, isBn2MultiBlk=false, splitAxis=BN2GS1S2（:681-685）。
- :691：无条件兜底改写 splitAxis = isBn2 ? BN2 : BN2GS1S2。也就是说：只要第 665 行没有提前 return，SetSplitAxis 里选的 BN2S2 会在这里被改回 BN2GS1S2（因为 BN2S2 分支要求 !isBn2）；BN2 只有在 isBn2 为真时才保留。
结论：BN2S2 是“窄窗口”路由 —— 必须同时满足 SetSplitAxis:1641 命中 + DoSparse:665 的 DoBn2s2Sparse() 成功 + blockOuter >= aicNum，否则最终都是 BN2 / BN2GS1S2。
4. 类型层面已固定的部分 vs 运行时依赖的部分
已固定（编译期/类型层面，无需 shape 即可判定）：
- FP32（DT_FLOAT）恒走 BN2GS1S2：isBn2（:1586）、isBn2MultiBlk（:1601）、bn2S2RouteLimit（:1637）三处都含 queryType != ge::DT_FLOAT，FP32 全不满足 → SetSplitAxis 走 else（:1647），DoSparse:691 也是 BN2GS1S2。这正好解释了「FP32 同 shape 过」。
- FP8（E5M2/E4M3FN/HIFLOAT8）同样恒排除 BN2/BN2S2/BN2S2 路由（:1587、:1603-1605、:1638-1639）。
- FP16（DT_FLOAT16）三条路都不被 dtype 排除：它既不是 DT_FLOAT 也不是 FP8。DetermineMode（common_regbase.cpp:1651-1667，注释「当前fp16都走高精度」）把 FP16 归为 DtypeEnum::FLOAT16_PRECISION（:1664-1666），这只是 tiling key 的 InputDType 值（bit 6-4=3），不参与选路。
运行时 shape/attrs 决定（静态源码无法确定具体 case）：
- shape：s1, s2, d, n1, n2, b, tailZeroCount（TND 时还有 d1==d）。
- attrs/输入：layoutType（TND/BSH/…）、isAllSame、isSparse（由 SetSparseParams 从 sparseMode/attnMask 推出）、sparseMode、isDeterministic（context_->GetDeterministic()）、hasRope、keepProb、dropMaskOuter。
- 核数：aicNum、由 DoSparse 算出的 blockOuter（BN2S2 幸存要 blockOuter >= aicNum）。
5. 补充：TND 确定性（varlen）路径的强制改写
若走 varlen regbase（TND + deterministic），CalcleTND*DeterParam 会在 DoSparse 之后把 splitAxis 再改掉（全部指向 BN2GS1S2 或保留 BN2S2）：
- DETER_CAUSAL → 无条件 BN2GS1S2（varlen_regbase.cpp:126）。
- DETER_DENSE：!SupportTNDBns2(deterPrefixData, deterMaxRound) → BN2GS1S2（varlen_regbase.cpp:189-192）。
- DETER_BAND：!SupportTNDBns2(…, prefix1.back()) → BN2GS1S2（varlen_regbase.cpp:388-391）。
- 同步轮数不足 deterMaxRound < allNeedSyncLoopNums*2 → BN2GS1S2（varlen_regbase.cpp:759-760）。
6. FP16 下的「条件 → 路径」分支表
#	条件（FP16 已满足 dtype 闸门）
A	!isBn2 && bn2S2RouteLimit 且 DoSparse:665 的 DoBn2s2Sparse() 成功、blockOuter >= aicNum
B	isBn2MultiBlk（b*n1>=256 或 >=128 且 s1/s2%128==0；非 TND；非 PREFIX/PREFIX_COMPRESS；s1/s2 ∈ (128, 640]；n1==n2；d<=512；d==d1；!hasRope）
C	isBn2（s1<=128 && s2<=128 && n1==n2 && d<=512 && tailZeroCount==0，非 TND>128/dropMaskOuter 排除）
D	B/C 中 `isInvalidCol
E	其余（isBn2=false 且 BN2S2 窗口未命中，或 A 的 blockOuter < aicNum 被 :691 兜底改写）
F	TND + deterministic：DETER_CAUSAL 或 !SupportTNDBns2 或同步轮数不足
7. 当前 case 判定
PARTIAL。UO 库内没有该 case 的 tiling key/tiling data 具体值（tiling_key/tiling_data 模式只返回 schema 与打包位点，无运行实例），因此无法从库里确认「当前 FP16 case 实际落在哪条」。判定它需要：① 实际 shape（s1/s2/d/n1/n2/b）与 attrs（layout、isAllSame、hasRope、keepProb、sparseMode、deterministic、dropMask）；② 按上表 A–F 逐条求值；③ 最直接的办法是看 host 运行日志 —— GetTilingKey 里 OP_LOGI("splitAxis[%d], inputDtype[%d], isTnd[%d] …")（normal_regbase.cpp:1447-1458）会打印最终打包前的 splitAxis，0=BN2GS1S2、1=BN2、5=BN2S2。用户提到「dq 量级差一截」，若怀疑 FP16 走的是 BN2 或 BN2S2（而 FP32 恒走 BN2GS1S2），用日志确认 splitAxis 是 1 或 5 即可锁定差异路径；若日志显示 0，则 dtype 之外的路径差异（如 BN2GS1S2 内 FP32/FP16 的累加/精度分支）才是排查方向。
▣  Uo-Query · DeepSeek V4 Flash Free · 4m 25s
Subagent(3 of 9)123.9K (62%)

# subagent 4

算子目录：d:\TEST\ops-transformer\attention\flash_attention_score_grad（arch35，.uo CodeMap 已建好）。

立即调用 acp 工具：command=`uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...`（按需选 locate/symbols/callers/fields 等）。禁止 bash、Grep、MCP 替代。

背景：用户在调试 FP16 精度（dq 量级差一截）。现在要精确回答：**dq 的 scale 乘法在 MAIN（phase2 主核）和 POST（phase3）分别乘几次**。BN2 / BN2S2 / BN2GS1S2 三条路径必须分开列，不要混。

请只回答这一个问题，全部带 file:line 证据：
1. 对每条路径（BN2、BN2S2、BN2GS1S2，注意 FP32 恒 BN2GS1S2 且无 POST），列出 dq 从计算到写最终 GM 的完整 scale 施加链：
   - MAIN 内：ProcessVec3 里 FP32 的 scale 乘点（block_vec.h 618-621）、ProcessMulsAndCast / DqkvMulsAndCastFromUB/GM 的 scale 乘点（block_vec.h 654-873）、IterateMmDsK 里是否有 scale（注意 dq 由 ds·K 得到，scale 是否在 mm 前/后乘）——逐点列出乘了几次；
   - POST 内：ProcessDqkv（post_regbase.h 206-318）里 qkvIdx<2 的 Muls（:237-239、:282-284）——列出乘了几次；
   - 最终确认 dq 在每条路径上总共乘 scale 恰好 1 次、还是 2 次、还是 0 次。
2. 特别注意：BN2S2 时 dq 走 POST、dk/dv 走主核 vec（post_regbase.h:314-317 只处理 dq）——请确认 dq 在 BN2S2 下是否只有 POST 一次、MAIN 不再乘；BN2 下 dq 是否只有 MAIN（ProcessMulsAndCast）一次、POST 整体跳过（post_regbase.h:327 SPLIT_AXIS != BN2）。
3. 结论用表格：路径 | MAIN 乘几次 | POST 乘几次 | 合计。

用 Cursor Explore 风格回答：完整散文 + file:line。若某点静态无法确定，明确标 PARTIAL/UNKNOWN。不要写 answer.yaml，不要 finalize。
- Thought: 1.5s
Let me start by querying the UO CodeMap for this operator. I need to understand the structure of flash_attention_score_grad operator.

The task asks me to analyze the dq scale multiplication in MAIN (phase2) and POST (phase3) for three paths: BN2, BN2S2, BN2GS1S2.

Let me first run the uo-query tool to locate the relevant files and understand the CodeMap.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode symbols --pattern ProcessVec3]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern block_vec.h]
- Thought: 2.4s
The CodeMap is fresh (uo_freshness.stale=false). The file is op_kernel/arch35/flash_attention_score_grad_block_vec.h. The task mentions block_vec.h 618-621, block_vec.h 654-873, and post_regbase.h 206-318 with specific line references. Let me locate those files and read the relevant windows.

Note: the machine-scope operator sources are outside .ascendc-pilot, but I can read them with windowed Read (never whole-file dumps). The task explicitly gives me line references, so I should read those windows.

Let me find the exact file paths first. The kernel files are under op_kernel/arch35/. Let me locate post_regbase.h too.
CodeMap 是 fresh 的（digest 211a7ec…）。先定位 kernel 侧文件并读取任务点名的窗口
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern post_regbase.h]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_vec.h [offset=560, limit=340]
- Thought: 4.7s
Good. I have the block_vec.h windows. Now let me look at:
1. ProcessVec3 (around line 618-621 confirmed: FP32 input → Muls with scaleValue at lines 619-621)
2. ProcessMulsAndCast / DqkvMulsAndCastFromUB (lines 654-718): Muls at line 708 (MM_IDX != DV_IDX)
3. DqkvMulsAndCastFromGM (lines 720-890): Muls at line 829 (MM_IDX != DV_IDX)
4. IterateMmDsK — need to find where dq is computed from ds·K and where scale might be applied. Need to look at that function.
5. post_regbase.h ProcessDqkv — the task says post_regbase.h 206-318 with Muls at 237-239 and 282-284. But the located file is flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h. There may also be other post files. Let me locate the post file for BN2S2 (non-G1S1?). Actually, the task refers to "post_regbase.h" generically. Let me find all files matching post in the op_kernel dir.

Let me read more of block_vec.h around IterateMmDsK, and also look for post files. Let me also query the CodeMap for ProcessDqkv and IterateMmDsK.
block_vec.h 的关键乘点已确认（618-621、707-709、828-830）。现在定位 IterateMmDsK 和 post 文件，以及 ProcessDqkv
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern IterateMmDsK]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ProcessDqkv]
- Thought: 50.8s
Now I have the ProcessDqkv location in flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h at line 207. The Muls at line 237-239 (qkvIdx < 2). Let me now read the full ProcessDqkv (lines 206-318) and Process (lines 318-360) from post_regbase.h.

Also I need to read IterateMmDsK in block_cube.h (lines 846-~1000) to see whether there's a scale in the mm for dq (ds·K). The mm dq = ds × K. Whether scale is applied before/after mm.

Also need to understand:
- How ProcessVec3 is reached (which paths): BN2 non-FP32? Actually ProcessVec3 is for BN2GS1S2 last vec and BN2S2? Need to check where ProcessVec3 is called from. The comment at 618: "input type fp32, no post, mov muls here" — IS_FP32_INPUT → Muls at 620. That means for FP32 input there's no post, and dq muls happens in ProcessVec3. But wait, ProcessVec3 computes dq? Actually ProcessVec3 computes mm1ResTensor = ds (after BroadcastSubMul at 582-603), then at 618-621 if FP32 input, Muls by scaleValue, then CastTransdataDeconflict to vecOutBuffer, then CopyUBToL1Vec3. So ProcessVec3 is the ds processing; the result vecOutBuffer goes to L1 (dSL1Buffer?) for IterateMmDsK to compute dq = ds·K. Hmm, wait — the comment says "input type fp32, no post, mov muls here" — this Muls applies to mm1ResTensor which is ds (dS). But then dq = ds·K mm doesn't include scale. And for non-FP32, ds is written to L1 without scale, then dq is computed in IterateMmDsK (mm with K), and then scale is applied in DqkvMulsAndCast (MAIN vec) or POST.

Wait, but where does the FP32 input path apply dq scale? ProcessVec3 Muls at 620 applies to mm1ResTensor = ds. Then CastTransdataDeconflict<INPUT_TYPE=FP32? ...> writes to vecOutBuffer = dSOutQue.AllocTensor. CopyUBToL1Vec3 copies to dstBuffer (dSL1Buffer). Then IterateMmDsK computes dq = ds·K with no scale. Then... where is the scale applied for FP32?

Hmm, wait. Let me re-check: IS_FP32_INPUT — is that FP32 input (input_type == fp32) or CALC_TYPE FP32? The comment says "input type fp32, no post, mov muls here". So when input is FP32, there's no POST phase, and scale muls for dq are done here in ProcessVec3 on ds. But wait — dq = ds·K; multiplying ds by scale before the mm is equivalent to multiplying dq by scale after the mm (scale is scalar). So the FP32 path applies scale once on ds in ProcessVec3, and dq gets it through the mm. Then DqkvMulsAndCast would NOT apply scale again... but hold on, DqkvMulsAndCastFromUB/GM has if constexpr (MM_IDX != DV_IDX) { Muls(...) } unconditionally! That would double-apply for FP32...

Hmm wait, but is IS_FP32_INPUT and the DqkvMulsAndCast used together? Let me think about which paths use which functions. There might be a template condition: for FP32 input, maybe the dq/dk/dv muls+cast path skips Muls? No — the if constexpr (MM_IDX != DV_IDX) is unconditional. So I need to check whether FP32 input path uses DqkvMulsAndCast at all. Perhaps for FP32 input, dq is written from ProcessVec3 path... but ProcessVec3 writes ds to L1, then IterateMmDsK computes dq into dqWorkSpaceGm (IS_DQ_WRITE_UB=false → GM workspace). Then ProcessMulsAndCast is called for DQ with IS_WRITE_UB=false → DqkvMulsAndCastFromGM which applies Muls again.

Hmm, that would be a double scale for FP32. But maybe IS_FP32_INPUT templates are distinct: maybe for FP32 input, IterateMmDsK writes dq directly to GM and then... Let me look at the kernel flow to understand.

Actually wait. Let me re-read the comment at line 618: "// input type fp32, no post, mov muls here". The Muls at 620 multiplies mm1ResTensor (ds) by scaleValue. But hold on — does ProcessVec3 handle the FP32 case only? What is VECTOR_BASEN? mm1ResTensor is dS result (S1×S2). The result is ds which then feeds IterateMmDsK (dq) and IterateMmDsQ (dk).

Hmm, but actually for dk, ds also multiplies Q. So if scale were applied to ds in ProcessVec3, both dq and dk would inherit the scale through their mm products. And for dv, dv = p·dy — p is computed... wait no, dv doesn't need scale? Actually in flash attention backward, dq = scale·ds·K? Hmm, actually the standard FA backward: dS = P ⊙ (dP - D), dP = dV·Kᵀ... Let me not get into the math; the code is authoritative.

Actually the math in FA2 backward: 
- dV = Pᵀ · dP
- dS = P ⊙ (dP·Kᵀ − rowsum) = P ⊙ (dV·Kᵀ... no)
- dQ = dS · K
- dK = dSᵀ · Q
- With scale: dS = scale · P ⊙ (dP·Kᵀ − D)? Actually in FA2: dS = P ⊙ (dP·Kᵀ − dS_rowmax) where the scale is applied to the mm result or inside. And dQ = dS·K, dK = dSᵀ·Q. The scale factor multiplies dQ, dK (but not dV). So the code applies scale to dq and dk but NOT dv (MM_IDX != DV_IDX). Consistent.

So the question: on each path, how many times is scale applied to dq?

Paths:
1. BN2 (split BN2, non-FP32? and FP32): MAIN-only (no POST). In MAIN: dq computed by IterateMmDsK (ds·K, no scale inside? need to check), then ProcessMulsAndCast → DqkvMulsAndCastFromGM (line 829 Muls) OR FromUB (line 708). So dq scale applied once in MAIN via DqkvMulsAndCast. But wait — is there also a scale applied inside IterateMmDsK? Need to read the full function.

   Also for FP32 input + BN2: ProcessVec3 Muls at 620 applies scale to ds! Then DqkvMulsAndCastFromGM would apply scale again → 2 times. Unless FP32+BN2 uses a different flow. Need to check: is ProcessVec3 used for BN2? ProcessVec3 is called where? Let me check the kernel files. Actually there might be different ProcessVec functions for different split modes. Need to look at kernel.h and kernel_deter.h.

   Hmm, wait. The task says "注意 FP32 恒 BN2GS1S2 且无 POST" — FP32 is always BN2GS1S2 (G1S1) with no POST. So for FP32, path is BN2GS1S2 with ProcessVec3 handling the scale (line 620) and no POST. And presumably for FP32, DqkvMulsAndCast is NOT called (since "no post, mov muls here"). Hmm, but that doesn't match "no post" — the POST phase is a separate kernel/phase. Let me check whether FP32+BN2GS1S2 uses DqkvMulsAndCast.

   Actually wait — I need to be careful. Let me re-read: "注意 FP32 恒 BN2GS1S2 且无 POST" — FP32 always BN2GS1S2 without POST. So for FP32 the ProcessVec3 Muls at 620 is THE scale for dq (applied to ds). Then dq computed by mm carries the scale. Then if DqkvMulsAndCastFromGM were also called, dq would be scaled twice. So the question is whether the FP32 template skips the Muls in DqkvMulsAndCast. From the code at 707-709 and 828-830, if constexpr (MM_IDX != DV_IDX) — no FP32 condition. So either FP32 flow doesn't call ProcessMulsAndCast for dq (writes dq directly from cube workspace without muls), or there's a double-scale. I must check the kernel flow for FP32.

2. BN2S2: dq goes to POST (ProcessDqkv). MAIN: dq computed by IterateMmDsK into dqWorkSpaceGm (IS_DQ_WRITE_UB=false?), then POST phase: ProcessDqkv applies Muls (line 237-239) for qkvIdx<2, then Cast, then DataCopy to dqGm. So dq scale = POST once. MAIN must NOT apply scale for dq in BN2S2. But the question says "BN2S2 时 dq 走 POST、dk/dv 走主核 vec（post_regbase.h:314-317 只处理 dq）". So in ProcessDqkv, qkvIdx loop 0..2: qkvIdx 0 = dq, 1 = dk, 2 = dv? Wait but the task says dk/dv go through main-core vec, and post only handles dq. Let me read ProcessDqkv fully to see which qkvIdx are processed. The task says post_regbase.h:314-317 only handles dq. Need to read lines 240-330.

   For BN2S2 MAIN: does the MAIN call ProcessMulsAndCast for DQ? The task claims MAIN doesn't multiply for BN2S2. Need to verify from kernel flow. Maybe for BN2S2, IS_DQ_WRITE_UB is false and dq goes to workspace GM, and MAIN does NOT call ProcessMulsAndCast<DQ>; only DK and DV get ProcessMulsAndCast. Need to check kernel.h flow.

3. BN2GS1S2: MAIN only? The task says BN2GS1S2 (with POST?) Hmm: "BN2GS1S2 三条路径" — three paths: BN2, BN2S2, BN2GS1S2. And "注意 FP32 恒 BN2GS1S2 且无 POST". So BN2GS1S2 has POST for non-FP32? Actually the post file is named "s1s2_bn2gs1s2_post_regbase.h" — for S1S2 and BN2GS1S2. The ProcessDqkv handles qkvIdx 0..2 for dq/dk/dv. For BN2GS1S2 (non-FP32), do dq, dk, dv all go to POST? Or dq only? Need to read Process (line 322) and the surrounding code.

So I need to read:
1. block_cube.h IterateMmDsK full (846-~1010) — check for scale inside mm.
2. post_regbase.h ProcessDqkv (206-330) + Process (322-380) — check qkvIdx conditions.
3. kernel.h flow — which path calls ProcessMulsAndCast for DQ, which calls ProcessVec3, and where POST is invoked; check SPLIT_AXIS conditions (BN2 vs BN2S2 vs BN2GS1S2).
4. Check IS_FP32_INPUT handling.

Let me read these files.
ProcessDqkv 定位在 flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h。现在读 post 文件的完整 ProcessDqkv/Process，以及 block_cube.h 的 IterateMmDsK 全文
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h [limit=240, offset=140]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_cube.h [limit=200, offset=840]
- Thought: 28.5s
Key findings so far:

1. IterateMmDsK (block_cube.h:846-946): pure mm (ds·K) + fixpout. No scale/Muls inside. The mm itself has no scale — MMParam has no scale; Muls is not called here. IterateMmDsKFixpout handles L0C→workspace/GM. Need to confirm IterateMmDsKFixpout has no Muls either — let me check that function.

2. ProcessDqkv (post_regbase.h:207-319):
   - Loop qkvIdx 0..2. qkvIdx 0 = dq (loop/inputTotalSize/qPostTailNum from qPostBlockFactor initially), 1 = dk, 2 = dv.
   - Ping: if (qkvIdx < 2) Muls(...scaleValue, pingSize) at 237-239.
   - Pong: if (qkvIdx < 2) Muls(...) at 282-284.
   - So dq (qkvIdx==0) gets Muls once per element in POST (either in ping or pong branch, but not both for the same element — ping/pong split the range). So each dq element: exactly 1 Muls in POST.
   - Line 314-317: // bn2s2 dk dv no need to do muls and cast; if constexpr (SPLIT_AXIS == 5) break; — so for SPLIT_AXIS==5 (BN2S2), after qkvIdx==0 (dq), break → only dq is processed in POST. dk/dv handled on main core.
   - Line 327: if constexpr (SPLIT_AXIS != BN2 && !IsSameType<T1, float>::value) { ProcessDqkv(); } — POST runs ProcessDqkv only when SPLIT_AXIS != BN2 (i.e., BN2S2 or BN2GS1S2) AND input type is NOT float (FP32). So:
     - BN2: POST skips ProcessDqkv entirely. ✓ (matches task claim post_regbase.h:327)
     - FP32 (T1==float): POST skips ProcessDqkv entirely. ✓ (matches "FP32 恒 BN2GS1S2 且无 POST")

3. Need to check:
   - SPLIT_AXIS values: BN2, BN2S2, BN2GS1S2 → what are the enum values? SPLIT_AXIS == 5 for BN2S2 per comment. Let me find the enum definition (likely in flash_attention_score_grad_common.h or the template args). Also need SPLIT_AXIS for BN2 and BN2GS1S2.
   - Which templates instantiate: FP32 input → always BN2GS1S2 (per the task statement; verify from kernel.h where ProcessVec3 called).
   - The MAIN flow for BN2S2: does it call ProcessMulsAndCast for DQ? Task says dk/dv go through main-core vec, dq only POST. Need to confirm: for BN2S2, IS_DQ_WRITE_UB=false and dq written to dqWorkSpaceGm without Muls in MAIN; then POST handles dq. But ProcessDqkv reads from dqkvWorkspaceqkvIdx — the workspace. So MAIN's IterateMmDsK writes dq to workspace GM; no scale. Then POST reads workspace, applies scale, casts, writes GM. ✓ So MAIN scale count for dq in BN2S2 = 0.
   - But wait — is there any other scale applied in MAIN for BN2S2 dq? Need to check kernel.h flow: for BN2S2, dq mm → dqWorkSpaceGm (via IterateMmDsKFixpout, no muls); is ProcessMulsAndCast<DQ> called? Let me read kernel.h ProcessBn2s2 (or similar) to confirm.
   - For BN2GS1S2 (non-FP32): dq → POST too? Line 315: break only for SPLIT_AXIS==5. For BN2GS1S2 (SPLIT_AXIS presumably == BN2GS1S2 ≠ 5), the loop continues for qkvIdx 1, 2 — so dk and dv are ALSO processed in POST with Muls (qkvIdx<2 → dk also muls; dv no muls). So for BN2GS1S2, dq, dk both get scale in POST; dv no scale. And MAIN doesn't apply scale for dq in BN2GS1S2 (dq goes to workspace without muls). Need to confirm from kernel flow.
   - For BN2 (non-FP32): MAIN ProcessMulsAndCast<DQ> → DqkvMulsAndCastFromGM (or FromUB if IS_DQ_WRITE_UB) applies Muls once (line 829/708). POST skipped. So BN2: 1× in MAIN, 0× in POST.
   - For FP32 (BN2GS1S2 template, no POST): ProcessVec3 line 619-621 Muls on ds. Then dq = ds·K mm inherits scale. Then does MAIN call ProcessMulsAndCast for dq? If yes → double scale! Need to check. Hmm. Let me look at kernel.h for the FP32 flow. Actually wait — ProcessVec3 is used in BN2GS1S2 last-vec (ProcessBn2gs1s2LastVec in kernel.h:42). For FP32 input, the comment says "input type fp32, no post, mov muls here". But is this the only scale for FP32? Let me check the flow around ProcessBn2gs1s2LastVec and the normal BN2GS1S2 process.

   Actually wait — for FP32, does the main flow also call ProcessMulsAndCast<DQ>? If yes, dq would be scaled twice (once via ds in ProcessVec3, once in DqkvMulsAndCast). That would be a bug... unless the FP32 template avoids calling ProcessMulsAndCast for DQ. OR — the ProcessVec3 Muls at 620 might only apply for non-FP32 (no — it's if constexpr (IS_FP32_INPUT)).

   Hmm, wait. Actually, I need to reconsider. What does ProcessVec3 compute? mm1ResTensor after BroadcastSubMul is dS. For FP32 input: Muls(mm1ResTensor, scale) → dS_scaled. Then CastTransdataDeconflict<INPUT_TYPE(FP32), CALC_TYPE> → vecOutBuffer, CopyUBToL1Vec3(dstBuffer=dSL1Buffer). Then IterateMmDsK: dq = dS_scaled · K. Then IterateMmDsKFixpout writes dq to outTensor (dqWorkSpaceGm or UB). Then does the FP32 flow call ProcessMulsAndCast? 

   Let me check what happens in the BN2GS1S2 flow for FP32. I need to read kernel.h. Also check the FP32 → template args mapping (IS_FP32_INPUT template arg, and which SPLIT_AXIS it uses).

   Actually, let me think about whether the FP32 ProcessVec3 Muls applies to dq or only to dk. The Muls at 620 is applied to mm1ResTensor = dS. dq = dS·K, dk = dSᵀ·Q. Both inherit the scale. dv = p·dy — no scale. So ProcessVec3's Muls replaces the per-dq/dk Muls in DqkvMulsAndCast for FP32. But then, if DqkvMulsAndCast is still called for FP32... double. So likely the FP32 flow either (a) doesn't call ProcessMulsAndCast at all, or (b) the DqkvMulsAndCast Muls would double-apply.

   Let me read the kernel.h to see the actual flow. Also kernel_deter.h (but deter may not be the debug path; the user is debugging FP16 precision — non-deter likely, but the task says to enumerate BN2/BN2S2/BN2GS1S2 paths).

Let me read kernel.h fully (or the relevant sections) and check:
- Where ProcessVec3 is called.
- Where ProcessMulsAndCast is called for DQ/DK/DV.
- SPLIT_AXIS values.
- IS_DQ_WRITE_UB settings.

Also check IterateMmDsKFixpout for any Muls.
ProcessDqkv 的 Muls 点（237-239、282-284）和 SPLIT_AXIS==5 的 break（314-317）、Process 的 FP32 跳过（327）已确认。现在读 kernel.h 主流程（看各路径如何调 ProcessVec3 / ProcessMulsAndCast / POST）和 IterateMmDsKFix
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h [limit=420, offset=1]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_cube.h [limit=120, offset=1040]
- Thought: 33.8s
Now I have a very clear picture forming. Let me note:

ComputeDqkvBn2 (kernel.h:313-...) — SPLIT_AXIS == BN2 path:
- ProcessVec3 (line 341) — for non-FP32, no Muls inside (the Muls at 620 is if constexpr (IS_FP32_INPUT)).
- IterateMmDsK → dq mm (line 370 or 382) — no scale inside (block_cube.h:846-946, pure Matmul + Fixpipe).
- ProcessMulsAndCast<DQ> (lines 379-380 / 391-392) → DqkvMulsAndCastFromUB (line 708 Muls) or FromGM (line 829 Muls) — 1× scale for dq.
- So BN2 non-FP32: dq scale = 1× in MAIN (ProcessMulsAndCast), 0× in POST (Process() skips ProcessDqkv for SPLIT_AXIS==BN2 at post_regbase.h:327).

ComputeDqkvBn2s2 (kernel.h:182-311) — SPLIT_AXIS == BN2S2 path:
- ProcessVec3 (line 208) — no FP32 Muls (non-FP32).
- IterateMmDsK → dq → dqWorkSpaceGm (line 234) — no scale, no ProcessMulsAndCast for DQ in this function!
- dk: IterateMmDsQ → dkWorkSpaceGm + ProcessMulsAndCast<DK> (line 250-251 or 264-265) — dk scale in MAIN.
- dv: IterateMmPDy + ProcessMulsAndCast<DV> (line 285-286 or 302-303) — dv no scale (MM_IDX == DV_IDX skips Muls).
- So for BN2S2: MAIN does NOT scale dq. dq written unscaled to dqWorkSpaceGm → POST ProcessDqkv reads dqkvWorkspace0, applies Muls (line 237-239), casts, writes dqGm. POST handles ONLY dq because SPLIT_AXIS==5 → break at line 314-317.
- So BN2S2: dq scale = 0× MAIN, 1× POST. ✓ matches task hypothesis.

Wait — need to double check: for BN2S2, is there any call to ProcessMulsAndCast<DQ> anywhere else? In ComputeDqkvBn2s2 I see only DK and DV ProcessMulsAndCast. The DQ mm result goes to dqWorkSpaceGm (line 234). And POST handles it. But hold on — what about when IS_DQ_WRITE_UB is true for BN2S2? Let me check the base class IS_DQ_WRITE_UB setting. In ComputeDqkvBn2s2, IterateMmDsK<CALC_TYPE, BaseClass::IS_DQ_WRITE_UB>(this->dqWorkSpaceGm, ...) — uses dqWorkSpaceGm regardless. Hmm, if IS_DQ_WRITE_UB were true, outTensor type would be LocalTensor and dqWorkSpaceGm wouldn't compile... Actually DqkvResPos<T, IS_WRITE_UB>::PosType is probably conditional. Since it's passing dqWorkSpaceGm (a GM tensor), IS_DQ_WRITE_UB must be false for BN2S2. Let me confirm IS_DQ_WRITE_UB in kernel_base.h — it probably is SPLIT_AXIS == BN2 && ... or similar. Let me check.

ComputeDqkvBn2gs1s2 / ProcessBn2gs1s2LastVec (kernel.h:42-160) — SPLIT_AXIS == BN2GS1S2 path:
- ProcessVec3 (line 62 or 126) — for FP32 input: Muls at 620 on ds! For non-FP32: no Muls.
- IterateMmDsK → dq → dqWorkSpaceGm (line 75 or 147) — no scale, no ProcessMulsAndCast for DQ in this function either!
- dk: IterateMmDsQ → dkWorkSpaceGm (line 79/151) — no ProcessMulsAndCast here!
- dv: IterateMmPDy → dvWorkSpaceGm (line 100/137) — no ProcessMulsAndCast here!
- So in BN2GS1S2 flow, NO ProcessMulsAndCast at all — everything (dq, dk, dv) goes to workspace unscaled, and POST handles dq+dk+dv (qkvIdx 0..2, no break since SPLIT_AXIS != 5).
- POST ProcessDqkv: qkvIdx<2 → dq & dk get Muls (237-239, 282-284); dv (qkvIdx==2) no Muls.
- For FP32 (T1==float): Process() skips ProcessDqkv entirely (line 327) → so dq scale must come from ProcessVec3's Muls at 620 (on ds, inherited by dq through mm). And dk similarly inherits. dv no scale.
  - So FP32 BN2GS1S2: dq scale = 1× in MAIN via ProcessVec3 line 620 (applied to dS before mm, so dq = scaled_ds · K), 0× POST. ✓ matches "FP32 恒 BN2GS1S2 且无 POST".
  - BUT: need to verify that for FP32 input, the BN2GS1S2 flow doesn't ALSO call ProcessMulsAndCast for dq/dk. From ProcessBn2gs1s2LastVec, no ProcessMulsAndCast call exists at all — the dq/dk/dv mm results go to workspace GM without muls. But wait — if POST is skipped for FP32, who writes dq/dk/dv to final GM?? ProcessDqkv is what writes dqkv from workspace to dqGm! If FP32 skips ProcessDqkv, then the workspace results never reach GM via POST... unless for FP32 the Fixpipe in IterateMmDsK/IterateMmDsQ/IterateMmPDy writes directly to final GM (not workspace). 

  AH — this is the key. For FP32, IS_DQ_WRITE_UB / IS_DK_WRITE_UB / IS_DV_WRITE_UB — if false, outTensor is GlobalTensor and Fixpipe writes to... let me check IterateMmDsKFixpout's !IS_WRITE_UB branch (block_cube.h:1040-1056 shows the IS_WRITE_UB=true branch with dualDstCtl... wait no, 1040-1056 is part of IterateMmDsKFixpout? Let me re-read. Actually the segment at 1040-1056 shows Fixpipe with outTensor[gmNOffset] and DQ_FIXPIPE_CONFIG = {CO2Layout::ROW_MAJOR, IS_WRITE_UB}. This might be the IS_WRITE_UB=true branch. I need to see the full IterateMmDsKFixpout — both branches, and what outTensor addresses are used (workspace vs final GM).

  Also, in kernel.h ProcessBn2gs1s2LastVec, IterateMmDsK is called with this->dqWorkSpaceGm — a workspace GM. But for FP32, dq must end in dqGm. Hmm, but wait — the POST reads dqkvWorkspace[qkvIdx] and writes dqkv[qkvIdx] (dqGm). If FP32 skips POST, the workspace never gets consumed... 

  Unless! For FP32, the "workspace" IS the final dqGm? No — dqWorkSpaceGm is separate (workspace GM, CALC_TYPE float), and ProcessDqkv reads dqkvWorkspaceqkvIdx with float type and writes dqkvqkvIdx OUTDTYPE. For FP32, OUTDTYPE == float too. But the write path is skipped.

  Hmm wait, actually maybe for FP32, outTensor for IterateMmDsK is dqGm not dqWorkSpaceGm. Let me check the template instantiation: this->cubeBlock.template IterateMmDsK<CALC_TYPE, BaseClass::IS_DQ_WRITE_UB>(this->dqWorkSpaceGm, ...). It always passes dqWorkSpaceGm. Hmm.

  Wait — actually maybe the answer is: FP32 dq is written by Fixpipe DIRECTLY to dqWorkSpaceGm, then... who copies workspace to dqGm? Let me check the Process() of the main kernel (not POST) — maybe there's a workspace→GM copy after the loop for FP32. Or maybe FP32's dqWorkSpaceGm actually aliases dqGm. Let me look at the kernel main Process and the base class to see IS_DQ_WRITE_UB and how dqWorkSpaceGm is defined. Also need to check the IS_WRITE_UB=false branch of IterateMmDsKFixpout to see where Fixpipe writes (workspace or final GM).

Actually — hold on. Let me reconsider. In IterateMmDsKFixpout for IS_WRITE_UB=false, Fixpipe writes outTensor[offset + gmNOffset]. outTensor = dqWorkSpaceGm (workspace, float). For non-FP32, POST reads it. For FP32 (T1==float), Process() skips ProcessDqkv — so who writes FP32 dq to final GM?

Let me look for a workspace→GM copy in the kernel main Process. Or maybe FP32 with "no post" means the entire dqkv write is done by... hmm. Let me read the rest of kernel.h (lines 421-757) — the Process() function, which likely contains the final copy for FP32. Also kernel_base.h for IS_DQ_WRITE_UB etc.

Actually wait — I should reconsider: maybe for FP32, outTensor passed to IterateMmDsK is NOT dqWorkSpaceGm but dqGm. Look at line 75: this->cubeBlock.template IterateMmDsK<CALC_TYPE, BaseClass::IS_DQ_WRITE_UB>(this->dqWorkSpaceGm, dSL1Buffer, ...). It's dqWorkSpaceGm. Hmm, but this is inside if constexpr (IS_DROP) branch. Let me read the whole kernel file including base class. Let me also check DqkvResPos definition and IterateMmDsKFixpout full body.

Let me continue reading kernel.h 421-757 and find IterateMmDsKFixpout (block_cube.h ~990-1056), and kernel_base.h IS_DQ_WRITE_UB.
BN2S2 的 MAIN 流程已确认（dq mm 后不调 ProcessMulsAndCast）。还需要：kernel.h 剩余部分（Process 主流程 + FP32 的 GM 写出）、IterateMmDsKFixpout 全文、以及 IS_DQ_WRITE_UB 定义
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h [limit=340, offset=421]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_cube.h [limit=60, offset=985]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern IS_DQ_WRITE_UB]
- Thought: 22.9s
Now I have crucial information:

kernel_base.h:99: IS_DQ_WRITE_UB = (SPLIT_AXIS == BN2 && !IS_BN2_MULTIBLK && !IS_DQ_RES_EXCEED_UB) — so for BN2S2 and BN2GS1S2, IS_DQ_WRITE_UB is ALWAYS false. dq mm result always goes to dqWorkSpaceGm (GM workspace, float) for BN2S2 and BN2GS1S2.

kernel.h:575-581: Process() dispatch:
- SPLIT_AXIS == BN2GS1S2 → ComputeDqkvBn2gs1s2 (no ProcessMulsAndCast for DQ; dq → workspace GM)
- SPLIT_AXIS == BN2S2 → ComputeDqkvBn2s2 (no ProcessMulsAndCast for DQ; dq → workspace GM)
- else (BN2) → ComputeDqkvBn2 (ProcessMulsAndCast<DQ> → scale 1×)

So for BN2GS1S2 and BN2S2 (non-FP32): MAIN writes dq unscaled to workspace; POST (ProcessDqkv) applies scale once (qkvIdx<2) and writes final dqGm.

For FP32: The BN2GS1S2 flow — but with Process() skipping ProcessDqkv in POST (post_regbase.h:327 !IsSameType<T1, float>::value). Who writes FP32 dq from workspace to dqGm? 

Hmm wait — let me reconsider. Maybe for FP32, the workspace IS the final output. Let me check the post kernel launch — maybe the POST is a separate kernel with different template params. Actually the task states FP32 is always BN2GS1S2 without POST. So the whole post phase isn't launched for FP32. Then how does dq get to dqGm?

Let me look at the ProcessVec3 more carefully. Line 618-621:
// input type fp32, no post, mov muls here
if constexpr (IS_FP32_INPUT) {
    Muls(mm1ResTensor, mm1ResTensor, constInfo.scaleValue, VECTOR_BASEM * VECTOR_BASEN);
}
This Muls is applied to mm1ResTensor = dS in UB. Then CastTransdataDeconflict<INPUT_TYPE, CALC_TYPE, VECTOR_BASEN>(vecOutBuffer, mm1ResTensor, ...) → vecOutBuffer (dSOutQue, INPUT_TYPE). Then CopyUBToL1Vec3 → dSL1Buffer.

Then IterateMmDsK computes dq = dS_scaled · K → workspace GM (dqWorkSpaceGm). But who moves dqWorkSpaceGm → dqGm for FP32?

Wait — maybe for FP32, dqWorkSpaceGm is bound to the actual dqGm? No, kernel_base.h:121 declares GlobalTensor<float> dqWorkSpaceGm separately.

Hmm, let me check how dqWorkSpaceGm is initialized (SetGlobalBuffer) in kernel_base.h. Maybe for FP32 it points to workspace, and there's a workspace→GM copy after the loop. OR maybe for FP32 the post kernel IS launched but with T1=float... no, then ProcessDqkv would be skipped.

Wait — actually, maybe for FP32 the dq fixpout writes directly to dqGm, not dqWorkSpaceGm. In kernel.h, ProcessBn2gs1s2LastVec calls IterateMmDsK<CALC_TYPE, IS_DQ_WRITE_UB>(this->dqWorkSpaceGm, ...). Hmm, always dqWorkSpaceGm.

Hold on — but for FP32, is ProcessBn2gs1s2LastVec even used? Let me check: IS_PRELOAD_TWO_TIMES (kernel_base.h:112-114) = HEAD_DIM_ALIGN<=128 && !IS_DROP && SPLIT_AXIS==BN2GS1S2 && NO_DETER && !IS_FP32_INPUT. So FP32 is NOT preload-two-times. FP32 uses Process() → ComputeDqkvBn2gs1s2 → ProcessBn2gs1s2LastVec. So yes, FP32 dq → dqWorkSpaceGm via IterateMmDsK.

So for FP32, after the main loop, dqWorkSpaceGm holds unscaled... wait no — SCALED dq! Because dS was pre-scaled in ProcessVec3:620. dq = dS_scaled · K. Then who copies dqWorkSpaceGm to dqGm?

Maybe the answer: For FP32, dqWorkSpaceGm is actually initialized to point at dqGm! Let me check kernel_base.h where these GM tensors are bound. The post kernel might also be launched with workspace; but if no POST for FP32, then either (a) dqWorkSpaceGm aliases dqGm, or (b) there's a copy. Let me check kernel_base.h around the SetGlobalBuffer.

Also I should check the POST kernel launch — the S1S2/BN2GS1S2 post kernel. For FP32, is the post kernel launched at all? The task statement says "FP32 恒 BN2GS1S2 且无 POST" — so presumably not launched. And "no post, mov muls here" comment confirms: for FP32 the scale happens in ProcessVec3 (on dS) instead of in post.

Let me read kernel_base.h to see dqWorkSpaceGm initialization and the kernel main entry (who calls Process / who calls post). Also check where dqkvWorkspace is set in the post kernel (dqkvWorkspaceqkvIdx — in post_regbase.h).
关键确认：IS_DQ_WRITE_UB 仅 BN2 且非 multiblk 才为 true（kernel_base.h:99），BN2S2/BN2GS1S2 的 dq mm 结果一律进 workspace GM。现在读 kernel_base.h 的 GM 绑定与入口，确认 FP32 下 dqWorkSpaceGm 的最终去向
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=240, offset=1]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h [limit=140, offset=1]
- Thought: 4.0s
Now I need to understand:
1. How InitCVCommonGlobalBuffer sets dqWorkSpaceGm — whether for FP32 it points to dqGm or workspace.
2. Where the post kernel is launched (kernel launch file), and whether FP32 skips post.
3. Whether the post kernel exists for BN2 (probably not — BN2 has no POST; post file is named s1s2_bn2gs1s2).

Let me find InitCVCommonGlobalBuffer in kernel_base.h (probably around line 240-400) and the kernel entry file. Let me also look at DqkvResPos and ProcessVec3's IS_FP32_INPUT condition context — verify IS_FP32_INPUT is the same as INPUT_TYPE==float (kernel_base.h:79).

Also — importantly — I should verify SPLIT_AXIS enum values (BN2, BN2S2, BN2GS1S2) and confirm SPLIT_AXIS==5 is BN2S2. Let me check the enum in common header. And check the kernel entry (flash_attention_score_grad_kernel_entry or similar) to see when post kernel is launched (whether for BN2, BN2S2, BN2GS1S2, FP32).
现在查 InitCVCommonGlobalBuffer（workspace 绑定）、SPLIT_AXIS 枚举值、以及 kernel 入口/后处理启动条件
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern InitCVCommonGlobalBuffer]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern SplitAxis]
- Thought: 15.8s
Excellent! Key confirmations:

SPLIT_AXIS 枚举 (template_tiling_key.h:53-56):
- 0: BN2GS1S2
- 1: BN2
- 5: BN2S2

So post_regbase.h:315 SPLIT_AXIS == 5 == BN2S2 ✓

InitCVCommonGlobalBuffer (kernel_base.h:261-282):
- Non-FP32 (line 261): dqWorkSpaceGm → workspace (either BN2 fixed offsets or postTilingData offsets for BN2S2/BN2GS1S2).
- FP32 (line 278-282): "// input type fp32, dq dk dv write to output gm directly" — dqWorkSpaceGm → dq (final GM)! So for FP32, the mm fixpout writes DIRECTLY to final dqGm. This confirms FP32 has no POST and no separate copy: dq is written to dqGm directly from the mm (after ds was pre-scaled in ProcessVec3:620).

So the FP32 path: dS scaled once in ProcessVec3 (block_vec.h:620) → dq = dS_scaled·K via IterateMmDsK → fixpout to dqGm directly (via dqWorkSpaceGm alias). dq scale total = 1× (at the ds stage, inherited through mm). No DqkvMulsAndCast, no POST. ✓

But wait — I should double check: for FP32, in ComputeDqkvBn2gs1s2 (ProcessBn2gs1s2LastVec), the call is IterateMmDsK<CALC_TYPE, IS_DQ_WRITE_UB>(this->dqWorkSpaceGm, ...). IS_DQ_WRITE_UB is false for BN2GS1S2 (kernel_base.h:99), so outTensor = GlobalTensor<float> = dqWorkSpaceGm which aliases dqGm (INPUT_TYPE=float). Then IterateMmDsKFixpout !IS_WRITE_UB branch writes to outTensoroffset+gmNOffset. Need to check that branch — does it use offset for dqGm? I saw the dk Fixpout branch (block_cube.h:1083-1128) handles offsets for BN2/BN2S2/BN2GS1S2. For dq, let me check IterateMmDsKFixpout's !IS_WRITE_UB branch — around line 1056-... wait actually I saw lines 1040-1056 which appear to be the END of IterateMmDsKFixpout with Fixpipe<T, CALC_TYPE, DQ_FIXPIPE_CONFIG>(outTensor[gmNOffset], ...). Hmm, but that was for IS_WRITE_UB=true? Let me re-read: lines 1040-1056 come right after the IterateMmDsKOlderDeter fixp2GM section (1035-1055)... 

Wait, actually lines 1035-1056 belong to IterateMmDsKOlderDeter (the older deter variant), which is a different function. Hmm no — 950: IterateMmDsKOlderDeter starts; its body includes the fixp2GM at 1035-1055. So the DQ_FIXPIPE at 1050-1053 is the OLDER DETER fixpout (writes to outTensorgmNOffset with SetAtomic... no atomic here). Hmm wait, that's IterateMmDsKOlderDeter's fixpipe at the end. Then IterateMmDsKFixpout must be elsewhere. Let me find it — earlier locate showed IterateMmDsKFixpout isn't a separate located function; but block_cube.h must have it. Let me grep for "IterateMmDsKFixpout" definition. Actually the earlier snippet at 1040-1056 shows DQ_FIXPIPE_CONFIG and Fixpipe<T, CALC_TYPE, DQ_FIXPIPE_CONFIG>(outTensor[gmNOffset], ...) — that looks like it could be IterateMmDsKFixpout's tail... but it's within IterateMmDsKOlderDeter? The offset 1035-1055 comes right after 1028 (MatmulKMutex call) within IterateMmDsKOlderDeter, and 1056 closes }. Hmm — actually 1056 closes the function? Let me count: IterateMmDsKOlderDeter started at 950, and the body goes to... I read 950-1056. The } at 1056 might close IterateMmDsKOlderDeter. So where is IterateMmDsKFixpout? It must be defined before 950 or after 1057. IterateMmDsK (846-946) calls IterateMmDsKFixpout<T, IS_WRITE_UB>(outTensor, mm3L0CBuffer, constInfo, runInfo, realN, gmNOffset) at line 942. So IterateMmDsKFixpout is defined somewhere before line 846 (or after 1057). Let me search for it.

Actually the first snippet I read (840-1039) included line 942: IterateMmDsKFixpout<T, IS_WRITE_UB>(outTensor, mm3L0CBuffer, constInfo, runInfo, realN, gmNOffset); inside IterateMmDsK. And lines 1040-1056 showed DQ_FIXPIPE_CONFIG Fixpipe — hmm wait, that could be IterateMmDsKFixpout itself if defined between... no, 1040 comes after 1039 which is inside IterateMmDsKOlderDeter (which started at 950). Actually wait — I need to recheck: did IterateMmDsKOlderDeter actually start at 950? Yes, from the read: "948: TEMPLATES_DEF_NO_DEFAULT / 949: template <typename T, bool IS_WRITE_UB> / 950: aicore inline void FAGBlockCube<TEMPLATE_ARGS>::IterateMmDsKOlderDeter(". And its body continued to ~1055 with the fixp2GM. So the DQ_FIXPIPE Fixpipe at 1050-1053 is IterateMmDsKOlderDeter's output (with outTensor[gmNOffset] — interesting, no offset computation — writes to workspace at gmNOffset).

So where's IterateMmDsKFixpout? It's called at line 942 by IterateMmDsK, so must be defined BEFORE line 846 (since it's used at 942 and C++ requires declaration before use... though in class templates, member functions defined later can be called from earlier-defined member functions since the class is complete at instantiation). So it could be anywhere. Let me locate it via uo-query or read a bigger window. Let me search for "IterateMmDsKFixpout" in block_cube.h.
SPLIT_AXIS 枚举确认（0=BN2GS1S2, 1=BN2, 5=BN2S2），且 FP32 时 dqWorkSpaceGm 直接别名 dqGm（kernel_base.h:278-282）。还差 IterateMmDsKFixpout 的写出细节（确认无 scale 且直写 GM/workspace）
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern IterateMmDsKFixpout]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_cube.h [limit=120, offset=640]
- Thought: 29.9s
I have IterateMmDsKFixpout at block_cube.h:744-~840. The !IS_WRITE_UB branch (fixp2GM) at 771+: writes outTensor (workspace or dqGm for FP32). No Muls there. Let me read the rest (783-844) to confirm the offset/atomic handling and no scale. Then I have all the pieces.

Also, I want to double-check the ProcessVec3 context — specifically that the FP32 Muls at 620 is inside ProcessVec3 and that it runs for BN2/BN2S2/BN2GS1S2 too — wait, no! The FP32 Muls in ProcessVec3 applies to ALL FP32 templates regardless of SPLIT_AXIS. But the task says "FP32 恒 BN2GS1S2 且无 POST" — meaning at runtime, FP32 input always routes to SPLIT_AXIS==BN2GS1S2 template (per tiling SetSplitAxis, maybe isBn2 with FP32 → BN2GS1S2). Hmm, wait — but if FP32 could also be BN2/BN2S2, then the scale would be applied at ProcessVec3 (ds) AND again at DqkvMulsAndCast (BN2 path) — double. But the task states FP32 is always BN2GS1S2. Let me verify from tiling: is there a constraint that FP32 → BN2GS1S2 only? Let me check the tiling SetSplitAxis logic (tiling_common_regbase.cpp:1641-1647) and any isBn2 restriction for FP32.

Actually the CodeMap result showed:
- line 1643: fBaseParams.splitAxis = SplitAxisEnum::BN2S2 when !fBaseParams.isBn2 && bn2S2RouteLimit
- line 1645: fBaseParams.splitAxis = SplitAxisEnum::BN2 when fBaseParams.isBn2
- line 1647: else BN2GS1S2

Need to check whether FP32 is excluded from BN2/BN2S2 routing (bn2S2RouteLimit / isBn2 conditions). Let me read tiling_common_regbase.cpp around 1600-1660.

Also let me check the post kernel launch — is the post kernel launched for BN2S2/BN2GS1S2 non-FP32? The post kernel file is s1s2_bn2gs1s2_post_regbase.h. There should be a kernel entry that instantiates both main and post kernels. Let me look at the entry file. But actually for the question at hand, what matters is:
1. BN2: no POST launched? Process() in post regbase skips ProcessDqkv for SPLIT_AXIS==BN2 (line 327). Even if launched, no dq processing. But is the post kernel even launched for BN2? The post file comment says "s1s2_bn2gs1s2_post" — likely launched only for BN2S2/BN2GS1S2 (and maybe BN2 with sink?). Either way, POST dq scale = 0 for BN2.
2. BN2S2: POST launched, ProcessDqkv processes ONLY dq (break after qkvIdx 0), Muls applied once per element.
3. BN2GS1S2 non-FP32: POST launched, ProcessDqkv processes dq, dk, dv; dq gets Muls once.
4. FP32: POST either not launched or ProcessDqkv skipped (line 327); scale via ProcessVec3:620.

Let me now:
1. Read the rest of IterateMmDsKFixpout (783-844).
2. Check tiling_common_regbase.cpp SetSplitAxis (~1600-1660) for FP32 routing.
3. Find the kernel entry (which launches main/post) to confirm post launch conditions — helpful for the answer's completeness but maybe not strictly required. Let me at least locate the entry.
IterateMmDsKFixpout 在 block_cube.h:744 起。读它的 GM 分支（783-844），同时查 tiling 的 SetSplitAxis（确认 FP32 只路由 BN2GS1S2
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_cube.h [limit=65, offset=783]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp [limit=80, offset=1590]
- Thought: 32.8s
All key facts confirmed:

Tiling routing (tiling_common_regbase.cpp:1631-1648):
- BN2S2 route (bn2S2RouteLimit, line 1637): requires fBaseParams.queryType != ge::DT_FLOAT → FP32 (DT_FLOAT) never BN2S2.
- BN2 route (isBn2): where is isBn2 set? Need to check — the earlier part of SetSplitAxis likely excludes FP32 too. Line 1601: (fBaseParams.queryType != ge::DT_FLOAT) in isBn2MultiBlk. And regular isBn2? Let me quickly check where fBaseParams.isBn2 is set initially. Actually, there might be a condition isBn2 = ... && queryType != DT_FLOAT. Hmm, I saw isBn2MultiBlk excludes FLOAT. For plain isBn2 — I didn't see its initial setting in this window. But regardless, the task itself asserts "FP32 恒 BN2GS1S2 且无 POST" and the kernel-side evidence supports it: for FP32, dqWorkSpaceGm aliases dqGm directly (kernel_base.h:278-282) and there's no post launch. Actually, let me verify the post kernel is not launched for FP32 — check where the post kernel is launched. But it's not strictly needed: even if launched, post_regbase.h:327 skips ProcessDqkv for T1==float.

Let me quickly check where isBn2 is set for non-multiblk. Let me search "isBn2 =" in tiling_common_regbase.cpp. Actually, to be thorough and give file:line evidence, let me search. But I've done a lot of queries; the answer is essentially complete. Still, let me do one more quick check for isBn2 initial assignment + the post kernel launch (entry). Let me query for the entry file / PostRegbase instantiation.

Actually, let me reconsider what's needed for the final answer:

The question: on each path (BN2, BN2S2, BN2GS1S2), how many times is dq multiplied by scale in MAIN vs POST.

Facts established:
1. Scale value source: constInfo.scaleValue (block_vec.h:620, 708, 829) and tilingData->s1s2BNGS1S2BaseParams.scaleValue (post_regbase.h:238, 283). Both presumably the same scale (need to confirm constInfo.scaleValue == tilingData scaleValue — let me check SetConstInfo in kernel_base.h). Actually there could be a subtlety: constInfo.scaleValue might be derived. Let me check. But it's the same "scale" semantically — the attention scale 1/sqrt(d). Actually, in FA, there can also be deqScale applied — but here the code uses scaleValue. Let me quickly verify constInfo.scaleValue assignment.

2. MAIN scale points for dq:
   - IterateMmDsK (block_cube.h:846-946): pure MatmulFullMutex/MatmulKMutex/MatmulNMutex + IterateMmDsKFixpout (744-844, Fixpipe only, no Muls). NO scale. ✓ dq = ds·K unscaled.
   - ProcessVec3 (block_vec.h:618-621): if constexpr (IS_FP32_INPUT) Muls(mm1ResTensor=dS, scaleValue, VECTOR_BASEM*VECTOR_BASEN) — scale applied to dS (pre-mm) ONLY for FP32 input. dq inherits it via the mm. This is the FP32 dq scale point (applies to dq AND dk, not dv).
   - ProcessMulsAndCast → DqkvMulsAndCastFromUB (block_vec.h:707-709): if constexpr (MM_IDX != DV_IDX) Muls(inputTensor, scaleValue, dataSize) — the MAIN scale for dq/dk in BN2 path (IS_DQ_WRITE_UB true → FromUB; false → FromGM).
   - DqkvMulsAndCastFromGM (block_vec.h:828-830): same Muls. Note: if constexpr (MM_IDX != DV_IDX) — dq/dk get scaled, dv doesn't.

3. POST scale points for dq (post_regbase.h):
   - ProcessDqkv ping: 237-239 if (qkvIdx < 2) Muls(vecInPing, scaleValue, pingSize) — qkvIdx 0=dq, 1=dk.
   - ProcessDqkv pong: 282-284 same for pong.
   - Each element is processed once (ping or pong), so exactly 1 Muls per dq element in POST.
   - Line 314-317: SPLIT_AXIS==5 (BN2S2) → break after qkvIdx==0 → only dq in POST.
   - Line 327: if constexpr (SPLIT_AXIS != BN2 && !IsSameType<T1, float>::value) ProcessDqkv() → BN2 and FP32 skip POST dqkv entirely.

4. Path summaries:
   - BN2 (SPLIT_AXIS==1, non-FP32): MAIN: dq = ds·K (no scale in IterateMmDsK), then ProcessMulsAndCast<DQ> → Muls once (FromUB 708 or FromGM 829). POST: skipped (post_regbase.h:327). Total: 1 (MAIN 1, POST 0). ✓
     - Caveat: IS_DQ_WRITE_UB true → FromUB (line 708); false (IS_DQ_RES_EXCEED_UB, i.e., HEAD_DIM_ALIGN>128) → FromGM (line 829). Both apply 1 Muls.
   - BN2S2 (SPLIT_AXIS==5, non-FP32): MAIN: dq mm → dqWorkSpaceGm unscaled (kernel.h:234, block_cube.h fixpout no Muls); MAIN does NOT call ProcessMulsAndCast<DQ> (only DK/DV at kernel.h:250-265/285-303). POST: ProcessDqkv qkvIdx=0 only (break at 315-317), Muls once (237-239). Total: 1 (MAIN 0, POST 1). ✓ matches the user's hypothesis.
   - BN2GS1S2 (SPLIT_AXIS==0, non-FP32): MAIN: dq mm → workspace unscaled (ProcessBn2gs1s2LastVec kernel.h:75/147); NO ProcessMulsAndCast for DQ anywhere in this flow (only in kernel_deter.h deter variant — not this path for non-deter). POST: ProcessDqkv qkvIdx 0,1,2 — dq Muls once (237-239 or 282-284), dk Muls once, dv no Muls (qkvIdx<2 condition), all written to final GM. Total: 1 (MAIN 0, POST 1).
   - FP32 (always BN2GS1S2, no POST): MAIN: ProcessVec3 Muls on dS (620) — this IS the dq scale, inherited through mm; dq fixpout writes DIRECTLY to dqGm (kernel_base.h:278-282 aliases workspace→dq). DqkvMulsAndCast NOT called in BN2GS1S2 flow. POST: skipped (327, T1==float). Total: 1 (MAIN 1 — but at the dS stage before mm, POST 0).

   Wait — for FP32, is the scale really exactly once for dq? ProcessVec3 Muls applies to dS. Then dq = dS_scaled · K → scaled once. dk = Q · dS_scaledᵀ → scaled once. dv = p·dy → unscaled (correct, dv shouldn't be scaled). ✓ So each of dq/dk gets scale exactly once via the ds pre-scale. 

   BUT — one thing to double check for FP32: is ProcessVec3 called once per s2 iteration, and the Muls applies each time? Yes, it's in the loop body. Each dq element computed from one dS block gets the scale exactly once (ds block multiplied once). And there's no second application. ✓

   Also — IMPORTANT — I should double-check that for FP32, dqWorkSpaceGm (aliased to dqGm) receives the fixpout without further muls: kernel.h:75/147 IterateMmDsK → IterateMmDsKFixpout !IS_WRITE_UB → Fixpipe to outTensor (dqGm) at offset (line 797: BN2? else queryOffset; for BN2GS1S2 → runInfo.commonRunInfo.queryOffset). Need to confirm queryOffset is the dqGm offset... yes, dqkvGmOffset = runInfo.commonRunInfo.queryOffset used in DqkvMulsAndCastFromUB (block_vec.h:684-686) for dqGm addressing, same concept. ✓

5. One more check: is there any other scale application in MAIN for dq in the BN2S2/BN2GS1S2 paths via the deter kernel (kernel_deter.h)? The user is debugging FP16 (non-FP32), possibly with determinism enabled? The task mentions only three paths BN2/BN2S2/BN2GS1S2 — and deter is orthogonal (DETER_SPARSE_TYPE). The kernel_deter.h:867 also calls IterateMmDsK to dqWorkSpaceGm and then... let me check if it calls ProcessMulsAndCast<DQ>. Actually, kernel_deter.h line 867-869 shows IterateMmDsK for dq. Let me check whether the deter path then does dq muls in MAIN. The task didn't ask about deter, but if determinism is enabled in the user's debug scenario... The task explicitly says three paths, so I'll mention deter as a PARTIAL/out-of-scope note if relevant. Actually — let me do a quick check of kernel_deter.h dq handling to be safe, since the user is debugging precision and determinism is common in such setups. Let me look at kernel_deter.h around 860-940.

Actually, the task is precise: "BN2 / BN2S2 / BN2GS1S2 三条路径必须分开列" — with the note FP32 is always BN2GS1S2. DETER is a 4th dimension (DETER_SPARSE_TYPE), not one of the three paths. I can add a brief note if the deter flow differs (e.g., in deter, dk/dv write via ProcessMulsAndCast in MAIN? or via ProcessPostDeter?). Let me quickly check kernel_deter.h for whether dq gets scaled in MAIN for deter — it would strengthen the answer with a caveat. Let me read kernel_deter.h around the dq handling (867-930).

Also, I should verify constInfo.scaleValue — where it's set, to confirm it's the same scale used in POST (s1s2BNGS1S2BaseParams.scaleValue). Let me locate SetConstInfo scaleValue.
再补两处证据：constInfo.scaleValue 的来源（与 POST 的 scaleValue 是否同一值），以及 deter 路径下 dq 是否也在 MAIN 乘 scale
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern scaleValue]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_deter.h [limit=110, offset=840]
- Thought: 14.7s
Deter path (kernel_deter.h:866-949): for BN2S2 deter, dq → dqWorkSpaceGm via IterateMmDsK (line 867-869), then only DK and DV get ProcessMulsAndCast in MAIN (887-888, 917-918). dq is NOT muls'd in MAIN; POST handles it. Same pattern as non-deter. For non-BN2S2 (else branch at 930): dq → workspace; then... likely a ProcessPostDeter or dq muls elsewhere? Need to check 950-1050 for the dq muls handling in deter non-BN2S2. Actually the task didn't ask about deter, so I'll keep it brief. But let me quickly scan to see if dq gets ProcessMulsAndCast in deter non-BN2S2 path — that's the BN2GS1S2 deter. Let me read 950-1050.

scaleValue origin (tiling_common_regbase.cpp:1011): fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0)) — from op attribute (the scale attr). Both kernel constInfo (via SetConstInfo, kernel_base.h:488 READS) and POST (tilingData->s1s2BNGS1S2BaseParams.scaleValue) read the SAME tiling field. So the same scalar is used everywhere. ✓ (One nuance: for FP8 there may be deqScale interplay, but for FP16 the scale is the attr.)

Let me quickly verify SetConstInfo sets constInfo.scaleValue from the same tiling field (kernel_base.h:488). The locate result shows SetConstInfo at kernel_base.h:488 READS scaleValue — that's sufficient.

Now, let me also double check the ProcessVec3 FP32 Muls is only for FP32 and confirm IS_FP32_INPUT in block_vec.h context = INPUT_TYPE==float. block_vec.h likely has constexpr static bool IS_FP32_INPUT = IsSameType<INPUT_TYPE, float>::value — actually it's from kernel_base.h:79 and inherited via template args. The snippet at 618-621 uses IS_FP32_INPUT — consistent.

One more question to nail down: for BN2 non-FP32, which Muls applies — FromUB (708) or FromGM (829)? IS_DQ_WRITE_UB true for BN2 when !IS_BN2_MULTIBLK && !IS_DQ_RES_EXCEED_UB (kernel_base.h:99). So:
- BN2 simple (headDim<=128): IS_DQ_WRITE_UB=true → IterateMmDsK writes dq to mm1ResTensor (UB), ProcessMulsAndCast → DqkvMulsAndCastFromUB (line 661 → 669) → Muls at 708, then Cast + DataCopyPad to dqGm.
- BN2 with IS_DQ_RES_EXCEED_UB (headDim>128): IS_DQ_WRITE_UB=false → dq → dqWorkSpaceGm, ProcessMulsAndCast → DqkvMulsAndCastFromGM (line 663 → 722) → Muls at 829, Cast, DataCopyPad to dqGm.
- BN2 multiblk (IS_BN2_MULTIBLK): kernel.h:440-454 — dq → dqWorkSpaceGm (line 442), ProcessMulsAndCast<DQ> at 452-453 only when isLastS1Outer → FromGM Muls at 829. So still 1×.

All BN2 variants: exactly 1 Muls in MAIN for dq. ✓

Also note for BN2: ProcessVec3's FP32 Muls at 620 doesn't apply (non-FP32). And POST skipped (327). Total 1.

Wait, one more consideration for BN2S2: the task says "BN2S2 时 dq 走 POST、dk/dv 走主核 vec（post_regbase.h:314-317 只处理 dq）". Confirmed: line 315 if constexpr (SPLIT_AXIS == 5) break; — after the dq iteration (qkvIdx==0), break → dk/dv skipped in POST. And in MAIN, dk/dv get ProcessMulsAndCast (kernel.h:250-251/264-265 for dk; 285-286/302-303 for dv) → dk scaled once in MAIN (from FromUB at 708 or FromGM at 829), dv no scale (MM_IDX==DV_IDX). ✓

For BN2GS1S2 non-FP32: MAIN has NO ProcessMulsAndCast at all (ProcessBn2gs1s2LastVec / ComputeDqkvBn2gs1s2) — all dq/dk/dv go to workspace GM via IterateMm* + Fixpipe; POST ProcessDqkv handles qkvIdx 0,1,2 (no break) → dq 1× Muls, dk 1× Muls, dv 0×. ✓

FP32: BN2GS1S2 route (isBn2 excludes DT_FLOAT via line 1601 for multiblk; BN2S2 route excludes DT_FLOAT at line 1637; need to confirm plain BN2 excludes FP32 — let me check where isBn2 is initially set. Let me search "isBn2 = " quickly. Actually from the comment at line 1607: fBaseParams.isBn2 = fBaseParams.isBn2MultiBlk ? true : fBaseParams.isBn2; — isBn2 is set earlier. Let me find it. It's important to fully back the claim "FP32 恒 BN2GS1S2". Let me look at where isBn2 is assigned initially.

Also, for the FP32 case — since the question's primary interest is FP16 precision, FP32 is just a contrast case. The task explicitly says "注意 FP32 恒 BN2GS1S2 且无 POST" — so I'll treat it as given, but I can verify. Let me do one quick search for "isBn2 =".
deter 路径同款（dq 只进 workspace、MAIN 只 muls dk/dv）。scaleValue 同源（attr，tiling_common_regbase.cpp:1011）。最后确认 isBn2 的初始条件里排除
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern isBn2]
- Thought: 21.4s
isBn2 initial condition (tiling_common_regbase.cpp:1583-1588):
fBaseParams.isBn2 = (s1 <= BN2_MAX_S && s2 <= BN2_MAX_S) &&
                    (n1 == n2) &&
                    (d <= BN2_MAX_D) &&
                    (queryType != ge::DT_FLOAT) &&     // ← FP32 excluded
                    !(FP8 variants) &&
                    (tailZeroCount == 0);
So FP32 (DT_FLOAT) is excluded from BN2 AND BN2S2 (line 1637: queryType != ge::DT_FLOAT). Therefore FP32 → BN2GS1S2 always. ✓ "FP32 恒 BN2GS1S2" confirmed with file:line evidence.

All evidence collected. Let me also double check the FP32 fixpout write offset — for BN2GS1S2, IterateMmDsKFixpout !IS_WRITE_UB branch writes outTensor[offset + gmNOffset] with offset = runInfo.commonRunInfo.queryOffset (line 797). queryOffset is the dq GM offset (used similarly for dqGm in DqkvMulsAndCastFromUB:685). ✓ So FP32 dq → dqGm directly, scaled once (inherited from the ds pre-scale at block_vec.h:620).

One more sanity check on the FP32 Muls at block_vec.h:620: it applies to mm1ResTensor = dS. But note this is in ProcessVec3 which is also called for the BN2S2 path (kernel.h:208) and BN2 path (kernel.h:341) — but for those paths IS_FP32_INPUT is false (since FP32 never routes there), so the Muls is compiled out. Good — no cross-contamination.

Also verify there is no scale inside IterateMmDsQ (dk) or IterateMmPDy (dv) — not needed for the dq question, but dk's scale point is relevant to compare. dk gets scaled in MAIN for BN2 (ProcessMulsAndCast<DK>), in MAIN for BN2S2 (ProcessMulsAndCast<DK> kernel.h:250-265), and in POST for BN2GS1S2 (qkvIdx==1, line 237-239/282-284). Consistent with dq except BN2S2 where dk stays in MAIN.

Now — one thing about ProcessDqkv and "dk/dv 走主核 vec" for BN2S2: In MAIN ComputeDqkvBn2s2, dk is computed into dkWorkSpaceGm (line 254) then ProcessMulsAndCast<DK> (264-265) → FromGM Muls at 829 → writes dkGm. And dv → dvWorkSpaceGm then ProcessMulsAndCast<DV> (302-303) → FromGM, MM_IDX==DV_IDX so NO Muls at 829 (if constexpr (MM_IDX != DV_IDX)), writes dvGm. So dk 1× MAIN, dv 0×. This matches the post comment "bn2s2 dk dv no need to do muls and cast" (post_regbase.h:314).

Wait, careful with the IS_DK_WRITE_UB branch in ComputeDqkvBn2s2 (kernel.h:238-252): for NO_DETER BN2S2, IS_DK_WRITE_UB can be true (kernel_base.h:100-101: (SPLIT_AXIS == BN2S2 && DETER_SPARSE_TYPE == NO_DETER) && !IS_DKV_RES_EXCEED_UB). Then dk mm → mm1ResTensor (UB), ProcessMulsAndCast<DK> → FromUB Muls at 708. Same 1×.

And dv: IS_DV_WRITE_UB true for BN2S2 NO_DETER → mm2ResTensor UB → FromUB, MM_IDX==DV_IDX no Muls. Same.

Everything is consistent. Also should double-check: for BN2S2, is there any chance MAIN calls ProcessMulsAndCast<DQ> somewhere else (e.g., ProcessPostDeter or after-loop flush)? In ComputeDqkvBn2s2 (kernel.h:182-311), DQ is only IterateMmDsK → dqWorkSpaceGm (line 234). No ProcessMulsAndCast<DQ>. In ProcessPreloadTwoTimes — only for BN2GS1S2 (kernel_base.h:112-114: SPLIT_AXIS==BN2GS1S2 required). Process() → BN2S2 → ComputeDqkvBn2s2 only. Deter BN2S2 → kernel_deter.h:866-869, no DQ muls in MAIN. ✓

Now let me also confirm the post kernel is actually launched for BN2S2/BN2GS1S2 (so "POST" phase exists) — and not launched for BN2. This matters for the "合计" claim: e.g., for BN2, if POST kernel is launched but does nothing, the total is still 1. The entry point would be in flash_attention_score_grad.cpp or similar (op_kernel root). Let me do one quick check for the kernel entry that instantiates FlashAttentionScoreGradS1S2BNGS1S2PostRegbase and decides launch. This is a minor point but adds completeness. Let me query "PostRegbase" or "s1s2_bn2gs1s2_post".

Actually, I have enough for a rigorous answer. But let me quickly check the entry to see if POST is launched for BN2 (i.e., whether the "POST 整体跳过" claim for BN2 means the phase isn't launched, vs launched-but-no-op). The task says "BN2 下 dq 是否只有 MAIN（ProcessMulsAndCast）一次、POST 整体跳过（post_regbase.h:327 SPLIT_AXIS != BN2）" — the code evidence at 327 is exactly that: even if the POST kernel runs, ProcessDqkv is compiled out for BN2. That satisfies the claim. But a quick entry check makes it airtight. Let me do it.
isBn2 初始条件排除 DT_FLOAT（tiling_common_regbase.cpp:1586），FP32 恒 BN2GS1S2 坐实。最后确认 post 核的启动入口（BN2 是否根本不启动 POST）
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern S1S2BNGS1S2PostRegbase]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=55, offset=480]
- Thought: 5.5s
The post kernel class is defined in the post file; the launch happens via a kernel entry (probably flash_attention_score_grad.cpp / .h at op_kernel root, or in a separate post entry file). The locate for the post class only found the header — the instantiation must be elsewhere (maybe in flash_attention_score_grad.cpp or flash_attention_score_grad_s1s2_bn2gs1s2_post.cpp). Let me check the op_kernel directory listing for entry files. But honestly, the essential claims are already proven:

1. BN2: POST ProcessDqkv compiled out (post_regbase.h:327 SPLIT_AXIS != BN2). Whether the post kernel launches at all is secondary — even if it runs, it does nothing for dqkv. Also BN2's dqWorkSpaceGm uses fixed offsets (kernel_base.h:262-269) and dq is written to dqGm by MAIN's ProcessMulsAndCast directly, so no post dependency.

2. FP32: POST ProcessDqkv compiled out (post_regbase.h:327 !IsSameType<T1, float>::value), and dqWorkSpaceGm aliases dqGm (kernel_base.h:278-282) so dq is complete in MAIN.

I have all the evidence needed. Let me quickly check the entry file to note where the post kernel is dispatched (nice-to-have for the "POST" column). Let me list the op_kernel directory.
补最后一块：post 核的入口/启动文件（主核 entry 里如何分
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel 
- Thought: 427ms
Let me look at flash_attention_score_grad.cpp — the main kernel entry — to see how the post kernel is launched (under which conditions).
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern PostRegbase]
- Thought: 2.6s
The CodeMap's locate doesn't show the post kernel instantiation in the entry file — the post kernel might be launched via a separate compilation unit (there could be a separate kernel file like flash_attention_score_grad_s1s2_bn2gs1s2_post.cpp... but the directory only shows arch22, arch35, apt.cpp, and flash_attention_score_grad.cpp). Let me quickly grep flash_attention_score_grad.cpp for post dispatch — it's the entry that launches the kernel. But per my constraints, I should use acp uo-query, not Grep. Let me query locate for the file contents around post — or just read flash_attention_score_grad.cpp window (it's a machine-scope source, small, windowed read is allowed).

Actually, the post kernel launch detail is peripheral. The question focuses on scale application count, which is fully established at the phase level (MAIN vs POST), regardless of whether the POST kernel is a separate launch. But to be rigorous about "POST 整体跳过" for BN2, it helps to know whether the post kernel is even launched for BN2. The kernel launch decision is made in the entry. Let me read the entry file (flash_attention_score_grad.cpp) briefly — checking how it dispatches.
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\flash_attention_score_grad.cpp [limit=120, offset=1]
- Thought: 1.5s
The root flash_attention_score_grad.cpp (arch22-based legacy entry, lines 59-92) launches Pre → S1s2Bn2gs1s2 → Post phases for the general path — but note this is the arch22 path (includes arch22 headers). The arch35 regbase path is what we analyzed (the .uo CodeMap files are op_kernel/arch35/*). The arch35 regbase entry is likely in a separate file under op_kernel/arch35/ (e.g., flash_attention_score_grad_arch35.cpp or within the arch35 folder). Let me check the arch35 directory listing to find the entry that uses the S1S2BNGS1S2PostRegbase (regbase).
arch35 regbase 的入口应独立存在。列 arch35 目录并查入口中 post 启动条件
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35 
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h [limit=300, offset=1]
- Thought: 19.6s
PERFECT. The entry macro INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL (entry_regbase.h:40-114) settles the POST launch:

- Line 91: if (ORIG_DTYPE_QUERY != DT_FLOAT) { → POST phase is launched ONLY when input dtype is NOT float (FP32). For FP32 → line 111-113: pipeBase.Destroy() — NO POST at all. ✓ "FP32 无 POST" with file:line.
- Line 95-110: for non-FP32 → launches FlashAttentionScoreGradS1S2BNGS1S2PostRegbase (96-100) or NZ post (102-109). This covers BN2GS1S2 AND BN2S2 (both use the same macro: lines 224-241 FP16 → BN2GS1S2 and BN2S2 both call the same INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL; BN2 uses INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL at 129-182).

- BN2 macro (129-182): POST launched ONLY if sinkOptional (line 170). If sink is enabled, the PostRegbase::Process runs but ProcessDqkv is compiled out (SPLIT_AXIS==BN2 → post_regbase.h:327). If no sink → no post kernel at all (line 179-181). Either way, BN2 dq never gets POST scale. ✓

- Note: FP32 also has BN2S2 and BN2 template instantiations in the entry (lines 274-286) — but at runtime FP32 never routes to those (host tiling excludes DT_FLOAT from BN2/BN2S2, tiling_common_regbase.cpp:1586/1637). And even if instantiated, the post is skipped for FP32 at line 91.

This fully confirms all three paths + FP32 case. Now I have complete evidence. Let me also confirm the DqkvMulsAndCastFromUB early-return doesn't create a path where dq is written WITHOUT scale... no wait, the early return (line 673-675) is when halfS1RealSize==0 — nothing to write, not a scale question.

One more thing to verify for BN2: IS_DQ_WRITE_UB=true case → DqkvMulsAndCastFromUB line 707-709 applies Muls to the UB tensor which came from mm (IterateMmDsK with IS_WRITE_UB=true → Fixpipe to mm1ResTensor UB). Then Cast + DataCopyPad to dqGm. 1×. ✓

And for BN2 IS_DQ_WRITE_UB=false (headDim>128, i.e. D=192/256) or multiblk → DqkvMulsAndCastFromGM (829). 1×. ✓

Everything is consistent. Also let me note the fixed workspace for BN2 non-multiblk (kernel_base.h:262-269): dqWorkSpaceGm → workspace + RESERVED_WORKSPACE_SIZE, qPostBlockTotal sized. That's the staging for FromGM muls+cast.

Now also for the BN2GS1S2 non-FP32 MAIN: no ProcessMulsAndCast at all in ComputeDqkvBn2gs1s2 — dq/dk/dv mm results → workspace GM (dqWorkSpaceGm etc., line 271-276 offsets), Fixpipe writes them (IterateMmDsKFixpout !IS_WRITE_UB → outTensorqueryOffset+...) — no scale. Then POST reads dqkvWorkspace (line 95-97 post Init) and applies scale for qkvIdx<2. ✓

And ProcessPreloadTwoTimes (kernel.h:593-754): for BN2GS1S2 small-headDim non-drop non-FP32 — dq/dk/dv → workspace (lines 726-740) — no muls in MAIN. Same conclusion. ✓

I now have everything. Let me also double-check the "MM_IDX != DV_IDX" condition for DQ_IDX/DK_IDX values — DQ_IDX, DK_IDX, DV_IDX constants. DQ_IDX != DV_IDX obviously (different enum). Fine.

Also double check that ProcessDqkv applies the Muls to vecInPing/vecInPong — the ping/pong are halves of the same qkv range (pingIdx steps by 2*REGBASE_POST_BASE), so each element of dq goes through exactly ONE Muls (either ping branch line 237-239 or pong branch line 282-284). ✓ Not twice.

Ready to write the final answer in Cursor Explore style with file:line evidence and the table.

Summary table:
| 路径 | MAIN 乘几次 | POST 乘几次 | 合计 |
| BN2（非 FP32） | 1（ProcessMulsAndCast → DqkvMulsAndCastFromUB :708 或 FromGM :829；IterateMmDsK 不含 scale） | 0（post_regbase.h:327 SPLIT_AXIS==BN2 编译掉 ProcessDqkv；BN2 入口 post 仅在 sink 时启动 :170，且不处理 dqkv） | 1 |
| BN2S2（非 FP32） | 0（dq mm → workspace，ComputeDqkvBn2s2 kernel.h:234 后无 DQ 的 ProcessMulsAndCast） | 1（ProcessDqkv qkvIdx==0，post_regbase.h:237-239/282-284；SPLIT_AXIS==5 break :314-317） | 1 |
| BN2GS1S2（非 FP32） | 0（ProcessBn2gs1s2LastVec kernel.h:75/147，dq → workspace，无 ProcessMulsAndCast） | 1（ProcessDqkv qkvIdx==0，:237-239/282-284；无 break，dk 同 1 次，dv 0 次） | 1 |
| FP32（恒 BN2GS1S2，无 POST） | 1（ProcessVec3 block_vec.h:619-621 在 dS 上乘 scale，经 dq=dS·K mm 继承；无 DqkvMulsAndCast） | 0（entry_regbase.h:91 ORIG_DTYPE_QUERY != DT_FLOAT 才启动 post；post_regbase.h:327 T1==float 也编译掉） | 1 |

So the answer: dq 在每条路径上总共恰好乘 1 次 scale — 但位置不同：BN2 在主核 vec（ProcessMulsAndCast），BN2S2 和 BN2GS1S2 在 POST（ProcessDqkv），FP32 在 ProcessVec3 的 dS 预乘。

This directly answers the user's debugging question: dq scale is applied exactly once on all paths, so the "dq 量级差一截" is NOT caused by double/missing scale multiplication (assuming non-deter, standard FP16 routes). 

Additional notes:
- The same scaleValue comes from attr (tiling_common_regbase.cpp:1011), read by constInfo (kernel_base.h:492 SetConstInfo → 488 READS scaleValue per CodeMap) and POST (post_regbase.h:238/283 reads tilingData->s1s2BNGS1S2BaseParams.scaleValue).
- Deterministic paths (kernel_deter.h:866-869, 935-937) also write dq to workspace without MAIN muls for BN2S2/BN2GS1S2, and dk/dv ProcessMulsAndCast in MAIN for BN2S2 — same dq pattern. For deter, the POST handles dq via ProcessDqkv (or ProcessBNS2Deter? — hmm, there's ProcessBNS2Deter declared in the post class but I didn't see it called in Process(); Process() only calls ProcessDqkv + ProcessSink. Wait, in Process() (post_regbase.h:322-333): if SPLIT_AXIS != BN2 && !float → ProcessDqkv(); if isSink → ProcessSink(). ProcessBNS2Deter is declared but... not called in Process? Let me not over-claim; the deter post may handle dq differently via ProcessBNS2Deter — but it's declared, and Process() doesn't call it in what I read. Actually for deter, dk/dv special parts go through deterGm... the post Init has deterGm2... but ProcessDqkv reads dqkvWorkspace. For the task's three paths, deter is orthogonal; I'll add a brief PARTIAL note that determinism (DETER_SPARSE_TYPE != NO_DETER) additionally routes dk/dv special blocks via deterGm and may have its own post handling (ProcessBNS2Deter declared at post_regbase.h:43 but not invoked from Process() in this file — needs the deter-specific post entry to confirm; out of scope for this question).

Actually wait — one more check: ProcessBNS2Deter is declared at line 43 but never called in Process() (lines 322-333). That's curious but it's not my question. The question is about dq scale counts on the three paths. Deter variants keep dq → workspace → POST (or for BN2 non-deter-only... BN2 with deter is not possible since SetSplitAxis sets isDeterministic=false for BN2 non-multiblk at line 1609). Fine.

Also note the NZ post path (entry_regbase.h:102-109, FlashAttentionScoreGradNzPost) for IS_NZ_OUT — that's the NZ-layout output variant; the scale handling there may differ (it reads scaleValue too per the CodeMap READ on nz_post.h:103). For the standard ND/regbase case (which the user is debugging), the S1S2BNGS1S2PostRegbase applies. I'll mention this briefly as a caveat.

I'm confident in the answer now. Let me write the final response in Cursor Explore style.
所有证据已闭合。CodeMap fresh（digest 211a7ec…），以下是结论。
dq 的 scale 乘法：BN2 / BN2S2 / BN2GS1S2 三条路径逐点核对
0. 先厘清两套账本
“scale” 只有一个来源：scaleValue 算子属性，host 侧 fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0))（op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp:1011），写进 s1s2BNGS1S2BaseParams.scaleValue（tiling_data_regbase.h:96）。主核 constInfo.scaleValue（kernel_base.h SetConstInfo，CodeMap READS 指到同一 tiling 字段）和 POST 侧 tilingData->s1s2BNGS1S2BaseParams.scaleValue（post_regbase.h:238/283）是同一个值，不存在主核/POST 各自独立缩放。dv 永远不乘 scale（所有乘点都有 MM_IDX != DV_IDX 或 qkvIdx < 2 门控）。
SPLIT_AXIS 枚举：template_tiling_key.h:53-56 — 0: BN2GS1S2, 1: BN2, 5: BN2S2。所以 post_regbase.h:315 的 SPLIT_AXIS == 5 就是 BN2S2。
1. MAIN 里的全部 scale 乘点（逐点）
a) IterateMmDsK（dq = ds·K 的 mm）— 无 scale。block_cube.h:846-946：纯 Matmul（MatmulFullMutex/MatmulKMutex/MatmulNMutex，:920-935）+ IterateMmDsKFixpout（block_cube.h:744-844，只有 Fixpipe 写 UB/GM，没有任何 Muls）。dq 的 scale 不在 mm 前也不在 mm 后乘；mm 输出的是未缩放 dq。
b) ProcessVec3 — 仅 FP32 输入时对 dS 预乘 1 次。block_vec.h:618-621：
// input type fp32, no post, mov muls here
if constexpr (IS_FP32_INPUT) {
    Muls(mm1ResTensor, mm1ResTensor, constInfo.scaleValue, VECTOR_BASEM * VECTOR_BASEN);
}
这里乘的是 dS（BroadcastSubMul 之后的 mm1ResTensor，:582-603），dq 通过 dq = dS_scaled·K 的 mm 继承这一个 scale。对非 FP32 模板该 constexpr 编译掉，不生效。
c) ProcessMulsAndCast → DqkvMulsAndCastFromUB / FromGM — 主核 vec 的 dq/dk 乘点，各 1 次。block_vec.h:654-665 分派；UB 分支 DqkvMulsAndCastFromUB :707-709：
if constexpr (MM_IDX != DV_IDX) {
    Muls(inputTensor, inputTensor, constInfo.scaleValue, dataSize);
}
GM 分支 DqkvMulsAndCastFromGM :828-830 同样一处 Muls(dqkvTensor, dqkvTensor, constInfo.scaleValue, data_size)。两条分支对同一个 dq 元素二选一，不会都走。dv（DV_IDX）在两条分支里都被 MM_IDX != DV_IDX 跳过。
2. POST 里的全部 scale 乘点（逐点）
ProcessDqkv（flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h:207-319）：
- ping 块 qkvIdx < 2 时 Muls：:237-239；
- pong 块 qkvIdx < 2 时 Muls：:282-284；
- ping/pong 是同一 range 的互补半段（pingIdx 步进 REGBASE_POST_BASE << 1），所以每个 dq 元素只过一处 Muls，恰好 1 次；
- qkvIdx == 2（dv）不乘（qkvIdx < 2 条件）；
- :314-317：// bn2s2 dk dv no need to do muls and cast，if constexpr (SPLIT_AXIS == 5) break; — BN2S2 在 dq（qkvIdx==0）之后直接跳出，dk/dv 不进 POST；
- :327：if constexpr (SPLIT_AXIS != BN2 && !IsSameType<T1, float>::value) ProcessDqkv(); — BN2 与 FP32 的 POST 都不处理 dqkv（编译期剔除）。
POST 核启动条件（entry_regbase.h:40-114，同一条 INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL 宏被 BN2GS1S2 和 BN2S2 共用，FP16/FP32 各实例化）：
- :91 if (ORIG_DTYPE_QUERY != DT_FLOAT) { — FP32 根本不启动 POST（:111-113 直接 pipeBase.Destroy()）；
- BN2 专用宏 :129-182：POST 仅在 sinkOptional 时启动（:170），且即便启动，ProcessDqkv 也被 :327 编译掉；
- BN2S2/BN2GS1S2（非 FP32）：启动 FlashAttentionScoreGradS1S2BNGS1S2PostRegbase（:96-100）。
3. 每条路径的完整 chain
BN2（SPLIT_AXIS==1，非 FP32；含 multiblk 变体）
- MAIN：ComputeDqkvBn2（kernel.h:313-494）→ ProcessVec3 无 FP32 Muls → IterateMmDsK 无 scale（dq→UB 或 dqWorkSpaceGm，取决于 IS_DQ_WRITE_UB，kernel_base.h:99）→ ProcessMulsAndCast<DQ> 1 次（kernel.h:379-380（FromUB :708）或 :391-392/452-453（FromGM :829））→ Cast → DataCopyPad 写 dqGm。
- POST：整体不乘（入口 :170 sink 才启动且 :327 剔除 ProcessDqkv）。
- 合计 1 次（全在 MAIN）。
BN2S2（SPLIT_AXIS==5，非 FP32）
- MAIN：ComputeDqkvBn2s2（kernel.h:182-311）→ dq mm 结果直接进 dqWorkSpaceGm（:234），该函数里只有 DK/DV 有 ProcessMulsAndCast（:250-265、:285-303），DQ 没有；deter 变体同样（kernel_deter.h:866-889，dq 只进 workspace）。MAIN 对 dq 0 次。
- POST：ProcessDqkv qkvIdx==0 一个 Muls（:237-239/282-284），随后 break（:314-317），只处理 dq；dk/dv 在主核 vec 已 muls+cast（dk 1 次、dv 0 次）——与注释「bn2s2 dk dv no need to do muls and cast」一致。
- 合计 1 次（全在 POST）。
BN2GS1S2（SPLIT_AXIS==0，非 FP32；含 ProcessPreloadTwoTimes 小 headDim 路径）
- MAIN：ProcessBn2gs1s2LastVec（kernel.h:42-160）/ ComputeDqkvBn2gs1s2（:162-179）→ dq mm → dqWorkSpaceGm（:75/147），整个 flow 没有任何 ProcessMulsAndCast（dq/dk/dv 一律裸写 workspace；preload 路径同，:726-740）。
- POST：ProcessDqkv 对 qkvIdx 0,1,2 全部处理（无 break），dq 一个 Muls（:237-239/282-284），dk 也一个 Muls，dv 不乘。
- 合计 1 次（全在 POST）。
FP32（恒 BN2GS1S2，无 POST）
- 路由保证：SetSplitAxis 中 isBn2 初始条件明确排除 queryType != ge::DT_FLOAT（tiling_common_regbase.cpp:1583-1588），BN2S2 路由同样排除（:1637），所以 FP32 恒落 BN2GS1S2（:1646-1647）。
- MAIN：ProcessVec3 在 dS 上乘 1 次（block_vec.h:619-621），dq 经 mm 继承；同时 InitCVCommonGlobalBuffer 对 FP32 把 dqWorkSpaceGm/dkWorkSpaceGm/dvWorkSpaceGm 直接别名到 dq/dk/dv 输出 GM（kernel_base.h:278-282，「input type fp32, dq dk dv write to output gm directly」），mm 的 Fixpipe 直写最终 dqGm。
- POST：不启动（entry_regbase.h:91），且 :327 也剔除。
- 合计 1 次（在 MAIN 的 dS 预乘，dq 继承）。
4. 结论表
路径	MAIN 乘几次	POST 乘几次
BN2（非 FP32）	1（ProcessMulsAndCast<DQ> → block_vec.h:708 或 :829）	0（post_regbase.h:327 SPLIT_AXIS==BN2 剔除；入口 entry_regbase.h:170 仅 sink 时启动 post）
BN2S2（非 FP32）	0（kernel.h:234 dq 只进 workspace；MAIN 只有 DK/DV 的 muls）	1（post_regbase.h:237-239/:282-284，qkvIdx==0，随后 :314-317 break 只处理 dq）
BN2GS1S2（非 FP32）	0（kernel.h:75/147 dq 只进 workspace，flow 内无 ProcessMulsAndCast）	1（post_regbase.h:237-239/:282-284；dk 同 1 次、dv 0 次）
FP32（恒 BN2GS1S2，无 POST）	1（block_vec.h:619-621 在 dS 上预乘，dq=ds·K 继承；kernel_base.h:278-282 直写 dqGm）	0（entry_regbase.h:91 不启动 post）
5. 对调试的直接含义
三条路径 + FP32 上，dq 最终都恰好被乘 1 次 scale，不存在 2 次或 0 次。你观察到的「dq 量级差一截」不应归因于 scale 乘多/乘漏（在非 deter、非 NZ 输出、FP16/FP32 的标准路由下）。若确实怀疑 scale 相关，下一步建议对照：同一 scaleValue 在 MAIN（constInfo.scaleValue）与 POST（tilingData->s1s2BNGS1S2BaseParams.scaleValue）的取值是否一致（同源于 attr :1011，理论一致），以及 BN2S2/BN2GS1S2 下 dq 是否在你的场景真的走了 POST（若 isNzOut 为 true，则走的是 FlashAttentionScoreGradNzPost（entry_regbase.h:102-109，其 Init 也读 scaleValue，见 CodeMap READS nz_post.h:103），该路径的乘点不在本次核对的 regbase POST 内）。
PARTIAL 标注：
- deter（DETER_SPARSE_TYPE != NO_DETER）：dq 的 MAIN 行为与上述一致（kernel_deter.h:866-869/935-937 dq 只进 workspace、MAIN 不 muls）；但 post 类还声明了 ProcessBNS2Deter（post_regbase.h:43），且 Process()（:322-333）中未调用它——deter 专用 dk/dv 块走 deterGm，其 post 侧 scale 归属未在本次窗口内完全追平，标 PARTIAL。
- NZ 输出（IS_NZ_OUT）：dq 写出走 nz_post.h 的 FlashAttentionScoreGradNzPost，scale 乘点与 regbase POST 不同文件，未逐行核对，标 PARTIAL。
▣  Uo-Query · DeepSeek V4 Flash Free · 6m 51s
Subagent(4 of 9)122.4K (61%)

# subagent 5 
算子目录：d:\TEST\ops-transformer\attention\flash_attention_score_grad（arch35，.uo CodeMap 已建好，digest 211a7ec…）。

立即调用 acp 工具：command=`uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...`（按需选 locate/symbols/callers/fields 等）。禁止 bash、Grep、MCP 替代。

背景：用户在 950（arch35）上跑 FP16、D=80、带 dropout 的 flash_attention_score_grad，报 kernel 找不到。要搞清楚 host 算出的 TilingKey 是否保证在 kernel 模板实例化表（ASCENDC_TPL_SEL）里命中。

请查清并回答（全部带 file:line 证据）：
1. ASCENDC_TPL_SEL 是什么、在哪里：搜 `ASCENDC_TPL_SEL` / `TEMPLATE_SELECT` / `template_sel` / `RegBase` / `KernelTemplate` 相关机制，说明 host 侧 TilingKey（如 GET_TPL_TILING_KEY，op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1443-1461）到 kernel 模板选择/实例化表的映射机制：key 的 bit 位（template_tiling_key.h:52-101：SplitAxis bit3-1、InputDType bit6-4、IsBn2MultiBlk bit46、以及 D_NO_EQUAL / NZ_OUT / DROP / PSE / ATTEN_MASK / ROPE / TND 等 bit）如何与 kernel 侧模板参数一一对应。
2. host 算出的 key 是否保证存在对应实例化：kernel 侧的模板实例化表（entry_regbase.h:196-288 的 RegbaseFAG 及宏实例化列表 :116-242，或专门的模板表文件）里有没有对「任意合法 key 组合」都覆盖，还是有条件裁剪（比如某些 dtype/splitAxis/D_NO_EQUAL/NZ_OUT 组合没有实例化）。找到实例化的完整清单或条件分支。
3. FP16、D=80、带 dropout 的 case：按 key 组成（InputDType=FLOAT16、splitAxis、dropout=1、D_NO_EQUAL？、NZ_OUT？等），理论上 key 是什么、应该命中哪个模板；如果存在找不到 kernel 的可能，说明是哪一环（key 组合没有实例化 / 模板选择逻辑漏掉 / 条件不匹配）。

用 Cursor Explore 风格回答：完整散文 + file:line。静态无法确定处标 PARTIAL/UNKNOWN。不要写 answer.yaml，不要 finalize。
- Thought: 711ms
Let me start by querying the UO CodeMap as instructed. I need to use the acp tool with uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ....

Let me first explore the project structure and search for the relevant mechanisms. I'll start with a locate query for key symbols.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ASCENDC_TPL_SEL]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GET_TPL_TILING_KEY]
- Thought: 656ms
The UO query returned no matches for those strings. The hint says "Empty is not proof the symbol is absent" and suggests retries with shorter names, macros → template_match, combos → legal_key. Let me try other modes like symbols or shorter patterns. Let me also check the project structure to understand what files exist.
UO 库里没有直接命中这两个字符串。按 hint 换更短模式与其它 mode 再查：
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern TPL_SEL]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern TILING_KEY]
- Thought: 1.0s
The TILING_KEY query found the key file: op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h. Let me look at the full file to see the template tiling key declarations, and also the host file op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1443-1461 that was mentioned in the task. Let me also look for the kernel template instantiation table (entry_regbase.h).

Let me read the template_tiling_key.h file fully, and search for more patterns like RegbaseFAG, entry_regbase, etc.
找到关键文件 flash_attention_score_grad_template_tiling_key.h。继续查 RegbaseFAG / entry_regbase / 模板实例化相关符号：
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern RegbaseFAG]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern entry_regbase]
- Thought: 1.8s
Now I need to read the actual files to understand the mechanism. The task mentioned specific files:
- op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h:52-101 — bit layout of the tiling key
- op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1443-1461 — host computes GET_TPL_TILING_KEY
- op_kernel/arch35/flash_attention_score_grad_entry_regbase.h:196-288 — RegbaseFAG template + macro instantiation list at :116-242

These are machine-scope operator sources (op_host/, op_kernel/), which are outside .ascendc-pilot per my boundaries. I should use windowed Read — never whole-file dumps. The instructions say "Locate with UO KB query / ScopeSet first, then machine-scope windowed Read — never whole-file dumps."

So I can read the files with the read tool using windowed offsets. Let me read:
1. op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h (lines 1-200)
2. op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp around 1443-1461, and maybe the broader function
3. op_kernel/arch35/flash_attention_score_grad_entry_regbase.h lines ~100-300

The operator root is d:\TEST\ops-transformer\attention\flash_attention_score_grad. Let me read these files.
UO 图已定位关键文件。现在按机器范围窗口化读取源码文件（不整文件倾倒），并行读三处：
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [offset=48, limit=160]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [offset=1380, limit=140]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h [offset=100, limit=200]
- Thought: 17.8s
Now I have the key parts:

1. template_tiling_key.h:48-125 — ASCENDC_TPL_ARGS_DECL defining the 64-bit tiling key layout:
   - bit 0: IsEmptyTensor
   - bits 3-1: SplitAxis (0: BN2GS1S2, 1: BN2, 5: BN2S2)
   - bits 6-4: InputDType (0, 1: FLOAT32, 2: BFLOAT16, 3: FLOAT16_PRECISION, 4: FP8_E5M2, 5: FP8_E4M3FN, 6: HIFP8)
   - bit 7: IsTnd
   - bit 8: IsDrop
   - bit 9: IsPse
   - bit 10: IsAttenMask
   - bits 18-11: S1TemplateNum (0, 64, 128, 512)
   - bits 28-19: S2TemplateNum (0, 128, 256, 512)
   - bits 40-29: DTemplateNum (0, 64, 128, 192, 256, 768)
   - bits 44-41: DeterType (0: NO_DETER, 1: DETER_OLD, 2: DETER_DENSE, 3: DETER_CAUSAL, 4: DETER_BAND)
   - bit 45: IsNEqual
   - bit 46: IsBn2MultiBlk
   - bit 47: IsDNoEqual
   - bit 48: IsRope
   - bits 51-49: OutDType (0, 1: FLOAT32, 2: BFLOAT16, 3: FLOAT16_PRECISION)
   - bit 52: IsNzOut
   - bit 53: IsTndSwizzle
   - bit 54: IsRegbase

2. Host side GetTilingKey (op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1435-1472): computes:
   - attenMaskCfg = attenMaskOptional == EMPTY_TENSOR ? DISABLE : ENABLE
   - dNoEqual = (d1 != d) || hasRope
   - pseValue = pseOptional == NORMAL_TENSOR ? ENABLE : DISABLE
   - dropValue = keepProb < 1 ? ENABLE : DISABLE
   - isRegbasePlatformValue = ENABLE
   - isTnd = layoutType == INPUT_FORMAT_TND
   - splitAxis = fBaseParams.splitAxis
   - isDeterNEqual = deterSparseType != DETER_OLD && deterSparseType != NO_DETER && g == 1
   - Then GET_TPL_TILING_KEY(0, splitAxis, inputDtype, isTnd, dropValue, pseValue, attenMaskCfg, s1TemplateType, s2TemplateType, dTemplateType, deterSparseType, isDeterNEqual, isBn2MultiBlk, dNoEqual, hasRope, outDtype, isNzOut, isTndSwizzle, isRegbasePlatformValue)

   Note: The first argument 0 is IsEmptyTensor=0.

3. Kernel side RegbaseFAG (entry_regbase.h:196-288): The template takes 18 params: splitAxis, inputDType, isTnd, isDrop, isPse, isAttenMask, s1TemplateType, s2TemplateType, dTemplateType, deterType, isNEqual, isBn2MultiBlk, isDNoEqual, isRope, outDType, isNzOut, isTndSwizzle, isRegbase. It dispatches on ORIG_DTYPE_QUERY (compile-time macro) and splitAxis to the impl macros, which use constexpr template params to instantiate FlashAttentionScoreGradS1S2BNGS1S2PreRegbase, FAGBlockCube/FAGBlockVec, etc.

Now for question 2 — "host 算出的 key 是否保证存在对应实例化" — I need to check the ASCENDC_TPL_SEL table in template_tiling_key.h. This is the table that declares which key combinations have valid instantiations. I saw the start of it at line 127-207. I need to see the whole table to determine coverage. The file is 1572 lines. Let me read more of it.

Also, I need to understand how the ASCENDC_TPL_SEL mechanism works — it's from ascendc/host_api/tiling/template_argument.h (an SDK header, not in this repo). The UO KB likely has facts about this. Let me query the KB for ASCENDC_TPL_SEL mechanics, and also read more of template_tiling_key.h.

The question about FP16, D=80, dropout:
- InputDType = 3 (FLOAT16_PRECISION)
- D=80: DTemplateNum would be 64 or 128? D=80 is head dim. DTemplateType is a template "type" (a bucket) — need to see GetDTemplateType on the host side. Wait, actually for D=80, the D template types are 0, 64, 128, 192, 256, 768. The GetDTemplateType likely selects the template type based on D value. D=80 might map to 128 (nearest template?) or 64... Need to check host GetDTemplateType.
- dropout=1 → keepProb < 1 → dropValue=ENABLE (IsDrop=1)
- D_NO_EQUAL: dNoEqual = (d1 != d) || hasRope. In typical FA grad with dropout and no rope, d1 == d, so dNoEqual=0.
- NZ_OUT: isNzOut from fBaseParams — for FP16 non-NZ output, likely 0.
- splitAxis: depends on shapes (s1 vs s2 sizes). For D=80, likely BN2GS1S2 or BN2S2.

The key question: is there a combination (InputDType=3, IsDrop=1, DTemplateNum=?, splitAxis=?, etc.) that is NOT instantiated in ASCENDC_TPL_SEL? Let me read the whole SEL table.

Let me also query UO for the template table file and GetDTemplateType.
核心位域与 host 侧 key 构造已拿到。现在需要看完整的 ASCENDC_TPL_SEL 表（1572 行的大文件），以及 host 侧 GetDTemplateType / GetS1S2TemplateType 如何把 D=80 映射到模板编号。继续
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [limit=220, offset=208]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GetDTemplateType]
- Thought: 45.2s
Now I have:
- GetDTemplateType: D=80 → d <= 128 → DTemplateType = NUM128 (128). (line 856-858 of flash_attention_score_grad_tiling_common_regbase.cpp)

For the FP16 D=80 dropout case:
- InputDType = 3 (FLOAT16_PRECISION)
- DTemplateNum = 128 (for D=80 since 64 < 80 <= 128)
- IsDrop = 1 (dropout enabled, keepProb < 1)
- D_NO_EQUAL: dNoEqual = (d1 != d) || hasRope. For D=80 without rope, d1 == d likely → 0. With rope → 1.
- splitAxis: depends on shape; typical FA grad uses BN2GS1S2 or BN2S2 or BN2.
- IsNzOut: depends on output layout.
- OutDType = 3 (FLOAT16_PRECISION, FP16 output)

Now let me check the ASCENDC_TPL_SEL table for FP16 (InputDType=3) entries with DTemplateNum=128 and IsDrop=1:
- Line 139-141: FP16, IsTnd=0, S1=128, S2=128, DTemplate=64,192,256,768 — NO 128! This is the non-TND non-deterministic case. Interesting: DTemplateNum 128 is missing in the first FP16 block.
- Line 161-163: FP16, IsTnd=0, DTemplate=128, IsNzOut=0,1 — has 128.
- Line 183-185: FP16, IsTnd=1, DTemplate=64,192,256,768 — NO 128.
- Line 205-207: FP16, IsTnd=1, DTemplate=128, IsNzOut=0,1 — has 128.
- Line 227-229: FP16, DeterType=1 (DETER_OLD), DTemplate=64,128,192,256,768 — has 128.
- Line 249-251: FP16, IsTnd=1, DeterType=1, DTemplate=64,128,192,256,768 — has 128.
- Line 271-273: FP16, DeterType=2,3,4, DTemplate=64,192,256,768 — NO 128! And IsNEqual=0,1. So DETER_DENSE/CAUSAL/BAND non-TND with DTemplate 128 missing!
- Line 293-295: FP16, DeterType=2,3,4, DTemplate=128, IsNzOut=0,1 — has 128.
- Line 315-317: FP16, IsTnd=1, DeterType=2,3,4, DTemplate=64,192,256,768 — NO 128.
- Line 337-339: FP16, IsTnd=1, DeterType=2,3,4, DTemplate=128, IsNzOut=0,1 — has 128.
- Line 359-361: FP16, IsTnd=1, DeterType=2,3,4, DTemplate=64,192,256,768, IsTndSwizzle=1 — NO 128.
- Line 381-383: FP16, IsTnd=1, DeterType=2,3,4, DTemplate=128, IsNzOut=0,1, IsTndSwizzle=1 — has 128.
- Line 395-415: FP16, SplitAxis=5 (BN2S2), IsTnd=1, DTemplate=64,128,192,256,768, DeterType=2,4, IsNEqual=1 — has 128.
- Line 417-427+: FP16, IsTnd=0, DTemplate=192 (line 427)... need to continue reading.

So the SEL table is NOT a full cross-product — it's a curated list of allowed combinations. The table covers most FP16 combos but there are specific rows where DTemplateNum=128 is excluded in the "64,192,256,768" rows, and included in the "128" rows. So whether the combo is covered depends on exactly which row the key matches.

Key question: does the ASCENDC_TPL_SEL mechanism match by exact combination (each SEL entry declares one row of instantiated templates), and if the host key doesn't match any row, the kernel won't be found → "kernel not found" error?

The mechanism: ASCENDC_TPL_ARGS_DECL declares the bit layout. ASCENDC_TPL_SEL with ASCENDC_TPL_ARGS_SEL entries declares which argument-value combinations are instantiated. Each ARGS_SEL entry enumerates values for each field. The framework compiles instantiations for each combination (cross product within a row). The runtime matches the tiling key from host against these rows; if no match → "kernel not found".

Wait, actually — I need to understand exactly how the SEL mechanism works: within one ASCENDC_TPL_ARGS_SEL block, the framework expands the cross-product of all listed values into individual template instantiations. So the set of valid keys = union over rows of cross-products. Host key must equal one of these.

For FP16, D=80 (DTemplate=128), dropout (IsDrop=1):
Row candidates (non-TND, non-deter, non-NZ):
- Row 153-174 (line 153): FP16, IsTnd=0, IsDrop=0,1, IsPse=0,1, IsAttenMask=0,1, S1=128, S2=128, DTemplate=128, DeterType=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=0,1, IsRope=0, OutDType=3, IsNzOut=0,1, IsTndSwizzle=0, IsRegbase=1 → covers FP16 D=80 dropout non-TND non-deter case ✓

So for a standard BN2GS1S2 (splitAxis=0), non-TND, non-deterministic, FP16, D=80, dropout: the key would be:
- IsEmptyTensor=0
- SplitAxis=0 (BN2GS1S2)
- InputDType=3
- IsTnd=0
- IsDrop=1
- IsPse=0 (no pse)
- IsAttenMask=0 (no atten mask)
- S1TemplateNum=128 (typical)
- S2TemplateNum=128
- DTemplateNum=128 (D=80)
- DeterType=0 (NO_DETER)
- IsNEqual=0 (non-deterministic → isDeterNEqual=0)
- IsBn2MultiBlk=0
- IsDNoEqual=0 (d1==d, no rope)
- IsRope=0
- OutDType=3
- IsNzOut=0
- IsTndSwizzle=0
- IsRegbase=1

This matches Row at lines 153-174. So the template should be instantiated and the key should hit.

BUT — the error is "kernel not found". When does this happen? One possibility: the ORIG_DTYPE_QUERY macro. The SEL table is guarded by #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16) (line 129). If the kernel is compiled with a specific ORIG_DTYPE_QUERY (e.g. DT_FLOAT for FP32-only build), then only that dtype's SEL rows are compiled. If the user runs FP16 but the binary was compiled with ORIG_DTYPE_QUERY = DT_FLOAT... but that would be a build config issue.

Actually wait — the more likely issue: the user runs on 950 (arch35) with FP16, D=80, dropout. The kernel "not found" error could come from the tiling key not matching any registered instantiation. Note that line 21 comment: "kernel通过宏定义隔离dtype编译tilingkey，降低耗时。tiling侧没有相关宏" — the kernel uses ORIG_DTYPE_QUERY macro to isolate dtype compilation of tiling keys.

Let me continue reading the rest of the SEL table (line 428+) to see the FP8 / BF16 / FP32 rows and see whether there are conditions that exclude FP16+dropout+D=80 combos. Also need to understand: in row 153-174, IsNzOut=0,1 — but host GetTilingKey passes fBaseParams.isNzOut. For FP16 normal output, isNzOut=0. OK.

Also important: what about the first row (lines 131-152): FP16 non-TND, DTemplate=64,192,256,768 — this covers D=64, 192, 256, 768 template values, but NOT 128. If host computes DTemplateType=128 for D=80, this row doesn't match. That's fine as long as row 153-174 exists.

Hmm, but wait — there's an important subtlety about how ASCENDC_TPL_SEL matching works. I recall in CANN's tiling template mechanism, the kernel is compiled per (key) with instantiations enumerated in the SEL table, and the runtime uses the tiling key to look up. If the key doesn't match any instantiation, the error is typically "can not find kernel ..." or similar. So the question is whether FP16+D=80+dropout is covered.

Let me also check: what about "D=80" — is that a supported head dim for FP16 in this operator? DTemplateType is a bucket (64/128/192/256/768). D=80 → 128. But note: within the kernel, DTemplateType(128) means the template parameter is 128, and the kernel handles D=80 by... let me check what the dTemplateType actually does — it's the D head-dim bucket used for loop bounds. That's a detail; for key matching, DTemplateNum=128 is what matters.

Also, I should check the mechanism of how the tiling key is looked up — the kernel registration in flash_attention_score_grad_apt.cpp (REGISTER_TILING...). The apt.cpp:39-57 uses template params: SplitAxis, InputDType, IsTnd, IsDrop, IsPse, IsAttenMask, S1TemplateNum, S2TemplateNum, DTemplateNum, DeterType, IsNEqual, IsBn2MultiBlk, IsDNoEqual, IsRope, OutDType, IsNzOut, IsTndSwizzle, IsRegbase — matching the 18 params of RegbaseFAG.

Let me read apt.cpp lines 30-60 to see the kernel entry and how the tiling key template args map. And also check whether there's a runtime "KERNEL NOT FOUND" path — e.g., ASCENDC_TPL_SEL compile-time generation. Also read more of the SEL table.

Let me continue reading the SEL table from line 428 to see remaining FP16 rows and other dtypes. The file is 1572 lines total. Let me read in a couple of large windows.
D=80 → GetDTemplateType 落到 NUM128（common_regbase.cpp:856-858）。继续读完 SEL 表剩余部分（428-1572），并看 apt.cpp 的 kernel 入口模板参数映射
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [limit=420, offset=428]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\flash_attention_score_grad_apt.cpp [limit=90, offset=1]
- Thought: 43.5s
Now I have a very clear picture of the FP16 SEL rows. Let me summarize the FP16 (InputDType=3) SEL rows and their DTemplateNum coverage, especially for the non-TND case (IsTnd=0) since the user case is 950 with FP16 (presumably BN2GS1S2 layout with normal tiling, but TND is possible).

FP16 rows (SplitAxis=0 unless noted):
1. L131-152: IsTnd=0, Deter=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=0,1, IsRope=0, IsNzOut=0, IsTndSwizzle=0, DTemplate={64,192,256,768} → NO 128
2. L153-174: IsTnd=0, Deter=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=0,1, IsRope=0, IsNzOut=0,1, IsTndSwizzle=0, DTemplate={128} → HAS 128
3. L175-196: IsTnd=1, Deter=0, ..., DTemplate={64,192,256,768} → NO 128
4. L197-218: IsTnd=1, Deter=0, ..., DTemplate={128}, IsNzOut=0,1 → HAS 128
5. L219-240: IsTnd=0, Deter=1 (DETER_OLD), DTemplate={64,128,192,256,768} → HAS 128
6. L241-262: IsTnd=1, Deter=1, DTemplate={64,128,192,256,768} → HAS 128
7. L263-284: IsTnd=0, Deter={2,3,4}, IsNEqual=0,1, DTemplate={64,192,256,768} → NO 128
8. L285-306: IsTnd=0, Deter={2,3,4}, IsNEqual=0,1, DTemplate={128}, IsNzOut=0,1 → HAS 128
9. L307-328: IsTnd=1, Deter={2,3,4}, DTemplate={64,192,256,768} → NO 128
10. L329-350: IsTnd=1, Deter={2,3,4}, DTemplate={128}, IsNzOut=0,1 → HAS 128
11. L351-372: IsTnd=1, Deter={2,3,4}, DTemplate={64,192,256,768}, IsTndSwizzle=1 → NO 128
12. L373-394: IsTnd=1, Deter={2,3,4}, DTemplate={128}, IsNzOut=0,1, IsTndSwizzle=1 → HAS 128
13. L395-416: SplitAxis=5 (BN2S2), IsTnd=1, Deter={2,4}, IsNEqual=1, IsBn2MultiBlk=0, DTemplate={64,128,192,256,768}, IsNzOut=0 → HAS 128
14. L417-438: IsTnd=0, Deter=0, IsDNoEqual=1, IsRope=1, DTemplate={192} (rope case) → NO 128 (but that's rope so D=80 → GetDTemplateType returns 192 for rope anyway — wait, GetDTemplateType: hasRope → NUM192. OK consistent!)
15. L439-460: IsTnd=1, Deter=0, IsDNoEqual=1, IsRope=1, DTemplate={192} → rope case
16. L461-482: IsTnd=0, Deter=1, IsDNoEqual=1, IsRope=1, DTemplate={192} → rope + deter
17. L483-504: IsTnd=1, Deter=1, IsDNoEqual=1, IsRope=1, DTemplate={192} → rope + deter TND
18. L505-526: IsTnd=0, Deter={2,3,4}, IsDNoEqual=1, IsRope=1, DTemplate={192} → rope + deter
19. L527-548: IsTnd=1, Deter={2,3,4}, IsDNoEqual=1, IsRope=1, DTemplate={192} → rope + deter TND
20. L549-570: IsTnd=1, Deter={2,3,4}, IsDNoEqual=1, IsRope=1, DTemplate={192}, IsTndSwizzle=1 → rope + deter + swizzle
21. L571-592: SplitAxis=1 (BN2), IsTnd=0, Deter=0, IsNEqual=0, IsBn2MultiBlk=0,1, IsDNoEqual=0,1, IsRope=0,1, DTemplate={64,128,192,256,768} → HAS 128 (BN2 non-TND)
22. L593-614: SplitAxis=1 (BN2), IsTnd=1, ..., DTemplate={64,128,192,256,768} → HAS 128
23. L615-636: SplitAxis=5 (BN2S2), IsTnd=0, Deter=0, ..., DTemplate={64,128,192,256,768} → HAS 128
24. L637-658: SplitAxis=5 (BN2S2), IsTnd=1, Deter=0, ..., DTemplate={64,128,192,256,768} → HAS 128
25. L659-680: SplitAxis=5 (BN2S2), IsTnd=1, Deter=0, ..., DTemplate={64,128,192,256,768}, IsTndSwizzle=1 → HAS 128

So for the FP16 non-TND, non-deterministic (Deter=0), D=80 (DTemplate=128), dropout case with SplitAxis=0 (BN2GS1S2):
- Key: IsDrop=1, IsPse=0/1, IsAttenMask=0/1, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=0/1, IsRope=0, IsNzOut=0, IsTndSwizzle=0, DTemplate=128
- Row 2 (L153-174) covers this: SplitAxis=0, IsTnd=0, InputDType=3, DTemplate=128, Deter=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=0,1, IsRope=0, IsNzOut=0,1 → covered ✓

But wait — there's an important caveat: Row 2 has IsNzOut=0,1. So NZ_OUT also covered. But what about IsBn2MultiBlk=1 (bit46)? For splitAxis=0 non-TND, rows only have IsBn2MultiBlk=0. Hmm, but isBn2MultiBlk is host-computed; for BN2GS1S2 is it ever 1? Let me check host: fBaseParams.isBn2MultiBlk is set somewhere. If the host sets IsBn2MultiBlk=1 for BN2GS1S2 non-TND, no SEL row matches (rows with IsBn2MultiBlk=0,1 only exist for SplitAxis=1 BN2). That could be a miss!

Actually wait, look at row 21/22 (BN2 splitAxis=1): IsBn2MultiBlk=0,1. And row 13 (BN2S2 splitAxis=5 TND): IsBn2MultiBlk=0. For BN2GS1S2 (splitAxis=0): all rows have IsBn2MultiBlk=0.

So if host computes splitAxis=0 AND isBn2MultiBlk=1 → no matching row → kernel not found. Need to check when host sets isBn2MultiBlk=1.

Also, the key question about what happens on miss: the ASCENDC_TPL_SEL mechanism — each ARGS_SEL generates a set of instantiations; at runtime, the tiling key must exactly match one generated key. If not → "kernel not found" error.

Another important caveat: which rows are compiled depends on ORIG_DTYPE_QUERY. In the build, the kernel is compiled multiple times (one per dtype) with ORIG_DTYPE_QUERY set to each dtype, and the tiling key includes InputDType bits; the runtime selects the compiled binary matching the tiling key. If the operator package was built with ORIG_DTYPE_QUERY=-1 (all dtypes in one binary), all rows are present. If built per-dtype... the FP16 rows need ORIG_DTYPE_QUERY=DT_FLOAT16 or -1.

Now for the user's case: FP16, D=80, dropout on 950. The key bits:
- InputDType=3 (FLOAT16_PRECISION)
- DTemplateNum=128 (D=80)
- IsDrop=1
- splitAxis: host fuzzy selection. For typical attention, splitAxis=BN2GS1S2 (0) or BN2S2 (5) or BN2 (1). Need to check GetSplitAxis logic — but the SEL table covers all three split axes for the FP16 Deter=0 non-TND case with DTemplate=128:
  - BN2GS1S2 (0): row 2 ✓
  - BN2 (1): row 21 ✓ (IsBn2MultiBlk=0,1)
  - BN2S2 (5): row 23 ✓ (IsBn2MultiBlk=0)
  
  Note for BN2S2 non-TND, only IsNzOut=0 (row 23). For BN2GS1S2 non-TND, IsNzOut=0,1 (row 2).

Now what about IsNEqual? isDeterNEqual = deterSparseType != DETER_OLD && deterSparseType != NO_DETER && g==1. For Deter=0 (NO_DETER), IsNEqual=0 always. OK.

What about IsBn2MultiBlk? Need to see host logic. If splitAxis != BN2 (i.e., for BN2GS1S2 or BN2S2), isBn2MultiBlk likely 0... but the SEL rows for BN2S2 TND (row 13) and BN2 (rows 21/22) include IsBn2MultiBlk variations. Let me check the host to see when isBn2MultiBlk=1.

Also what about D=80 specifically — wait, is D=80 even allowed? D head dim must be one of the DTemplateType buckets? No — the template bucket just needs D <= bucket value. D=80 → bucket 128. OK.

But there's a subtle thing: what if the host's d1 != d (D_NO_EQUAL)? For FA grad with different Q and KV head dims... For D=80 with dropout, if query head dim != key head dim → IsDNoEqual=1. Rows with IsDNoEqual=1 and DTemplate=128:
- Row 2: IsDNoEqual=0,1 ✓ (non-TND Deter=0)
- Row 5: Deter=1 with DTemplate=128 ✓
- Row 8: Deter={2,3,4} with DTemplate=128 ✓
So D_NO_EQUAL=1 with D=80 non-TND FP16 is covered by row 2 (IsDNoEqual=0,1).

Hmm wait — but the ROPE rows (14-20) have DTemplate={192} only, and host GetDTemplateType returns NUM192 for hasRope, so consistent.

So for a standard FP16 non-TND D=80 dropout case, the key should be covered by row 2 (L153-174). So why "kernel not found"?

Possibilities:
1. The build didn't include FP16 instantiations (ORIG_DTYPE_QUERY issue) — e.g., operator package built only for BF16/FP32; or the ASCENDC_TPL_SEL only instantiates rows for the compiled dtype, and the FP16 rows are under #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16) — if compiled with ORIG_DTYPE_QUERY = -1... wait, that means all dtypes' rows are present? Hmm, but the row inside still has InputDType=3 for FP16. Let me think about how the template mechanism works: ASCENDC_TPL_SEL generates instantiations of the global template function flash_attention_score_grad<...> for every combination listed in the ARGS_SEL rows. The compiled binary's kernel table (KernelBin) contains those instantiations with their keys. At runtime, the host tiling key is used to look up the kernel by key. If not found → error like "TilingKey not found" / "kernel not found".

2. The user's actual scenario may be TND (input layout TND with actual_seq_qlen). In that case IsTnd=1. Row 4 (L197-218) covers IsTnd=1, DTemplate=128, Deter=0, IsNzOut=0,1 → covered ✓.

3. IsTndSwizzle: for TND with swizzle enabled, rows 11/12 cover Deter={2,3,4} but NOT Deter=0 with DTemplate=128! Let me check: row 11 (L351-372): IsTndSwizzle=1, Deter={2,3,4}, DTemplate={64,192,256,768} (no 128). Row 12 (L373-394): IsTndSwizzle=1, Deter={2,3,4}, DTemplate={128}, IsNzOut=0,1 → has 128. But no row with IsTndSwizzle=1 and Deter=0 (NO_DETER)! And no row with IsTndSwizzle=1, Deter=1.

So if host computes IsTndSwizzle=1 AND DeterType=0 (NO_DETER, the common non-deterministic case), then NO SEL row matches → kernel not found! That's a real gap for TND+swizzle+non-deterministic.

But wait — when is IsTndSwizzle enabled? tndBaseInfo.isTndSwizzle — need to check host. It's probably only enabled for specific shapes/versions (TND + deterministic + certain dtype?). Let me check the host code for isTndSwizzle.

4. IsBn2MultiBlk=1 with splitAxis=0 → no row. Need host check.

Let me look at host: where isBn2MultiBlk and isTndSwizzle are set. Also the splitAxis determination. Let me query the UO KB and read the relevant host code.

Also — CRITICAL: I should double check the exact matching semantics of ASCENDC_TPL_SEL. In CANN (ascendc template), ASCENDC_TPL_SEL defines the "template selection table": the compiler generates one kernel instantiation per combination (cross product of each ARGS_SEL row), and the runtime hash-lookup by tiling key. The apt template function has template params matching the ASCENDC_TPL_ARGS_DECL fields. GET_TPL_TILING_KEY packs the values into the 64-bit key in the exact order of ASCENDC_TPL_ARGS_DECL.

Now the important question: GET_TPL_TILING_KEY signature at host line 1460-1468 passes 19 args in the DECL order (IsEmptyTensor=0 first). The order in the template function flash_attention_score_grad (apt.cpp:35-38) is the same 19 params. RegbaseFAG (entry_regbase.h:197-200) takes 18 params (no IsEmptyTensor — it's dispatched via if constexpr in apt). Good — consistent mapping.

Now, bit layout in key vs DECL: the DECL assigns:
- IsEmptyTensor bit 0 (1 bit)
- SplitAxis bits 3-1 (3 bits) — ASCENDC_TPL_3_BW
- InputDType bits 6-4 (3 bits)
- IsTnd bit 7
- IsDrop bit 8
- IsPse bit 9
- IsAttenMask bit 10
- S1TemplateNum bits 18-11 (8 bits)
- S2TemplateNum bits 28-19 (10 bits)
- DTemplateNum bits 40-29 (12 bits)
- DeterType bits 44-41 (4 bits)
- IsNEqual bit 45
- IsBn2MultiBlk bit 46
- IsDNoEqual bit 47
- IsRope bit 48
- OutDType bits 51-49 (3 bits)
- IsNzOut bit 52
- IsTndSwizzle bit 53
- IsRegbase bit 54

This matches the task description (SplitAxis bit3-1, InputDType bit6-4, IsBn2MultiBlk bit46, D_NO_EQUAL bit47, etc.)

Now let me check the host for isTndSwizzle and isBn2MultiBlk and splitAxis determination. Also GetS1S2TemplateType to confirm S1TemplateNum/S2TemplateNum=128 for typical shapes.

Actually, also need to think about what "kernel 找不到" (kernel not found) means concretely. In CANN there are two lookup layers:
1. Tiling-key based template instantiation table (ASCENDC_TPL_SEL / template_argument.h): compile-time-generated instantiations; runtime lookup by tiling key.
2. Binary selection by arch: each op has kernel binaries for arch35 etc.

If the tiling key doesn't match any instantiation in the compiled binary, error is typically "ERROR: the kernel with tilingKey=xxx is not found" or "kernel does not support this tilingKey" — this is the "找不到 kernel" scenario the user sees.

So my answer should: (a) explain the mechanism; (b) enumerate the FP16 D=80 dropout case key; (c) confirm the standard case IS covered (row 2 L153-174 / TND row 4 L197-218); (d) identify gaps: IsTndSwizzle=1 + Deter=0 (no row); IsBn2MultiBlk=1 + splitAxis=0 (no row); also BN2S2 TND non-deter row 24 has IsNzOut=0 only; BN2S2 + IsNzOut=1 + Deter=0 (non-TND row 23 has IsNzOut=0 only)... wait row 23 (L615-636) BN2S2 non-TND: IsNzOut=0. Is there a BN2S2 non-TND IsNzOut=1 row? Row 2 is SplitAxis=0. Hmm, for splitAxis=5 non-TND there's only row 23 with IsNzOut=0. But is BN2S2+NZ_OUT possible? Probably only for specific output formats.

Let me now check the host-side computation of isBn2MultiBlk, isTndSwizzle, splitAxis. Query the UO KB.
SEL 表 FP16 区已基本读完。关键还需 host 侧 isBn2MultiBlk、isTndSwizzle、splitAxis 的赋值逻辑，以及 S1/S2 模板编号的选择。并行
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern isBn2MultiBlk]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern isTndSwizzle]
- Thought: 32.2s
Key findings:

1. isBn2MultiBlk (common_regbase.cpp:1596-1606): bnSparseLimit && (s1 > BN2_MAX_S || s2 > BN2_MAX_S) && (s1 <= BN2_MULTIBLK_SEQ && s2 <= BN2_MULTIBLK_SEQ) && (n1 == n2) && d <= BN2_MAX_D && (queryType != DT_FLOAT) && (d == d1) && !(queryType is FP8...). And line 1608-1615: isBn2 = isBn2MultiBlk ? true : isBn2; if (isBn2 && !isBn2MultiBlk) { isDeterministic=false; if ((TND && d > ALIGN128) || dropMaskOuter) { isBn2=false; ... } }. Line 1616-1620: if (isBn2MultiBlk) { isDeterministic = false; if (dropMaskOuter) { isBn2MultiBlk = false; } }.

Wait, the snippet at 1616-1621 from the UO shows:
1616:    if (fBaseParams.isBn2MultiBlk) {
1617:        fBaseParams.isDeterministic = false;
and packing value site at 1620: fBaseParams.isBn2MultiBlk = false guarded by if (fBaseParams.isBn2MultiBlk) and if (fBaseParams.dropMaskOuter) — so if dropMaskOuter is true, isBn2MultiBlk is forced false!

Wait — is dropMaskOuter related to dropout? Need to check. Actually dropMaskOuter refers to the drop_mask being an outer tensor (separate tensor) rather than baked into... Hmm. Let me check what dropMaskOuter means. If the user has dropout with a drop_mask tensor input... that could be dropMaskOuter=true. If isBn2MultiBlk is forced to false when dropMaskOuter, then the key has IsBn2MultiBlk=0 → matches rows with IsBn2MultiBlk=0 → OK for FP16 non-TND.

But actually the important one: what does SetSplitAxis do at the end — fBaseParams.splitAxis = fBaseParams.isBn2 ? SplitAxisEnum::BN2 : SplitAxisEnum::BN2GS1S2; (line 691 in normal_regbase.cpp DoSparse, and similar in common). And also for TND (line 692: if (fBaseParams.layoutType == INPUT_FORMAT_TND)). Need to see the splitAxis for TND.

2. isTndSwizzle (normal_regbase.cpp:461-463): enableSwizzle && layoutType == TND && templateSupportCond && b < TND_SWIZZLE_PREFIX_NUM && !isSeqExistZero && tailZeroCount == 0. The templateSupportCond at lines ~456-460: (s2 > 128 && s1 >= TND_SWIZZLE_MIN_S1_SIZE_1) || ... — need to read. But crucially, isTndSwizzle requires TND layout.

Now — is there a gap for TND + swizzle + non-deterministic (Deter=0) + FP16 + DTemplate=128? From the SEL table:
- Row 11 (L351-372): IsTndSwizzle=1, Deter={2,3,4}, DTemplate={64,192,256,768} — no 128, no Deter=0
- Row 12 (L373-394): IsTndSwizzle=1, Deter={2,3,4}, DTemplate={128} — no Deter=0
- Row 20 (L549-570): IsTndSwizzle=1, Deter={2,3,4}, IsDNoEqual=1, IsRope=1, DTemplate={192}
- Row 25 (L659-680): IsTndSwizzle=1, SplitAxis=5, Deter=0, DTemplate={64,128,192,256,768}, IsDNoEqual=0,1, IsRope=0, IsNzOut=0 → HAS Deter=0 + DTemplate=128 + IsTndSwizzle=1 for splitAxis=5 (BN2S2)! 

Wait — row 25 is SplitAxis=5, IsTnd=1, Deter=0, DTemplate={64,128,192,256,768}, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=0,1, IsRope=0, OutDType=3, IsNzOut=0, IsTndSwizzle=1, IsRegbase=1. So for TND + BN2S2 + swizzle + non-deter + FP16 + D=80 (DTemplate=128) → covered ✓.

But for TND + BN2GS1S2 (splitAxis=0) + swizzle + non-deter (Deter=0) + DTemplate=128 → NOT covered (rows 11/12 only Deter={2,3,4}). 

Hmm, but does isTndSwizzle require a specific splitAxis? The templateSupportCond might require BN2S2. Let me read normal_regbase.cpp around 430-463 to see templateSupportCond and splitAxis selection for TND.

3. Also need to check IsNewDeter and deterSparseType — DeterType in the key comes from fBaseParams.deterSparseType (line 1464). DETER_OLD=1, DETER_DENSE=2, DETER_CAUSAL=3, DETER_BAND=4, NO_DETER=0. For non-deterministic mode (GetDeterministic()==0), deterSparseType=NO_DETER=0 presumably.

Wait, actually let me reconsider: maybe the "kernel not found" case is deterministic mode (deterSparseType != 0) with DTemplate=128 in certain combos? No — rows 5/6 (Deter=1) and 8/10 (Deter={2,3,4}) cover 128 for non-TND/TND. Row 8 (L285-306): IsTnd=0, Deter={2,3,4}, DTemplate={128}, IsNzOut=0,1 ✓.

OK so for the standard case, all covered. Let me now check:
- The splitAxis selection for the user case. For 950 (arch35) FA grad, the typical shapes: query B,N1,S1,D, key B,N2,S2,D. The splitAxis selection (SetSplitAxis in common_regbase.cpp around 1581-1621) — let me read that function fully, plus the TND splitAxis handling.
- Also the s1/s2 template: GetS1S2TemplateType — for S1/S2 template types (0, 64, 128, 512 / 0, 128, 256, 512). S1TemplateNum=128, S2TemplateNum=128 are the covered values in all FP16 rows. If host computes something else (e.g., S1=512 for long sequences), need rows... For FP16 rows, all have S1=128, S2=128. Hmm — what if the shape makes s1TemplateType=512 or 64? Those aren't in any FP16 SEL row! Interesting — but wait, GetS1S2TemplateType might clamp to 128 for FP16. Let me check.

Let me read:
1. common_regbase.cpp SetSplitAxis function (around 1560-1650)
2. normal_regbase.cpp DoOpTiling around 430-470 (isTndSwizzle templateSupportCond) 
3. GetS1S2TemplateType
4. The splitAxis handling for TND

Also I should check how the host decides between BN2GS1S2/BN2S2/BN2 for the user's case.
关键约束已浮现：isBn2MultiBlk（common_regbase.cpp:1596-1621）、isTndSwizzle（normal_regbase.cpp:461-463）。还需看 SetSplitAxis 完整逻辑、TND 的 splitAxis 选择、以及 GetS1S2TemplateType 是否 clamp 到 128。并行读窗口
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp [limit=130, offset=1540]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=80, offset=420]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GetS1S2TemplateType]
- Thought: 55.4s
Very important finding at normal_regbase.cpp:444-451 — isNzOut:

fBaseParams.isNzOut =
    (fBaseParams.splitAxis == SplitAxisEnum::BN2GS1S2 &&
     fBaseParams.d > NUM64 &&
     fBaseParams.d < NUM128 && fBaseParams.d % FP16_C0_SIZE != 0 &&
     !(queryType is FP8/FLOAT) &&
     fBaseParams.deterSparseType != DETER_OLD) &&
    fBaseParams.enableSwizzle && fBaseParams.s1 >= NZ_OUT_MIN_S_SIZE && fBaseParams.s2 >= NZ_OUT_MIN_S_SIZE;

For D=80: 64 < 80 < 128, 80 % 16 != 0 (80/16=5 exactly, so 80 % 16 == 0!). Wait, FP16_C0_SIZE — what is it? For FP16, C0=16. 80 % 16 = 0, so fBaseParams.d % FP16_C0_SIZE != 0 is FALSE for D=80. So isNzOut=0 for D=80. Good — the D=80 case has isNzOut=0.

Note: isNzOut additionally requires enableSwizzle && splitAxis==BN2GS1S2 && s1/s2 >= NZ_OUT_MIN_S_SIZE. For D=80, the % 16 check fails → isNzOut=0 always.

Also templateSupportCond (lines 453-460): isTndSwizzle requires !isDeterministic && splitAxis == BN2S2 && ... OR isDeterministic && splitAxis == BN2GS1S2 && deterSparseType == DETER_DENSE && false (the first branch is always false — note && false at line 455!). So in practice, isTndSwizzle=1 ONLY when splitAxis == BN2S2 (and TND layout, non-deterministic).

And we found row 25 (L659-680): SplitAxis=5 (BN2S2), IsTnd=1, Deter=0, DTemplate={64,128,192,256,768}, IsDNoEqual=0,1, IsNzOut=0, IsTndSwizzle=1 → covered for FP16 TND BN2S2 swizzle non-deter D=80. ✓

So the isTndSwizzle gap I hypothesized (TND+swizzle+Deter=0) is actually covered by row 25 since swizzle only applies to BN2S2 in non-deterministic mode. Good.

Now GetS1S2TemplateType (common_regbase.cpp:812-845): for FP16 (queryType not FLOAT/FP8/HIFP8), the else branch at line 830+: else if (AlignTo(s1, 16) > 16 || ...) — need to see the full function body to know what S1/S2 template types FP16 gets. Let me read lines 812-846 fully.

Also SetSplitAxis (common_regbase.cpp:1581-1649):
- isBn2 = s1<=BN2_MAX_S && s2<=BN2_MAX_S && n1==n2 && d<=BN2_MAX_D && queryType!=FLOAT && !FP8 && tailZeroCount==0
- isBn2MultiBlk: requires layoutType != TND, bnLimit (b*n1 >= 256 or >=128 with s1%128==0 && s2%128==0), (s1 > BN2_MAX_S || s2 > BN2_MAX_S), s1/s2 <= BN2_MULTIBLK_SEQ, n1==n2, d <= BN2_MAX_D, queryType != FLOAT, d == d1, !FP8, !hasRope
- If isBn2MultiBlk → isBn2 = true; if dropMaskOuter → isBn2=false, isBn2MultiBlk=false (line 1616-1623)
- splitAxis final: if !isBn2 && bn2S2RouteLimit → BN2S2 (and possibly layoutType forced TND if isAllSame); else if isBn2 → BN2; else → BN2GS1S2 (line 1641-1648)

bn2S2RouteLimit (lines 1631-1639): !hasRope && d <= BN2_MAX_D && (layoutType == TND || (isAllSame && !isDeterministic) || bn2S2NotTndLimit) && (keepProb >= 1 || (d <= NUM128 && keepProb < 1)) && n1==n2 && queryType != FLOAT && !FP8.

KEY INSIGHT for the user case: FP16, D=80, dropout (keepProb < 1). For BN2S2 route with dropout: d <= NUM128 && keepProb < 1 → 80 <= 128 ✓. So BN2S2 with dropout is allowed for D=80.

Now, what about the s1/s2 relationship? For non-TND: bn2S2NotTndLimit requires s1 < s2, s2 <= BN2S2_MAX_S, s2-s1 >= BN2_MAX_S, d <= BN2S2_WRITE_UB_D, !isSparse, !isDeterministic. For TND: just layoutType==TND && isAllSame && !isDeterministic (bn2S2RouteLimit). Hmm wait — for TND: layoutType == INPUT_FORMAT_TND || (isAllSame && !isDeterministic) || bn2S2NotTndLimit — so TND layout automatically allows BN2S2 (subject to the rest: !hasRope, d<=BN2_MAX_D, keepProb condition, n1==n2, !FLOAT, !FP8, and NOT isBn2 first).

Now the question for the user's case: FP16, D=80, dropout, on 950. What's the actual splitAxis? Depends on shapes:
- If s1/s2 large enough or TND → BN2S2 or BN2GS1S2.
- The key: splitAxis is what it is; all three splits are covered in the FP16 SEL table for the non-TND D=80 dropout non-deter case:
  - BN2GS1S2 (0): row 2 (L153-174) — IsDrop=0,1, IsDNoEqual=0,1, IsNzOut=0,1, DTemplate=128 ✓
  - BN2 (1): row 21 (L571-592) — DTemplate={64,128,192,256,768}, IsBn2MultiBlk=0,1, IsDrop=0,1, IsDNoEqual=0,1, IsRope=0,1, IsNzOut=0 ✓ — BUT wait: for BN2 with dropout... SetSplitAxis: if isBn2 && dropMaskOuter → isBn2=false. But if dropMaskOuter is false, BN2 with dropout is possible. Row 21 covers IsDrop=0,1 ✓.
  - BN2S2 (5): row 23 (L615-636) — DTemplate={64,128,192,256,768}, IsDrop=0,1, IsDNoEqual=0,1, IsNzOut=0 ✓

So the standard FP16 D=80 dropout non-TND non-deter case IS covered regardless of splitAxis.

For TND (IsTnd=1): rows 4 (L197-218, splitAxis=0 DTemplate=128), 22 (L593-614, splitAxis=1 DTemplate=64..768), 24 (L637-658, splitAxis=5 DTemplate=64..768 IsNzOut=0), 25 (L659-680, splitAxis=5 + swizzle + IsNzOut=0). All cover IsDrop=0,1, IsDNoEqual=0,1, Deter=0.

Hmm wait — row 4 has IsNzOut=0,1 and covers IsDNoEqual=0,1? Let me re-check row 4 (L197-218): IsTnd=1, DTemplate=128, Deter=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=0,1 (line 211), IsRope=0, IsNzOut=0,1 (line 214), IsTndSwizzle=0, IsRegbase=1 → ✓.

So in ALL standard FP16 D=80 dropout cases (any splitAxis, TND or not, DETER=0), the key matches an SEL row. Where could it fail?

Remaining suspicious gaps for FP16:
1. S1/S2 template type ≠ 128: If the shape makes GetS1S2TemplateType return S1=64/S2=128 or S1=128/S2=256 etc. for FP16, no FP16 row covers it (all FP16 rows have S1=128, S2=128). Need to check the FP16 path in GetS1S2TemplateType (line 830-845).
2. IsBn2MultiBlk=1 with dropMaskOuter: forced false at line 1618-1621. But what about isBn2MultiBlk=1 WITHOUT dropMaskOuter? Then splitAxis=BN2 (line 1644-1645). Row 21/22 cover IsBn2MultiBlk=0,1 → covered ✓. But wait — for BN2 + isBn2MultiBlk=1 + TND? isBn2MultiBlk requires layoutType != TND (line 1593), so BN2 multi-blk is never TND. Row 21 (non-TND) covers IsBn2MultiBlk=0,1 ✓.
3. Rope: user case has no rope presumably. Rope rows (Deter=0): only DTemplate={192} (rows 14/15). Host GetDTemplateType returns 192 for hasRope — consistent. Also IsDNoEqual=1 forced for rope (dNoEqual = (d1!=d) || hasRope). OK.
4. IsNEqual=1: isDeterNEqual = deterSparseType not in {0,1} && g==1. For Deter=2,3,4 rows, IsNEqual=0,1 covered.

So where's the "kernel not found"? Let me think about what "kernel 找不到" actually means in CANN runtime for these AscendC template operators. 

The runtime dispatch: after host tiling computes the tiling key, the runtime looks up the compiled kernel binary by (opType, key). The compiled binary has the list of instantiated template keys from ASCENDC_TPL_SEL. If no match → error "kernel not found" (often "AICoreError" or "TilingKey not found", or in GE logs "get kernel by tiling key failed").

Given the user's case is FP16 D=80 dropout — the most likely candidates for failure:

A. D=80 → DTemplateType=128, but the FP16 non-TND DETER=0 row 1 (L131-152) has DTemplate {64,192,256,768} — NO 128. Wait, but row 2 (L153-174) has DTemplate={128}. Both rows are within the same #if ORIG_DTYPE_QUERY==DT_FLOAT16. Both are in the table. So DTemplate=128 IS covered by row 2. Unless... hmm.

Hold on. Let me re-examine: are these SEL rows AND-ed or OR-ed? Each ASCENDC_TPL_ARGS_SEL is an alternative; the union covers all. Row 2 covers D=80 FP16 non-TND non-deter. So covered.

B. ORIG_DTYPE_QUERY compile-time: The rows are guarded #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16). In the actual kernel build, ORIG_DTYPE_QUERY is defined per compile unit. If the operator was built with a specific dtype macro (say the build system compiles the kernel 3 times: FP16, BF16, FP32 with ORIG_DTYPE_QUERY set accordingly), then each binary has only its own dtype's rows. The InputDType bit also distinguishes. This shouldn't cause a miss for FP16 as long as an FP16 build exists.

C. The real gotcha — d1 != d (D_NO_EQUAL) + dropout + D=80: covered by row 2 (IsDNoEqual=0,1).

D. What about IsBn2MultiBlk + dropout: covered (row 21/22 for BN2; dropMaskOuter forces it false anyway).

E. S1TemplateNum/S2TemplateNum: For FP16, GetS1S2TemplateType line 830+ — need to read. If FP16 gets S1=64 (e.g., for small s1) or S1=512, no FP16 row has those! Wait — DECL allows S1TemplateNum ∈ {0, 64, 128, 512} and S2TemplateNum ∈ {0, 128, 256, 512}. The FP16 SEL rows ALL use 128/128. If host computes e.g. S1=64 for small sequences, the key won't match any FP16 row → kernel not found! Let me read GetS1S2TemplateType lines 830-846 to see the FP16 path.

Let me also double check the empty tensor path — the user's D=80 dropout case is not empty.

Also potential issue: D=80 with FP16 and dropout — is there a known limitation where FP16+dropout+BN2GS1S2 non-TND works but BN2S2+dropout requires d<=128 — the bn2S2RouteLimit already restricts to d<=128 with keepProb<1. 80<=128 ✓.

Let me read GetS1S2TemplateType full body. And also check where s1TemplateType is used for the tiling key (fBaseParams.s1TemplateType).
isNzOut 对 D=80 恒为 0（80 % 16 == 0，normal_regbase.cpp:447）。isTndSwizzle 只在 BN2S2 非确定性下生效（:453-460），SEL 表 row 25 覆盖。现在必须确认 FP16 的 S1/S2 模板编号是否恒为 128——读 GetS1S2TemplateType 完整函数
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp [limit=60, offset=812]
- Thought: 1m 39s
Critical finding: GetS1S2TemplateType for FP16 (line 830-844):
- If (align16(s1) > 16 || align16(s2) > 16) && align16(s1)*align16(s2) >= 128*128 → S1=128, S2=128
- Else (fallthrough at 843-844): S1=128, S2=128 — always 128/128 for FP16!

So FP16 always gets S1TemplateNum=128, S2TemplateNum=128. Good — no gap there. (The FLOAT d>256 gets 64/128, FP8 gets 64/256, HIFP8 gets 512/512 — those are other dtypes.)

Now let me verify the full picture for the user's FP16 D=80 dropout case:

Key composition (assuming standard non-TND, non-deterministic, no rope, no pse/atten_mask, BN2GS1S2 or BN2S2 or BN2):
- IsEmptyTensor=0 (bit0)
- SplitAxis: 0/1/5 (bits3-1)
- InputDType=3 (FLOAT16_PRECISION) (bits6-4)
- IsTnd=0 (bit7)
- IsDrop=1 (dropout, keepProb<1) (bit8)
- IsPse=0/1 (bit9) — pse only if pse_shift present
- IsAttenMask=0/1 (bit10)
- S1TemplateNum=128 (bits18-11)
- S2TemplateNum=128 (bits28-19)
- DTemplateNum=128 (bits40-29) — D=80
- DeterType=0 (NO_DETER) (bits44-41) — non-deterministic
- IsNEqual=0 (bit45)
- IsBn2MultiBlk=0 or 1 (bit46)
- IsDNoEqual=0 (bit47) — d1==d, no rope
- IsRope=0 (bit48)
- OutDType=3 (bits51-49) — FP16 output
- IsNzOut=0 (bit52) — D=80 %16==0
- IsTndSwizzle=0 (bit53)
- IsRegbase=1 (bit54)

This key matches:
- splitAxis=0 (BN2GS1S2) non-TND: row 2 L153-174 ✓ (DTemplate=128, Deter=0, IsDrop=0,1, IsDNoEqual=0,1, IsNzOut=0,1)
- splitAxis=1 (BN2) non-TND: row 21 L571-592 ✓ (DTemplate=64,128,..., IsBn2MultiBlk=0,1, IsDrop=0,1)
- splitAxis=5 (BN2S2) non-TND: row 23 L615-636 ✓ (DTemplate=64,128,..., IsDrop=0,1, IsNzOut=0)

And for TND (IsTnd=1):
- splitAxis=0: row 4 L197-218 ✓
- splitAxis=1: row 22 L593-614 ✓
- splitAxis=5: row 24 L637-658 ✓ (IsNzOut=0)
- splitAxis=5 + swizzle: row 25 L659-680 ✓

So the key SHOULD be found. The template selection mechanism guarantees a hit for the standard FP16 D=80 dropout case.

BUT — wait. I need to double-check the ASCENDC_TPL_SEL semantics. There's a subtlety: maybe each ASCENDC_TPL_ARGS_SEL row is NOT an alternative but the instantiation set is generated per row, and the runtime hash is per instantiated (key → binary). The union of all rows is the instantiation table. Since row 2 covers the user key, it should be instantiated.

However — there is one more important consideration: the empty tensor rows / IsEmptyTensor=0 vs the & 0x1 key registration (apt.cpp:57). Not relevant.

Now, let me consider the more subtle "kernel not found" paths:

1. Dropout with BN2GS1S2 + D=80 in the FIRST FP16 row — wait no, row 2 covers it.

2. What if the user's case is D=80 with keepProb < 1 AND the FP16 row 1 (L131-152) is the only row enabled in some build? No — row 1 and row 2 are in the same #if block, both compiled.

3. IsRegbase=1: All FP16 rows have IsRegbase=1. Host always sets isRegbasePlatformValue=ENABLE. ✓

4. The IsEmptyTensor first arg in GET_TPL_TILING_KEY is hardcoded 0 (host line 1460-1461), and the empty tensor path (tiling.cpp:237) uses TILING_KEY_1 = 1? The empty tensor key sets TILING_KEY1 (=1?) at bit0... Actually host line 237: GET_TPL_TILING_KEY(TILING_KEY_1, 0, ..., TILING_KEY_1) — hmm, that's the empty tensor path with first arg TILING_KEY1. Not relevant for the user's case.

5. Dropout without drop_mask tensor input? — not a key bit; IsDrop is only keepProb<1. Fine.

6. D=80 with hasRope? — not the case described.

7. What about the d1 != d scenario where query D=80, key D=80 but dropout... no.

Hmm, wait. Let me reconsider. Maybe the "kernel 找不到" is not about the SEL table at all. Let me think about what the user actually experiences on 950 (arch35): "报 kernel 找不到" — this could be the GE/AICPU error "Kernel not found by tilingKey" OR it could be the AscendC runtime "kernel binary not found for arch".

Actually — hold on. Let me reconsider the D=80 constraint more carefully. D=80 for FP16: is it a "supported" head dim? The DTemplateType buckets are 64/128/192/256/768. D=80 → bucket 128. The kernel then processes D=80 with the D=128 template. But wait — what about the D=80 % 16 != 0 condition I saw in isNzOut? 80 % 16 == 0, so isNzOut=0. OK.

BUT — there's BN2S2_WRITE_UB_D and other D limits. For dropout+BN2S2: d <= NUM128 && keepProb < 1 — 80 <= 128 ✓.

Let me also reconsider: maybe the problem is the first FP16 row for non-TND has DTemplate {64,192,256,768} and hosts could compute DTemplateType=128 — wait, but that's row 1, and row 2 covers 128. Both are present. Unless... there's an issue with how the runtime matches keys when MULTIPLE rows produce keys that differ only in DTemplateNum — no, they're distinct keys.

Hmm, wait — actually, I should look again at the row 1/row 2 distinction. Both are FP16 non-TND non-deter. Row 1: DTemplate {64,192,256,768}, IsNzOut=0. Row 2: DTemplate {128}, IsNzOut=0,1. Why split into two rows? Because DTemplate=128 + NZ_OUT is supported, but DTemplate={64,192,256,768} + NZ_OUT is NOT (the FP16 NZ_OUT support only for D=128 template?). And D=80 is exactly the NZ_OUT scenario (64<d<128, d%16!=0 → isNzOut=1)! Wait — D=80 % 16 == 0 → isNzOut=0. But for D=72 or D=100, isNzOut=1 (72%16≠0, 100%16≠0) and splitAxis==BN2GS1S2 + enableSwizzle + s1/s2 >= NZ_OUT_MIN_S_SIZE. Then DTemplateType=128 (64<d<128) and IsNzOut=1 → matches row 2 (IsNzOut=0,1) ✓. So NZ_OUT+D=128-template is exactly row 2's purpose.

OK so for D=80 specifically: isNzOut=0 always. Row 2 covers it (IsNzOut=0). Fine.

So for the user's exact case (FP16, D=80, dropout): the tiling key SHOULD hit. So why "kernel not found"?

Possibilities remaining:
1. The runtime error is NOT about the tiling key table — it's about the compiled kernel binary missing for the arch (e.g., the operator package for arch35 wasn't built with FP16 support, or binary selection by ORIG_DTYPE_QUERY). The ORIG_DTYPE_QUERY macro: if the kernel .cpp is compiled with ORIG_DTYPE_QUERY defined per-dtype (build splits), and the FP16 compile produced the binary, then InputDType=3 rows exist in the FP16 binary. If the build only produced BF16 (ORIG_DTYPE_QUERY=DT_BF16), then FP16 keys don't exist → "kernel not found". This is a build/packaging question, not a code logic question — PARTIAL.

2. The D=80 is not a legal "D" for this operator's FP16 support — maybe FP16 requires d % 16 == 0 or specific D values. Let me check if there's a shape validation that allows D=80 at all. Actually, the user says "跑 FP16、D=80、带 dropout ... 报 kernel 找不到". Let me check if D=80 passes host validation (CheckParams) — if validation rejects D=80, the error would be different ("not supported" not "kernel not found"). Let me search for D validation.

3. Is there a different tiling path (e.g., TilingNormalRegbase vs another tiling for arch35)? The user's arch35 → FlashAttentionScoreGradTilingNormalRegbase (per normal_regbase.cpp:423-425, DAV_3510 → hit).

4. Check the ASCENDC_TPL_SEL compile guards: the FP16 block requires ORIG_DTYPE_QUERY == -1 or DT_FLOAT16. If the kernel build defines ORIG_DTYPE_QUERY=-1 (all dtypes), then ALL dtype rows (FP16, BF16, FP32, FP8) are compiled into ONE binary. Hmm wait — actually if ORIG_DTYPE_QUERY == -1, then ALL blocks compile (FP16 block because -1 matches, BF16 block because -1 matches, etc.)? That would give one huge binary. And at runtime, the key's InputDType bits select the right instantiation. That works.

   BUT if ORIG_DTYPE_QUERY == DT_FLOAT16 (per-dtype build), then only FP16 rows exist in the FP16 binary, and the framework has 3-4 binaries with the same opType, distinguished at runtime by... the key's InputDType bits presumably. Both approaches work IF the packaging includes the right binaries.

5. IsDrop bit 8 vs the DECL order: I should double-check that GET_TPL_TILING_KEY argument order matches the DECL order. Host line 1460-1468 passes: (0=IsEmptyTensor, splitAxis, inputDtype, isTnd, dropValue, pseValue, attenMaskCfg, s1TemplateType, s2TemplateType, dTemplateType, deterSparseType, isDeterNEqual, isBn2MultiBlk, dNoEqual, hasRope, outDtype, isNzOut, isTndSwizzle, isRegbasePlatformValue). DECL order: IsEmptyTensor, SplitAxis, InputDType, IsTnd, IsDrop, IsPse, IsAttenMask, S1TemplateNum, S2TemplateNum, DTemplateNum, DeterType, IsNEqual, IsBn2MultiBlk, IsDNoEqual, IsRope, OutDType, IsNzOut, IsTndSwizzle, IsRegbase. ✓ matches.

Now — the question in the task asks: "host 算出的 key 是否保证存在对应实例化" — i.e., does the SEL table guarantee coverage of arbitrary legal key combos, or is it conditionally pruned? I've now mapped the FP16 part. The answer: the table is a curated list (NOT full cross-product), but for the FP16 D=80 dropout case every splitAxis/TND/NZ_OUT combination IS covered, with two notable exceptions to flag:
- The FP16 non-TND DETER=0 rows split DTemplateNum coverage: row 1 {64,192,256,768} vs row 2 {128}. So D=80 (→128) relies on row 2; D≤64 (→64) relies on row 1. If D were 65-128 → 128 ✓. OK.
- Actually wait, there IS a real gap: **FP16 + IsTnd=1 + Deter=1 (DETER_OLD) + DTemplate... row 6 covers {64,128,192,256,768} ✓. No gap.
- FP16 + TND + DETER=2,3,4 + DTemplate=128 + IsTndSwizzle=1: row 12 covers {128} IsNzOut=0,1 ✓.
- FP16 + TND + DETER=2,3,4 + DTemplate=128 + IsTndSwizzle=0: row 10 covers ✓.
- FP16 + IsTnd=0 + DETER=2,3,4 + DTemplate=128: row 8 covers ✓.
- FP16 + DETER=1 + DTemplate=128: rows 5/6 ✓.

So honestly, for the user's case the SEL table has coverage. Unless the host computes something outside the rows:
- S1TemplateNum/S2TemplateNum: always 128/128 for FP16 ✓ (common_regbase.cpp:838-844).
- DeterType: what does host set for non-deterministic? deterSparseType. Need to verify: for GetDeterministic()==0, deterSparseType=NO_DETER(0) → row 2 ✓. For deterministic mode... rows 7-10. What if the user's environment has deterministic enabled? Then deterSparseType could be DETER_OLD (1), DETER_DENSE (2), DETER_CAUSAL (3), DETER_BAND (4). Rows 5-10 cover DTemplate=128 for both TND and non-TND. ✓.
- BUT: what about IsBn2MultiBlk=1 + splitAxis... For BN2 (splitAxis=1): row 21 covers IsBn2MultiBlk=0,1 ✓. For BN2GS1S2 (splitAxis=0): all rows have IsBn2MultiBlk=0. Is it possible for host to set isBn2MultiBlk=1 while splitAxis=BN2GS1S2? Looking at SetSplitAxis: isBn2MultiBlk → isBn2=true → splitAxis=BN2 (line 1644-1645). So no. And DoSparse line 680-685: if splitAxis==BN2 && isBn2MultiBlk && (isInvalidCol||isInvalidRow) → isBn2=false, isBn2MultiBlk=false, splitAxis=BN2GS1S2. So splitAxis=BN2GS1S2 always has isBn2MultiBlk=0. ✓ consistent.
- TND + BN2GS1S2 + isTndSwizzle: impossible (templateSupportCond requires BN2S2 for non-deter) ✓.

So the SEL coverage for the user's case is fine. Therefore the "kernel not found" is likely:
1. A build/packaging issue (FP16 instantiation not compiled into the delivered binary — ORIG_DTYPE_QUERY mismatch), or
2. A shape/route mismatch: e.g., the host computes splitAxis=BN2S2 + IsTnd=1 + IsNzOut=1 — wait row 24/25 have IsNzOut=0 only for BN2S2 TND. Can host produce IsNzOut=1 with splitAxis=BN2S2? isNzOut requires splitAxis==BN2GS1S2 (normal_regbase.cpp:445) — so BN2S2 → isNzOut=0. ✓.
3. A mismatch between the DECL value domain and host enum values: e.g., SplitAxis host enum values. Host SplitAxisEnum: BN2GS1S2, BN2, BN2S2 — but the DECL says SplitAxis values {0, 1, 5} where 0: BN2GS1S2, 1: BN2, 5: BN2S2. Host passes static_cast<uint8_t>(splitAxis) — if host enum BN2S2 == 5? Need to check the enum definition. If host enum BN2S2 == 2 (not 5), the key would have SplitAxis=2, which no SEL row has → kernel not found! This is a strong candidate. Let me check SplitAxisEnum.

Let me query the SplitAxisEnum definition. Also DtypeEnum/OutDtype: OutDType passed = fBaseParams.outDtype — check the host outDtype value for FP16: should be 3 (FLOAT16_PRECISION)? If host outDtype is something else (e.g., 0 or 1=FLOAT32), mismatch. Need to check where outDtype is set.

Let me query SplitAxisEnum and outDtype in the UO KB.
FP16 的 S1/S2 模板编号恒为 128/128（common_regbase.cpp:838-844），无 gap。现在排查 host 侧枚举值与 SEL 位域 value domain 是否一致——特别是 SplitAxisEnum（DECL 里 BN2S2=5）与 `out
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern SplitAxisEnum]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern BN2GS1S2]
- Thought: 2.6s
SplitAxis enum values confirmed:
- kernel: constexpr uint8_t BN2GS1S2 = 0; BN2 = 1; BN2S2 = 5; (flash_attention_score_grad_common.h:93-95)
- SEL DECL: SplitAxis values {0, 1, 5} (template_tiling_key.h:56) — consistent with kernel constants.

Now I need to verify the host SplitAxisEnum values match. The host uses SplitAxisEnum::BN2GS1S2 etc. — I need to find its definition. It's likely in a shared header (flash_attention_score_grad_tiling_common_regbase.h or an enum in the host). Let me check the host enum. Also DtypeEnum::FLOAT16_PRECISION value and outDtype set. And check DeterSparseType values (NO_DETER=0, DETER_OLD=1, etc.).

Also — one thing I haven't checked: the host SplitAxisEnum might be defined in the same header as the kernel constants, or in the host tiling data header. Let me query for the enum definition. Also check outDtype — where is fBaseParams.outDtype set (should be 3 for FP16)?

Let me query:
1. SplitAxisEnum definition (enum class values)
2. outDtype assignment
3. DeterSparseType values
枚举值 kernel 侧确认（common.h:93-95：BN2GS1S2=0, BN2=1, BN2S2=5，与 SEL 表一致）。还需确认 host 侧 SplitAxisEnum/DeterSparseType/outDtype 的具体数值
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern outDtype]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern DeterSparseType]
- Thought: 40.0s
Key facts:
- outDtype = inputDtype (common_regbase.cpp:1182, ProcessQuantInfo) — for FP16, inputDtype=3 (FLOAT16_PRECISION, per DetermineMode:1653-1666 "当前fp16都走高精度") → outDtype=3. ✓ matches SEL OutDType=3.
- deterSparseType = GetDeterSparseTilingKey() (normal_regbase.cpp:663). Need to check GetDeterSparseTilingKey to see when it returns NO_DETER (0). For non-deterministic mode it should return NO_DETER. Let me check that function quickly.

So the whole FP16 D=80 dropout chain looks consistent. The key should hit. So why kernel not found?

Wait — I should double-check one more critical thing: Is the tiling key lookup done against the compiled kernel binary, or is the "kernel not found" error related to ORIG_DTYPE_QUERY builds? Let me think about the ASCENDC_TPL_SEL mechanism more concretely:

In AscendC (CANN), the ASCENDC_TPL_ARGS_DECL + ASCENDC_TPL_SEL + ASCENDC_TPL_ARGS_SEL macros are from ascendc/host_api/tiling/template_argument.h (the SDK). The compiler (ccec) reads these macros to generate instantiations of the global template kernel flash_attention_score_grad<...> for each SEL combination, and builds a lookup table keyed by the tiling key (packed per ARGS_DECL bit layout). At runtime, the host tiling sets the key via context->SetTilingKey(...); the runtime looks up the instantiated kernel by that key. If no match → typically error "KernelTilingKey not found" / "can not find kernel" (in CANN: "Can not find the kernel which tilingKey=..." or "kernel not found: FlashAttentionScoreGrad_xxx").

Now — the FP16 rows are inside #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16). Question: how is ORIG_DTYPE_QUERY defined during the actual kernel build? Let me check the build config (CMakeLists / op_impl). If the operator is built with ORIG_DTYPE_QUERY=DT_FLOAT16 (per-dtype kernel binaries), then the FP16 rows compile into the FP16 binary — fine. If built with -1, all rows compile.

BUT there's a subtlety: if (ORIG_DTYPE_QUERY == DT_FLOAT16) at entry_regbase.h:223 — the RegbaseFAG function body has #if (ORIG_DTYPE_QUERY == DT_FLOAT16) ... #endif blocks. If ORIG_DTYPE_QUERY == -1, NONE of the dtype blocks inside RegbaseFAG compile! Wait no — if ORIG_DTYPE_QUERY == -1, then #if (ORIG_DTYPE_QUERY == DT_FLOAT16) is #if (-1 == DT_FLOAT16) → false; #if (-1 == DT_BF16) → false; #if (-1 == DT_FLOAT) → false. So RegbaseFAG would have an EMPTY body → no code! That would be a compile error or a no-op kernel...

Hmm, that suggests ORIG_DTYPE_QUERY is never -1 in the actual kernel build — it's defined per build as a specific dtype (DT_FLOAT16, DT_BF16, DT_FLOAT, or FP8...). Actually wait — but then with ORIG_DTYPE_QUERY=DT_FLOAT16, the SEL table's #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16) includes ONLY the FP16 rows (InputDType=3). And the kernel entry if (ORIG_DTYPE_QUERY == DT_FLOAT16) at apt.cpp:60-64 and RegbaseFAG:223-243 compile the FP16 body. Consistent: each dtype gets its own kernel binary, and only that dtype's SEL rows are in it.

Then the runtime: how does it choose the binary? By the tiling key's InputDType bits presumably (the key includes InputDType=3 for FP16). If the operator package for arch35 has FP16 binary, the FP16 keys resolve. The user's error suggests the FP16 binary or the specific key is missing.

Hmm wait, actually I recall in CANN the ASCENDC_TPL_SEL mechanism with the macro ASCENDC_TPL_ARGS_SEL — the "kernel selection table" gets baked into the kernel meta (json) during compile, and the tiling key lookup happens against that table. If host computes a key not in the table → the error message is usually "TilingKey is not in the KernelTilingKey..." or "kernel not found". 

So the final analysis for the user's case:

Case: FP16, D=80, dropout (keepProb<1), non-deterministic, no rope/pse/atten_mask (typical):
- key: SplitAxis=0 or 5 (or 1), InputDType=3, IsTnd=0, IsDrop=1, IsPse=0, IsAttenMask=0, S1=128, S2=128, DTemplate=128, Deter=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=0, IsRope=0, OutDType=3, IsNzOut=0, IsTndSwizzle=0, IsRegbase=1
- SEL rows that match:
  - splitAxis=0: row L153-174 ✓
  - splitAxis=1: row L571-592 ✓
  - splitAxis=5: row L615-636 ✓
- So the key IS in the table — provided the FP16 rows were compiled into the delivered kernel binary.

So the "kernel not found" must come from either:
1. The delivered kernel binary doesn't include FP16 rows (build/packaging: ORIG_DTYPE_QUERY mismatch, missing FP16 compile unit, or the binary selection doesn't find arch35 FP16 binary), OR
2. The actual case differs from the standard one in a way that misses the table. E.g.:
   - IsTnd=1 + splitAxis=0 + IsTndSwizzle=1 + Deter=0: impossible per templateSupportCond (swizzle requires BN2S2 for non-deter).
   - IsDNoEqual=1 (d1 != d) + DTemplate=128: row 2 has IsDNoEqual=0,1 ✓; row 4 ✓ (TND). Rows 21-25 (BN2/BN2S2) have IsDNoEqual=0,1 ✓.
   - IsBn2MultiBlk=1 + splitAxis=0: impossible (SetSplitAxis guarantees splitAxis=BN2 when isBn2MultiBlk; DoSparse:680-685 resets to BN2GS1S2 with isBn2MultiBlk=0).
   - keepProb<1 + BN2S2 + D>128: bn2S2RouteLimit forbids (line 1635-1636). But if somehow BN2S2 + D>128 + dropout happened, the key DTemplate=192+ with IsDrop=1 + splitAxis=5 non-TND → row 23 has DTemplate=64,128,192,256,768 → actually still covered! Hmm wait row 23 DTemplate={64,128,192,256,768} — yes covered even for D>128 with dropout. But bn2S2RouteLimit prevents it anyway.
   - What if the head dim is such that DTemplateType=768 but the user says D=80 — no, D=80 → 128.

Hmm — wait. Actually, let me reconsider the exact scenario. The user says "报 kernel 找不到" (reports kernel not found). What if the host actually does NOT go through FlashAttentionScoreGradTilingNormalRegbase but through a different tiling (e.g., varlen/tiling.cpp) for their input format? E.g., if input layout is BSND vs TND vs BS2N2GD... The user didn't specify layout. The default BSND non-varlen path → normal_regbase. If TND → could be varlen_regbase which has its own splitAxis logic.

Also — I realize I should verify the GetDeterSparseTilingKey to confirm Deter=0 for non-deterministic. And also check the arch35 platform support: IsTilingNeed / GetSupportInfo — maybe FP16 is not supported on arch35 in this operator version? The task says "用户 950 (arch35) 上跑 FP16" — but maybe the operator's arch35 support excludes FP16? Let me check the support logic — FlashAttentionScoreGradTilingNormalRegbase::IsTilingNeed (normal_regbase.cpp:420-428 showed DAV_3510 → true, but there may be a dtype check above).

Let me read normal_regbase.cpp around 380-428 (IsTilingNeed / support check) and GetDeterSparseTilingKey.
outDtype = inputDtype（common_regbase.cpp:1182）→ FP16 时 OutDType=3 ✓。还需要确认 arch35 平台支持判定（IsTilingNeed，normal_regbase.cpp:380-428 可能含 dtype 限制）和 GetDeterSparseTilingKey（决定 DeterType 位
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=70, offset=355]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GetDeterSparseTilingKey]
- Thought: 24.8s
Confirmed:
- GetDeterSparseTilingKey (normal_regbase.cpp:790-814): non-deterministic → NO_DETER (0). ✓ So a non-deterministic run has DeterType=0 → matches FP16 rows 2/4/21/22/23/24/25.
- IsCapable (normal_regbase.cpp:413-428): arch35 (DAV_3510) → "基础模板 全部支持" → true (unless tndSoftmaxIn attr non-empty). No dtype restriction here.

So the host-side tiling key for FP16 D=80 dropout non-deterministic is well-defined and the SEL table has matching rows.

Now let me put together the definitive answer for question 3 with the exact bit composition, then discuss where "kernel not found" could still arise. Before finalizing, let me also double check the empty-tensor TILING_KEY_1 value: at host tiling.cpp:237, GET_TPL_TILING_KEY(TILING_KEY_1, 0, ..., TILING_KEY_1) — the first arg is IsEmptyTensor=1 (TILING_KEY_1 presumably 1), and the last arg is IsRegbase... wait, TILING_KEY1 appears both at first (IsEmptyTensor) and last (IsRegbase) position. Let me check TILING_KEY1's value. Actually the empty-tensor path is irrelevant for the user's case (D=80 with dropout isn't empty). Skip.

One more thing to verify: the exact bit values computed for the user's case, and enumerate precisely which SEL row matches. Let me also double check that the D=80 → 128 DTemplateType mapping is what actually gets into the key: GetTilingKey uses fBaseParams.dTemplateType (line 1464), set by FuzzyForBestSplit → GetDTemplateType (line 1479: dInner = GetDTemplateType(fBaseParams)). Wait — FuzzyForBestSplit (normal_regbase.cpp:1474-1481) calls GetS1S2TemplateType and GetDTemplateType; GetDTemplateType sets fBaseParams.dTemplateType = NUM128 for D=80 (common_regbase.cpp:856-858). ✓

Also, S1/S2: FuzzyForBestSplit → GetS1S2TemplateType sets fBaseParams.s1TemplateType/s2TemplateType = 128/128 for FP16 (common_regbase.cpp:838-844) regardless. ✓

Let me also sanity-check keepProb → IsDrop: GetTilingKey line 1440: dropValue = fBaseParams.keepProb < 1 ? ENABLE : DISABLE. User says "带 dropout" → keepProb<1 → IsDrop=1. ✓

And dNoEqual line 1438: (d1 != d) || hasRope — no rope, d1==d → 0. If the user's query and kv have different head dims (d1≠d) → 1; both covered in rows.

Now, the missing-link analysis for "kernel not found". Static evidence from code shows the FP16 D=80 dropout key IS listed in the ASCENDC_TPL_SEL table (row L153-174 for BN2GS1S2 non-TND; L197-218 TND; L571-592 BN2; L615-636 BN2S2; L593-614 BN2+TND; L637-658 BN2S2+TND; L659-680 BN2S2+TND+swizzle). So a runtime "kernel not found" with this exact key would NOT be caused by the SEL table content itself — unless:

(a) The delivered kernel binary was compiled without the FP16 rows (ORIG_DTYPE_QUERY ≠ DT_FLOAT16 and ≠ -1 at compile time; e.g., only BF16/FP32 build shipped, or the build system prunes FP16), or the binary selection at runtime picks a binary whose SEL table lacks FP16 (arch35 vs other arch mismatch).

(b) The user's actual case deviates from the assumptions — e.g., layout BS2N2GD (from SupportTrans2BS2N2GD, normal_regbase.cpp:669-672), TND, rope, deterministic mode, pse/atten_mask, sparse mode with DETER_OLD (which for FP16 non-TND DTemplate=128... row 5 covers DETER_OLD DTemplate={64,128,192,256,768} ✓; but DETER_OLD + NZ_OUT? row 5 has IsNzOut=0. isNzOut requires deterSparseType != DETER_OLD (line 450), so DETER_OLD → isNzOut=0 → consistent ✓).

(c) A mismatch between DTemplateNum=128 for D=80 vs the D=80 head-dim legality: hmm — actually wait. I should double check whether D=80 is even a supported head dim for FP16 in this operator, or whether the host validation restricts D values. If D=80 passes host CheckParams (I saw shape checks but not D-value restrictions in the window I read), then fine.

Actually, hold on — let me reconsider (b) more carefully for a subtle one: BS2N2GD layout! normal_regbase.cpp:669-672: if (SupportTrans2BS2N2GD(fBaseParams)) { fBaseParams.layoutType = INPUT_FORMAT_BS2N2GD; }. If the layout is set to BS2N2GD, then isTnd = (layoutType == INPUT_FORMAT_TND) → false. So key IsTnd=0. Fine — row 2 covers.

But wait — is there something about InputDType for FP16 in DetermineMode? Line 1653-1666: FP16 → DtypeEnum::FLOAT16_PRECISION. What is DtypeEnum::FLOAT16_PRECISION's numeric value? The DECL says InputDType=3 = FLOAT16_PRECISION. If DtypeEnum::FLOAT16_PRECISION == 3 in the host's DtypeEnum, consistent. Let me verify the DtypeEnum numeric values. This matters: if host DtypeEnum::FLOAT16_PRECISION is defined as e.g. 3 in a shared header (probably flash_attention_score_common_regbase.h or tiling common header), then consistent. I saw kernel constants: constexpr uint8_t FLOAT16_PRECISION = 3; BFLOAT16 = 2; (flash_attention_score_grad_common.h:98-99). And the SEL DECL comment says InputDType 3: FLOAT16_PRECISION (template_tiling_key.h:60). Host DetermineMode sets inputDtype = DtypeEnum::FLOAT16_PRECISION. Need DtypeEnum definition — likely in optiling namespace (from the common headers). Let me check quickly whether DtypeEnum::FLOAT16_PRECISION == 3.

Let me search for DtypeEnum in the UO.
GetDeterSparseTilingKey（normal_regbase.cpp:790-814）：非确定性 → NO_DETER=0 ✓。IsCapable（:413-428）：arch35 基础模板全支持。最后核对 host DtypeEnum 数值（FP16 必须是 3 才能与 SEL 表 InputDType=3 对齐
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern FLOAT16_PRECISION]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern DtypeEnum]
- Thought: 1m 49s
The host DtypeEnum is optiling::DtypeEnum (from the SDK header), values confirmed by usage: FLOAT32=1, BFLOAT16=2, FLOAT16_PRECISION=3, FLOAT8_E5M2=4, FLOAT8_E4M3FN=5, HIFLOAT8=6 (via DTYPE_ENUM_INDEX_4/5/6 — meaning index 4/5/6). Kernel constants confirm FLOAT16_PRECISION=3 (common.h:98). ✓ consistent.

Now I have a complete chain. Let me also double-check the InputDType value domain in the DECL: {0, 1, 2, 3, 4, 5, 6} and comment: 1: FLOAT32, 2: BFLOAT16, 3: FLOAT16_PRECISION, 4: FP8_E5M2, 5: FP8_E4M3FN, 6: HIFP8. And 0 is... some default. Host sets inputDtype=3 for FP16 ✓.

Wait — one important detail: DtypeEnum::FLOAT32 = 1 in DECL comment ("1: FLOAT32"), and host sets FLOAT32=1? The DECL comment says bit 6-4: 1: FLOAT32, 2: BFLOAT16, 3: FLOAT16_PRECISION. So host DtypeEnum FLOAT32=1 ✓ consistent (though host code uses DtypeEnum::FLOAT32 — the optiling enum, which must equal 1 for consistency; the DECL was written to match).

Also, the OutDType value domain {0,1,2,3}: outDtype=inputDtype=3 for FP16 ✓.

Now let me also quickly verify the IsEmptyTensor first arg in the host key is 0, and the empty-tensor path is separate. In GetTilingKey (normal_regbase.cpp:1460): first arg 0 = IsEmptyTensor=0. ✓.

One more check — the S1TemplateNum/S2TemplateNum value domain: {0, 64, 128, 512} and {0, 128, 256, 512}. Host FP16 → 128/128 ✓ (in domain).

DTemplateNum value domain: {0, 64, 128, 192, 256, 768}; D=80 → 128 ✓ (in domain).

DeterType domain: {0,1,2,3,4}; NO_DETER=0 ✓.

So the host key is: IsEmptyTensor=0, SplitAxis∈{0,1,5}, InputDType=3, IsTnd∈{0,1}, IsDrop=1, IsPse∈{0,1}, IsAttenMask∈{0,1}, S1=128, S2=128, DTemplate=128, Deter=0, IsNEqual=0, IsBn2MultiBlk∈{0,1}, IsDNoEqual∈{0,1}, IsRope=0, OutDType=3, IsNzOut=0, IsTndSwizzle∈{0,1}, IsRegbase=1.

And ALL these combos match at least one SEL row. Let me verify IsNEqual=0 is in domain of the matched rows — yes all rows have IsNEqual=0 (rows 2,4,21-25) or {0,1} (rows 7-10).

Now, one more possibility I should double check: d1 != d — in flash attention grad, could the user's case have query head dim != key/value head dim? For "D=80" the task says D=80 — presumably d=d1=80, so IsDNoEqual=0.

So my static conclusion: For FP16, D=80, dropout (keepProb<1), non-deterministic, arch35 — the host key is guaranteed to be in the ASCENDC_TPL_SEL instantiation table (rows cited). Therefore the "kernel not found" is most likely NOT caused by the key↔SEL table mismatch for the plain case. The failure candidates:

1. ORIG_DTYPE_QUERY / build config: The FP16 SEL rows and the RegbaseFAG FP16 body are guarded by #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16) (template_tiling_key.h:129, entry_regbase.h:223). If the operator binary was built with ORIG_DTYPE_QUERY set to a non-FP16 dtype only (e.g., the build script compiles the kernel per dtype but the delivered .o/.so for arch35 lacks the FP16 compile unit), then the FP16 keys don't exist in the instantiation table → runtime "kernel not found" for FP16. Also if ORIG_DTYPE_QUERY=-1 was used at compile, the RegbaseFAG body would be empty for all dtypes (all three #if blocks false) — a compile-config trap: ORIG_DTYPE_QUERY=-1 only makes sense for the SEL table expansion but the function bodies require a concrete dtype, so -1 cannot be the effective value in the kernel build. Actually wait — hold on. Let me reconsider: the #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16) in the SEL table and #if (ORIG_DTYPE_QUERY == DT_FLOAT16) in the function body — these are DIFFERENT conditions. If ORIG_DTYPE_QUERY == -1: SEL table includes FP16 rows (because -1 matches), but RegbaseFAG body is empty (because -1 != DT_FLOAT16). That means with -1, the SEL table declares FP16 instantiations but the kernel body is a no-op for them — the compile would generate a function with no statements (probably compiles, returns nothing). That's a real hazard IF the build uses -1. The comment at line 21 says "kernel通过宏定义隔离dtype编译tilingkey，降低耗时。tiling侧没有相关宏" — kernel uses macro to isolate dtype compilation of tiling keys to reduce compile time. So the intended build sets ORIG_DTYPE_QUERY per dtype (DT_FLOAT16 / DT_BF16 / DT_FLOAT / FP8...). The build system (CMake) likely compiles the kernel N times with different ORIG_DTYPE_QUERY values. If for some reason the FP16 pass was skipped (e.g., FP16 not in the build dtype list, or the CMake only builds BF16), then FP16 tiling keys exist in NO binary → "kernel not found" for FP16 input. This is the most plausible root cause, but it's a build/packaging fact that the .uo CodeMap cannot confirm — mark PARTIAL/UNKNOWN for the actual build config.

2. Actual case differs from assumptions (TND/varlen path, rope, deterministic, BS2N2GD layout, pse/atten_mask): the key bits then differ, and while most combos are covered, there are some genuinely absent combos in the FP16 table worth flagging:
   - FP16 + IsTnd=1 + DETER=0 + DTemplate=128 + IsTndSwizzle=1 + splitAxis=0: NO row (swizzle rows only Deter={2,3,4} for splitAxis=0; row 25 swizzle+Deter=0 only splitAxis=5). But host can't produce it (templateSupportCond requires BN2S2 for non-deter) → unreachable.
   - FP16 + IsTnd=0 + DETER=1 (DETER_OLD) + DTemplate=128 + IsNzOut=1: row 5 has IsNzOut=0 only, and host isNzOut requires deterSparseType != DETER_OLD → unreachable.
   - FP16 + splitAxis=5 (BN2S2) + IsNzOut=1: rows 23/24/25 have IsNzOut=0 only; host isNzOut requires splitAxis==BN2GS1S2 → unreachable.
   - FP16 + S1TemplateNum=512 (HIFP8 only): unreachable for FP16.
   So the pruned table is consistent with the host reachable set for FP16 D=80 dropout.

3. Runtime binary lookup by (opType, key): If the tiling key lookup fails due to key mismatch with the compiled instantiations (i.e., the table was generated from a DIFFERENT template_tiling_key.h version than the host tiling used to compute the key — e.g., host and kernel built from different commits), the key bits could disagree. The task mentions digest 211a7ec — a single CodeMap. Cross-build version skew is UNKNOWN statically.

4. D=80 + dropout + dropMaskOuter interplay: For BN2 (isBn2=true) with dropout where dropMask is an outer tensor (dropMaskOuter=true), SetSplitAxis forces isBn2=false/isBn2MultiBlk=false → splitAxis=BN2GS1S2 → row 2 covers. For BN2S2 route with dropout: allowed when d<=128 (line 1635-1636). ✓

5. The empty-tensor path (TILING_KEY_1): irrelevant.

Actually — one more thing worth verifying: the user says "D=80、带 dropout 的 flash_attention_score_grad" — for FA grad, dropout means keepProb<1 and a drop_mask input. Some op versions require dropout only with specific layouts. Fine.

Let me also double-check whether there's a "varlen" tiling path that the host might route to instead (e.g., if input format is TND with actual_seq_qlen). The varlen_regbase.cpp exists. For TND inputs, the dispatch (tiling.cpp / op_tiling.cc) may choose VarlenRegbase. In varlen, splitAxis and deterSparseType logic may differ (e.g., TND causal → BN2GS1S2, SupportTNDBns2 → BN2S2). The SEL rows for TND are rows 3-4, 6, 9-13, 15, 17, 19-20, 22, 24-25 — which cover FP16 IsTnd=1 Deter∈{0,1,2,3,4} DTemplate=128 combos (rows 4,6,10,12,22,25 for DTemplate=128). Row 4: TND Deter=0 DTemplate=128 IsTndSwizzle=0 IsNzOut=0,1 ✓; row 12: TND Deter={2,3,4} DTemplate=128 IsTndSwizzle=1 ✓; row 25: TND BN2S2 Deter=0 DTemplate=128 IsTndSwizzle=1 ✓. So TND covered too.

Hmm, but wait — varlen path: what about IsTnd=1 + Deter=0 + splitAxis=0 + DTemplate=128 — covered by row 4. And DETER_OLD (1) + TND + DTemplate=128 — row 6 ✓.

OK. One more angle: the REGISTER_TILING_DEFAULT / key-based tiling-data dispatch inside the kernel — the apt.cpp:54-57 uses REGISTER_TILING_FOR_TILINGKEY for the empty tensor. The non-empty path uses REGISTER_TILING_DEFAULT. This is about tiling data structure selection, not kernel binary selection. Not the "kernel not found" cause.

Let me also confirm the exact host key value in hex for the user's typical case to present concretely:

Bits (LSB first):
- bit0 IsEmptyTensor=0
- bits3-1 SplitAxis=0 (BN2GS1S2) → 0
- bits6-4 InputDType=3 → 3<<4 = 0x30
- bit7 IsTnd=0
- bit8 IsDrop=1 → 0x100
- bit9 IsPse=0
- bit10 IsAttenMask=0
- bits18-11 S1=128 → 128<<11 = 0x40000
- bits28-19 S2=128 → 128<<19 = 0x4000000
- bits40-29 D=128 → 128<<29 = 0x1000000000
- bits44-41 Deter=0
- bit45 IsNEqual=0
- bit46 IsBn2MultiBlk=0
- bit47 IsDNoEqual=0
- bit48 IsRope=0
- bits51-49 OutDType=3 → 3<<49 = 0x6000000000000
- bit52 IsNzOut=0
- bit53 IsTndSwizzle=0
- bit54 IsRegbase=1 → 0x40000000000000

Sum: 0x40000000000000 + 0x6000000000000 + 0x1000000000 + 0x4000000 + 0x40000 + 0x100 + 0x30
= 0x4600000_0000000 + ... let me not compute precisely; I can present the bit pattern instead. Actually let me compute:
0x40000000000000 (bit54)
0x06000000000000 (bits51-49 = 3<<49 = 0x6000000000000)
0x00000010000000 (bits40-29: 128<<29 = 0x1000000000)
0x00000000400000 (bits28-19: 128<<19 = 0x4000000)
0x00000000000400 (bits18-11: 128<<11 = 0x40000)
0x00000000000100 (bit8 = 0x100)
0x00000000000030 (bits6-4: 3<<4 = 0x30)

Total = 0x46000010040430... let me be careful:
bit54: 0x40000000000000
bits51-49: 0x6000000000000 → combined 0x46000000000000
bits40-29 (128<<29 = 2^36 = 0x1000000000): 0x46000010000000
bits28-19 (128<<19 = 2^26 = 0x4000000): 0x46000010400000
bits18-11 (128<<11 = 2^18 = 0x40000): 0x46000010400400
bit8 (0x100): 0x46000010400500
bits6-4 (0x30): 0x46000010400530

So key ≈ 0x46000010400530 for the typical BN2GS1S2 non-TND non-deter FP16 D=80 dropout case (with pse=0, attenMask=0, nz=0, swizzle=0, bn2multiblk=0, dnoequal=0). I could present this as the expected key, but I should be careful: it depends on IsPse/IsAttenMask/IsBn2MultiBlk/IsDNoEqual which depend on the user's actual graph. I'll present the bit pattern, not a single hex.

Now, I have enough for a thorough answer. Let me also quickly double check one of the remaining FP16 rows between 848-1572 to make sure there isn't some conditional IsDrop=0-only row or FP8 rows that might be relevant... The FP8 (InputDType 4/5/6) rows are after the FP16 block. Not relevant. But let me confirm there's nothing between 848-1572 that prunes FP16 further — actually the FP16 block ended at line 681 (#endif), then BF16 block starts at 682. So the FP16 rows are exactly lines 129-681. I've read 127-847 (with the BF16 block starting at 682). The FP16 block is fully covered by my reads (129-681). Good.

Wait — I read up to line 847, which covers FP16 (129-681) and BF16 beginning (682-847). I haven't seen BF16's end or FP32/FP8 blocks, but those don't matter for the FP16 case. Fine.

One more consideration for question 2's "任意合法 key 组合是否全覆盖": The answer is definitively NO — the SEL table is a curated pruning, NOT the full cross-product of the DECL domains. The DECL value domains are: SplitAxis{0,1,5}×InputDType{0..6}×IsTnd{0,1}×IsDrop{0,1}×IsPse{0,1}×IsAttenMask{0,1}×S1{0,64,128,512}×S2{0,128,256,512}×DTemplate{0,64,128,192,256,768}×Deter{0..4}×IsNEqual{0,1}×IsBn2MultiBlk{0,1}×IsDNoEqual{0,1}×IsRope{0,1}×OutDType{0,1,2,3}×IsNzOut{0,1}×IsTndSwizzle{0,1}×IsRegbase{0,1} — that's astronomically large. The SEL table enumerates ~40 rows for FP16 etc. So coverage is per-row curated; host logic is written to produce only combos in the table. This is exactly the kind of "host-key ↔ kernel-instantiation" coupling that can break (kernel not found) if a host path produces a key outside the curated rows.

Concrete FP16 rows that exist for DTemplate=128 + IsDrop=1:
- Row L153-174 (BN2GS1S2, non-TND, Deter=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=0|1, IsRope=0, IsNzOut=0|1, IsTndSwizzle=0) ✓
- Row L197-218 (BN2GS1S2, TND, Deter=0, ... IsNzOut=0|1, IsTndSwizzle=0) ✓
- Row L219-240 (BN2GS1S2, non-TND, Deter=1, DTemplate={64,128,192,256,768}) ✓
- Row L241-262 (BN2GS1S2, TND, Deter=1, ...) ✓
- Row L285-306 (BN2GS1S2, non-TND, Deter={2,3,4}, DTemplate=128, IsNEqual=0|1, IsNzOut=0|1) ✓
- Row L329-350 (BN2GS1S2, TND, Deter={2,3,4}, DTemplate=128, IsNzOut=0|1) ✓
- Row L373-394 (BN2GS1S2, TND, Deter={2,3,4}, DTemplate=128, IsTndSwizzle=1, IsNzOut=0|1) ✓
- Row L571-592 (BN2, non-TND, Deter=0, DTemplate={64,128,...}, IsBn2MultiBlk=0|1, IsDNoEqual=0|1, IsRope=0|1) ✓
- Row L593-614 (BN2, TND, Deter=0, DTemplate={64,128,...}, IsBn2MultiBlk=0|1) ✓
- Row L615-636 (BN2S2, non-TND, Deter=0, DTemplate={64,128,...}, IsDNoEqual=0|1, IsNzOut=0) ✓
- Row L637-658 (BN2S2, TND, Deter=0, DTemplate={64,128,...}, IsNzOut=0) ✓
- Row L659-680 (BN2S2, TND, Deter=0, DTemplate={64,128,...}, IsTndSwizzle=1, IsNzOut=0) ✓

Notable FP16 gaps (host-reachable? mostly not):
- BN2S2 + IsNzOut=1: unreachable (isNzOut requires splitAxis==BN2GS1S2)
- TND + DETER=0 + IsTndSwizzle=1 + splitAxis=0: unreachable (templateSupportCond → BN2S2)
- BN2GS1S2 DETER=0 with DTemplate=64/192/256/768 + IsNzOut=1: row 1 has IsNzOut=0 — but wait, can isNzOut=1 happen with DTemplate≠128? isNzOut requires 64<d<128 → DTemplate=128 always. So consistent.
- BN2 non-TND + DETER=1 (DETER_OLD): NO BN2 row for Deter=1! Rows 21/22 are Deter=0 only. But can host produce splitAxis=BN2 + DETER_OLD? SetSplitAxis: if isBn2 && !isBn2MultiBlk → isDeterministic=false (line 1609)! So BN2 (non-multiblk) is only non-deterministic → Deter=0. And isBn2MultiBlk → isDeterministic=false (line 1617) → Deter=0. So BN2+DETER_OLD unreachable. ✓ consistent.
- BN2S2 + DETER=1/2/3/4: rows 13 (Deter={2,4} TND IsNEqual=1) and... non-TND BN2S2 rows 23 (Deter=0) only! What about BN2S2 + DETER_DENSE/CAUSAL/BAND? Row 13: SplitAxis=5, IsTnd=1, Deter={2,4}, IsNEqual=1, DTemplate={64,128,192,256,768}, IsNzOut=0, IsTndSwizzle=0. So BN2S2+TND+DETER_DENSE/BAND with IsNEqual=1 covered. Non-TND BN2S2 + DETER: no row! But is it reachable? bn2S2RouteLimit requires !fBaseParams.isDeterministic in the bn2S2NotTndLimit path (line 1630), OR isAllSame && !isDeterministic (line 1633) — for non-TND, bn2S2NotTndLimit requires !isDeterministic; the TND path allows deterministic. If deterministic + non-TND + s1<s2... → not BN2S2 (bn2S2RouteLimit fails since !isDeterministic false and !isAllSame? hmm, isAllSame && !isDeterministic — deterministic makes it false). So non-TND BN2S2 only when non-deterministic → Deter=0 → row 23 ✓. And TND BN2S2 deterministic → Deter={2,4}? Hmm wait — row 13 has IsNEqual=1 fixed, Deter={2,4}. Deterministic TND BN2S2: what if deterSparseType=3 (DETER_CAUSAL)? Row 13 only has {2,4}! If host produces DETER_CAUSAL + BN2S2 + TND + FP16 + DTemplate=128 → NO ROW → kernel not found! Let me check whether that's reachable: GetDeterSparseTilingKey: deterministic → DETER_DENSE (2) for dense, DETER_CAUSAL (3) for causal, DETER_BAND (4) for band. And the BN2S2 route for TND deterministic: bn2S2RouteLimit allows (layoutType==TND → first disjunct true, no !isDeterministic requirement). Then splitAxis=BN2S2 if !isBn2. Then for DETER_CAUSAL... the varlen/DoSparse logic: SupportTrans2BS2N2GD etc. and the TND BN2S2 deter path uses CalcleTNDCausalDeterPrefix in varlen_regbase (line 126 sets splitAxis=BN2GS1S2 for causal!). Actually in varlen_regbase.cpp:123-126: if (deterSparseType != DETER_CAUSAL) return; splitAxis = BN2GS1S2; — hmm that's for the causal prefix path, forcing BN2GS1S2 for causal. So DETER_CAUSAL → BN2GS1S2 (row 9/10 covers). DETER_DENSE/BAND → BN2S2 possible (row 13 {2,4} covers). OK, so row 13's {2,4} matches the reachable set. Consistent.

So overall: the FP16 curated table is carefully matched to the host reachable set — every host-reachable FP16 D=80 dropout key is covered. This strongly suggests that IF the user gets "kernel not found" for the exact FP16+D=80+dropout case, the root cause is NOT a missing row in the SEL table but rather:
1. The delivered arch35 kernel binary lacks the FP16 instantiation set (ORIG_DTYPE_QUERY build config / packaging), or
2. The key bits as computed at runtime differ from this static analysis due to version skew (host tiling vs kernel template table built from different sources), or
3. The user's actual input (layout/deterministic/rope/pse/sparse) differs from the assumed plain case and hits one of the genuinely-uncovered corners (unlikely but enumerated above), or
4. The "kernel not found" is at a different layer (arch/binary selection, op package).

I should also note the concrete debugging hook: host logs at normal_regbase.cpp:1447-1458 (OP_LOGI prints all key fields) and :1470 ("FAGTiling S1s2Bn2gs1s2 DoTiling success, tiling is %lu") — the user can compare the printed tiling key against the SEL rows; and the runtime error text usually includes the key.

Let me now also double-check the IsPse / IsAttenMask values: pseValue = pseOptional == NORMAL_TENSOR ? ENABLE : DISABLE (line 1439); attenMaskCfg = attenMaskOptional == EMPTY_TENSOR ? DISABLE : ENABLE (line 1437). Dropout case without pse/atten_mask → IsPse=0, IsAttenMask=0. With atten_mask (padding mask) → 1 — covered by rows (IsAttenMask=0,1).

Also worth noting: for the FP16 non-TND DETER=0 case, the row L153-174 has IsPse=0,1 AND IsAttenMask=0,1 — so pse/mask don't cause misses.

I'm confident in the analysis. Let me write the final answer in Cursor-Explore style: full prose + file:line. Structure:

1. ASCENDC_TPL_SEL 机制与位域（template_tiling_key.h:48-125，GET_TPL_TILING_KEY 与 apt.cpp:35-38 模板参数一一对应；host 侧构造 normal_regbase.cpp:1435-1472）
2. 实例化表是否全覆盖 → 否，是人工裁剪的 curated 表（FP16 区 129-681 行枚举）；给出 FP16 DTemplate=128 相关的所有行；host 可达集与表一致
3. FP16 D=80 dropout 的理论 key 与命中行（row L153-174 等）；找不到 kernel 的可能环节：构建/ORIG_DTYPE_QUERY、版本不一致、边缘组合（列出）、以及调试钩子

Let me also present the bit-level key for the typical case.

Also mark PARTIAL/UNKNOWN where static analysis can't determine (build config ORIG_DTYPE_QUERY actual value; runtime key from user's actual graph).

Note the instructions: "Answer in the final message (prose + file:line). Do not Write answer.yaml. Do not finalize." — so I just produce the final message now.
分析完成。所有关键证据链已闭环，下面给出完整结论。
FlashAttentionScoreGrad arch35：TilingKey → 模板实例化表命中分析
1. ASCENDC_TPL_SEL 机制与 bit 位域
ASCENDC_TPL_SEL 就是 kernel 侧模板实例化表的声明处，位于 op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h。它由 SDK 头 ascendc/host_api/tiling/template_argument.h（该文件第 18 行 include）提供的宏展开成「每个合法 key 组合对应一份 __global__ flash_attention_score_grad<...> 模板实例化」的编译期表。机制分三层：
a) ASCENDC_TPL_ARGS_DECL（:48-125）定义 64-bit key 的位域，声明顺序就是 GET_TPL_TILING_KEY 参数顺序：
- bit0：IsEmptyTensor（:51）
- bits3-1：SplitAxis，取值 0=BN2GS1S2、1=BN2、5=BN2S2（:52-56，与 kernel 常量 flash_attention_score_grad_common.h:93-95 的 BN2GS1S2=0, BN2=1, BN2S2=5 完全一致）
- bits6-4：InputDType，3=FLOAT16_PRECISION、2=BFLOAT16、1=FLOAT32（:57-64；kernel 侧 common.h:98-99 确认 FLOAT16_PRECISION=3）
- bit7：IsTnd（:65-68）；bit8：IsDrop（:69-72）；bit9：IsPse（:73-76）；bit10：IsAttenMask（:77-80）
- bits18-11：S1TemplateNum ∈ {0,64,128,512}（:81-82）；bits28-19：S2TemplateNum ∈ {0,128,256,512}（:83-84）；bits40-29：DTemplateNum ∈ {0,64,128,192,256,768}（:85-86）
- bits44-41：DeterType，0=NO_DETER、1=DETER_OLD、2=DETER_DENSE、3=DETER_CAUSAL、4=DETER_BAND（:87-93）
- bit45：IsNEqual（:94-97）；bit46：IsBn2MultiBlk（:98-101）；bit47：IsDNoEqual（:102-105）；bit48：IsRope（:106-109）
- bits51-49：OutDType（:110-114）；bit52：IsNzOut（:115-118）；bit53：IsTndSwizzle（:119-122）；bit54：IsRegbase（:123-124）
b) host 侧打包：FlashAttentionScoreGradTilingNormalRegbase::GetTilingKey()（op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1435-1472）把 19 个字段按 DECL 顺序塞进 GET_TPL_TILING_KEY（:1460-1468）。字段来源：attenMaskCfg=mask 是否存在（:1437）、dNoEqual=(d1!=d)||hasRope（:1438）、pseValue（:1439）、dropValue=keepProb<1（:1440）、isRegbasePlatformValue=ENABLE（:1441）、isTnd（:1442）、isDeterNEqual（:1444-1446）；并打印全部字段（:1447-1458）与最终 key（:1470）。
c) kernel 侧消费：op_kernel/flash_attention_score_grad_apt.cpp:35-38 的 __global__ flash_attention_score_grad<...> 模板参数顺序与 DECL 逐一对应（19 个），在 :77-78 原样转发给 RegbaseFAG（entry_regbase.h:196-200 的 18 参数模板）。RegbaseFAG 内部再按 ORIG_DTYPE_QUERY（编译期宏）+ if constexpr (splitAxis == BN2GS1S2/BN2S2/BN2) 分发到 INVOKE_FAG_GENERAL_*_IMPL_FP16/BF16/FP32 宏（entry_regbase.h:116-126、223-288），最终实例化 FAGBlockCube/FAGBlockVec/FlashAttentionScoreGradKernel 等（:64-84、:144-168）。所以 key 的每个 bit 与 kernel 模板参数是一一对应的：runtime 用 host 的 key 查编译期生成的实例化表，命中则找到 kernel 二进制，未命中即报「kernel 找不到」。
2. 实例化表是否覆盖「任意合法 key」——否，是人工裁剪的 curated 表，但 host 可达集与表对齐
ASCENDC_TPL_SEL（:127 起）不是 DECL 值域的笛卡尔积，而是逐行 ASCENDC_TPL_ARGS_SEL 枚举允许组合。FP16 区为 :129-681（#if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16)，:129）。我逐行核对，FP16 + DTemplateNum=128 的相关行如下：
行	splitAxis	IsTnd
:131-152	0	0
:153-174	0	0
:175-196	0	1
:197-218	0	1
:219-240	0	0
:241-262	0	1
:263-284	0	0
:285-306	0	0
:307-328	0	1
:329-350	0	1
:351-372	0	1
:373-394	0	1
:395-416	5	1
:417-438	0	0
:571-592	1	0
:593-614	1	1
:615-636	5	0
:637-658	5	1
:659-680	5	1
（FP16 块 :681 结束，之后 :682 起是 BF16 区，与 FP16 无关。）
结论：表是有条件裁剪的——例如 FP16 非 TND 的 DETER=0 场景把 DTemplateNum 拆成两行（:131-152 无 128、:153-174 只有 128），DETER=2,3,4 的非 TND 行（:263-284）同样无 128。但这些裁剪恰好与 host 可达集一致，关键对齐点：
- DTemplateNum 由 GetDTemplateType 决定（op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp:847-870）：D≤64→64、D≤128→128、…；hasRope→192（与 rope 行只列 192 对齐）。
- S1/S2 模板：GetS1S2TemplateType（:812-845）对 FP16 恒返回 128/128（:838-844），恰好是 FP16 所有行唯一的 S1/S2 取值。
- IsNzOut（normal_regbase.cpp:444-451）要求 splitAxis==BN2GS1S2 && 64<d<128 && d%16!=0 && enableSwizzle && s1/s2≥阈值，因此永远落在 DTemplate=128 的行（:153-174、:197-218）上；BN2S2 行只列 IsNzOut=0 不会产生缺口。
- IsTndSwizzle（:461-463）的 templateSupportCond（:453-460）非确定性下只允许 splitAxis==BN2S2，恰好对应 :659-680 行；确定性+BN2GS1S2 分支带 && false（:455）实际不可达。
- IsBn2MultiBlk（common_regbase.cpp:1596-1606）要求非 TND、bnLimit、s1/s2 超 BN2 上限等；一旦为真 host 强制 splitAxis=BN2（:1644-1645），只命中 :571-592 行（IsBn2MultiBlk=0,1 都在表内）；dropMaskOuter 时还会被强制清零（:1616-1623）。DoSparse（normal_regbase.cpp:674-690）无效行列时重置为 BN2GS1S2+isBn2MultiBlk=0。
- IsDNoEqual、IsRope、IsNEqual、IsPse、IsAttenMask、OutDType（=inputDtype，common_regbase.cpp:1182，FP16→3）在各行取值域内。
所以静态上：FP16 的 host 可达 key 集合 ⊆ SEL 表实例化集合，未见 host 能产生而表缺失的组合。
3. FP16、D=80、带 dropout 的理论 key 与命中
假定标准场景（非确定性、无 rope/pse/atten_mask、d1==d、非 TND）：
位	字段
bit0	IsEmptyTensor
bits3-1	SplitAxis
bits6-4	InputDType
bit7	IsTnd
bit8	IsDrop
bit9/10	IsPse/IsAttenMask
bits18-11/28-19	S1/S2
bits40-29	DTemplateNum
bits44-41	DeterType
bit45	IsNEqual
bit46	IsBn2MultiBlk
bit47	IsDNoEqual
bit48	IsRope
bits51-49	OutDType
bit52	IsNzOut
bit53	IsTndSwizzle
bit54	IsRegbase
该 key（典型值 ≈ 0x46000010400530，BN2GS1S2 非 TND 分支）必然命中：
- splitAxis=0：:153-174（DTemplate=128、Deter=0、IsDrop=0,1、IsDNoEqual=0,1、IsNzOut=0,1）✓
- splitAxis=1：:571-592 ✓；splitAxis=5：:615-636 ✓
- 若输入是 TND（IsTnd=1）：:197-218（splitAxis=0）、:593-614（splitAxis=1）、:637-658/:659-680（splitAxis=5，含 swizzle）均覆盖 ✓
即：就这份代码而言，FP16+D=80+dropout 的 key 在 SEL 表里一定有对应实例化，kernel 侧 RegbaseFAG 也一定能编译出该模板（entry_regbase.h:223-242 FP16 分支 + splitAxis 三分支齐全）。
那么「kernel 找不到」最可能出在哪一环（按可能性排序，静态证据 + PARTIAL/UNKNOWN 标注）
1. 构建/打包环节（PARTIAL，代码外事实）：FP16 SEL 行与 RegbaseFAG FP16 函数体都受 #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16)（template_tiling_key.h:129）与 #if (ORIG_DTYPE_QUERY == DT_FLOAT16)（entry_regbase.h:223）控制。若交付的 arch35 kernel 二进制里没有 FP16 编译单元（例如构建脚本只编了 BF16/FP32 pass，或 ORIG_DTYPE_QUERY 定义与实际 dtype 不匹配），则 FP16 的 key 在所有二进制里都不存在 → runtime 报找不到 kernel。注意 :21 注释说明该宏正是为「按 dtype 隔离编译、降低耗时」而设——每 dtype 单独编译，任何一档缺失即整体缺失。实际构建配置不在 CodeMap 内，UNKNOWN。
2. host 与 kernel 版本不一致（UNKNOWN）：若 host tiling 与 kernel 的 template_tiling_key.h 来自不同提交，位域/取值域错位会让 key 永远对不上表。可通过 normal_regbase.cpp:1470 打印的 tiling is %lu 与 SEL 表比对验证。
3. 用户实际图与假设不符，落入表中确实缺失的角落（可能性低，均已列证据为不可达）：如 BN2S2+IsNzOut=1（isNzOut 要求 splitAxis==BN2GS1S2）、TND+swizzle+splitAxis=0+Deter=0（templateSupportCond 限定 BN2S2）、BN2+DETER_OLD（BN2 强制非确定性）、rope+D=80（rope 时 GetDTemplateType 返回 192，与 rope 行只列 192 对齐）。若用户实际开了确定性/rope/sparse/PREFIX 布局，请用 normal_regbase.cpp:1447-1458 的 OP_LOGI 字段日志核对后再对照表。
4. 空 tensor 路径（flash_attention_score_grad_tiling.cpp:237 的 TILING_KEY_1 分支）与本 case 无关。
给用户的实证抓手：跑一次用例抓 host 日志中的 splitAxis/inputDtype/isTnd/dropValue/pseValue/attenMaskCfg/s1TemplateType/s2TemplateType/dTemplateType/isDeterministic/nEqual/isBn2MultiBlk/dNoEqual/hasRope/outDtype/isNzOut/isTndSwizzle/isRegbasePlatformValue（normal_regbase.cpp:1449-1451）与 tiling is %lu（:1470），对照上述行表即可定位是 key 组合还是二进制缺失。
静态代码层面结论：SEL 表对 FP16+D=80+dropout 的所有 host 可达 key 均有实例化行（:153-174 等），key→模板映射闭环成立；「kernel 找不到」在纯静态上更指向构建期 ORIG_DTYPE_QUERY/打包缺失或版本不一致（PARTIAL/UNKNOWN），而非表内裁剪。未写 answer.yaml，未 finalize。
▣  Uo-Query · DeepSeek V4 Flash Free · 9m 59s
Subagent(5 of 9)135.3K (68%)

# subagent 6

算子目录：d:\TEST\ops-transformer\attention\flash_attention_score_grad（arch35，.uo CodeMap 已建好，digest 211a7ec…）。

立即调用 acp 工具：command=`uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...`（按需选 locate/symbols/callers/fields 等）。禁止 bash、Grep、MCP 替代。

背景：用户在 950 上跑 FP16、D=80、带 dropout 的 flash_attention_score_grad 报 kernel 找不到。要弄清三个模板参数/开关如何裁剪实例化组合：ORIG_DTYPE_QUERY、IsDNoEqual（D_NO_EQUAL / IS_D_NO_EQUAL）、IsNzOut（NZ_OUT / IS_NZ_OUT）。

请查清并回答（全部带 file:line 证据）：
1. ORIG_DTYPE_QUERY 是什么：定义在哪（entry_regbase.h? common.h?）、取值怎么来（host 侧从 input dtype 映射？template_tiling_key 的 InputDType 值 3=FLOAT16？）、在模板实例化列表里怎么参与（FP16/BF16/FP32 各实例化哪些组合）。
2. IsDNoEqual（IS_D_NO_EQUAL / D_NO_EQUAL）：host 侧怎么判断（tiling_normal_regbase.cpp / tiling_common_regbase.cpp 里 d != d1 之类条件）、TilingKey 哪个 bit、kernel 模板里 D_NO_EQUAL 分支怎么处理（D=80 场景 d1 是否等于 d，会不会走到 D_NO_EQUAL=1 而模板没实例化 D_NO_EQUAL 组合）。
3. IsNzOut（IS_NZ_OUT / NZ_OUT）：host 侧怎么判断（输出 layout NZ?）、TilingKey 哪个 bit、kernel 模板里 NZ 输出组合的实例化条件（entry_regbase.h:102-109 FlashAttentionScoreGradNzPost、:116-242 实例化列表里 NZ_OUT 变体是否齐全）。
4. 组合裁剪结论：这三个开关分别在哪些取值下会「砍掉」实例化组合（即 key 打出来了但 kernel 表里没有对应模板）；FP16 + D=80 + dropout 时最可能被砍的是哪个开关。

用 Cursor Explore 风格回答：完整散文 + file:line。静态无法确定处标 PARTIAL/UNKNOWN。不要写 answer.yaml，不要 finalize。
- Thought: 492ms
Let me start by querying the UO CodeMap for this operator project. I need to understand the structure first, then dig into the specific questions.

Let me call the acp tool with uo-query commands.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ORIG_DTYPE_QUERY]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern D_NO_EQUAL]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern NZ_OUT]
- Thought: 3.5s
Good start. Now I need to dig into the key files. Let me look at:

1. The tiling key template file flash_attention_score_grad_template_tiling_key.h — full listing, especially the ASCENDC_TPL_ARGS_DECL block (bits for InputDType, IsDNoEqual, IsNzOut), the macro ORIG_DTYPE_QUERY, and the instantiation list.
2. The host-side determination of IsDNoEqual in flash_attention_score_grad_tiling_normal_regbase.cpp / tiling_common_regbase.cpp.
3. The entry_regbase.h file:102-109 FlashAttentionScoreGradNzPost and :116-242 instantiation list.

Wait — the task mentions entry_regbase.h lines 102-109 and 116-242. Let me find those files. The CodeMap says sibling files are in op_kernel/arch35/. Let me locate entry_regbase.h.

Let me query more:
- locate pattern entry_regbase
- symbols for the tiling key file
- callers

Let me also read the template_tiling_key.h file directly since it's in pilot scope? No — wait. Machine-scope operator sources (op_host/, op_kernel/, ...) are outside .ascendc-pilot. Locate with UO KB query / ScopeSet first, then machine-scope windowed Read — never whole-file dumps.

So I can read machine-scope files with windowed Read. The working directory is D:\TEST\AscendC-Pilot but the operator is at d:\TEST\ops-transformer\attention\flash_attention_score_grad. I can read files there with the read tool (windowed, not whole-file dumps).

Let me first do more uo-query calls:
1. locate entry_regbase
2. locate IsDNoEqual in host files (tiling_normal_regbase.cpp, tiling_common_regbase.cpp)
3. locate InputDType / template_tiling_key
4. locate ORIG_DTYPE_QUERY usage / callers

Let me query callers of ORIG_DTYPE_QUERY, locate the template tiling key file fully, locate entry_regbase.
Initial locate results are good. Let me now dig into the template tiling key definition, the entry/instantiation file, and host-side condition logic.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern entry_regbase]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern template_tiling_key]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode callers --pattern ORIG_DTYPE_QUERY]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern InputDType]
- Thought: 4.7s
Good progress. Now I need to read the actual files. The template_tiling_key.h is important - I need to see the full ASCENDC_TPL_ARGS_DECL block including IsDNoEqual, IsNzOut bits. Let me also look at entry_regbase.h lines around 100-250 (FlashAttentionScoreGradNzPost at 102-109 and the instantiation list 116-242), and the host-side code for IsDNoEqual / IsNzOut determination.

Since these are machine-scope operator sources, I should do windowed Read. Let me read:
1. template_tiling_key.h (full file is reasonable — it's a template declaration file, probably ~200 lines)
2. entry_regbase.h around lines 90-250
3. tiling_common_regbase.cpp around lines 1640-1700 (DetermineMode InputDType) and the IsDNoEqual determination
4. tiling_normal_regbase.cpp around lines 400-480 (already have snippet)

Let me also query for IsDNoEqual host side. Let me search "dNoEqual" in host files.
Now let me read the key machine-scope files in windows (the template tiling key header and the entry instantiation file), and query the host-side Is
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [offset=20, limit=220]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern dNoEqual]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern isDNoEqual]
- Thought: 20.1s
Excellent. Key findings so far:

1. ORIG_DTYPE_QUERY: defined in flash_attention_score_grad_template_tiling_key.h:22-24 as (-1) default. The ASCENDC_TPL_SEL block at line 127+ uses #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16) to select FP16 instantiation list. So the value comes from compile-time macro (-D flag at kernel compile time), not from host-side dtype mapping directly at runtime — it's a compile-time build switch that prunes the instantiation list. When -1 (default, i.e., not defined at kernel build), all dtype branches are compiled. When set to DT_FLOAT16, only FP16 combos are compiled (reduces compile time).

Need to see the rest of the ASCENDC_TPL_SEL block (lines 240-1572) to see BF16 and FP32 branches and what combos they instantiate. That's a big file — let me read more windows but with the query tool instead maybe. Actually the read tool is fine for machine-scope windowed reads. Let me read lines 240-520 to see the remaining FP16 sel blocks and the BF16/FP32 blocks.

2. IsDNoEqual: TilingKey bit 47 (template_tiling_key.h:105). Host-side: dNoEqual = (fBaseParams.d1 != fBaseParams.d) || fBaseParams.hasRope at tiling_normal_regbase.cpp:1438, packed into tiling key at :1466 (13th argument = position of IsDNoEqual). Interesting — dNoEqual includes hasRope! So with rope, IsDNoEqual=1 too.

Need to check d1 determination — where is d1 set? In tiling_normal_regbase.cpp presumably from attrs (D1 attr? head dim of V?). For D=80 scenario: D=80, D1? d1 is typically the actual d of V (dv head dim). If d1 == d == 80 → dNoEqual = 0 unless hasRope. But wait — the question says "D=80 场景 d1 是否等于 d". Need to find where fBaseParams.d1 is set.

3. IsNzOut: TilingKey bit 52 (template_tiling_key.h:118). Host-side: isNzOut computed at tiling_normal_regbase.cpp:444-451:
   - requires splitAxis == BN2GS1S2
   - d > 64 && d < 128 && d % 16 != 0 (FP16_C0_SIZE = 16 presumably)
   - not fp8/fp32
   - deterSparseType != DETER_OLD
   - enableSwizzle && s1 >= NZ_OUT_MIN_S_SIZE && s2 >= NZ_OUT_MIN_S_SIZE

   For D=80: d > 64, d < 128, d % 16 != 0 (80 % 16 == 0!). Wait 80 % 16 = 0. So d % FP16_C0_SIZE != 0 would be FALSE → isNzOut = false! Hmm, unless FP16_C0_SIZE is not 16. Let me check the constant. FP16_C0_SIZE — likely 16. 80 % 16 == 0 → condition d % FP16_C0_SIZE != 0 is false → isNzOut = 0. So for D=80, IsNzOut=0 anyway. But wait — the user says 950 (Ascend 950), FP16, D=80 with dropout, kernel not found. Let me check what NZ_OUT_MIN_S_SIZE is and whether D=80 with isNzOut would even be 1. Actually with d=80, isNzOut=false per this condition. So IsNzOut isn't the culprit for D=80 unless... hmm. But wait, is d aligned? Maybe the tiling path sets dTemplateType or DTemplateNum=64? For D=80, DTemplateNum candidates are 64,128,192,256,768. Hmm, D=80 → dTemplateType would be 128 (aligned up). Actually GetDTemplateType picks the template.

Wait, let me reconsider. Actually I should check the FP16_C0_SIZE value. Let me query.

Also I need to check the entry_regbase.h instantiation list — the task mentions FlashAttentionScoreGradNzPost at :102-109 and instantiation list at :116-242. Let me read entry_regbase.h lines 90-260.

Also check the kernel-side IsNzOut instance condition — the task says "kernel 模板里 NZ 输出组合的实例化条件（entry_regbase.h:102-109 FlashAttentionScoreGradNzPost、:116-242 实例化列表里 NZ_OUT 变体是否齐全）". So entry_regbase.h has the instantiation list that must match the ASCENDC_TPL_SEL list.

Let me also check where ORIG_DTYPE_QUERY is defined for kernel build — in CMake or in the entry? Search for "DT_FLOAT16" and "ORIG_DTYPE_QUERY" definitions in kernel CMake or compile options. Let me search with uo-query for "ORIG_DTYPE_QUERY" more, e.g., in CMake files. Actually the locate found only 1 site for ORIG_DTYPE_QUERY in the CodeMap (the macro definition). The comment says "kernel通过宏定义隔离dtype编译tilingkey，降低耗时。tiling侧没有相关宏" — kernel uses macro to isolate dtype compilation of tilingkey; tiling side has no related macro. So ORIG_DTYPE_QUERY is a compile-time define passed when compiling the kernel binary, probably in CMake per-dtype or via operator build config (dtag). Value = -1 default (all dtypes) or DT_FLOAT16/DT_FLOAT/DT_BF16 (one dtype).

Let me now:
1. Read entry_regbase.h lines 90-260 (FlashAttentionScoreGradNzPost + instantiation list).
2. Read template_tiling_key.h lines 240-560 to see rest of FP16 sels + BF16/FP32 blocks.
3. Query FP16_C0_SIZE and NZ_OUT_MIN_S_SIZE values.
4. Query d1 setting (fBaseParams.d1).
5. Check the kernel entry (flash_attention_score_grad_apt.cpp) for how IsNzOut/IsDNoEqual feed into FlashAttentionScoreGradNzPost.
Key facts emerging. Now let me read the entry instantiation file and the rest of the tiling-key selection block, plus the constants
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h [limit=190, offset=85]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern FP16_C0_SIZE]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern NZ_OUT_MIN_S_SIZE]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern fBaseParams.d1]
- Thought: 5.7s
The fBaseParams.d1 query was truncated and gave many irrelevant results. Let me use a more targeted query. Also I need to see:
1. The full ASCENDC_TPL_SEL block — FP16 section (lines 240-520 of template_tiling_key.h), then BF16 and FP32 sections. Note from the read of lines 20-239: FP16 sel blocks: line 131 (BN2GS1S2 DTemplate 64,192,256,768 IsNzOut=0), line 153 (BN2GS1S2 DTemplate 128, IsNzOut 0,1), line 175 (TND IsTnd=1 DTemplate 64,192,256,768 IsNzOut=0), line 197 (TND IsTnd=1 DTemplate 128 IsNzOut 0,1), line 219 (DeterType=1 DTemplate 64,128,192,256,768 IsNzOut=0). And the file is 1572 lines. So there are more FP16 sels plus BF16 and FP32.

2. Where d1 comes from (GetTilingKey context in tiling_normal_regbase.cpp lines ~1420-1470). Let me read that window.

3. The rest of entry_regbase.h (lines 275-289) for the FP32 branch.

4. The kernel entry flash_attention_score_grad_apt.cpp to see how ORIG_DTYPE_QUERY gates the compile (the RegbaseFAG call) and how the binary is built with ORIG_DTYPE_QUERY defined (compile-time macro). Let me also search for "ORIG_DTYPE_QUERY" definition in build files — maybe CMakeLists or kernel build config. The CodeMap only found one definition site (the header default). But the real definition happens at kernel compile time (e.g., -DORIG_DTYPE_QUERY=DT_FLOAT16), which is likely in a build script outside the CodeMap (build config in the operator package, e.g., kernel_meta or CMake). Let me search for "DT_FLOAT16" to see usage.

Let me also check the template_match mode or tiling_key mode to see the actual instantiation combos the kernel build registered. There's a "templates" mode and "template_match" mode in uo-query. Let me try --mode templates or --mode tiling_key for the project.

Let me do these in parallel:
- read template_tiling_key.h offset 240 limit 200 (continue FP16 sels)
- read tiling_normal_regbase.cpp offset 1400 limit 80 (GetTilingKey incl. dNoEqual/d1)
- uo-query locate DT_FLOAT16
- uo-query tiling_key mode
Let me continue reading the tiling-key selection blocks, the host GetTilingKey context, and check how the kernel binary gates on ORIG_DTYPE_QUERY.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [limit=260, offset=240]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=90, offset=1390]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern DT_FLOAT16]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode tiling_key]
- Thought: 26.8s
I have the FP16 sel block partially. Key observations:

FP16 (ORIG_DTYPE_QUERY == DT_FLOAT16 or -1) sel blocks so far (lines 129-499):
1. L131: BN2GS1S2, TND=0, DTemplate 64/192/256/768, Deter 0, IsDNoEqual 0,1, IsNzOut 0 → FFFF
2. L153: BN2GS1S2, TND=0, DTemplate 128, Deter 0, IsDNoEqual 0,1, IsNzOut 0,1 → FFFF
3. L175: TND, DTemplate 64/192/256/768, Deter 0, IsDNoEqual 0,1, IsNzOut 0 → FFTF
4. L197: TND, DTemplate 128, Deter 0, IsDNoEqual 0,1, IsNzOut 0,1 → FFTF
5. L219: BN2GS1S2, DTemplate 64/128/192/256/768, Deter 1 (DETER_OLD), IsDNoEqual 0,1, IsNzOut 0 → TFFF
6. L241: TND, DTemplate 64/128/192/256/768, Deter 1, IsDNoEqual 0,1, IsNzOut 0 → TFTF
7. L263: BN2GS1S2, DTemplate 64/192/256/768, Deter 2/3/4, IsNEqual 0,1, IsDNoEqual 0,1, IsNzOut 0 → TFFF
8. L285: BN2GS1S2, DTemplate 128, Deter 2/3/4, IsNEqual 0,1, IsDNoEqual 0,1, IsNzOut 0,1 → TFFF
9. L307: TND, DTemplate 64/192/256/768, Deter 2/3/4, IsNEqual 0,1, IsDNoEqual 0,1, IsNzOut 0 → TTTF
10. L329: TND, DTemplate 128, Deter 2/3/4, IsNEqual 0,1, IsDNoEqual 0,1, IsNzOut 0,1 → TTTF
11. L351: TND, DTemplate 64/192/256/768, Deter 2/3/4, IsNEqual 0,1, IsDNoEqual 0,1, IsNzOut 0, IsTndSwizzle 1 → TTTT
12. L373: TND, DTemplate 128, Deter 2/3/4, IsNEqual 0,1, IsDNoEqual 0,1, IsNzOut 0,1, IsTndSwizzle 1 → TTTT
13. L395: BN2S2 (SplitAxis=5), TND=1, DTemplate 64/128/192/256/768, Deter 2/4, IsNEqual 1, IsDNoEqual 0,1, IsNzOut 0 → TTTF
14. L417: Rope BN2GS1S2 DTemplate 192 Deter 0 IsDNoEqual 1 IsRope 1 IsNzOut 0 → FFFF
15. L439: Rope TND DTemplate 192 Deter 0 IsDNoEqual 1 IsRope 1 IsNzOut 0 → FFTF
16. L461: Rope BN2GS1S2 DTemplate 192 Deter 1 IsDNoEqual 1 IsRope 1 IsNzOut 0 → TFFF
17. L483: Rope TND DTemplate 192 Deter 1 IsDNoEqual 1 IsRope 1 IsNzOut 0 → TFTF (cut at 499)

So for the FP16 dtype, every sel block includes both IsDNoEqual 0 and 1 (ASCDNDC_TPL_BOOL_SEL(IsDNoEqual, 0, 1)). So IsDNoEqual isn't pruned in FP16 — both values are instantiated. The question's premise "会不会走到 D_NO_EQUAL=1 而模板没实例化 D_NO_EQUAL 组合" needs checking for each sel block. In all FP16 sels seen so far, IsDNoEqual ∈ {0,1} is always present. So for D=80 without rope, dNoEqual = (d1 != d) || hasRope. Need d1 value.

Wait — interesting: dNoEqual includes hasRope! auto dNoEqual = (fBaseParams.d1 != fBaseParams.d) || fBaseParams.hasRope; at tiling_normal_regbase.cpp:1438. So even when d1==d, with rope enabled, IsDNoEqual=1. The rope-only sel blocks (L417-L499) explicitly have IsDNoEqual=1, IsRope=1. So rope combos are covered too.

IsNzOut in FP16: present only in sels where DTemplateNum == 128 (L153, L197, L285, L329, L373, L389) — IsNzOut ∈ {0,1}; everywhere else IsNzOut=0 only. So the NZ_OUT variant is only instantiated for DTemplateNum=128 combos. This matches the host-side condition: isNzOut requires d in (64,128) i.e., D=80 → dTemplateType=128. Wait — need to check GetDTemplateType for D=80. Let me check. If D=80 → dTemplateType likely 128. And isNzOut condition requires d % FP16_C0_SIZE != 0. Need FP16_C0_SIZE value. FP16_C0_SIZE is likely 16. If so, 80 % 16 == 0 → isNzOut=false for D=80! Hmm, but then D=80 wouldn't produce IsNzOut=1.

Hmm wait, let me reconsider. Maybe FP16_C0_SIZE = 16. 80 % 16 = 0 → false → isNzOut = 0. So D=80 would NOT get NZ_OUT. Unless FP16_C0_SIZE is something else. Let me find its definition. It's referenced at tiling_normal_regbase.cpp:444 but defined where? Probably in a common header. Let me search.

Also need d1: where is fBaseParams.d1 set? The query truncated. Let me search "d1" in tiling_normal_regbase.cpp. d1 is likely from V head dim attr (D1). In FAG, d = head dim of Q/K, d1 = head dim of V. For D=80 scenario with V also D=80, d1 == d → dNoEqual=0. But the user asks "D=80 场景 d1 是否等于 d，会不会走到 D_NO_EQUAL=1". So need to confirm where d1 comes from.

Also important: the ORIG_DTYPE_QUERY compile-time value. The header default is -1 (all dtypes compiled). The kernel binary might be built with ORIG_DTYPE_QUERY=DT_FLOAT16 etc. Where is that set? The CodeMap only knows the header. It's likely set in the kernel build CMake or a build script (kernel_meta / ascendc kernel build config). Since we can't search outside CodeMap except machine-scope reads... Let me check the operator package for CMakeLists.txt or build script that defines ORIG_DTYPE_QUERY. Files like CMakeLists.txt at the operator root. Let me look at the operator dir listing. Actually — working dir is the pilot repo, but the operator is at d:\TEST\ops-transformer\attention\flash_attention_score_grad. Let me read the top-level of the operator dir to find build files.

Also I should read the rest of entry_regbase.h (275-289) and rest of template_tiling_key.h BF16/FP32 sections (lines 500-1572). That's a lot; I can sample. The question asks "在模板实例化列表里怎么参与（FP16/BF16/FP32 各实例化哪些组合）" — I need at least the BF16 and FP32 sel block headers. Let me read 500-900 and 900-1572 in windows. Actually the file is 1572 lines; the sel blocks are big. Let me sample at intervals to capture the #if boundaries and sel block headers. Let me use grep-like reading: read offset 500 limit 300, then offset 800 limit 300, etc. That's a lot of reads but acceptable for windowed reads. Actually, better: use uo-query templates mode or search for "DT_BF16" / "DT_FLOAT" occurrences to find the #if boundaries. But the locate for DT_FLOAT16 only found one host site (because CodeMap indexes only certain entities). Let me use the read tool with targeted offsets.

Actually, let me try uo-query with mode=templates or search pattern "ORIG_DTYPE_QUERY == DT_BF16".

Let me also verify what the kernel build sets ORIG_DTYPE_QUERY to — search machine-scope for it in CMake files. The operator dir may have build/CMakeLists. Let me list the operator directory first.

Let me plan the next batch:
1. read operator dir root listing (find CMake / build scripts)
2. read template_tiling_key.h 500-800 (continue)
3. read entry_regbase.h 275-289 (tail)
4. uo-query locate "FP16_C0_SIZE" definition — it only found usage at 444. Definition likely in a header like flash_attention_score_grad_tiling_common_regbase.h or defs. Search pattern "constexpr.*FP16_C0_SIZE" won't work; try locate pattern "FP16" or "C0_SIZE".
5. Where d1 is set: locate "d1" in tiling_normal_regbase.cpp — the earlier query was truncated with 32 results. Try search mode with pattern "d1" target file. Use --file option maybe. The uo-query has --file. Let me try --mode search --pattern "d1" ... hmm. Alternatively read tiling_normal_regbase.cpp around the beginning where fBaseParams.d and d1 are assigned (probably in Init or ProcessTiling). Let me search "d1" via read+grep... I can't grep. Let me try uo-query search mode with pattern "headDim" or "d1 =".

Let me batch these.
Let me check the operator root for build files (where ORIG_DTYPE_QUERY would be passed), continue through the BF16/FP32 selection sections, and find where d1/FP16_C0_SIZE come
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad 
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [limit=220, offset=500]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h [limit=20, offset=270]
- Thought: 7.1s
The entry_regbase.h file is 289 lines total. The user asked about "entry_regbase.h:102-109 FlashAttentionScoreGradNzPost、:116-242 实例化列表里 NZ_OUT 变体是否齐全". The instantiation list is in template_tiling_key.h actually (the ASCENDC_TPL_SEL block), not in entry_regbase.h. entry_regbase.h has RegbaseFAG which dispatches by splitAxis to INVOKE macros. Note entry_regbase.h:91 if (ORIG_DTYPE_QUERY != DT_FLOAT) gates the post-processing: for FP32, no post. And the NZ_OUT post uses FlashAttentionScoreGradNzPost at :102-109.

Now, the FP16 section in template_tiling_key.h ends at line 681 (#endif), BF16 section starts at 682. Let me continue reading from 720 to see the BF16 combos and then the FP32 section. I want to know:
- BF16: which sels include IsNzOut ∈ {0,1}
- FP32: IsNzOut? (host condition excludes DT_FLOAT → IsNzOut never for FP32)

Also I should confirm the whole FP16 section structure — I've seen lines 127-681. FP16 sels at lines: 131, 153, 175, 197, 219, 241, 263, 285, 307, 329, 351, 373, 395, 417, 439, 461, 483, 505, 527, 549, 571, 593, 615, 637, 659. That's 25 sel blocks.

Now key remaining questions:
1. Where does ORIG_DTYPE_QUERY get set at build time? Check CMakeLists.txt at operator root, and op_kernel build scripts. Let me read CMakeLists.txt (root) and op_kernel dir listing.
2. Where is fBaseParams.d1 set? Search in tiling_normal_regbase.cpp / tiling_common_regbase.cpp. Query "d1" with mode search or locate pattern "= fBaseParams.d1" or read the Init section. Let me use uo-query search mode for "d1". The earlier locate for "fBaseParams.d1" returned truncated with dqIsNeedDeter etc. Let me try pattern "d1 =".
3. FP16_C0_SIZE definition — search "FP16_C0" or in a header. Let me try locate pattern "C0_SIZE" or read tiling_normal_regbase.cpp top includes / header file.

Let me batch:
- read CMakeLists.txt (root) - find ORIG_DTYPE_QUERY build define
- read op_kernel dir listing
- uo-query locate "FP16_C0" 
- uo-query search mode "d1" with target file? The search mode takes --pattern and --target maybe. Let me try --mode search --pattern "d1 = fBaseParams". Hmm, search mode may be textual. Let me try locate pattern "d1".
The entry file is only 289 lines (the instantiation list actually lives in template_tiling_key.h). Now let me find where ORIG_DTYPE_QUERY is defined at build time, where d1 is set on the host, and the FP16_C0_SIZE constant.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\CMakeLists.txt 
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel 
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern FP16_C0]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern "d1"]
- Thought: 15.9s
The search output was truncated. Let me be more targeted. I need:
1. Where fBaseParams.d1 is set (host side). Probably in tiling_normal_regbase.cpp or tiling_common_regbase.cpp in ProcessTiling / InitFromContext. Let me read the top of tiling_normal_regbase.cpp where fBaseParams fields are filled. Actually let me use uo-query locate with pattern "d1" but restricted. The locate mode doesn't accept file restriction, but the search mode does have --file maybe. Let me try locate with pattern "valueD1" or "d1 =". Hmm.

Actually the earlier --mode locate --pattern fBaseParams.d1 gave truncated output with 32 results — the file list included tiling_common_regbase.cpp with line 186 (queryType != attentionInType) and line 1712. Line 1712 could be the DetermineMode d1 assignment. Let me read tiling_common_regbase.cpp around 1700-1760.

Also, let me check where d and d1 are initialized — maybe in tiling_normal_regbase.cpp Init or in fuzzy base params. Let me read the beginning of tiling_normal_regbase.cpp (lines 1-120) to see includes and constants like FP16_C0_SIZE and NZ_OUT_MIN_S_SIZE definitions. FP16_C0_SIZE might be defined in a common header (flash_attention_score_grad_tiling_common.h?). The locate only shows usage at 444; the definition may be in a header included by the .cpp that CodeMap doesn't index as separate entity (it found only "usage" because headers may not be in CodeMap). Let me read the top of tiling_normal_regbase.cpp to find includes and constants.

Also read CMakeLists in op_kernel dir? The op_kernel dir has no CMakeLists (entries only arch22, arch35, two .cpp files). So build config comes from the outer CANN build system (compiling kernel with -DORIG_DTYPE_QUERY=...). Actually, the kernel binary build for CANN operators typically uses kernel_meta or the ascendc build with --cce-aicore-args... The ORIG_DTYPE_QUERY macro is likely passed by the operator build framework per-dtype when building "flash_attention_score_grad_fp16" etc. Since no CMakeLists defines it in the repo, the macro comes from the build system config (op info / kernel build flags) — that's PARTIAL/UNKNOWN from within this repo. But we can note: the header default (-1) means all three dtype families compiled; the per-dtype builds (if any) pass DT_FLOAT16/DT_BF16/DT_FLOAT.

Let me look at op_kernel/flash_attention_score_grad.cpp and flash_attention_score_grad_apt.cpp — the entry that calls RegbaseFAG. The apt.cpp had the template with all 19 params. Let me read flash_attention_score_grad.cpp (probably the main entry) to see the kernel function and how it uses ORIG_DTYPE_QUERY (maybe the real entry defines RegbaseFAG call). Also check if there's a build script. Let me read op_kernel/flash_attention_score_grad.cpp fully (windowed).

Also the docs/ dir might contain build notes. Let me check docs dir listing.

Batch:
1. read tiling_common_regbase.cpp offset 1680 limit 80 (DetermineMode tail incl. d1/inputDtype)
2. read op_kernel/flash_attention_score_grad.cpp (limit 200)
3. read tiling_normal_regbase.cpp offset 1 limit 120 (includes + constants)
4. read docs dir listing
The search was too broad. Let me look at targeted windows: the DetermineMode tail in tiling_common_regbase.cpp (where d1 would be set), the kernel main entry, the top of tiling_normal_regbase.cpp for
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp [limit=90, offset=1680]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\flash_attention_score_grad.cpp [limit=120]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=120]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\docs 
- Thought: 26.8s
Very useful. Now I found fBaseParams.d1 = valueShape->GetStorageShape().GetDim(INPUT_DIM_2) / fBaseParams.n2; at tiling_normal_regbase.cpp:109 (SBH layout). d = query dim / headNum. So d1 = V head dim. For D=80 scenario with V also having head dim 80, d1 == d → dNoEqual = (d1 != d) || hasRope = false (no rope). Good.

Note also fBaseParams.d = fBaseParams.hasRope ? ROPE_D_192 : ... at line 108 — with rope, d is forced to 192 (ROPE_D_192)! Interesting: rope sets d=192 → dNoEqual = true (via hasRope || d1 != d). And the sel blocks for rope are DTemplateNum=192, IsDNoEqual=1, IsRope=1.

Now I need to see where d1 is set for other layouts (BNSD, TND). Let me read more of GetShapeAttrsInfo (lines 120-260) to see BNSD and TND branches. Also want to find where the constants FP16_C0_SIZE and NZ_OUT_MIN_S_SIZE are defined (maybe in a header flash_attention_score_grad_tiling_common_regbase.h or in op_host headers). Let me look for headers: op_host dir listing.

Also need the tail of the template_tiling_key.h BF16/FP32 sections (lines 720-1572) to characterize BF16 and FP32 instantiation combos, particularly IsNzOut presence and IsDNoEqual presence. Let me read the remaining part. I'll sample: 720-1000, 1000-1280, 1280-1572. That's a lot; but necessary for the "FP16/BF16/FP32 各实例化哪些组合" question. Let me read 720-1100 first (BF16 rest + FP32 start), and check where #endif of BF16 is and FP32 sel blocks.

Also, I should confirm what ORIG_DTYPE_QUERY is set to during kernel build. Since the repo doesn't contain the build define (no CMake in op_kernel), it's set by the CANN operator build framework. Note flash_attention_score_grad_apt.cpp uses #if (ORIG_DTYPE_QUERY == DT_FLOAT16) etc. So kernel binary build passes -DORIG_DTYPE_QUERY=<value>. PARTIAL/UNKNOWN from this repo — but the header default (-1) compiles everything, and per-dtype build would compile only one family. The user says "kernel 找不到" on 950 — that's an Ascend kernel loading error meaning the tiling key produced at runtime has no matching compiled template in the kernel binary.

Let me now:
1. read tiling_normal_regbase.cpp 120-300 (BNSD + TND branches, d1 assignments)
2. read template_tiling_key.h 720-1000 (BF16)
3. read template_tiling_key.h 1000-1280 (BF16 tail + FP32 start)
4. read op_host dir listing (find header with FP16_C0_SIZE / NZ_OUT_MIN_S_SIZE)
Found d1 assignment. Now let me get the other layout branches (BNSD/TND) for d1, continue through BF16/FP32 sel sections, and find the constants
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=190, offset=120]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [limit=260, offset=720]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host 
- Thought: 7.1s
I have a good picture of BF16 now. BF16 mirrors FP16 with OutDType=2 and InputDType=2, with IsNzOut ∈ {0,1} only for DTemplateNum=128 combos, IsDNoEqual always {0,1}. Let me continue to the FP32 section (should start after BF16 #endif). Let me find the boundaries: BF16 section likely ends around line 1100ish. Let me read 980-1300 and 1300-1572 to capture the FP32 section and the end of the file.

Also, I want to see the end of the file — the closing of ASCENDC_TPL_SEL and maybe a comment on how ORIG_DTYPE_QUERY is passed. Let me read 980-1572 in two windows. Also FP16_C0_SIZE definition — it's not in the CodeMap beyond usage; likely defined in a header included by tiling_normal_regbase.cpp, e.g., flash_attention_score_grad_tiling_normal_regbase.h or a common constants header. Let me list op_host/arch35 dir and read the tiling normal header.
Let me finish the tiling-key selection file (FP32 section + tail) and locate the constants
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [limit=300, offset=980]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [limit=300, offset=1280]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35 
- Thought: 9.6s
Now I have the complete structure of the template_tiling_key.h ASCENDC_TPL_SEL. Let me now:

1. Read the tiling_normal_regbase.h to find FP16_C0_SIZE and NZ_OUT_MIN_S_SIZE constants.
2. Also check the kernel entry point that instantiates RegbaseFAG: flash_attention_score_grad_apt.cpp is the arch35 apt file; it must call RegbaseFAG from entry_regbase.h with template args derived from the tiling key. Let me look at how apt.cpp dispatches: read lines 90-250 of flash_attention_score_grad_apt.cpp.
3. Also verify the GET_IS_NZ_OUT kernel-side function (flash_attention_score_grad_common.h:267) — it computes IsNzOut for kernel classes. That's the kernel-side condition: SPLIT_AXIS==BN2GS1S2 && dtype not float/fp8/hifp8 && HEAD_DIM_ALIGN==128 && !IS_DETER_OLD. Interesting — the kernel-side GET_IS_NZ_OUT doesn't require d%16!=0. Hmm, but for D=80, HEAD_DIM_ALIGN would be 128 (aligned). Let me check HEAD_DIM_ALIGN usage. Actually GET_IS_NZ_OUT(SPLIT_AXIS, HEAD_DIM_ALIGN, ...) is a constexpr function computing the template param IsNzOut for the block classes. Wait, but the host isNzOut is what goes into the tiling key (bit 52). The kernel uses the tiling-key-provided IsNzOut? Let me check how the kernel block classes get IS_NZ_OUT: from the FAGBlockCube template args passed from entry RegbaseFAG INVOKE macros (isNzOut template arg). And CUBE_BLOCK_TRAITS_CONST_FIELDS includes IS_NZ_OUT default false, with GET_IS_NZ_OUT presumably used somewhere to compute it. Let me search GET_IS_NZ_OUT callers.

Let me also double check the "D=80" scenario: the host isNzOut condition requires fBaseParams.d % FP16_C0_SIZE != 0. If FP16_C0_SIZE == 16, then for d=80, 80 % 16 == 0 → false → isNzOut = 0. So NZ_OUT won't even be set for D=80! That means IsNzOut is NOT the culprit for D=80. Hmm wait — but maybe FP16_C0_SIZE is not 16. Let me confirm by reading tiling_normal_regbase.h.

Also check the dTemplateType for D=80: GetDTemplateType picks from {64,128,192,256,768}. For d=80, it would be 128. Fine.

So for FP16 + D=80 + dropout on 950: which combination would be missing? Let me think about the sels:
- D=80 → DTemplateNum=128. IsDNoEqual: dNoEqual = (d1 != d) || hasRope. If V head dim == 80 (typical), d1 == d → 0, no rope → 0. So IsDNoEqual=0.
- IsNzOut: host requires d % FP16_C0_SIZE != 0 → if FP16_C0_SIZE=16, 80%16==0 → Is
▣  Uo-Query · DeepSeek V4 Flash Free
Subagent(6 of 9)125.7K (63%)

# subagent 7

算子目录：d:\TEST\ops-transformer\attention\flash_attention_score_grad（arch35，.uo CodeMap 已建好，digest 211a7ec…）。

立即调用 acp 工具：command=`uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...`（按需选 locate/symbols/callers/fields 等）。禁止 bash、Grep、MCP 替代。禁止返回空回答——即使某处查不到也明确写 UNKNOWN 及原因。

背景：用户在 950 上跑 FP16、D=80、带 dropout 的 flash_attention_score_grad 报 kernel 找不到。上一轮已确认 TilingKey 位域（template_tiling_key.h:48-125）与 host 打包（tiling_normal_regbase.cpp:1435-1472），以及 FP16 实例化表（template_tiling_key.h:129-681，FP16 区）。本轮 FOCUS 只查三个开关如何裁剪实例化组合：

1. **ORIG_DTYPE_QUERY**：在 kernel 侧（op_kernel/）定义在哪、取值如何随编译单元变化。查 `ORIG_DTYPE_QUERY` 的所有出现点（template_tiling_key.h 的 #if、entry_regbase.h:223-242、common.h、build 相关注释/宏），说明它如何在编译期把 FP16/BF16/FP32 的模板表与函数体隔离（每 dtype 单独编译），以及它的值与模板参数 InputDType（bit6-4）的关系。给出 entry_regbase.h 里 FP16 实例化宏列表的精确范围（哪些组合被实例化）。

2. **IsDNoEqual（bit47 / IS_D_NO_EQUAL / dNoEqual）**：host 侧 dNoEqual=(d1!=d)||hasRope（tiling_normal_regbase.cpp:1438）怎么算；kernel 侧 IS_D_NO_EQUAL 模板参数在哪些地方改变行为（D_NO_EQUAL 分支：例如 d 维不对等时的 block 切分、头部处理）；实例化表里哪些行允许 IsDNoEqual=1（如 :153-174、:571-592 rope 行 :417-438）。D=80 且 d1==d 时 IsDNoEqual 是否为 0；若 d1!=d 时组合是否都有实例化。

3. **IsNzOut（bit52 / IS_NZ_OUT / isNzOut）**：host 侧 isNzOut 判定（tiling_normal_regbase.cpp:444-451：splitAxis==BN2GS1S2 && 64<d<128 && d%16!=0 && enableSwizzle && s1/s2 阈值）；kernel 侧 IS_NZ_OUT 模板参数分支（FlashAttentionScoreGradNzPost，nz_post.h；entry_regbase.h:102-109）；实例化表里 IsNzOut=1 的行（:153-174、:197-218 等）。D=80 时 80%16==0 是否使 isNzOut 恒为 0。

4. **结论**：这三个开关各自在什么取值下会「砍掉」组合导致 kernel 找不到（若 host 可达集与 SEL 表完全对齐就明确说不可达）；FP16 + D=80 + dropout 场景下这三个开关的值各是什么、是否命中表内行。

用 Cursor Explore 风格回答：完整散文 + file:line，逐条回答 1-4。不要写 answer.yaml，不要 finalize。
- Thought: 876ms
Let me start by querying the UO CodeMap for the operator. The task asks me to focus on three switches: ORIG_DTYPE_QUERY, IsDNoEqual (bit47 / IS_D_NO_EQUAL / dNoEqual), and IsNzOut (bit52 / IS_NZ_OUT / isNzOut), and how they prune instantiation combinations.

Let me first run uo-query in various modes to locate the relevant symbols.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ORIG_DTYPE_QUERY]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern IS_D_NO_EQUAL]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern IS_NZ_OUT]
- Thought: 7.1s
Good start. Now I need more detail:

1. ORIG_DTYPE_QUERY — I have the definition at template_tiling_key.h:22-24. Need to find all usages (the #if sections), entry_regbase.h:223-242, common.h, and the FP16 instantiation table in template_tiling_key.h:129-681.

2. IsDNoEqual — need host-side dNoEqual calc (tiling_normal_regbase.cpp:1438), the tiling key bit 47, the instantiation table rows. Need to see template_tiling_key.h fully (esp. the table lines 129-681), entry_regbase.h FP16 rows.

3. IsNzOut — host side isNzOut at tiling_normal_regbase.cpp:444-451, kernel side FlashAttentionScoreGradNzPost in nz_post.h, entry_regbase.h:102-109, instantiation table rows :153-174, :197-218.

Let me query for more symbols and then read the actual files. The files are in machine scope (op_host/, op_kernel/) — but wait, per my boundaries: "Machine-scope operator sources (op_host/, op_kernel/, …) are outside .ascendc-pilot. Locate with UO KB query / ScopeSet first, then machine-scope windowed Read — never whole-file dumps."

So I can use Read on machine-scope files with windowed reads. Let me locate the files first, then read windowed.

Let me do more uo-query calls to get:
- locate entry_regbase.h FP16 instantiation
- locate dNoEqual in tiling_normal_regbase.cpp
- locate isNzOut in tiling_normal_regbase.cpp
- locate nz_post.h
- locate FlashAttentionScoreGradNzPost

Let me also check callers for these.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern dNoEqual]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern isNzOut]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern FlashAttentionScoreGradNzPost]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern nz_post]
- Thought: 2.8s
I have good data. Now I need to read the actual files to get the precise instantiation table content (template_tiling_key.h:129-681), entry_regbase.h (FP16 rows), and where ORIG_DTYPE_QUERY is used in entry_regbase.h, common.h, etc.

Let me query for ORIG_DTYPE_QUERY in more detail — it seems there's only 1 definition site found, but the task says it's used in entry_regbase.h:223-242 and common.h and build comments. Let me query with different patterns or check the files. Actually locate returned total_matched=1 — maybe the CodeMap doesn't track preprocessor usages the same way. Let me look for ORIG_DTYPE as a broader pattern, and also look for entry_regbase and the FP16 rows.

Let me read the key files in windows. First, let me find the paths:
- op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h (the full table 129-681)
- op_kernel/arch35/flash_attention_score_grad_entry_regbase.h? The task mentions entry_regbase.h:223-242. Let me locate it.

Let me query more.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern entry_regbase]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ORIG_DTYPE]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GET_IS_NZ_OUT]
- Thought: 3.4s
Now I need to read the actual source files to get the exact instantiation table and the FP16 rows. Per my boundaries, machine-scope files (op_kernel/, op_host/) are outside .ascendc-pilot but I can use "machine-scope windowed Read — never whole-file dumps."

Let me find the file paths. The operator dir is d:\TEST\ops-transformer\attention\flash_attention_score_grad. So:
- op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h
- op_kernel/arch35/flash_attention_score_grad_entry_regbase.h
- op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp
- op_kernel/arch35/flash_attention_score_grad_common.h

Let me read the template_tiling_key.h file first (the whole SEL table 129-681), then entry_regbase.h 80-260, then the host file windows 1400-1475 and 420-470, then common.h around 200-280.

These are windowed reads of machine-scope files, which is allowed. Let me read them.
Now let me read the actual machine-scope files in windowed fashion to extract the exact instantiation tables and macros
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [offset=48, limit=220]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h [offset=85, limit=220]
- Thought: 9.6s
I now have the entry_regbase.h content. Note the FP16 wrapper is guarded by if (ORIG_DTYPE_QUERY == DT_FLOAT16) at line 117 (INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL_FP16). And RegbaseFAG's FP16 block at 223-243 is guarded by #if (ORIG_DTYPE_QUERY == DT_FLOAT16).

Note: the FP16 macro at line 117 uses if (ORIG_DTYPE_QUERY == DT_FLOAT16) as a runtime condition — actually ORIG_DTYPE_QUERY is a compile-time macro (-1 by default, or DT_FLOAT16/DT_BF16/DT_FLOAT when built for a specific dtype). If ORIG_DTYPE_QUERY == -1 (i.e., not defined by build flags), if (-1 == DT_FLOAT16) is false at compile time but still requires the macro body to compile — meaning all three dtype branches are compiled in? Wait, no: if ORIG_DTYPE_QUERY == -1, all three if (ORIG_DTYPE_QUERY == DT_FLOAT16) / == DT_BF16 / == DT_FLOAT are runtime-false but the compiler still needs to compile the bodies. Hmm, but for -1, the compiler would warn of constant condition but still compile all three bodies — meaning all dtypes compile. That's the default "all dtypes in one binary" mode.

Actually, since ORIG_DTYPE_QUERY is a macro with integer value, if (ORIG_DTYPE_QUERY == DT_FLOAT16) is a compile-time constant condition; modern compilers will eliminate the false branch. So:
- ORIG_DTYPE_QUERY == -1 (default): all three branches compile (runtime constant conditions), so all dtypes available.
- ORIG_DTYPE_QUERY == DT_FLOAT16: only FP16 branch (lines 223-243, plus the INVOKE macro) is compiled; BF16 and FP32 branches are #if'd out in the template_tiling_key.h SEL table and in RegbaseFAG.

Now for the template_tiling_key.h table. The FP16 section is lines 129-~681 (from the task statement). I've seen rows:
- :131-152 (FP16, SplitAxis 0=BN2GS1S2, non-TND, DTemplateNum 64/192/256/768, DeterType 0, IsDNoEqual 0/1, IsRope 0, IsNzOut 0)
- :153-174 (FP16, BN2GS1S2, non-TND, DTemplateNum 128, IsDNoEqual 0/1, IsNzOut 0/1)
- :175-196 (FP16, BN2GS1S2, TND, DTemplateNum 64/192/256/768, IsDNoEqual 0/1, IsNzOut 0)
- :197-218 (FP16, BN2GS1S2, TND, DTemplateNum 128, IsDNoEqual 0/1, IsNzOut 0/1)
- :219-240 (FP16, BN2GS1S2, non-TND, DTemplateNum 64/128/192/256/768, DeterType 1 (DETER_OLD), IsDNoEqual 0/1, IsNzOut 0)
- :241-262 (FP16, BN2GS1S2, TND, DeterType 1, DTemplateNum 64/128/192/256/768, IsDNoEqual 0/1, IsNzOut 0)

I need to continue reading the table (lines 263-681) to enumerate all FP16 rows, especially the rope rows (:417-438 per the task) and the TND swizzle rows. Let me continue reading the file.
Let me continue reading the instantiation table to enumerate all FP16 rows
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [limit=430, offset=263]
- Thought: 49.7s
I now have the FP16 instantiation table rows from lines 129-681. Let me enumerate them carefully:

FP16 section (#if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16)), lines 129-681:

Row 1 (:131-152): SplitAxis=0 (BN2GS1S2), InputDType=3 (FP16), IsTnd=0, IsDrop 0/1, IsPse 0/1, IsAttenMask 0/1, S1=128, S2=128, DTemplate 64/192/256/768, DeterType=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual 0/1, IsRope=0, OutDType=3, IsNzOut=0, IsTndSwizzle=0, IsRegbase=1 → FFFFF... FagTilingWithTemplateFFFF

Row 2 (:153-174): same but DTemplate=128, IsNzOut 0/1 → FagTilingWithTemplateFFFF

Row 3 (:175-196): same as row 1 but IsTnd=1, IsNzOut=0 → FagTilingWithTemplateFFTF

Row 4 (:197-218): IsTnd=1, DTemplate=128, IsNzOut 0/1 → FagTilingWithTemplateFFTF

Row 5 (:219-240): IsTnd=0, DTemplate 64/128/192/256/768, DeterType=1 (DETER_OLD), IsNzOut=0 → FagTilingWithTemplateTFFF

Row 6 (:241-262): IsTnd=1, DTemplate 64/128/192/256/768, DeterType=1, IsNzOut=0 → FagTilingWithTemplateTFTF

Row 7 (:263-284): IsTnd=0, DTemplate 64/192/256/768, DeterType 2/3/4 (DETER_DENSE/CAUSAL/BAND), IsNEqual 0/1, IsNzOut=0 → FagTilingWithTemplateTFFF

Row 8 (:285-306): IsTnd=0, DTemplate=128, DeterType 2/3/4, IsNEqual 0/1, IsNzOut 0/1 → FagTilingWithTemplateTFFF

Row 9 (:307-328): IsTnd=1, DTemplate 64/192/256/768, DeterType 2/3/4, IsNEqual 0/1, IsNzOut=0, IsTndSwizzle=0 → FagTilingWithTemplateTTTF

Row 10 (:329-350): IsTnd=1, DTemplate=128, DeterType 2/3/4, IsNEqual 0/1, IsNzOut 0/1, IsTndSwizzle=0 → FagTilingWithTemplateTTTF

Row 11 (:351-372): IsTnd=1, DTemplate 64/192/256/768, DeterType 2/3/4, IsNEqual 0/1, IsNzOut=0, IsTndSwizzle=1 → FagTilingWithTemplateTTTT

Row 12 (:373-394): IsTnd=1, DTemplate=128, DeterType 2/3/4, IsNEqual 0/1, IsNzOut 0/1, IsTndSwizzle=1 → FagTilingWithTemplateTTTT

Row 13 (:395-416): SplitAxis=5 (BN2S2), IsTnd=1, DTemplate 64/128/192/256/768, DeterType 2/4, IsNEqual=1, IsBn2MultiBlk=0, IsDNoEqual 0/1, IsRope=0, IsNzOut=0, IsTndSwizzle=0 → FagTilingWithTemplateTTTF

Row 14 (:417-438): SplitAxis=0, IsTnd=0, DTemplate=192, DeterType=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=1 (only!), IsRope=1, IsNzOut=0, IsTndSwizzle=0 → FagTilingWithTemplateFFFF (rope row, non-TND, d=192)

Row 15 (:439-460): SplitAxis=0, IsTnd=1, DTemplate=192, DeterType=0, IsDNoEqual=1, IsRope=1, IsNzOut=0 → FagTilingWithTemplateFFTF (rope row, TND)

Row 16 (:461-482): SplitAxis=0, IsTnd=0, DTemplate=192, DeterType=1, IsDNoEqual=1, IsRope=1, IsNzOut=0 → FagTilingWithTemplateTFFF (rope row, deter old)

Row 17 (:483-504): SplitAxis=0, IsTnd=1, DTemplate=192, DeterType=1, IsDNoEqual=1, IsRope=1, IsNzOut=0 → FagTilingWithTemplateTFTF

Row 18 (:505-526): SplitAxis=0, IsTnd=0, DTemplate=192, DeterType 2/3/4, IsNEqual 0/1, IsDNoEqual=1, IsRope=1, IsNzOut=0 → FagTilingWithTemplateTFFF

Row 19 (:527-548): SplitAxis=0, IsTnd=1, DTemplate=192, DeterType 2/3/4, IsNEqual 0/1, IsDNoEqual=1, IsRope=1, IsNzOut=0, IsTndSwizzle=0 → FagTilingWithTemplateTTTF

Row 20 (:549-570): SplitAxis=0, IsTnd=1, DTemplate=192, DeterType 2/3/4, IsNEqual 0/1, IsDNoEqual=1, IsRope=1, IsNzOut=0, IsTndSwizzle=1 → FagTilingWithTemplateTTTT

Row 21 (:571-592): SplitAxis=1 (BN2), IsTnd=0, DTemplate 64/128/192/256/768, DeterType=0, IsNEqual=0, IsBn2MultiBlk 0/1, IsDNoEqual 0/1, IsRope 0/1, IsNzOut=0 → FagTilingWithTemplateFFFF (BN2 rows allow rope both 0/1)

Row 22 (:593-614): SplitAxis=1, IsTnd=1, same → FagTilingWithTemplateFFTF

Row 23 (:615-636): SplitAxis=5 (BN2S2), IsTnd=0, DTemplate 64/128/192/256/768, DeterType=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual 0/1, IsRope=0, IsNzOut=0 → FagTilingWithTemplateFFFF

Row 24 (:637-658): SplitAxis=5, IsTnd=1, IsTndSwizzle=0 → FagTilingWithTemplateFFTF

Row 25 (:659-680): SplitAxis=5, IsTnd=1, IsTndSwizzle=1 → FagTilingWithTemplateFFTT

So the FP16 section has 25 rows (lines 131-680). All FP16 rows have InputDType=3 (FLOAT16_PRECISION = 3), OutDType=3.

Note: IsEmptyTensor is not in the SEL — the SEL rows all set IsEmptyTensor=0. Empty tensor handled separately in tiling.cpp (SetTilingKey with TILING_KEY_1).

Key observations:
- Row 1 (:131-152): DTemplate 64/192/256/768 → d=80 maps to DTemplate=64 (dTemplateType selection). Wait, need to understand how d maps to DTemplateType. From the previous round: DTemplateType values are 64, 128, 192, 256, 768 (bit 40-29). For d=80, GetDTemplateType probably returns 64 (aligned to 64? or 128?). Let me check. Actually, in the previous round summary it says "已确认 TilingKey 位域（template_tiling_key.h:48-125）与 host 打包（tiling_normal_regbase.cpp:1435-1472)". I should check GetDTemplateType to see what D=80 maps to. Let me query.

- Row 1 has IsDNoEqual 0/1, IsNzOut=0. So for FP16 + D=80 + dropout + non-TND + BN2GS1S2: IsDNoEqual=(d1!=d)||hasRope. If d1==d and no rope → IsDNoEqual=0, IsNzOut=0 (since 80%16==0 → isNzOut false), DTemplateType=? Then the row :131-152 matches: SplitAxis=0, InputDType=3, IsTnd=0, IsDrop=1, IsPse=0/1, IsAttenMask=0/1, S1=128, S2=128, DTemplate in (64,192,256,768), DeterType=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=0, IsRope=0, OutDType=3, IsNzOut=0, IsTndSwizzle=0, IsRegbase=1.

So the combination should be present as long as DTemplateType ∈ {64, 192, 256, 768}. For D=80, which DTemplateType is selected? Need to check GetDTemplateType. If D=80 → DTemplateType=64 (maybe). If it produces 128, then row 2 (:153-174) with DTemplate=128, IsNzOut 0/1 also exists. So either way it's covered.

Now, the interesting question is: what could make kernel not found? The user's scenario: FP16, D=80, dropout on 950 (arch35? Actually 950 might be a different platform - the .uo CodeMap is arch35. 950 maybe Ascend 950 → arch35?). "kernel 找不到" — the tiling key lookup failed in the kernel binary (SEL table).

Possible causes:
1. If host sets a tilingKey bit that no SEL row covers. E.g., isNzOut=1 while DTemplateType=64 (row 1 has IsNzOut=0 only). But 80%16==0 → isNzOut=0. So not that.
2. If hasRope=1 with IsDNoEqual... no, rope rows require IsDNoEqual=1 and DTemplate=192 only. If hasRope with d=80, host sets dNoEqual=1 (because hasRope) and DTemplateType would be 64 → no row matches (rope rows only DTemplate=192) → kernel not found! But user said "带 dropout" not rope. So rope not in scenario.
3. Dropout with IsDrop=1: rows allow IsDrop 0/1, fine.

Let me now check:
- GetDTemplateType in host (what D=80 maps to)
- how dropValue is computed (tiling_normal_regbase.cpp:1435-1472 area)
- the isNzOut host calc with FP16_C0_SIZE: FP16_C0_SIZE=16, 80%16==0 → the condition fBaseParams.d % FP16_C0_SIZE != 0 is false → isNzOut=0 regardless. So for D=80, isNzOut is ALWAYS 0. Good.

Now I need to check the host side more: dNoEqual at 1438, the tilingKey packing at 1460, and GetDTemplateType mapping for d=80. Let me query for GetDTemplateType and DTemplateType host logic. Also check the FP16_C0_SIZE definition and NZ_OUT_MIN_S_SIZE.

Also need to check the kernel-side ORIG_DTYPE_QUERY usage: it's defined as a macro default (-1). Where does the build define it per-dtype? The task asks: "在 kernel 侧（op_kernel/）定义在哪、取值如何随编译单元变化。查 ORIG_DTYPE_QUERY 的所有出现点（template_tiling_key.h 的 #if、entry_regbase.h:223-242、common.h、build 相关注释/宏）". The uo-query locate found only 1 definition site (the #ifndef default in template_tiling_key.h:22-24). But it's used in:
- template_tiling_key.h:129, 682, ... (SEL sections: FP16/BF16/FP32)
- entry_regbase.h:91 (if (ORIG_DTYPE_QUERY != DT_FLOAT)), 117 (== DT_FLOAT16), 121 (== DT_BF16), 125 (== DT_FLOAT), 223 (#if == DT_FLOAT16), 245, 267
- apt.cpp:60, 65, 70 (#if (ORIG_DTYPE_QUERY == DT_FLOAT16/FLOAT/BF16))

Wait — the CodeMap only found ORIG_DTYPE_QUERY in template_tiling_key.h. But the entry_regbase.h snippet clearly shows if (ORIG_DTYPE_QUERY == DT_FLOAT16) at line 117 and #if (ORIG_DTYPE_QUERY == DT_FLOAT16) at line 223. The locate pattern ORIG_DTYPE only matched template_tiling_key.h — probably the UO index treats these as macro references but only indexes definition sites. Hmm, coverage says "definition_sites_count:1, total_matched:1, first_hit". So the index doesn't track the reference sites in entry_regbase.h. That's a limitation; I read the actual file so I have the info.

Where is ORIG_DTYPE_QUERY set per compilation unit? Let me search for where it's defined with a value — maybe in the build scripts (CMakeLists or a compile option) or in a header like "flash_attention_score_grad_common.h". Let me query locate for "DT_FLOAT16" or check apt.cpp's usage. Also check build config. Let me look at apt.cpp and how the kernel is compiled. Also, in the ASCENDC kernel framework, the tiling key template instantiation is generated per dtype via separate compilation with -DORIG_DTYPE_QUERY=... This is often done in the operator's CMakeLists or "compile" config with aoc options like -DORIG_DTYPE_QUERY=3 for FP16. The comment at template_tiling_key.h:21 says "kernel通过宏定义隔离dtype编译tilingkey，降低耗时。tiling侧没有相关宏" — the macro separates dtype compilation.

Let me check common.h around the ORIG_DTYPE_QUERY usage. Also the apt.cpp — it has #if (ORIG_DTYPE_QUERY == DT_FLOAT16) etc. Let me read those windows. And also read host tiling_normal_regbase.cpp 1420-1475 (GetTilingKey), 430-470 (isNzOut), and the DTemplateType mapping function. Let me query for GetDTemplateType.
The FP16 table is fully enumerated. Now let me check the host-side D template mapping, dropValue logic, and the apt.cpp/common.h usage of ORIG_DTYPE_
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GetDTemplateType]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern dropValue]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern FP16_C0_SIZE]
- Thought: 5.5s
Now I have the DTemplateType mapping. For D=80: d <= 128 → NUM128. So dTemplateType=128. This maps to FP16 rows :153-174 (non-TND, DTemplate=128, IsDNoEqual 0/1, IsNzOut 0/1) — that row exists and allows IsDrop 0/1, IsPse 0/1, IsAttenMask 0/1.

Important: GetDTemplateType returns NUM128 for d=80 (80 <= 128). Wait — but there's also a "fuzzy" path: FuzzyForBestSplit calls GetDTemplateType(fBaseParams) to get dInner for fuzzy search. The actual dTemplateType used for tiling key comes from fBaseParams.dTemplateType set in GetDTemplateType. For d=80 without rope → NUM128. Good.

Now let me read the host GetTilingKey region (lines 1420-1475) to see the dropValue/pseValue/attenMaskCfg computation, dNoEqual calc at 1438, and the isRegbasePlatformValue. Also need to see the FBaseParams init to understand hasRope/d1. Let me read tiling_normal_regbase.cpp around 1400-1472.
Now let me read the host GetTilingKey region and the common.h / apt.cpp ORIG_DTYPE usage windows
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=80, offset=1395]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\flash_attention_score_grad_apt.cpp [limit=130, offset=30]
- Thought: 7.2s
Now I have everything on the host GetTilingKey: dNoEqual = (fBaseParams.d1 != fBaseParams.d) || fBaseParams.hasRope (tiling_normal_regbase.cpp:1438). dropValue = keepProb < 1 → ENABLE for dropout.

Now let me check common.h usage of ORIG_DTYPE_QUERY. The uo-query didn't find ORIG_DTYPE_QUERY references in common.h. Let me check where the macro is defined with a value. Actually the locate for "ORIG_DTYPE" found only template_tiling_key.h. Let me look at where the actual per-dtype define occurs — maybe in CMakeLists / build configs. Let me search for it via read of the operator dir listing, or via uo-query on patterns like "DT_FLOAT16" definitions, or search for "aoc" options. Actually the harness says locate is the primary tool; but I can also read files within my allowed scope. The build files (CMakeLists.txt etc.) may be in the operator dir. Let me check what files exist.

Also need to check common.h around 200-280 (TEMPLATES_DEF, GET_IS_NZ_OUT and possibly DTemplateType / NZ logic, plus where ORIG_DTYPE_QUERY might appear in a comment or macro list). Let me read common.h window.
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_common.h [limit=120, offset=180]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern NZ_OUT_MIN_S_SIZE]
- Thought: 127ms
Now I have a solid picture. Let me check where ORIG_DTYPE_QUERY gets set to a per-dtype value — the build system. Let me check the operator directory for CMakeLists.txt or build config. Also check whether there is an "aoc" compile option. Since ORIG_DTYPE_QUERY is a macro, the typical way is -DORIG_DTYPE_QUERY=3 in the aoc command for FP16, or via "compile_options" in CMake. Let me list the operator root dir to see the build files.
Let me check how ORIG_DTYPE_QUERY gets set during build (compile options / CMake), and look at the kernel #if structure in template_tiling_key.h near the FP32 section boundary
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad 
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ORIG_DTYPE_QUERY --siblings]
- Thought: 310ms
The --siblings flag isn't valid. Let me check the CMakeLists.txt to see how ORIG_DTYPE_QUERY is defined per compilation unit.
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\CMakeLists.txt 
- Thought: 703ms
The root CMakeLists delegates to subdirectories. Let me check op_kernel/CMakeLists.txt which likely has the aoc compile flags defining ORIG_DTYPE_QUERY per compilation unit.
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\CMakeLists.txt 
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel 
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\flash_attention_score_grad 
- Thought: 2.9s
No CMakeLists in op_kernel — the build config is probably external (in the CANN build system, not in the operator source tree). Let me look for build-related comments/macros in the kernel sources. The task says "build 相关注释/宏". Let me grep the template_tiling_key.h for DT_FLOAT16 definitions and see if there's a header where the dtype values are defined (e.g., in common.h or elsewhere). Also look at the flash_attention_score_grad.cpp in op_kernel root (the non-apt entry) — maybe it contains the "USE_CASE" / compile-time defines.

Let me also check for "aoc" or "ccec" options in docs, and look at the arch35 directory listing to understand the file set. And importantly, query where DT_FLOAT16 is defined (probably ge dtype enum in kernel includes, or a local define).
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\flash_attention_score_grad.cpp 
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern DT_FLOAT16]
- Thought: 1m 44s
DT_FLOAT16 on the kernel side — the kernel uses DT_FLOAT16 as a macro comparison target. Where is DT_FLOAT16 defined for the kernel? It comes from kernel_operator.h includes probably (ge dtype constants or commondef). The #if (ORIG_DTYPE_QUERY == DT_FLOAT16) usage means DT_FLOAT16 is a compile-time constant (enum value). In the kernel, commondef namespace is used (entry_regbase.h line 21 using namespace commondef;). The DT_FLOAT16 etc. likely come from a header (e.g., "kernel_dtype.h" or "common_def.h") in CANN. That's external — not in the operator source tree. I'll note that the values: in ge/AscendC dtype enums, DT_FLOAT16 = 1? Actually ge::DataType: DT_FLOAT = 0, DT_FLOAT16 = 1, DT_INT8 = 2, DT_INT32 = 3, DT_UINT8 = 4, ..., DT_BF16 = 27. In the CANN common dtypes, DT_FLOAT16=1, DT_FLOAT=0, DT_BF16=27. But the kernel uses commondef. Hmm.

The key question is: how does ORIG_DTYPE_QUERY change per compilation unit? Answer: The build system (CANN op compile, e.g., via "ccec/aoc" or the msopgen compile with --cce-aicore-params) passes -DORIG_DTYPE_QUERY=<dtype> when compiling the FP16 kernel, -DORIG_DTYPE_QUERY=DT_BF16 for BF16, etc. And when not defined, the default -1 in template_tiling_key.h:22-24 makes all three sections active (all dtypes in one binary).

The comment at template_tiling_key.h:21 explicitly says: "kernel通过宏定义隔离dtype编译tilingkey，降低耗时。tiling侧没有相关宏" — i.e., the kernel side isolates dtype compilation via this macro to reduce compile time; the tiling side has no such macro.

I don't have the external build scripts in the operator tree (no CMakeLists in op_kernel, no aoc options visible). The harness boundaries say machine-scope operator sources are outside .ascendc-pilot but windowed reads are allowed. The build script for the kernel is outside this operator tree (in CANN package / msopgen). I can state that ORIG_DTYPE_QUERY is only defaulted in template_tiling_key.h:22-24 and referenced in the kernel (template_tiling_key.h #if, entry_regbase.h, apt.cpp); its per-TU value is injected by the external build (not present in this source tree — UNKNOWN exact compile flags; likely -DORIG_DTYPE_QUERY=DT_FLOAT16 for the FP16 TU). That's honest.

Now let me verify a couple more things:

1. The FP32 section boundary in template_tiling_key.h:682-? to confirm the FP16 region ends at 681. Already confirmed: 681 is #endif of the FP16 section; 682 is #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_BF16).

2. Kernel-side IS_D_NO_EQUAL behavior — I have 7 branch sites from uo-query. Also, where is IS_D_NO_EQUAL used as a template param and where does "dNoEqual" change block splitting / head handling? Let me also check the DTemplateType (dTemplateType=128 → HEAD_DIM_ALIGN=128). Note the cast_softmax_grad.h site uses HEAD_DIM_ALIGN and Duplicate zeroing when IS_D_NO_EQUAL. presfmg_regbase.h DoSoftmaxGrad uses IS_D_NO_EQUAL for buffer zeroing. kernel_base.h SetConstInfo computes Dv offsets. kernel_deter.h GetNextDxAndQueryOffsetTND / SetRunInfoDeterForTND compute dy offsets separately. kernel_base.h SetRunInfo / GetNextDxAndQueryOffset same.

Let me also double check the entry_regbase.h:102-109 range the task mentions — it's the NZ post invocation block (lines 95-110): if constexpr (!IS_NZ_OUT) { FlashAttentionScoreGradS1S2BNGS1S2PostRegbase... } else { FlashAttentionScoreGradNzPost... }. Wait, in entry_regbase.h I read lines 85-114: line 95 if constexpr (!IS_NZ_OUT) → PostRegbase; else → NzPost at lines 101-110. The task mentioned entry_regbase.h:102-109 for NzPost; that matches lines 102-109 in my read: FlashAttentionScoreGradNzPost<INPUT_TYPE, CALC_TYPE, OUTDTYPE, ...> with Init/Process at 107-109.

3. Where is the kernel TEMPLATES_DEF macro defined? It expands to the template parameter list <typename INPUT_TYPE, typename CALC_TYPE, typename OUTDTYPE, bool IS_ATTEN_MASK, ... bool IS_NZ_OUT, ...>. That's in common.h presumably (CUBE_BLOCK_TRAITS macros at 284-304 generate it). Good enough — I have the macro list from common.h:284-304 showing IS_NZ_OUT and IS_D_NO_EQUAL as template fields.

4. Confirm host-side d1 semantics: dNoEqual = (d1 != d) || hasRope. D=80, d1==d → 0, no rope → 0. Good.

5. Confirm isNzOut for D=80: 80 % 16 == 0 → condition fBaseParams.d % FP16_C0_SIZE != 0 false → isNzOut=0, regardless of other conditions. Also d < 128 and d > 64 would be true for 80, but the %16 check kills it. So isNzOut is ALWAYS 0 for D=80. Also note for D=80, dTemplateType=128 (row :153-174 has IsNzOut 0/1), so even if isNzOut were 1, the row :153-174 covers it for the non-TND case. But isNzOut=1 is unreachable at D=80.

6. FP16 + D=80 + dropout: 
   - splitAxis: default for normal FAG is BN2GS1S2 (0)? The host decides. If standard BNSD/non-TND with s1s2, splitAxis=0. For TND might be 0 too or BN2S2 (5) or BN2 (1). The user's case is presumably BN2GS1S2 (the common case).
   - InputDType=3 (FLOAT16_PRECISION). host: fBaseParams.inputDtype — from queryType DT_FLOAT16 → 3? In the key decl, InputDType bit 6-4: 3=FLOAT16_PRECISION. On host, inputDtype is set presumably from queryType mapping: ge::DT_FLOAT16 → 3. Let me check the host mapping of inputDtype to be thorough — fBaseParams.inputDtype assignment. Let me query.
   - IsDrop=1 (keepProb<1).
   - IsTnd=0 (BNSD layout).
   - S1TemplateType=128, S2TemplateType=128.
   - DTemplateType=128 (d=80 → 128).
   - DeterType=0 (non-deterministic).
   - IsNEqual=0.
   - IsBn2MultiBlk=0.
   - IsDNoEqual=0 (d1==d, no rope).
   - IsRope=0.
   - OutDType=3.
   - IsNzOut=0 (80%16==0).
   - IsTndSwizzle=0.
   - IsRegbase=1.

   This maps exactly to FP16 row 2 (:153-174): SplitAxis=0, InputDType=3, IsTnd=0, IsDrop 0/1, IsPse 0/1, IsAttenMask 0/1, S1=128, S2=128, DTemplate=128, DeterType=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual 0/1, IsRope=0, OutDType=3, IsNzOut 0/1, IsTndSwizzle=0, IsRegbase=1. ✓ present.

So with default build (ORIG_DTYPE_QUERY == -1) or FP16-only build (== DT_FLOAT16), the combination exists. The combination is reachable and in the table.

But wait — what about IsPse / IsAttenMask? User has dropout; pse and attenMask optional. Both 0/1 allowed. Fine.

Also IsEmptyTensor=0 — normal case. Good.

7. What could "kernel not found" be then? The task says "结论：这三个开关各自在什么取值下会「砍掉」组合导致 kernel 找不到（若 host 可达集与 SEL 表完全对齐就明确说不可达）". So I need to analyze each switch for gaps:

IsDNoEqual:
- Host reachable: dNoEqual=1 iff d1!=d or hasRope.
- Table coverage of IsDNoEqual=1:
  - BN2GS1S2 non-TND, DTemplate∈{64,192,256,768}, Deter=0 (row :131-152): YES 0/1.
  - BN2GS1S2 non-TND, DTemplate=128 (row :153-174): YES 0/1.
  - TND equivalents rows :175-218: YES.
  - DETER_OLD rows :219-262: YES 0/1.
  - DETER_NEW rows :263-350: YES 0/1; swizzle rows :351-394: YES 0/1.
  - BN2S2+TND rows :395-416: YES 0/1.
  - Rope rows :417-570: IsDNoEqual forced to 1 (rope implies dNoEqual) — matches host: hasRope ⇒ dNoEqual=1. Note rope rows only have DTemplate=192! If hasRope with d=80: GetDTemplateType returns 192 when hasRope (line 849-852) → DTemplate=192, so rope rows :417-438 match (DTemplate=192, Deter=0, IsTnd=0, IsDNoEqual=1, IsRope=1, IsNzOut=0). ✓ consistent.
  - BN2 rows :571-614: IsDNoEqual 0/1, IsRope 0/1 — but wait, row :571-592 has SplitAxis=1 (BN2), non-TND: IsDNoEqual 0/1, IsRope 0/1. So BN2 supports dNoEqual=1 and rope both independently.
  - BN2S2 non-TND rows :615-636: IsDNoEqual 0/1, IsRope=0.
  - BN2S2 TND rows :637-680: IsDNoEqual 0/1, IsRope=0.
  
  So IsDNoEqual=1 is covered in essentially every row family (0,1 allowed) except the rope rows force it to 1 (which is consistent with host semantics). Gap analysis: host dNoEqual=1 happens when d1!=d (asymmetric K/V dims) or hasRope. For d1!=d without rope: row families covering D=80 (DTemplate=128): non-TND row :153-174 allows IsDNoEqual 0/1 ✓. So no gap. UNKNOWN potential gap: if d1!=d and hasRope with d != 192 → host GetDTemplateType forces 192 for hasRope, so fine. If d1!=d, no rope, D=80: DTemplate=128, covered by :153-174 (or TND :197-218).

IsNzOut:
- Host reachable isNzOut=1 requires: splitAxis==BN2GS1S2 && 64<d<128 && d%16!=0 && dtype not fp8/fp32 && deter != DETER_OLD && enableSwizzle && s1>=min && s2>=min.
  - So d must be in (64,128) and NOT divisible by 16: e.g., 80? no — 80%16==0 → excluded. 72? 72%16=8 → isNzOut could be 1 if other conditions hold (enableSwizzle etc.).
  - Table rows with IsNzOut=1: only DTemplate=128 rows: :153-174 (non-TND), :197-218 (TND), :285-306 (DETER_NEW non-TND), :329-350 (DETER_NEW TND), :373-394 (DETER_NEW TND swizzle). Note rows with DTemplate=64/192/256/768 and IsNzOut=1 DO NOT exist. And DETER_OLD rows have IsNzOut=0 only.
  - Now: isNzOut=1 requires 64<d<128 → dTemplateType=128 (GetDTemplateType: d<=128 → 128). So any d that could produce isNzOut=1 has DTemplate=128. ✓ aligned.
  - isNzOut=1 also requires deterSparseType != DETER_OLD (host). DETER_NEW rows :285-306 etc. allow IsNzOut 0/1 ✓. DETER_OLD (1) rows :219-262 have IsNzOut=0 — but host excludes DETER_OLD from isNzOut=1 ✓.
  - What about fp32/fp8? Host excludes them; GET_IS_NZ_OUT (kernel) also excludes float/fp8. But the SEL rows for FP32 (InputDType=1) presumably have IsNzOut=0 only (they're in a later section). Also the isNzOut=1 rows are all FP16 (InputDType=3) and BF16 (InputDType=2) sections. For BF16, similar rows presumably exist in the BF16 section. I don't need to fully enumerate those.
  - EnableSwizzle gate: isNzOut=1 requires enableSwizzle; if not enabled → 0. No gap.
  - So isNzOut host-reachable set ⊆ table rows with IsNzOut=1: only d∈(64,128)\{multiples of 16}, DTemplate=128, deter∈{0,2,3,4}, fp16/bf16, BN2GS1S2. Rows :153-174 covers non-TND deter=0; :197-218 TND deter=0; :285-306 non-TND deter new; :329-350 TND deter new; :373-394 TND deter new + swizzle. All ✓. So no gap — host reachable set aligns with table.
  - D=80: 80%16==0 → isNzOut=0 ALWAYS. ✓ no impact.

ORIG_DTYPE_QUERY:
- This is the one that can "cut" combinations: if the kernel binary was compiled with ORIG_DTYPE_QUERY == DT_FLOAT16 (FP16-only TU), then the SEL table only contains FP16 rows. If ORIG_DTYPE_QUERY == DT_BF16, the FP16 rows aren't compiled in at all — host requests FP16 → no kernel. If ORIG_DTYPE_QUERY == DT_FLOAT, only FP32. If ORIG_DTYPE_QUERY == -1 (default, not set by build), all three sections compile in one binary.
- Also inside RegbaseFAG (entry_regbase.h:223-287), the FP16 dispatch is guarded by #if (ORIG_DTYPE_QUERY == DT_FLOAT16) — so in a BF16-only build, FP16 combos not only are absent from the SEL table but also the dispatch code isn't compiled.
- Relationship to InputDType (bit6-4): InputDType is a runtime tiling key field whose value is decided by host from query dtype (3 for FP16). ORIG_DTYPE_QUERY is a compile-time selector that decides which SEL sections are instantiated and which dtype the T1/half template arguments use. They are consistent by construction in a proper build: FP16 query → host sets InputDType=3 → needs the FP16 section (compiled when ORIG_DTYPE_QUERY ∈ {-1, DT_FLOAT16}).

So the "kernel not found" in FP16+D=80+dropout: if the deployed kernel binary was compiled as a BF16-only or FP32-only TU (ORIG_DTYPE_QUERY=DT_BF16/DT_FLOAT), the FP16 rows are absent → kernel lookup fails even though the combination would be present in the FP16 table. Alternatively if the build left it -1, everything's present. Also, mismatch in the empty-tensor path: apt.cpp:60-74 compiles empty-tensor code only for matching ORIG_DTYPE_QUERY; a build with ORIG_DTYPE_QUERY=-1 compiles all three blocks (each guarded by distinct #if, so exactly one instantiates at runtime... actually with -1 none of the #if (ORIG_DTYPE_QUERY == DT_FLOAT16) blocks are compiled!). Hmm wait — this is important:

In apt.cpp lines 60-74:
#if (ORIG_DTYPE_QUERY == DT_FLOAT16)
    FlashAttentionScoreGradEmptyTensorRegbase<half> op; ...
#endif
#if (ORIG_DTYPE_QUERY == DT_FLOAT)
    ... float ...
#endif
#if (ORIG_DTYPE_QUERY == DT_BF16)
    ... bfloat16_t ...
#endif
If ORIG_DTYPE_QUERY == -1, none of these three blocks compile → empty-tensor path has NO op! That would be a bug for the -1 default... unless the build ALWAYS defines ORIG_DTYPE_QUERY to a concrete value (3/0/27 etc.) and the -1 default is just a fallback for the tiling-key header only (template_tiling_key.h:129 (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16) compiles all sections when -1). Hmm, but then in apt.cpp with -1 the empty tensor path would be empty. That suggests the real builds always pass a concrete ORIG_DTYPE_QUERY. Also note entry_regbase.h:91 if (ORIG_DTYPE_QUERY != DT_FLOAT) — with -1 that's true (skips the post stage for float only... wait != DT_FLOAT is true → post stage runs for -1 too). And entry_regbase.h:116-126 uses if (ORIG_DTYPE_QUERY == DT_FLOAT16) — runtime-style if, not #if: with -1 all three branches are compiled but only the matching one executes. But in the SEL table, -1 means ALL sections are instantiated.

So the exact behavior differs between #if-style guards (template_tiling_key.h, apt.cpp) and if-style guards (entry_regbase.h INVOKE macros). For the FP16+D=80+dropout scenario the key question is what the deployed binary's ORIG_DTYPE_QUERY value was. If the user's environment built with -DORIG_DTYPE_QUERY=DT_FLOAT16 (FP16-only build to save compile time — exactly what the comment at template_tiling_key.h:21 describes), and the framework dispatches by tiling key, then FP16 combos are present. If the binary was built for BF16/FP32 only (e.g., a different platform's kernel set, or a stale kernel cache), FP16 combos are absent → "kernel not found".

I should also confirm how host computes inputDtype (fBaseParams.inputDtype) — mapping queryType→3 for FP16. Let me check quickly. Also check S1TemplateType/S2TemplateType for D=80 standard case (GetS1S2TemplateType returns 128/128 presumably).

Let me do a couple more targeted queries to confirm:
1. fBaseParams.inputDtype assignment (host).
2. GetS1S2TemplateType behavior for typical sizes.
3. Where TEMPLATES_DEF / TEMPLATES_DEF_NO_DEFAULT are defined (to show the kernel template arg list includes IS_D_NO_EQUAL / IS_NZ_OUT — the task explicitly asked for this in entry_regbase.h).

Actually, the task asked: "给出 entry_regbase.h 里 FP16 实例化宏列表的精确范围（哪些组合被实例化）" — the FP16 macro list in entry_regbase.h is: INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL_FP16 (line 116-118), used at lines 225-241 for the three splitAxis branches (BN2GS1S2, BN2S2, BN2), each instantiating with (half, float, half, ...). And INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL_FP16 (184-186) — wait, actually line 236-241 uses INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL_FP16 for the BN2 branch. Yes: line 237 INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL_FP16(...). So FP16 instantiates:
- splitAxis==BN2GS1S2: INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL (half,float,half,...) lines 225-228
- splitAxis==BN2S2: same macro lines 231-234
- splitAxis==BN2: INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL (half,float,half,...) lines 237-240
all gated by #if (ORIG_DTYPE_QUERY == DT_FLOAT16) (line 223) and the FP16 wrapper if (ORIG_DTYPE_QUERY == DT_FLOAT16) (line 117).

Hmm wait — there's a subtlety: INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL_FP16 (line 116-118) does if (ORIG_DTYPE_QUERY == DT_FLOAT16) INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL(__VA_ARGS__). With ORIG_DTYPE_QUERY==-1, this compiles the whole body but guarded by runtime-if false... Actually the if guards the whole INVOKE macro body do { ... } while(0)? No — if (cond) MACRO(...) expands to if (cond) do { ... } while (0) — the whole body is inside the if statement, so with -1 (false at compile time), the compiler still must parse and compile the body (it's in the TU), but it won't execute. With -1, all three dtype bodies compile. OK.

Also note: with -1, template_tiling_key.h compiles all three SEL sections (FP16/BF16/FP32) — the dispatch framework will find any dtype combo. But apt.cpp empty-tensor path compiles NO empty-tensor op with -1. That's an inconsistency but only affects empty-tensor path. Since the task is about FP16+D=80+dropout (normal non-empty), not critical; I can flag it as an observation.

Now the key conclusion for "kernel 找不到": The three switches, in the FP16+D=80+dropout case:
- ORIG_DTYPE_QUERY: controls whether the FP16 SEL section is compiled at all. If the deployed .o/.json was built with ORIG_DTYPE_QUERY=DT_BF16 or DT_FLOAT, the FP16 combination (InputDType=3) is absent → kernel not found. Also entry_regbase.h:223 #if (ORIG_DTYPE_QUERY == DT_FLOAT16) means a BF16-only build has no FP16 dispatch code at all.
- IsDNoEqual=0 for D=80 d1==d (no rope): row :153-174 covers IsDNoEqual 0/1 → present. If d1!=d → dNoEqual=1 → still covered (:153-174 allows 1). No cut.
- IsNzOut=0 for D=80 (80%16==0 → host isNzOut expression false; kernel GET_IS_NZ_OUT requires HEAD_DIM_ALIGN==128 i.e., dTemplateType=128 AND fp16/bf16 — for D=80 dTemplateType=128, but host gate d%16!=0 fails → 0). Row :153-174 allows IsNzOut 0/1 → present. No cut.

Therefore: FP16+D=80+dropout combination is in the table (row :153-174: SplitAxis=0/BN2GS1S2, InputDType=3, IsTnd=0, IsDrop∈{0,1}, IsPse∈{0,1}, IsAttenMask∈{0,1}, S1=128, S2=128, DTemplate=128, Deter=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual∈{0,1}, IsRope=0, OutDType=3, IsNzOut∈{0,1}, IsTndSwizzle=0, IsRegbase=1) — provided the FP16 section was compiled (ORIG_DTYPE_QUERY ∈ {-1, DT_FLOAT16}). If the host reachable key equals exactly that, then "kernel not found" is NOT caused by these three switches; it points at either (a) the FP16 SEL section not being compiled into the deployed binary (ORIG_DTYPE_QUERY mismatch / wrong binary), or (b) the kernel binary being for a different arch/SoC (950 vs arch35 build), or (c) the key lookup mechanism needing the exact combination present in the generated binary.

Wait — one more: 950. The task says "用户在 950 上跑". The .uo CodeMap is arch35. Ascend 950 would use arch35? The 950 chip is typically arch35 (Ascend 910C?). Actually Ascend 950 → arch35 seems plausible per this repo's layout (arch35 is the newer arch). Not part of this focus; I'll note it as a possible factor outside the three switches.

Let me quickly confirm the host inputDtype mapping and GetS1S2TemplateType so I can state the exact key fields. Also confirm DTemplateType selection happens via FuzzyForBestSplit → GetDTemplateType (d=80 → 128). Let me query inputDtype on host.
Let me confirm the host-side inputDtype mapping and the S1/S2 template selection, plus where TEMPLATES_DEF is generated
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern inputDtype]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern TEMPLATES_DEF]
- Thought: 1m 41s
I now have everything I need. Let me summarize the complete analysis:

Host DetermineMode (tiling_common_regbase.cpp:1652-1667): FP16 (ge::DT_FLOAT16) → falls into the final else → fBaseParams.inputDtype = DtypeEnum::FLOAT16_PRECISION (= 3). outDtype = inputDtype (line 1182). So host InputDType=3, OutDType=3 for FP16. This matches the SEL table rows' InputDType=3/OutDType=3.

Now the complete picture for FP16 + D=80 + dropout:

Tiling key fields:
- bit0 IsEmptyTensor = 0
- bit3-1 SplitAxis = 0 (BN2GS1S2, normal s1s2 path)
- bit6-4 InputDType = 3 (FLOAT16_PRECISION)
- bit7 IsTnd = 0 (BNSD layout, not TND)
- bit8 IsDrop = 1 (keepProb < 1)
- bit9 IsPse = 0 or 1
- bit10 IsAttenMask = 0 or 1
- bit18-11 S1TemplateType = 128
- bit28-19 S2TemplateType = 128
- bit40-29 DTemplateType = 128 (D=80 → GetDTemplateType returns NUM128 since 64<80≤128)
- bit44-41 DeterType = 0 (non-deterministic)
- bit45 IsNEqual = 0
- bit46 IsBn2MultiBlk = 0
- bit47 IsDNoEqual = 0 (d1==d && !hasRope)
- bit48 IsRope = 0
- bit51-49 OutDType = 3
- bit52 IsNzOut = 0 (80%16==0 → host gate fails)
- bit53 IsTndSwizzle = 0
- bit54 IsRegbase = 1

This is exactly row 2 of the FP16 SEL table (:153-174): SplitAxis=0, InputDType=3, IsTnd=0, IsDrop∈{0,1}, IsPse∈{0,1}, IsAttenMask∈{0,1}, S1=128, S2=128, DTemplate=128, Deter=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual∈{0,1}, IsRope=0, OutDType=3, IsNzOut∈{0,1}, IsTndSwizzle=0, IsRegbase=1 → present.

Q1 ORIG_DTYPE_QUERY: 
- Definition: template_tiling_key.h:21-24, default -1 ("kernel通过宏定义隔离dtype编译tilingkey，降低耗时。tiling侧没有相关宏").
- Usage sites:
  - template_tiling_key.h:129 (#if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16) — FP16 section 129-681), :682 (BF16 section), and later FP32 section (need to confirm line — but it's around 920+; I saw 682 for BF16. The FP32 section #if would be #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT) further down. I didn't read that far, but the pattern is clear from 129 and 682.)
  - entry_regbase.h:91 (if (ORIG_DTYPE_QUERY != DT_FLOAT) — post stage only for non-FP32), :116-118 (FP16 wrapper macro if (ORIG_DTYPE_QUERY == DT_FLOAT16)), :120-122 (BF16 wrapper), :124-126 (FP32 wrapper), :223 (#if (ORIG_DTYPE_QUERY == DT_FLOAT16) — FP16 dispatch in RegbaseFAG, 223-243), :245 (BF16 dispatch), :267 (FP32 dispatch).
  - apt.cpp:60 (#if == DT_FLOAT16 → EmptyTensorRegbase<half>), :65 (DT_FLOAT → float), :70 (DT_BF16 → bfloat16_t).
- How it isolates: template_tiling_key.h:129-681 (FP16), :682-~ (BF16), then FP32. With ORIG_DTYPE_QUERY==-1 all three sections compile (one binary, all dtypes). With ORIG_DTYPE_QUERY==DT_FLOAT16 only FP16 rows compile (single-dtype TU, reduced compile time). The InputDType runtime field (bit6-4) is orthogonal: it's part of the tiling key hash; the framework only finds a row if the FP16 section was compiled in that TU. In RegbaseFAG the #if (ORIG_DTYPE_QUERY == DT_FLOAT16) block binds template types half/float/half to InputDType=3 combos.
- Note: with -1, entry_regbase.h's if (ORIG_DTYPE_QUERY == DT_FLOAT16) guards (116-118) are compile-time-constant false-ish (actually -1 != DT_FLOAT16 → false, so the FP16 invoke body is still compiled but the condition is false; the FP16 dispatch code at 223 is #if'd so with -1 the FP16 dispatch block IS compiled (since #if (-1 == DT_FLOAT16) is false!). WAIT — careful!

entry_regbase.h:223: #if (ORIG_DTYPE_QUERY == DT_FLOAT16) — with ORIG_DTYPE_QUERY == -1, this #if is FALSE → the FP16 dispatch block (225-241) is NOT compiled! Same for BF16 (245) and FP32 (267). So with -1, RegbaseFAG has NO dispatch body at all! Hmm — but then how does the SEL table's "all three sections" mode work? The SEL table (ASCENDC_TPL_SEL) is used by the tiling key → kernel entry machinery (the framework generates the dispatch table from ASCENDC_TPL_SEL), while RegbaseFAG is the per-combination function that actually instantiates the operator class. If ORIG_DTYPE_QUERY == -1 and all three SEL sections are compiled, but RegbaseFAG's dispatch bodies are all #if'd out...

Actually wait, maybe I misread. Let me re-check entry_regbase.h:223-243: 

#if (ORIG_DTYPE_QUERY == DT_FLOAT16)
    if constexpr (splitAxis == BN2GS1S2) {
        INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL_FP16(...)
        return;
    } else if constexpr (splitAxis == BN2S2) { ... } else if constexpr (splitAxis == BN2) { ... }
#endif

So the FP16 body is inside #if (ORIG_DTYPE_QUERY == DT_FLOAT16). With -1, this body is excluded, and BF16/FP32 bodies also excluded. So with -1, RegbaseFAG is EMPTY — it compiles but does nothing. But the comment says "-1" default is to include all dtypes in the SEL table... The template_tiling_key.h:129 condition is (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16) — explicitly allows -1 to include FP16 rows. So the SEL table includes all rows for -1, but the dispatch function RegbaseFAG's dtype bodies are all #if'd out for -1.

Hmm, is that a real inconsistency, or does the framework only use the SEL table to select the template instantiation of flash_attention_score_grad<...> (apt.cpp), which then calls RegbaseFAG? For -1: SEL includes all rows → the framework instantiates flash_attention_score_grad<...> for every combination → each calls RegbaseFAG<...> → but RegbaseFAG's body for FP16 is not compiled → empty function → runtime does nothing (silently) → kernel "not found"? Actually no — if the function body is empty, the kernel would launch but do nothing, which would present as wrong results, not "kernel not found".

Hold on. Maybe the -1 value never reaches entry_regbase.h because the actual build always defines ORIG_DTYPE_QUERY to a concrete dtype value per TU (3 TUs: FP16/BF16/FP32), and the -1 default only exists for the tiling-key header standalone usage (e.g., when the SEL table is consumed by the host-side tiling key generation or the framework's kernel selection without a dtype-split build). The comment at template_tiling_key.h:21 "kernel通过宏定义隔离dtype编译tilingkey，降低耗时" strongly suggests the intended build defines ORIG_DTYPE_QUERY per TU.

For the analysis, the important part: whether FP16+D=80+dropout is found depends on the deployed binary containing the FP16 TU (ORIG_DTYPE_QUERY == DT_FLOAT16) or an all-dtype TU (ORIG_DTYPE_QUERY == -1 AND with RegbaseFAG bodies — which, per source, would be empty). Honestly, I should flag the -1 behavior as a caveat: in the checked-in source, with -1 the SEL table includes all dtypes but RegbaseFAG dtype dispatch bodies are #if-excluded, which would make -1 builds non-functional for the actual computation (silent no-op), so real builds must define ORIG_DTYPE_QUERY to a concrete dtype. The exact value injected per TU is set by the external build system (not present in this operator tree — CMakeLists only recurses subdirs; no kernel CMakeLists found in op_kernel/). I'll mark that as UNKNOWN for the exact build flags but explain the mechanism.

Actually, wait — let me double-check: is there a possibility that the FP16 section is selected for -1 via SEL, and RegbaseFAG's FP16 body compiled via a different macro expansion? No — I read the actual file. entry_regbase.h:223 #if (ORIG_DTYPE_QUERY == DT_FLOAT16). With -1 it's false. Confirmed by reading.

So the mechanism: per-dtype TUs. The user's FP16 scenario requires the FP16 TU. If the 950 environment loaded a kernel binary built with a non-FP16 ORIG_DTYPE_QUERY (or a stale binary with no FP16 section), "kernel 找不到" occurs — this is the ORIG_DTYPE_QUERY "cut".

Q2 IsDNoEqual:
- Host: tiling_normal_regbase.cpp:1438 dNoEqual = (fBaseParams.d1 != fBaseParams.d) || fBaseParams.hasRope — packed at bit47 via GET_TPL_TILING_KEY arg 13 (line 1466). For D=80 with d1==d and no rope: 0.
- Kernel template param IsDNoEqual (apt.cpp:37, entry_regbase.h INVOKE macros at 47, 67, 71, 77, 81, 104, 131, 147, 151, 157, 161; common.h CUBE_BLOCK_TRAITS_CONST_FIELDS line 297). 7 behavior sites:
  1. cast_softmax_grad.h:76-81 (CopyInSoftmaxGrad): when IS_D_NO_EQUAL, zero-fill yTensor/dxTensor before DataCopyPad (padding to HEAD_DIM_ALIGN because d≠d1).
  2. kernel_deter.h:145-150 (GetNextDxAndQueryOffsetTND): computes bOffsetDv/s1OffsetDv/n2OffsetDv/gOffsetDv when D_NO_EQUAL (V-tensor has different D), :160-164 dyOffset uses Dv offsets.
  3. kernel_deter.h:291-293 (SetRunInfoDeterForTND): dyOffset = GetDxOffset when D_NO_EQUAL; :301-303 valueOffset = GetValueOffset.
  4. presfmg_regbase.h:491-505, 525+ (DoSoftmaxGrad): Duplicate zero fills in V buffers when D_NO_EQUAL (nBurst * tempDimAlign).
  5. kernel_base.h:523-557 (SetConstInfo): builds the whole "Dv" family of constInfo offsets (s1Dv, gS1Dv, n2GS1Dv, s2Dv, n2S2Dv, gDv, n2Dv, bN2Dv, n2GDv, bN2GDv, plus Rope Dr offsets) when IS_D_NO_EQUAL; else aliases them to the D versions.
  6. kernel_base.h:1078-1080 (SetRunInfo): dyOffset = GetDxOffset; :1095-1097 valueOffset = GetValueOffset.
  7. kernel_base.h:2265-2270 (GetNextDxAndQueryOffset TND swizzle branch): Dv offsets for b/s1/n2/g.
- So IS_D_NO_EQUAL=1 changes: separate Dy/DV GM addressing (value offset computed from GetValueOffset, Dv size), zero-fill of the padded D columns in softmax-grad input buffers, and Dv const info family. It's a compile-time branch on a runtime-decided key bit.
- Table coverage of IsDNoEqual=1: every non-rope FP16 row allows IsDNoEqual 0/1 (:145, :167, :189, :211, :233, :255, :277, :299, :321, :343, :365, :387, :409, :585, :607, :629, :651, :673). Rope rows force IsDNoEqual=1 (:431, :453, :475, :497, :519, :541, :563) — consistent because hasRope ⇒ dNoEqual=1 on host (1438). So if d1!=d (no rope), IsDNoEqual=1, D=80 → DTemplate=128 → row :153-174 allows IsDNoEqual=1 ✓. TND equivalent :197-218 ✓. So no gap: all host-reachable dNoEqual=1 combos exist in the table. The only theoretical gap would be d1!=d + hasRope + D≠192, but hasRope forces DTemplate=192 (GetDTemplateType:849-852) and rope rows only cover DTemplate=192 — aligned. Also BN2S2 TND rows :395-416 and :637-680 don't allow rope (IsRope=0) but that's a rope limitation, not DNoEqual.
- D=80, d1==d → IsDNoEqual=0. Present in :153-174.

Q3 IsNzOut:
- Host: tiling_normal_regbase.cpp:444-451. Full conjunction:
  (a) splitAxis == BN2GS1S2
  (b) 64 < d < 128
  (c) d % 16 != 0 (FP16_C0_SIZE=16)
  (d) queryType not fp8/fp32 (i.e., fp16 or bf16)
  (e) deterSparseType != DETER_OLD
  (f) enableSwizzle (isExceedL2Cache || isLargeInvalidBlk) && blockOuter == aicNum
  (g) s1 >= NZ_OUT_MIN_S_SIZE && s2 >= NZ_OUT_MIN_S_SIZE
- Packed at bit52 (GET_TPL_TILING_KEY arg 16, line 1467).
- Kernel: template param IS_NZ_OUT (common.h:299; apt.cpp:37; entry_regbase.h:95-110): if constexpr (!IS_NZ_OUT) { PostRegbase (row-major fixp2gm) } else { FlashAttentionScoreGradNzPost (nz_post.h) }. And in block_cube.h the three Fixpout iterators use if constexpr (!IS_NZ_OUT) row-major fixpipe (CO2Layout::ROW_MAJOR) vs NZ layout fixpipe (CO2Layout::NZ) at :773, :1085, :1394. Also GET_IS_NZ_OUT (common.h:267-274) is the kernel-side constant: BN2GS1S2 && !fp32/fp8 && HEAD_DIM_ALIGN==128 (i.e., dTemplateType==128) && !DETER_OLD.
- D=80: 80 % 16 == 0 → clause (c) fails → isNzOut=0 ALWAYS on host (regardless of enableSwizzle/s1/s2). Kernel GET_IS_NZ_OUT would also give false because HEAD_DIM_ALIGN==128 is true (dTemplateType=128) but that only matters if host set the bit; host always 0 at D=80. ✓
- Table rows with IsNzOut=1 exist only for DTemplate=128: :153-174 (non-TND deter 0), :197-218 (TND deter 0), :285-306 (non-TND deter new), :329-350 (TND deter new), :373-394 (TND deter new + swizzle). Since host isNzOut=1 requires 64<d<128 → GetDTemplateType → NUM128, and requires deter≠DETER_OLD, and fp16/bf16 — all consistent with the rows that allow IsNzOut=1. DETER_OLD rows (:219-262, :461-504, etc.) have IsNzOut=0 only — host excludes DETER_OLD from isNzOut=1 (clause e). FP32 rows: fp32 excluded on host (clause d) and kernel GET_IS_NZ_OUT excludes float — the FP32 SEL rows (later section) presumably have IsNzOut=0. So host-reachable isNzOut=1 set ⊆ table. No gap.
- Note: row :153-174 has BOTH IsDNoEqual 0/1 AND IsNzOut 0/1 — the cross product. Also row :285-306 allows IsNEqual 0/1 + IsNzOut 0/1. So even the cross products (DNoEqual=1 & NzOut=1) exist for DTemplate=128 non-TND.

Q4 Conclusion:
- FP16 + D=80 + dropout (BNSD, non-TND, non-deterministic, no rope, d1==d): key = (IsEmpty=0, SplitAxis=0, InputDType=3, IsTnd=0, IsDrop=1, IsPse∈{0,1}, IsAttenMask∈{0,1}, S1=128, S2=128, DTemplate=128, Deter=0, IsNEqual=0, IsBn2MultiBlk=0, IsDNoEqual=0, IsRope=0, OutDType=3, IsNzOut=0, IsTndSwizzle=0, IsRegbase=1) → row :153-174 present.
- The three switches for this scenario: ORIG_DTYPE_QUERY=DT_FLOAT16 (or -1), IsDNoEqual=0, IsNzOut=0. All within table.
- "kernel 找不到" is NOT explained by IsDNoEqual or IsNzOut (both 0, and both 0/1 variants are in the FP16 table). It can only be explained by ORIG_DTYPE_QUERY: the deployed kernel binary must contain the FP16 section — i.e., compiled with ORIG_DTYPE_QUERY == DT_FLOAT16 (or -1 with the caveat about RegbaseFAG dispatch bodies). If the 950 binary was compiled for another dtype (e.g., DT_BF16/DT_FLOAT TU) or the FP16 TU is missing/stale, lookup fails. Also verify the arch: .uo CodeMap is arch35; if the 950 runtime expects a different arch build (arch22/arch2x kernel — flash_attention_score_grad.cpp is arch22), the arch35 binary wouldn't match. That's outside the three switches but worth flagging.

Also worth noting the -1 default caveat: with -1, the SEL table (template_tiling_key.h) includes all dtypes, but RegbaseFAG's dtype dispatch blocks (entry_regbase.h:223/245/267) are #if-excluded for -1, so a -1 build would have an empty RegbaseFAG — meaning real production builds must pass a concrete ORIG_DTYPE_QUERY per TU (the exact flags aren't in this tree — UNKNOWN; likely ccec/aoc -DORIG_DTYPE_QUERY=... from the CANN op build system). And apt.cpp empty-tensor path (60-74) also requires concrete values (with -1 none of the empty-tensor ops compile).

Let me also confirm the FP32 section location for completeness — read template_tiling_key.h lines 693-1000 or so to find #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT). Actually let me just do a quick grep-ish read. I'll read the region around the BF16/FP32 boundary. Actually to save tokens, I can query locate for "DT_FLOAT)" — but that pattern would match many. Let me just read a small window at ~900-980 to find the FP32 #if line. Actually, for the answer I mainly need to know the FP16 region is 129-681 and BF16 starts at 682. The FP32 #if line number is nice-to-have. Let me query it quickly.

Actually — I should be careful about reading too much. Let me do one quick read to find the FP32 #if marker line. I'll search via uo-query for a distinctive FP32 pattern. The pattern "ORIG_DTYPE_QUERY == DT_FLOAT" should hit entry_regbase.h and apt.cpp... but earlier "ORIG_DTYPE" locate only returned template_tiling_key.h — the index seems limited. Let me just read lines 920-1000 of template_tiling_key.h quickly... Actually, a targeted read is fine and cheap.
One last check — the FP32 section marker in the SEL table and the FP16→BF16 boundary line
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_template_tiling_key.h [limit=60, offset=906]
- Thought: 7.9s
I have enough. The BF16 section starts at 682 with InputDType=2; the FP32 section starts later (with InputDType=1) — I don't need its exact line, the pattern is confirmed.

Now let me compose the final Cursor-Explore-style answer. The task is complete with all 4 questions answerable. I must not write answer.yaml or finalize. I'll answer in prose with file:line references.

Key facts to cite:
- ORIG_DTYPE_QUERY default: op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h:22-24 (default -1; comment at :21).
- FP16 SEL region: template_tiling_key.h:129-681 (25 rows); BF16 region starts :682; FP32 later (InputDType=1 rows, e.g., seen :906 area is BF16 TND rows).
- Rows: :131-152, :153-174, :175-196, :197-218, :219-240, :241-262, :263-284, :285-306, :307-328, :329-350, :351-372, :373-394, :395-416, :417-438, :439-460, :461-482, :483-504, :505-526, :527-548, :549-570, :571-592, :593-614, :615-636, :637-658, :659-680.
- entry_regbase.h: INVOKE macro definitions :40-114; FP16 wrapper :116-118; BF16 :120-122; FP32 :124-126; RegbaseFAG template :197-200; FP16 dispatch #if :223-243; BF16 :245-265; FP32 :267-287. NzPost selection :95-110 (PostRegbase row-major vs FlashAttentionScoreGradNzPost at :102-109).
- apt.cpp:35-38 template args; :60-74 empty tensor dtype blocks.
- Host: GetTilingKey tiling_normal_regbase.cpp:1435-1472; dNoEqual :1438; dropValue :1440; tilingKey packing :1460-1468. isNzOut host: :444-451. DetermineMode inputDtype: tiling_common_regbase.cpp:1652-1667; outDtype=inputDtype :1182. GetDTemplateType: tiling_common_regbase.cpp:847-870 (hasRope→192; d≤64→64; d≤128→128; d≤192→192; d≤256→256; else 768).
- Kernel IsDNoEqual sites: cast_softmax_grad.h:76; kernel_deter.h:145, 291; presfmg_regbase.h:491, 525; kernel_base.h:523, 1078, 1095, 2265.
- Kernel IsNzOut sites: block_cube.h:773, 1085, 1394; common.h:267-274 GET_IS_NZ_OUT; entry_regbase.h:95-110; common.h:299 template field.
- Kernel template field list: common.h:284-304 (IS_D_NO_EQUAL :297, IS_NZ_OUT :299), TEMPLATES_DEF :309-311.

Now write the final answer. Format: Cursor Explore style, full prose, numbered 1-4, with file:line. Also include the "UNKNOWN" items: exact build flags that inject ORIG_DTYPE_QUERY per TU (not in operator tree), and note the -1 caveat (RegbaseFAG dispatch bodies #if'd out → production builds must define concrete value).
查询完成。以下按 1-4 逐条给出完整结论（所有行号均来自 digest 211a7ec3… 的 CodeMap 及对应机器文件窗口读取）。
1. ORIG_DTYPE_QUERY —— 编译期 dtype 隔离开关
定义位置：op_kernel/arch35/flash_attention_score_grad_template_tiling_key.h:21-24。文件头注释（:21）明说设计意图：“kernel通过宏定义隔离dtype编译tilingkey，降低耗时。tiling侧没有相关宏”。默认值在 :22-24 兜底为 -1（#ifndef ORIG_DTYPE_QUERY / #define ORIG_DTYPE_QUERY (-1)）。
取值如何随编译单元变化：它是一个预处理器宏，值由 kernel 侧编译（TU）注入——即每个 dtype 单独编译一份 kernel 二进制，各 TU 用不同的 -DORIG_DTYPE_QUERY=…（FP16 TU = DT_FLOAT16，BF16 = DT_BF16，FP32 = DT_FLOAT）。本算子源码树里没有设置该宏的编译脚本（op_kernel/ 下无 CMakeLists；根 CMakeLists.txt 只做子目录递归），因此“具体由哪个构建命令注入”在本仓不可见，标记 UNKNOWN（外部 CANN/算子构建系统注入，通常为 ccec/aoc 的 -D 选项）。这不是障碍：源码里所有消费点都把它当编译期常量。
消费点（按文件）：
- template_tiling_key.h:129 —— #if (ORIG_DTYPE_QUERY == -1) || (ORIG_DTYPE_QUERY == DT_FLOAT16) 包住 FP16 整段 SEL 表（:129-681，共 25 行 ARGS_SEL）；:682 起是 BF16 段（InputDType=2）；再往后是 FP32 段（InputDType=1，如 :906 附近可见 BF16 TND 行仍在 BF16 段内）。所以 -1 或 DT_FLOAT16 才编译 FP16 行；BF16/FP32 单 dtype 编译时 FP16 行整个不存在。
- entry_regbase.h：
- :91 if (ORIG_DTYPE_QUERY != DT_FLOAT) —— 决定主 kernel 之后是否跑 post 阶段（NZ/ROW_MAJOR 回写）。
- :116-118 / :120-122 / :124-126 —— 三个“invoke 包装宏” …_FP16 / _BF16 / _FP32，各自用 if (ORIG_DTYPE_QUERY == DT_FLOAT16/BF16/FLOAT) 守卫宏体。
- :223-243 #if (ORIG_DTYPE_QUERY == DT_FLOAT16) —— RegbaseFAG 里 FP16 三分支（BN2GS1S2 / BN2S2 / BN2）派发，绑定模板实参 half, float, half；:245-265 是 BF16（bfloat16_t, float, bfloat16_t），:267-287 是 FP32（float, float, float）。
- op_kernel/flash_attention_score_grad_apt.cpp:60-74 —— 空 tensor 路径同样按 #if (ORIG_DTYPE_QUERY == DT_FLOAT16/FLOAT/BF16) 分别实例化 FlashAttentionScoreGradEmptyTensorRegbase<half/float/bfloat16_t>。
- common.h 本身不引用该宏（UO 检索只命中 template_tiling_key.h 一个定义点），但它的 TEMPLATES_DEF（common.h:309-311）经 CUBE_BLOCK_TRAITS_*（:284-304）生成 kernel 侧全模板参数表，供 FlashAttentionScoreGradNzPost（nz_post.h:25-26）等类使用。
与 InputDType（bit6-4）的关系：两者正交。InputDType 是运行时 tiling key 字段（位域声明在 template_tiling_key.h:57-64，FP16=3），由 host 决定——DetermineMode（op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp:1652-1667）把 queryType==ge::DT_FLOAT16 落到 else 分支 DtypeEnum::FLOAT16_PRECISION（:1664-1665），outDtype=inputDtype（:1182）。而 ORIG_DTYPE_QUERY 是编译期开关，决定该 TU 的 SEL 表里有没有 InputDType=3 的行、以及 RegbaseFAG 里有没有 half 实参的派发代码。二者必须“同 dtype”才对得上：FP16 请求 → host 打 InputDType=3 → 只有 ORIG_DTYPE_QUERY∈{-1, DT_FLOAT16} 的 TU 才含该组合。
FP16 实例化宏列表的精确范围（entry_regbase.h）：RegbaseFAG（:197-200，模板参数顺序与 apt.cpp:35-38 完全一致）在 #if (ORIG_DTYPE_QUERY == DT_FLOAT16) 块（:223-243）内对三个 splitAxis 各调一次 FP16 宏：
- splitAxis==BN2GS1S2 → INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL_FP16(half, float, half, …)（:225-228，宏体 :40-114）
- splitAxis==BN2S2 → 同宏（:231-234）
- splitAxis==BN2 → INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL_FP16(half, float, half, …)（:237-240，宏体 :129-182）
即 FP16 TU 实例化三组 half/float/half 的组合；每个组合内部再按模板开关（IS_ATTEN_MASK/IS_PSE/IS_DROP/IS_TND/IS_BN2_MULTIBLK/DETER_SPARSE_TYPE/IS_N_EQUAL/IS_D_NO_EQUAL/IS_ROPE/IS_NZ_OUT/IS_TND_SWIZZLE/SPLIT_AXIS/s1/s2/d）展开为具体的 kernel 类（Cube/Vec block、pre/post、presfmg、NzPost）。
一个必须点破的坑：若 ORIG_DTYPE_QUERY 真为 -1，SEL 表会编译三段 dtype（template_tiling_key.h:129/682/…），但 RegbaseFAG 的三个 dtype 派发块都被 #if (==DT_FLOAT16/BF16/FLOAT) 排除（entry_regbase.h:223/245/267），apt.cpp:60-74 空 tensor 块也全部为空——即 -1 构建的函数体是空的（静默 no-op）。因此生产构建必须给每个 TU 注入具体 dtype 值，-1 只是模板头单独编译/回退时的占位。这正是“kernel 找不到/不干活”最可能的源头之一：950 上装的二进制若是非 FP16 TU（BF16/FP32 单 dtype 编译）或旧产物，FP16 组合从 SEL 表到派发代码都不存在。
2. IsDNoEqual（bit47 / IS_D_NO_EQUAL / dNoEqual）
host 侧：op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:1438 —— dNoEqual = (fBaseParams.d1 != fBaseParams.d) || fBaseParams.hasRope。打包进 TilingKey 第 13 个实参（:1466，位域声明 template_tiling_key.h:102-105，bit47）。即“K/V 的 D 与 Q 的 D 不等”或“带 rope”任一成立即为 1。D=80 且 d1==d、无 rope → IsDNoEqual=0。
kernel 侧行为（模板参数 IsDNoEqual，链上 apt.cpp:37 → entry_regbase.h 各 invoke 宏实参 → common.h:297 模板字段表；UO 检索到 7 个 if constexpr (IS_D_NO_EQUAL) 分支点）：
- vector_api/cast_softmax_grad.h:76-81（CopyInSoftmaxGrad）：D_NO_EQUAL 时先把 y/dx 缓冲区按 curLoopSize*HEAD_DIM_ALIGN Duplicate 清零，再 DataCopyPad（d≠d1 时尾列补零）。
- flash_attention_score_grad_kernel_deter.h:145-150（GetNextDxAndQueryOffsetTND）：单独计算 Dv 维的 b/s1/n2/g 偏移（n2GDv/gDv/dSizeV）；:160-164 dyOffset 用 Dv 偏移族，否则复用 queryOffset。
- flash_attention_score_grad_kernel_deter.h:291-293（SetRunInfoDeterForTND）：dyOffset=GetDxOffset；:301-303 valueOffset=GetValueOffset。
- flash_attention_score_grad_presfmg_regbase.h:491-505、:525-527（DoSoftmaxGrad）：V 侧 input 缓冲按 nBurst*tempDimAlign 预清零，规避 Dv 尾列脏数据。
- flash_attention_score_grad_kernel_base.h:523-557（SetConstInfo）：IS_D_NO_EQUAL 时建立整族 Dv 常量（s1Dv/gS1Dv/n2GS1Dv/s2Dv/n2S2Dv/gDv/n2Dv/bN2Dv/n2GDv/bN2GDv，rope 时再加 Dr 族 :534-545）；否则全部别名到 D 版（:546-557）。
- flash_attention_score_grad_kernel_base.h:1078-1080（SetRunInfo）：dyOffset=GetDxOffset；:1095-1097 valueOffset=GetValueOffset。
- flash_attention_score_grad_kernel_base.h:2265-2270（GetNextDxAndQueryOffset，TND swizzle 分支）：同样的 Dv 偏移族。
- 即开关=1 时改变的是“Dv 独立寻址 + 尾列清零”的整条数据通路，全部为编译期分支。
实例化表覆盖：FP16 段里除 rope 行外每一行都允许 IsDNoEqual 0/1——BN2GS1S2 非 TND :145/:167，TND :189/:211，DETER_OLD :233/:255，DETER_NEW :277/:299/:321/:343/:365/:387，BN2S2+TND :409，BN2 行 :585/:607，BN2S2 行 :629/:651/:673。rope 行（:417-570）强制 IsDNoEqual=1（:431/:453/:475/:497/:519/:541/:563）——与 host 语义自洽：hasRope ⇒ dNoEqual=1（:1438）。所以：
- D=80、d1==d → IsDNoEqual=0，命中 :153-174（DTemplate=128 行）。
- 若 d1!=d（无 rope）→ IsDNoEqual=1，仍命中 :153-174（该行允许 0/1）；TND 则命中 :197-218。
- host 可达的 IsDNoEqual=1 组合与 SEL 表完全对齐，本开关不会砍组合。唯一的“形态学”限制是 rope 行只有 DTemplate=192——但 host 在 hasRope 时强制 dTemplateType=NUM192（tiling_common_regbase.cpp:849-852），所以对齐。
3. IsNzOut（bit52 / IS_NZ_OUT / isNzOut）
host 侧：op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp:444-451，六条合取：
1. splitAxis == BN2GS1S2（:445）
2. 64 < d < 128（:446-447）
3. d % FP16_C0_SIZE != 0（:447，FP16_C0_SIZE=16）
4. 非 fp8/fp32（:448-449，即仅 FP16/BF16 可取 1）
5. deterSparseType != DETER_OLD（:450）
6. enableSwizzle && s1>=NZ_OUT_MIN_S_SIZE && s2>=NZ_OUT_MIN_S_SIZE（:442,:451）
打包在 GET_TPL_TILING_KEY 第 16 实参（:1467；位域 template_tiling_key.h:115-118，bit52）。D=80：80%16==0 ⇒ 第 3 条恒假 ⇒ isNzOut 恒为 0，与 enableSwizzle/s1/s2 无关。
kernel 侧：模板参数 IS_NZ_OUT（common.h:299 模板字段；apt.cpp:37；entry_regbase.h:95-110）：
- entry_regbase.h:95-110 —— if constexpr (!IS_NZ_OUT) 走 FlashAttentionScoreGradS1S2BNGS1S2PostRegbase（row-major post），else 走 FlashAttentionScoreGradNzPost<…>（:102-109，定义在 op_kernel/arch35/flash_attention_score_grad_nz_post.h:26，Process :242-253 内 DoWork<0/1/2> + ProcessSink）。
- flash_attention_score_grad_block_cube.h:773（IterateMmDsKFixpout）、:1085（IterateMmDsQFixpout）、:1394（IterateMmPDyFixpout）—— if constexpr (!IS_NZ_OUT) 用 CO2Layout::ROW_MAJOR FixpipeParams 回写，else 用 CO2Layout::NZ（T/NZ 布局出）。
- 侧证常量 GET_IS_NZ_OUT（common.h:267-274）：BN2GS1S2 && 非 fp32/fp8 && HEAD_DIM_ALIGN==128 && 非 DETER_OLD——即 kernel 侧只认 dTemplateType=128 的非 FP32/FP8 场景，与 host 一致。
实例化表覆盖：FP16 段中允许 IsNzOut=1 的行只有 DTemplate=128 的行：:153-174（BN2GS1S2 非 TND、Deter=0）、:197-218（TND、Deter=0）、:285-306（非 TND、DETER_NEW）、:329-350（TND、DETER_NEW）、:373-394（TND、DETER_NEW+swizzle）。DETER_OLD 行（:219-262/:461-504 等）IsNzOut 仅 0——host 第 5 条已排除。由于 host isNzOut=1 要求 64<d<128 → GetDTemplateType（tiling_common_regbase.cpp:847-870）必给 NUM128，且非 DETER_OLD、仅 FP16/BF16——host 可达的 IsNzOut=1 集合 ⊆ SEL 表，完全对齐，无缺口。D=80 时该开关恒 0，落在 :153-174（允许 0/1）内，无影响。
4. 结论：FP16 + D=80 + dropout 下三个开关的值与表内命中
逐开关“砍组合”能力：
- IsDNoEqual：0 或 1 在 FP16 表里都是全行覆盖（唯一强制点 rope 行=1 与 host 语义自洽）。它不砍任何 host 可达组合；D=80、d1==d、无 rope 时为 0。
- IsNzOut：host 可达的 1 只出现在 d∈(64,128) 且 d%16≠0 的 FP16/BF16、BN2GS1S2、非 DETER_OLD、enableSwizzle 场景，全部落在 DTemplate=128 的 5 行内。它也不砍组合；D=80 时因 80%16==0 恒为 0。
- ORIG_DTYPE_QUERY：唯一能“砍掉”组合的开关——若部署的 kernel 二进制是 BF16/FP32 单 dtype TU（-DORIG_DTYPE_QUERY=DT_BF16/DT_FLOAT），FP16 整段 SEL 表（:129-681）与 RegbaseFAG FP16 派发（entry_regbase.h:223-243）都不存在，host 即使打出 InputDType=3 的 key 也查不到 kernel。若 TU 未注入（-1），SEL 表虽全，但 RegbaseFAG 三 dtype 派发块全部 #if 排除 → 空函数，同样表现为“找不到/不执行”。
FP16 + D=80 + dropout（BNSD、非 TND、非确定性、无 rope、d1==d）的完整 key 与命中行：
- IsEmptyTensor=0、SplitAxis=0(BN2GS1S2)、InputDType=3、IsTnd=0、IsDrop=1（dropValue = keepProb<1 ? ENABLE : DISABLE，tiling_normal_regbase.cpp:1440）、IsPse∈{0,1}、IsAttenMask∈{0,1}、S1=128、S2=128、DTemplate=128（D=80 → GetDTemplateType :856-858 归入 NUM128）、Deter=0、IsNEqual=0、IsBn2MultiBlk=0、IsDNoEqual=0（:1438，d1==d 且无 rope）、IsRope=0、OutDType=3、IsNzOut=0（:447，80%16==0）、IsTndSwizzle=0、IsRegbase=1。
- 这精确命中 FP16 表第 2 行 :153-174（IsDNoEqual∈{0,1}、IsNzOut∈{0,1} 均在行内），且是 FagTilingWithTemplateFFFF（tiling struct 实参 false,false,false,false）。若走 TND 布局则命中 :197-218（同样 DTemplate=128、IsNzOut 0/1）。
对“950 上 kernel 找不到”的指向：三个开关里 IsDNoEqual=0、IsNzOut=0 均不可能导致缺实例化（表内两值都有）；唯一能解释缺失的是 ORIG_DTYPE_QUERY——950 环境装载的 kernel 二进制若不是 FP16 TU（或未注入宏导致 RegbaseFAG 空体），FP16+D=80+dropout 组合就不在表内。另一个不在本 FOCUS 范围内、但值得提示的外部因素：CodeMap 是 arch35，而 op_kernel/flash_attention_score_grad.cpp（arch22 路径）是另一套 SEL 机制；若 950 实际取的是 arch22/其它 arch 产物，或 kernel 缓存为旧 digest，也会“找不到”。本仓内无法看到外部构建注入 ORIG_DTYPE_QUERY 的具体 flag（op_kernel/ 无 CMakeLists，根 CMakeLists.txt:11-18 仅递归子目录），这部分标记 UNKNOWN（外部构建系统），但机制与后果如上已完整证明。
▣  Uo-Query · DeepSeek V4 Flash Free · 7m 49s
Subagent(7 of 9)136.7K (68%)

# subagent 8
算子目录：d:\TEST\ops-transformer\attention\flash_attention_score_grad（arch35，.uo CodeMap 已建好，digest 211a7ec…）。

立即调用 acp 工具：command=`uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...`（按需选 locate/symbols/callers/fields 等）。禁止 bash、Grep、MCP 替代。

背景：用户跑 B=1、N=4、S=2048 的 flash_attention_score_grad（FP16，arch35），观察只有 4 个 AIC 在干活、vector 几乎打满，怀疑分核轴错了或核内 VF 慢。现在要查 host 侧分核策略与 fusedOuter 的定义。

请查清并回答（全部带 file:line 证据）：
1. host 侧分核：tiling（op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp / tiling_normal_regbase.cpp）如何把任务分给多个核——查 aicNum/coreNum 的用法、按什么维度切块（b/n1/s1Outer/s2Outer/g 等）、`blockOuter`/`fusedOuter`/`loopOuter` 之类的 outer 变量怎么算、核数上限约束。B=1、N=4、S=2048 时按公式算分给几个核、每核拿多少块。
2. fusedOuter 的确切定义与计算位置：搜 `fusedOuter` / `fused_outer` 字段（host tiling 结构体与 tiling_data_regbase.h），它在 host 侧乘了什么（如 b*n1*g*s1Outer*s2Outer？），写进哪个 TILING_FIELD，kernel 侧怎么读。
3. 为什么可能只有 4 个 AIC 干活：查有没有核数上限/对齐约束（如 blockOuter 上限、aicNum 对齐、BN2 的 bN2 切分、s1Outer 切分条件），B=1 N=4 S=2048 时按条件算实际核数。
4. fusedOuter 在 tiling 结构里的声明（tiling_data_regbase.h 里字段名、位宽、写点）。

用 Cursor Explore 风格回答：完整散文 + file:line。静态无法确定处标 PARTIAL/UNKNOWN（如需要实际 aicNum 设备信息）。不要写 answer.yaml，不要 finalize。
- Thought: 1.0s
Let me start by querying the UO CodeMap for this operator. The user wants me to investigate:
1. Host-side tiling / core splitting strategy
2. fusedOuter definition and computation location
3. Why only 4 AICs might be working
4. fusedOuter declaration in tiling structure

Let me start with the uo-query tool. The project is d:\TEST\ops-transformer\attention\flash_attention_score_grad.

Let me run multiple queries to find the relevant symbols.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern fusedOuter]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern blockOuter]
- Thought: 13.0s
The query results give a lot of useful info. Let me now dig deeper into:

1. The tiling flow — where aicNum is set, what splits happen (b/n1/s1Outer/s2Outer/g), and the conditions for different paths (DoBn2s2Sparse, GetSparseBlockInfoBn2, DoBn2MultiBlkSparse, DoSparse).
2. fusedOuter definition — from the results, fusedOuter is a local variable in host code, computed as:
   - Line 523: fBaseParams.b * fBaseParams.n2 * fBaseParams.g * fBaseParams.s2Outer (in DoBn2s2Sparse path)
   - Line 557: fBaseParams.b * fBaseParams.n2 * fBaseParams.g (in GetSparseBlockInfoBn2)
   - Line 1561: fBaseParams.b * fBaseParams.n2 * fBaseParams.g * s1s2oCount (in GetSparseBlockInfo)
   - Line 632: fBaseParams.b * fBaseParams.n2 * fBaseParams.g (in DoBn2MultiBlkSparse)
   
   So fusedOuter is a host-side local variable, not a tiling field. It's the total number of "bn2g" (or with s2Outer/s1s2oCount) blocks.

3. Need to find aicNum definition — where it's set (GetCoreNum?), the maximum core constraints, and whether there's a limit like 40 for AIC.

Let me query more:
- aicNum usage / where it's set
- the main tiling flow: DoTiling / GetTilingData, the branching on layoutType, isSparse, splitAxis
- TILING_FIELD for fusedOuter? The user asks "写进哪个 TILING_FIELD，kernel 侧怎么读" — fusedOuter is a local variable, and it seems the kernel uses blockOuter and blockStarts/blockEnds instead. Let me verify with symbols query for fusedOuter in kernel.

Let me also look at fields query for aicNum, and symbols for the tiling flow. Also need n2, g, s1Outer, s2Outer computation — the "coreNum" and "aicNum" setting.

Let me run several queries in parallel:
1. locate aicNum
2. locate coreNum
3. symbols for GetTilingData / DoTiling flow in normal_regbase
4. locate fusedOuter in kernel side (maybe in tiling_data_regbase.h — is there a fusedOuter field? The TDF list shows blockOuter but not fusedOuter; let me check symbols for "fused" in the tiling_data header).
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern aicNum]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode symbols --pattern FlashAttentionScoreGradTilingNormalRegbase]
- Thought: 12.3s
The mode list is: search, constraints, neighbors, impact, field, branches, templates, tiling_key, tiling_data, kernel_branch, template_match, buffer, gaps, legal_key, locate, kernel_api, kernel_launch, compile.

So "symbols" isn't valid. Let me use search mode for the tiling flow. I need to understand the main tiling flow:

1. Where is DoTiling / the main entry? GetTilingData? Let me search for the function flow in normal_regbase.cpp.
2. The split axis decision (BN2GS1S2, BN2, BN2S2 etc.), and the s1Outer/s2Outer computation.
3. Where fusedOuter is written to tiling data (if at all) — the question asks whether fusedOuter is written to a TILING_FIELD. From what we see, fusedOuter is a local variable; the tiling field is blockOuter. Let me check the tiling_data_regbase.h for any "fused" fields.

Let me look at:
- search mode for "DoTiling" or the main flow
- search mode for "fused" in kernel tiling_data
- tiling_data mode to see the TILING_DATA structures
- Search for the splitAxis enum and where it's decided (BN2 vs BN2GS1S2 vs BN2S2)
The symbols mode isn't in this plugin's list — the valid modes are search/constraints/neighbors/impact/field/branches/templates/tiling_key/tiling_data/kernel_branch/template_match/buffer/gaps/legal_key/locate/kernel_api/kernel_launch/compile. Let me use search and tiling_data to trace the flow
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern fused]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode tiling_data --pattern FlashAttentionScoreGradS1S2BNGS1S2SplitCoreParamsRegbase]
- Thought: 38.0s
The search fused output was truncated. Let me read the saved output file to see what it contains. Actually, the output file is at C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b8c5e83001NOw5W5kNRaCC24 — but that's outside the allowed read scope (pilot:uo/, pilot:runs/, pilot:context/, pilot:memory/, method:...). Hmm, my boundaries say I may read those pilot dirs. The tool output file is a cache location. Actually the instructions say I can read machine-scope operator sources with windowed Read. The tool-output cache is neither. Let me be careful — the instruction says "Use Grep to search the full content or Read with offset/limit" which is the tool's own suggestion. The boundary list says "You may read: pilot:uo/, pilot:runs/, pilot:context/, pilot:memory/, method:cognitive-skills/operator-analysis/" and "Machine-scope operator sources (op_host/, op_kernel/**, …) are outside .ascendc-pilot. Locate with UO KB query / ScopeSet first, then machine-scope windowed Read". 

The tool output directory is not in my allowed list. But it's the acp tool output itself, saved by the harness. I think reading it is acceptable as it's the direct output of the acp tool I invoked (the tool suggested reading it). However, to be safe and avoid violating boundaries, I could instead re-run the query with a more specific pattern to reduce output. Let me instead do targeted queries:

1. search --pattern fusedOuter in kernel — check if kernel reads a fused field. Actually let me check the tiling_data_regbase.h for "fused" fields via field/locate on the kernel file. The locate for blockOuter showed tiling data struct. Let me check whether there's a "fusedOuter" TILING_FIELD at all: the earlier locate for "fusedOuter" had fused_outer_candidates_count: 0 and all locations were in host .cpp files. So fusedOuter is NOT a tiling field — it's a host-local variable. Good, that answers part of Q2: fusedOuter never gets written to tiling data; the kernel reads blockOuter/blockStarts/blockEnds instead.

Let me now check:
- The main tiling flow: GetTilingData in op_host/flash_attention_score_grad_tiling.cpp (line 541 aicNum usage there too) — how it dispatches to normal/varlen regbase.
- The split axis logic in normal_regbase: DoTiling, ComputeTilingData? Search for "SplitAxisEnum" and "DoSparse" callers, plus where s1Outer/s2Outer are computed (CalcS1S2OuterInfo / GetParseS1S2OuterInfo), and coreNum usage — e.g., a cap like aicNum <= 40? Let me search "coreNum" and "MAX_CORE_NUM" and "CORE_LIST_NUM".

Also the question asks: B=1, N=4, S=2048 → how many cores. That depends on the split path chosen. N=4 heads, d=128 presumably (FP16). S=2048. s1Outer/s2Outer depends on inner/tail computation. For FP16, d=128. Need to see CalcTiling (or CalS1S2) to know s1Outer/s2Outer for S=2048. Let me search for "s1Outer" definitions and "CalcS1S2".

Also Q3: why only 4 AICs might be working. The bN2 split: b=1, n2=? — n2 might be n1/... wait n2 relates to head split for multi-blk: BN2GS1S2. For N=4, g=1: fusedOuter = bn2g = 1n21. If n2 = n1 = 4 (no BN2 multi-blk split), then fusedOuter=4 → blockFactor = ceil(4/aicNum)=1 (if aicNum=40) → blockOuter = ceil(4/1)=4 → only 4 blocks → 4 cores! That's exactly the observed behavior: 4 AICs busy. 

So the answer to Q3: with b=1, n2=4, g=1, s1s2oCount=1 (if no S1S2 outer split), fusedOuter = 4 → blockOuter = 4 → only 4 cores get blocks; the rest get empty [0,0) ranges. Unless s1Outer/s2Outer splits create more blocks (DoBn2MultiBlkSparse multiplies blockFactor by s1Outers2Outer and blockOuter stays at 4 — wait no, in DoBn2MultiBlkSparse, blockOuter = ceil(fusedOuter/blockFactor) which is 4, then blockFactor = s1Outers2Outer, fusedOuter = s1Outers2Outer — but blockOuter stays 4! Wait, then blockStartsi = blockFactor * i covers only 4 blocks each spanning s1Outers2Outer... so each core handles all S1S2 blocks of its BN. So still only 4 cores. Hmm.

But wait — in the BN2S2 path (DoBn2s2Sparse at line 523-525), fusedOuter = bn2gs2Outer, blockOuter = ceil(fusedOuter / ceil(fusedOuter/aicNum)). If s2Outer >= 10, fusedOuter = 4s2Outer ≥ 40 = aicNum → blockOuter could reach 40 cores. So the number of busy cores depends on which split path is taken and the s2Outer value.

For S=2048, s2Outer depends on s2Inner — for FP16, the s2 inner block size... I need to see the CalcS1S2 logic. Let me look at lines around 300-460 of normal_regbase, which seems to be the CalcTiling / DoTiling area (GetPlatformInfo at 373-396, enableSwizzle at 442).

Also line 665: if (DoBn2s2Sparse() && fBaseParams.blockOuter >= fBaseParams.aicNum) — this is important! In DoSparse, it tries DoBn2s2Sparse first, and only accepts if blockOuter >= aicNum (i.e., enough blocks to fill all cores). Otherwise falls back to GetSparseBlockInfo / other paths. Similarly line 674: if (fBaseParams.splitAxis == SplitAxisEnum::BN2 && fBaseParams.isBn2MultiBlk) calls DoBn2MultiBlkSparse.

So the actual decision tree matters. Let me read the source file directly (machine-scope windowed read is allowed). The file is d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp. Let me read the key regions:
- Lines ~300-760 (GetPlatformInfo, DoTiling dispatch, DoSparse, DoBn2s2Sparse, GetSparseBlockInfoBn2, DoBn2MultiBlkSparse)
- Lines ~1540-1700 (GetSparseBlockInfo, GetSparsePrefixBlockInfo)
- The CalcS1S2 stuff — search for "s1Outer" computation.

Let me also check op_host/flash_attention_score_grad_tiling.cpp line ~541 for aicNum usage (kernel launch / compile info).

I'll do parallel: read the normal_regbase.cpp window 300-760, and search for s1Outer/s2Outer compute functions.
The search fused output was truncated to a cache file outside my read scope; instead I'll do targeted queries. fusedOuter locate showed it's a host-local variable (0 tiling-field candidates). Now let me trace the main tiling flow and the split-axis
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern SplitAxisEnum]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern s1Outer]
- Thought: 27.6s
Now I have a much clearer picture. Key findings so far:

1. fusedOuter is a host-local variable in flash_attention_score_grad_tiling_normal_regbase.cpp, computed differently in each path:
   - Line 523 (DoBn2s2Sparse): fBaseParams.b * fBaseParams.n2 * fBaseParams.g * fBaseParams.s2Outer
   - Line 557 (GetSparseBlockInfoBn2): fBaseParams.b * fBaseParams.n2 * fBaseParams.g then *= s1s2oCount
   - Line 632 (DoBn2MultiBlkSparse): fBaseParams.b * fBaseParams.n2 * fBaseParams.g then *= (s1Outer * s2Outer)
   - Line 704 (DoSparse else branch / dense): fBaseParams.b * fBaseParams.n2 * fBaseParams.g * fBaseParams.s1Outer * fBaseParams.s2Outer
   - Line 1561 (GetSparseBlockInfo): fBaseParams.b * fBaseParams.n2 * fBaseParams.g * s1s2oCount

2. It is NOT a TILING_FIELD — no fusedOuter field in tiling_data_regbase.h. The kernel reads blockOuter, blockStarts, blockEnds, blockFactor (maxValidBBLen), s1Outer, s2Outer instead. The TILING_DATA class FlashAttentionScoreGradS1S2BNGS1S2SplitCoreParamsRegbase (tiling_data_regbase.h:194-231) has fields s1Outer (int64_t), s1Inner, s1CvInner, s1Tail, s1CvTail, s2Outer (int64_t), s2Inner, s2Tail, blockOuter (uint32_t), maxValidBBLen (uint32_t), bandIdx (int64_t).

3. aicNum is set from compileInfoPtr->aicNum (line 385) or ascendcPlatform.GetCoreNumAic() in the else branch (line 392-393ish). Let me see the else branch: line 391-396. It got truncated in snippet. The facts say rhs = "ascendcPlatform.GetCoreNumAic()" for line 385... wait no, the fact is attached to E_FIELD_859e9f44dcdd which is at line 385, but the snippet shows 385 = fBaseParams.aicNum = compileInfoPtr->aicNum; and facts rhs = "ascendcPlatform.GetCoreNumAic()". Hmm, possibly the fact mapping is on the else branch. Let me read that region of the file to confirm.

4. Split axis decision: 
   - normal_regbase.cpp:691: fBaseParams.splitAxis = fBaseParams.isBn2 ? SplitAxisEnum::BN2 : SplitAxisEnum::BN2GS1S2;
   - common_regbase.cpp:1641-1648: BN2S2 route: if (!fBaseParams.isBn2 && bn2S2RouteLimit) { splitAxis = BN2S2 } else if (isBn2) { BN2 } else { BN2GS1S2 }
   - normal_regbase.cpp:665: if (DoBn2s2Sparse() && fBaseParams.blockOuter >= fBaseParams.aicNum) — the BN2S2 sparse path is accepted only when blockOuter >= aicNum, otherwise fallback.
   - DoSparse at 660-720: calls DoBn2s2Sparse, and if that doesn't produce blockOuter >= aicNum, goes to fallback: SupportTrans2BS2N2GD → DoBn2MultiBlkSparse if splitAxis==BN2 && isBn2MultiBlk; else GetSparseBlockInfo (or GetSparseBlockInfoBn2?). Wait, actually the flow at 665-690: DoSparse tries DoBn2s2Sparse() && blockOuter >= aicNum → return success. Otherwise (line 668-690): if SupportTrans2BS2N2GD... some conversion; then splitAxis set; then TND → GetSparseUnpadBlockInfo; sparse → GetSparsePrefixBlockInfo or GetSparseBlockInfo; else dense path at 702-719.

Wait, there seem to be two similar functions: DoSparse at 660, and another block at 691+ (which is inside DoSparse?). Actually looking at the snippet of splitAxis::3 at 684: "fBaseParams.splitAxis = SplitAxisEnum::BN2GS1S2; earlyReturn = false;" then at 687 "if (earlyReturn) return res;" then 691: fBaseParams.splitAxis = fBaseParams.isBn2 ? SplitAxisEnum::BN2 : SplitAxisEnum::BN2GS1S2; then the dispatch. So DoSparse's else branch: after SupportTrans2BS2N2GD conversion, sets splitAxis, then dispatches:
- TND layout → GetSparseUnpadBlockInfo
- isSparse && PREFIX/PREFIX_COMPRESS → GetSparsePrefixBlockInfo
- isSparse → GetSparseBlockInfo (which internally may call GetSparseBlockInfoBn2 for BN2 split)
- dense → inline block split using fusedOuter = bn2gs1Outers2Outer (line 704)

Let me now read the actual source file regions to get precise statements:
- Lines 370-560 (GetPlatformInfo, DoSplit, s1Outer/s2Outer calc, enableSwizzle, DoBn2s2Sparse)
- Lines 620-760 (DoSparse dispatch, DoBn2MultiBlkSparse)
- Lines 1540-1700 (GetSparseBlockInfo, GetSparsePrefixBlockInfo)
- Lines 1880-1920 (tiling data write: s1s2BNGS1S2SplitCoreParams)

Also need: where is DoSparse called from (ComputeTiling / DoTiling), where is s1Inner/s2Inner computed (CalcS1S2Split?), where isBn2 decided, bn2S2RouteLimit. And the kernel read side: SetConstInfo in flash_attention_score_grad_kernel_base.h:488 and how blockStarts/blockEnds/blockOuter are consumed (loop over blocks per core).

Let me also search for "isBn2" and "bn2S2RouteLimit" definitions and "GetCoreNumAic" for aicNum.

Let me read the source file directly in windows. The file path: d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp

I'll read lines 360-560 first, then 620-760, then 1540-1710, then 1880-1920.
Now let me read the actual source windows to pin down the flow precisely (machine-scope window
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [offset=360, limit=200]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [offset=620, limit=140]
- Thought: 3.8s
Now I have the core flow. Let me now read:
1. Lines 1540-1710 (GetSparseBlockInfo, GetSparsePrefixBlockInfo)
2. Lines 1880-1920 (InitTilingData writes)
3. SetSplitAxis in common_regbase.cpp around 1600-1650 (bn2S2RouteLimit, isBn2 decisions) — need to see how isBn2 / n2 are determined and the bn2S2RouteLimit conditions.
4. Where isBn2 and n2 set — search for "isBn2" assignment and "n2 =" in common_regbase / normal_regbase.
5. Kernel side: SetConstInfo (kernel_base.h:488) reading blockOuter/blockStarts/blockEnds, and how the core loop iterates (per-core block range loop).

Also need CORE_LIST_NUM = 36 (from common_regbase.h:136) — interesting! So blockStarts/blockEnds arrays are sized 36, not aicNum. And the kernel launch: how many cores launched? Check op_host/flash_attention_score_grad_tiling.cpp line 541 (aicNum usage) — maybe launch core num is aicNum.

Let me read those regions now.
Now the sparse/dense block-split internals and the tiling-data write site
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=175, offset=1540]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=60, offset=1880]
- Thought: 2.3s
Now I need:
1. SetSplitAxis in common_regbase.cpp — around line 1600-1650, to understand isBn2, bn2S2RouteLimit, and the decision conditions. Also where n2 is set (n2 = n1/g? or is it a head split?). Let me look at where isBn2 is determined — search for "isBn2".
2. Kernel side consumption: SetConstInfo at kernel_base.h:488 reading blockOuter etc, and the kernel loop over blocks (blockStart/blockEnd per core).
3. The kernel launch core count: op_host/flash_attention_score_grad_tiling.cpp line 541 aicNum usage.

Let me search for isBn2 assignments and read the common_regbase SetSplitAxis region.
Now the split-axis decision in common_regbase, plus where isBn2/n2 are set
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern isBn2]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp [limit=80, offset=1580]
- Thought: 3.0s
Excellent! Now I have the SetSplitAxis logic. Key constants to pin down:
- BN2_MAX_S
- BN2_MAX_D
- BN2_MULTIBLK_BN256, BN2_MULTIBLK_BN128
- BN2_MULTIBLK_SEQ
- ALIGN128
- BN2S2_MAX_S, BN2S2_WRITE_UB_D

Let me search for those constants. Also I need:
1. Where n2 is set (n2 = n1/g? probably). Search "n2 =" in common_regbase.
2. Kernel side consumption: SetConstInfo (kernel_base.h:488) and the per-core block loop.
3. The kernel launch: how many cores does the kernel launch with (op_host/flash_attention_score_grad_tiling.cpp line 541 aicNum usage).
4. Check where blockStart/blockEnd is read by kernel: "blockStarts" read in kernel.

Let me search constants and read the kernel_base SetConstInfo region.
Let me pin down the constants and the kernel-side consumption of blockOuter/blockSt
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern BN2_MAX_S]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern blockStarts]
- Thought: 1.8s
Now I have the constants referenced. Let me find the constant values (BN2_MAX_S, BN2_MAX_D, BN2_MULTIBLK_BN256, BN2_MULTIBLK_BN128, BN2_MULTIBLK_SEQ, ALIGN128, BN2S2_MAX_S, BN2S2_WRITE_UB_D). Let me search for these in common_regbase.h. Also need to see the kernel Process (kernel.h:493) that reads blockStarts/blockEnds to determine per-core loops, and the kernel launch (op_host/flash_attention_score_grad_tiling.cpp around line 541).

Let me search for the constants' definitions.
Let me find the constant values and the kernel's per
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern BN2_MULTIBLK_BN_256]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h [limit=90, offset=480]
- Thought: 3.9s
Now I see the kernel side. Key kernel facts:
- kernel.h:502-503: if (this->tilingData->s1s2BNGS1S2BlockNumList.blockEnds[this->cBlockIdx] == 0) { return; } — cores with empty blockEnds return immediately.
- kernel.h:510-511: GetNextValidIdx(runInfos[0], taskId, this->tilingData->s1s2BNGS1S2BlockNumList.blockStarts[this->cBlockIdx], curLoopIdx) — per-core iteration starts from blockStartscBlockIdx.

So the actual core assignment is: blockStartscore..blockEndscore per core. Cores >= blockOuter get [0, 0) → return early (only 4 cores work if blockOuter=4).

I still need:
1. The constants' numeric values: BN2_MAX_S, BN2_MAX_D, BN2_MULTIBLK_BN256, BN2_MULTIBLK_BN128, BN2_MULTIBLK_SEQ, BN2S2_MAX_S, BN2S2_WRITE_UB_D, ALIGN128, CORE_INIT_NUM, MAX_CORE_NUM. Let me grep the common_regbase.h header directly (machine-scope windowed read). Also where n2 is set.

2. The kernel launch core count: op_host/flash_attention_score_grad_tiling.cpp line 541 — aicNum usage. Let me read that.

3. Where cBlockIdx is set (kernel side) — GetBlockIdx in kernel_base.h SetConstInfo? The kernel gets its core index via GetBlockIdx().

Let me read the common_regbase.h header for constants, and the tiling.cpp launch region.
Now the constant values in the header, and the kernel-launch core count in the main t
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern BN2_MAX_D]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\flash_attention_score_grad_tiling.cpp [limit=80, offset=500]
- Thought: 3.4s
Now I need the actual constant values. They are likely defined in the common_regbase.h header. Let me read the header file directly for the constants (BN2_MAX_S, BN2_MAX_D, BN2_MULTIBLK_BN256, BN2_MULTIBLK_BN128, BN2_MULTIBLK_SEQ, BN2S2_MAX_S, BN2S2_WRITE_UB_D, ALIGN128, CORE_INIT_NUM, MAX_CORE_NUM). Let me also check where n2 is set (n2 = n1/g) — in the fuzzy params init. And also check FuzzyForBestSplit / where s1Inner/s2Inner get values, so I can compute s1Outer/s2Outer for S=2048.

Also I need where the kernel gets cBlockIdx — SetConstInfo kernel_base.h:488.

Let me grep the header for the constants. I'll read the header file, searching for these defines. The header is op_host/arch35/flash_attention_score_grad_tiling_common_regbase.h. Let me grep it via read with a window. Actually I can use the grep tool? No — "禁止 bash、Grep、MCP 替代" — that's about not using Grep as a substitute for uo-query. But for reading machine-scope operator sources, windowed Read is allowed. The grep tool isn't listed in my available tools anyway (only acp and read). So I'll use uo-query locate for constants, or read the header directly.

Let me use locate for the constants in the header: BN2_MAX_S definition location. The locate for BN2_MAX_D showed only usage sites, not the definition — meaning the constants may be defined in the .h file. Let me search for the macro/const definitions.
The constants must be defined in the header — let me locate their definitions and also check where n2 is initialized
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern BN2S2_MAX_S]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern CORE_INIT_NUM]
- Thought: 4.7s
The constant values are likely #defines in the common_regbase.h header which the CodeMap doesn't index as COMPILE_VAR (only usages are indexed). Let me read the header file directly to get the numeric values. The header is op_host/arch35/flash_attention_score_grad_tiling_common_regbase.h. Let me search for the constants within it by reading the header (windowed). I'll read the whole file if it's not too big, or grep for the defines.

Actually let me read the header — first check its size by reading the first chunk and searching for "BN2_MAX". I'll read the file with offset to find the #defines. Let me just read the header file directly, it might be ~1500 lines. Let me read a window and look for the #define section.
The constants are #defines in the header — let me read the header directly to get numeric values, and find where n2 is initialized
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.h [limit=400]
- Thought: 3.5s
Now I have the constant values:
- CORE_INIT_NUM = 40 (line 72)
- ALIGN128 = 128 (line 109)
- BN2_MAX_S = 128 (line 110)
- BN2S2_MAX_S = 1024 (line 111)
- BN2_MULTIBLK_SEQ = 640 (line 112)
- BN2_MULTIBLK_BN_128 = 128 (line 113)
- BN2_MULTIBLK_BN_256 = 256 (line 114)
- BN2_MAX_D = 512 (line 115)
- BN2S2_WRITE_UB_D = 128 (line 116)
- CORE_LIST_NUM = 36 (line 136)

Now let me check the FuzzyBaseInfoParamsRegbase struct for blockStarts/blockEnds (lines 355+) and n2 setting. Let me also find where n2 is set (n2 = n1/g — from line 369: fBaseParams.n1 = fBaseParams.n2 * fBaseParams.g; — n1 = n2 * g, so n2 = n1/g; for N=4 heads with g=1, n2 = 4).

Let me continue reading the header to see blockStarts/blockEnds and blockOuter/blockFactor/maxValidBBLen fields in the struct. Then I need:
1. Where n2 is initialized in the fuzzy params — search "n2 =" in normal_regbase.cpp.
2. FuzzyForBestSplit to estimate s1Inner/s2Inner values for S=2048 FP16 → to compute s1Outer/s2Outer.
3. Kernel SetConstInfo (kernel_base.h:488) and where cBlockIdx is set.
4. GetNextValidIdx to see how kernel iterates through blocks — the loop ends when blockInnerIdx reaches blockEndscore? Let me check the end of Process and GetNextValidIdx.

Let me read the rest of the header (400-611) and then the FuzzyForBestSplit / n2 init, and kernel SetConstInfo region.
Now the rest of the params struct (block arrays), then where n2 is initialized and FuzzyForBestSplit
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.h [limit=212, offset=400]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern n2 = fBaseParams.n1]
- Thought: 930ms
The search pattern with = broke the CLI parsing. Let me try different approach — read the region of normal_regbase.cpp where fuzzy params are initialized (probably lines 100-360). I saw line 369: fBaseParams.n1 = fBaseParams.n2 * fBaseParams.g; in some function. Let me read lines 250-370 to find n2/n1/g initialization. Also need FuzzyForBestSplit.
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=160, offset=120]
- Thought: 22.4s
Now I understand n2/n1/g:
- For BSH layout (which is the common case for B=1 N=4 S=2048 FP16): n2 = headNum / g; g = query H dim / key H dim. For MHA with N=4 heads: g=1, n2=4. n1 = n2 * g = 4 (line 369).
- isBn2 requires s1 <= BN2_MAX_S (128) && s2 <= BN2_MAX_S (128) — for S=2048 this FAILS, so isBn2 = false.
- isBn2MultiBlk requires bnLimit: b*n1 >= 256 or (bn1 >= 128 && s1%128==0 && s2%128==0). For b=1, n1=4: bn1 = 4 < 128 → bnLimit false → isBn2MultiBlk = false.
- bn2S2RouteLimit: requires n1==n2 (4==4 ✓), d <= BN2_MAX_D (512), layoutType TND or (isAllSame && !isDeterministic) or bn2S2NotTndLimit. bn2S2NotTndLimit: s1 < s2 && s2 <= 1024 && s2-s1 >= 128 && d <= 128 && !isSparse && !isDeterministic. For BSH, s1=s2=2048 → s1<s2 false → bn2S2NotTndLimit false. isAllSame for BSH? isAllSame probably set in ProcessOptionalInput for BSH as true (default for fixed shapes?). If isAllSame && !isDeterministic → bn2S2RouteLimit could be true → splitAxis = BN2S2, and layoutType set to TND (if isAllSame).

So for B=1, N=4, S=2048, FP16 BSH:
- SetSplitAxis: isBn2=false (S>128), isBn2MultiBlk=false (b*n1=4 < 128), bn2S2RouteLimit: likely TRUE (n1==n2=4, d=128<=512, isAllSame presumably true, !hasRope, keepProb>=1) → splitAxis=BN2S2 and layoutType=INPUT_FORMAT_TND if isAllSame.
- DoOpTiling → DoSplit() computes s1Inner/s2Inner/s1Outer/s2Outer.
- DoSparse → CalcleDeterParam (non-deterministic → returns?) → DoBn2s2Sparse(): splitAxis==BN2S2 && deterSparseType != DETER_OLD → continue; then if (fBaseParams.isSparse || fBaseParams.layoutType == INPUT_FORMAT_TND) return GetBlockInfoOfBNS4TND(); — since layoutType was set to TND (isAllSame case), it goes to GetBlockInfoOfBNS4TND(), NOT the inline dense formula!

Interesting. So the BN2S2 path with TND layout goes to GetBlockInfoOfBNS4TND (in varlen? no, probably in normal_regbase or common). Wait — GetBlockInfoOfBNS4TND is mentioned at line 518 in DoBn2s2Sparse. Let me check what that does — need to see if it also uses fusedOuter = b*n2gs2Outer and blockOuter = ceil(...). Let me search for GetBlockInfoOfBNS4TND.

Also note line 665: if (DoBn2s2Sparse() && fBaseParams.blockOuter >= fBaseParams.aicNum) — the BN2S2 path is accepted ONLY if blockOuter >= aicNum (all cores used). Otherwise, it falls to the else branch: SupportTrans2BS2N2GD → for BN2S2 non-TND... Actually for TND + BN2S2, after DoBn2s2Sparse returns false (or blockOuter < aicNum), SupportTrans2BS2N2GD(fBaseParams) checks sparseMode <= PREFIX_COMPRESS && isAllSame && layoutType==TND → likely TRUE for BSH-isAllSame converted to TND. Then layoutType = INPUT_FORMAT_BS2N2GD.

Wait — SupportTrans2BS2N2GD sets layoutType = BS2N2GD, and then DoSparse at 691: splitAxis = isBn2 ? BN2 : BN2GS1S2 → isBn2 false → BN2GS1S2; then layoutType == INPUT_FORMAT_TND? No, it's BS2N2GD now. isSparse? For BSH dense (no mask) isSparse false → else branch: fusedOuter = bn2gs1Outers2Outer, blockFactor = ceil(fusedOuter/aicNum), blockOuter = ceil(fusedOuter/blockFactor).

Hmm, so this is the key: for the BN2S2 route with TND-equivalent layout, if the BN2S2 split cannot fill all cores (blockOuter < aicNum), it converts to BS2N2GD with BN2GS1S2 split, and uses the dense formula at line 704-706.

Now let me compute for B=1, N=4 (n2=4), g=1, s1=s2=2048, d=128, FP16:

First I need s1Outer/s2Outer values from FuzzyForBestSplit. For S=2048, the s1Inner/s2Inner values depend on the fuzzy split algorithm (tries inner sizes given UB budget). I need to look at FuzzyForBestSplit to know the typical s1Inner/s2Inner for this config. Actually, the important thing: s1Outer = ceil(s1 / s1CvInner), s1CvInner = min(s1, s1Inner * s1CvRatio=2). s2Outer = ceil(s2 / cvS2Inner), cvS2Inner = min(s2, s2Inner * s2CvRatio=1).

If FuzzyForBestSplit returns e.g. s2Inner=128 for FP16 d=128, then cvS2Inner=128, s2Outer = ceil(2048/128) = 16; s1Inner maybe 128 → s1CvInner=256 → s1Outer = ceil(2048/256) = 8. Then fusedOuter = bn2gs1Outers2Outer = 141816 = 512. blockFactor = ceil(512/40) = 13; blockOuter = ceil(512/13) = 40. → 40 cores, each ~13 blocks. That would be fine.

But the observed behavior is only 4 cores. That suggests the BN2S2 path was taken and GetBlockInfoOfBNS4TND produced blockOuter=4? Or maybe the BN2 path was taken? Wait, isBn2=false for S=2048. So not BN2.

Hmm, but wait — the observed "4 AIC 在干活" could also mean the kernel was launched with only 4 cores by the framework (aicNum configured = 4? e.g., on a device with 4 AIC?). Actually, arch35 devices typically have 40 AIC. But the user says "只有 4 个 AIC 在干活" — with vector almost full. If aicNum=40 and blockOuter=4, then only 4 of the 40 launched cores do work. 

What produces blockOuter=4? If splitAxis=BN2S2 and layoutType became TND: DoBn2s2Sparse → GetBlockInfoOfBNS4TND. Need to see that function — maybe it splits by BN only when... Let me check GetBlockInfoOfBNS4TND. If it computes fusedOuter = b*n2gs2Outer with s2Outer... for TND maybe s2Outer=1 when s2<=inner? No — s2=2048.

Alternatively, maybe the user's actual case: BSH non-TND, bn2S2RouteLimit requires layoutType == TND || (isAllSame && !isDeterministic) || bn2S2NotTndLimit. isAllSame for BSH? isAllSame is set in ProcessOptionalInput — for BSH probably true by default (fixed length). If isAllSame && !isDeterministic → bn2S2RouteLimit true → splitAxis=BN2S2, layoutType = isAllSame ? TND : BSH. So layoutType becomes TND (even though input was BSH). Then DoBn2s2Sparse → GetBlockInfoOfBNS4TND since layoutType==TND.

Then DoSparse checks DoBn2s2Sparse() && blockOuter >= aicNum — if GetBlockInfoOfBNS4TND yields blockOuter=4 (< 40), it falls through to SupportTrans2BS2N2GD → layoutType=BS2N2GD, then dense branch (704). Hmm, but that would give fusedOuter=512 → 40 cores. Unless... hmm.

Wait, actually maybe GetBlockInfoOfBNS4TND sets blockOuter=4 and returns true with blockOuter >= aicNum? If aicNum is 4! If the device/compile config has aicNum=4 (e.g., 910B with 4 AIC? no, 910B has 40... but maybe an environment with aicNum=4, or the kernel is launched on a subset). Hmm — actually some arch35 (920/930) configurations or simulation environments have fewer cores. But we cannot determine actual aicNum statically — the user says "只有 4 个 AIC 在干活" — could mean the runtime only has 4 AIC available or only 4 launched.

Wait, but the user says B=1 N=4 S=2048, observed 4 AIC busy. The most consistent static explanation: fusedOuter (BN-partition) = bn2g = 141 = 4 → blockOuter = 4 → 4 blocks → 4 cores busy; remaining cores get [0,0) and return at kernel.h:502-503. This is the BN2 path (DoBn2MultiBlkSparse at 632-636 or GetSparseBlockInfoBn2 at 557-559), or a BN2S2 path where s2Outer contribution is 1.

But wait — for the pure BN2 split path, isBn2 requires s1<=128 && s2<=128, so S=2048 can't take BN2. Unless... the user's actual test used s=2048 but isBn2MultiBlk? b*n1=4 < 128 → no.

Hmm. Let me reconsider: what if the BN2S2 route's GetBlockInfoOfBNS4TND uses a different formula. Let me look at that function. Also, I should check whether there is a cap like aicNum = min(aicNum, CORE_LIST_NUM=36) somewhere — blockStarts arrays are CORE_LIST_NUM=36, so if aicNum=40, blocks beyond 36 can't be stored... Actually the loops write blockStartsi for i < blockOuter into a CORE_LIST_NUM-sized array — if blockOuter > 36, that's a buffer overflow... but they guard for (uint32_t i = static_cast<uint32_t>(blockOuter); i < CORE_LIST_NUM; i++). Hmm, but blockOuter could be up to 40. Interesting — maybe there's a cap making aicNum <= 36? Let me search for "min" with aicNum... Actually, in the dense branch, blockOuter = ceil(fusedOuter/blockFactor); with aicNum=40, blockOuter can be up to 40 > CORE_LIST_NUM=36. That would overflow blockStarts39. Unless aicNum ≤ 36 in practice. MAX_CORE_NUM in tiling_data header — let me check its value.

Let me now find GetBlockInfoOfBNS4TND and MAX_CORE_NUM, and also look at FuzzyForBestSplit to estimate s1Inner/s2Inner.
Now let me look at GetBlockInfoOfBNS4TND (the BN2S2/TND path), MAX_CORE_NUM, and FuzzyForBestSplit
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GetBlockInfoOfBNS4TND]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern FuzzyForBestSplit]
- Thought: 8.1s
Very important discovery at PostTiling (normal_regbase.cpp:1483-1506):

auto numBlocks = 0;
if (fBaseParams.isDeterministic || (fp8)) {
    numBlocks = fBaseParams.aicNum;
} else {
    numBlocks = CalcTschBlockDim(s1s2BNGS1S2SplitCoreParams_->get_blockOuter() * AICV_RATIO_DEFAULT,
                                 fBaseParams.aicNum, fBaseParams.coreNum);
}
context_->SetBlockDim(numBlocks);

So the launch block dim = CalcTschBlockDim(blockOuter * 2, aicNum, coreNum). CalcTschBlockDim presumably = min(aicNum, max(blockOuter2, coreNum?)) — need to see CalcTschBlockDim. If blockOuter=4 → blockOuter2=8 → blockDim might be max(8, ...) but capped by aicNum=40 → 8 cores? But user observes 4 AIC busy. Hmm — but wait, blockStarts/blockEnds are per-core: only cores with blockEndscore > 0 do work. blockOuter=4 means only 4 blocks → 4 cores busy regardless of blockDim launch count.

Actually the important observation: SetBlockDim(numBlocks) = CalcTschBlockDim(blockOuter * 2, aicNum, coreNum). Let me find CalcTschBlockDim. If it's in the host framework... it may be in this repo. Let me search.

Also FuzzyForBestSplit: s1Inner = GetS1S2TemplateType(fBaseParams).first / 2; s2Inner = GetS1S2TemplateType(fBaseParams).second. Need GetS1S2TemplateType to get the template sizes for S=2048 FP16. Let me check GetS1S2TemplateType in common_regbase.cpp:812.

For the "4 AIC busy" question — I now think the most likely static explanation given the code: 
- Option A: BN2S2 route taken, GetBlockInfoOfBNS4TND (load-balanced per-core splitting, CaclePerCoreBlockInfo). For b=1, the load balancing might only split across... let me look at CaclePerCoreBlockInfo (varlen:1264-1312) — it fills cores until blockOuter = coreIdx+1. For b=1 with s2Outer blocks... Let me read that function. It's at varlen 1264-1312. And FillBlockInfoLoadBalance at 1685+ of normal... Actually FillBlockInfoLoadBalance in normal_regbase.cpp:1685-... I read the start of it: totalBlockInfoi = actualS1Outer*actualS2Outer; acturalBlockInfo... BinarySearchMaxBlockNumPerCore: left = acturalBlockInfob+1 (probably min), right = acturalBlockInfob (max total?). Binary search finds the minimal maxBlockNumPerCore such that IsPossible — i.e., the load-balanced block count per core. CaclePerCoreBlockInfo then assigns blocks to cores sequentially: each core takes up to maxBlockNumPerCore blocks → number of cores = ceil(totalBlocks / maxBlockNumPerCore).

For B=1, N=4, S=2048: totalBlocks (per b, summed over n2*g) = b * n2g * s1Outers2Outer? FillBlockInfoLoadBalance computes per-batch actualS1OuteractualS2Outer in totalBlockInfoi... then acturalBlockInfo... I need to read the rest of FillBlockInfoLoadBalance and CaclePerCoreBlockInfo to see how n2g multiplies in.

Let me read varlen_regbase.cpp:1216-1320 (GetBlockInfoOfBNS4TND, BinarySearchMaxBlockNumPerCore, CaclePerCoreBlockInfo, IsPossible) and normal_regbase.cpp:1685-1800 (FillBlockInfoLoadBalance).
Now let me read the load-balancing core-assignment functions (CaclePerCoreBlockInfo, IsPossible, FillBlockInfoLoadBalance) and CalcTschBlockDim + `GetS1S
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_varlen_regbase.cpp [limit=130, offset=1260]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern CalcTschBlockDim]
- Thought: 1.0s
CalcTschBlockDim isn't in the UO KB (probably in the framework library, not part of this operator's .uo graph). Let me search for it in the repo directly, and read the rest of FillBlockInfoLoadBalance and the remainder of IsPossible.

Actually let me read FillBlockInfoLoadBalance (normal_regbase.cpp:1685-1800ish), and search for CalcTschBlockDim and GetS1S2TemplateType in the machine files. GetS1S2TemplateType is in common_regbase.cpp:812. Let me read that.
CalcTschBlockDim isn't in the CodeMap (likely framework code). Let me read FillBlockInfoLoadBalance, GetS1S2TemplateType, and search the repo for CalcTschBlockDim
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=130, offset=1714]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp [limit=80, offset=800]
- Thought: 1m 18s
Now I have GetS1S2TemplateType: for FP16 (not FP8/FLOAT/HIFLOAT8), S=2048: s1TemplateType = 128, s2TemplateType = 128. So in FuzzyForBestSplit: s1Inner = 128/2 = 64, s2Inner = 128.

DoSplit: s1CvRatio=2 → s1CvInner = min(2048, 642=128) = 128 → s1Outer = ceil(2048/128) = 16. s2CvRatio=1 → cvS2Inner = min(2048, 1281) = 128 → s2Outer = ceil(2048/128) = 16.

So for B=1, N=4 (n2=4), g=1, S=2048, FP16: s1Outer=16, s2Outer=16.

Now compute the different paths:

Path A: BN2GS1S2 dense (DoSparse else branch, lines 701-722):
- fusedOuter = bn2gs1Outers2Outer = 1411616 = 1024
- blockFactor = ceil(1024/aicNum) = ceil(1024/40) = 26
- blockOuter = ceil(1024/26) = 40
- → 40 cores, each ~26 blocks. blockStartsi=26i, blockEndsi=min(26(i+1),1024). Cores 0-39... but wait blockOuter=40 > CORE_LIST_NUM=36! The array is sized 36. Hmm — the loop for (i=0;i<blockOuter;i++) writes blockStarts39 — out of bounds! Unless CalcTschBlockDim caps the actual launch. Wait, actually, maybe aicNum for arch35 is 40 but blockOuter caps... hold on: blockFactor = ceil(1024/40) = 26 (25.6 → 26); blockOuter = ceil(1024/26) = 40 (39.38 → 40). Hmm, but CORE_LIST_NUM = 36. This is suspicious — writing blockStarts36..39 would overflow the fBaseParams.blockStarts array (CORE_LIST_NUM=36) in the host struct. Actually wait — the dense branch at 712-715 loops i < blockOuter = 40 → writes blockStarts39 → out-of-bounds write into blockEnds0..3! Unless aicNum ≤ 36. Hmm.

Actually maybe on real arch35 devices aicNum is 40 but the actual use caps blockOuter to min(blockOuter, CORE_LIST_NUM)? I don't see a cap in the code. But there's a subtlety: the arrays in FuzzyBaseInfoParamsRegbase are blockStarts36 and blockEnds36. If blockOuter=40, the write at line 712-715 would overflow into blockEnds — a real bug possibility, OR aicNum in practice is ≤ 36 on this platform. Note: CORE_LIST_NUM=36 and the tiling data BlockNumListParamsRegbase uses MAX_CORE_NUM. Let me check MAX_CORE_NUM in tiling_data_regbase.h. Also this may be a 910B-style device with 40 AIC... Actually let me not over-speculate; note it as PARTIAL.

Path B: BN2S2 route (if bn2S2RouteLimit true → splitAxis=BN2S2, layoutType=TND when isAllSame):
- DoBn2s2Sparse: splitAxis==BN2S2, deterSparseType != DETER_OLD → not early return. isSparse or layoutType==TND → GetBlockInfoOfBNS4TND() (the varlen override at varlen:1216).
- GetBlockInfoOfBNS4TND → FillBlockInfoLoadBalance: computes per-batch, per-s2Outer-column "acturalBlockInfo" (fractional block counts based on the causal/band intersection area), plus totalBlockInfo. Then BinarySearchMaxBlockNumPerCore finds minimal maxBlockNumPerCore such that IsPossible → assigns cores greedily in CaclePerCoreBlockInfo: loops b × (n2*g) × s2Outer columns, packing them into cores; blockOuter = coreIdx+1.
- For B=1, N=4, S=2048 DENSE (no mask): actualS1Len=2048, actualS2Len=2048, s1CvInner=128, cvS2Inner=128. acturalBlockInfo0 = acturalS1Num/128 + acturalS2Num/128 for each j. For dense: leftIntersectionPoint = max(128*j - actualCalcS2Token, 0). Hmm, actualCalcS2Token for dense? For sparseMode NO_MASK, s2Token... In dense case, acturalS1Begin = leftIntersectionPoint; acturalS1End = min(2048, 128j + 128 + actualCalcS1Token). If tokens are 0 and dense: for column j: acturalS1Begin = 128j, acturalS1End = 128j+128 → acturalS1Num=128 → 128/128 = 1; acturalS2Num = 128 → 128/128 = 1; total = 2 per column. So each of the 16 s2Outer columns has weight 2 → acturalBlockInfo0=2. acturalBlockInfob (total) = Σ acturalBlockInfoi * n2g = 1624 = 128. acturalBlockInfob+1 = min column weight = 2.
- BinarySearchMaxBlockNumPerCore: left = acturalBlockInfob+1 = 2; right = acturalBlockInfob = 128. Binary search finds minimal maxBlockNumPerCore with IsPossible → the minimal per-core capacity such that the greedy packing fits all columns. Greedy packing: columns are b × n2g × s2Outer = 1*416 = 64 columns of weight 2 each, total weight 128. Minimal capacity per core such that 64 columns of weight 2 fit in cores = ceil(128/capacity)... BinarySearchMin for IsPossible: needCoreNum counts cores needed. With capacity c, each core holds floor... hmm IsPossible packs columns greedily: while currentSum + num > possibleMax → new core. For uniform weight 2 columns, with capacity 64: each core holds 32 columns → 2 cores. With capacity 128: 1 core. Binary search between 2 and 128 finds the minimal capacity that keeps needCoreNum ≤ some bound? Let me look at the rest of IsPossible (varlen 1373-1417) — I read up to 1389. Need to see the rest: the second half (isBn2MultiBlk false branch) probably computes needCoreNum and returns needCoreNum <= aicNum? or needCoreNum <= max cores allowed (like <= aicNum or <= 2blockOuter target...). Let me read 1389-1417.

Important: I notice in IsPossible for isBn2MultiBlk=false (the common BN2S2 non-multiblock case), it iterates... I need the rest. Let me read the remainder.

Also note: CaclePerCoreBlockInfo returns blockOuter = coreIdx+1, and DoSparse's gate: DoBn2s2Sparse() && blockOuter >= aicNum. If GetBlockInfoOfBNS4TND yields blockOuter < aicNum (e.g., only 2-4 cores needed for small workloads), the BN2S2 route is REJECTED and falls to the BS2N2GD + BN2GS1S2 dense path. So the "4 AIC" observation is NOT from the BN2S2 load-balance path (that one maximizes core usage). It must be from the DENSE fallback... but the dense fallback with s1Outer=16, s2Outer=16 gives fusedOuter=1024 → blockOuter=40. Hmm, that gives 40 cores, not 4.

Wait, wait. Let me reconsider. Let me recompute: blockFactor = ceil(fusedOuter / aicNum) = ceil(1024/40) = ceil(25.6) = 26. blockOuter = ceil(fusedOuter / blockFactor) = ceil(1024/26) = ceil(39.38) = 40. Yes 40. So not 4.

Hmm, so where does 4 come from? Options:
1. The user's S=2048 config is actually TND/BSH with actualSeqQlen... no, fixed.
2. Maybe n2 here isn't 4. What if the user's N=4 means n1=4 total heads but the input layout is BSH with g = queryDim/keyDim... In BSH: g = q H dim / k H dim. For MHA N=4: q H=4, k H=4 → g=1, n2 = headNum/g = 4/1 = 4. n1 = n2*g = 4. OK.
3. Maybe the user is running with deterministic enabled? Then SetSplitAxis: isBn2 false. bn2S2RouteLimit requires !isDeterministic for the isAllSame condition (line 1633: (fBaseParams.layoutType == INPUT_FORMAT_TND || (fBaseParams.isAllSame && !fBaseParams.isDeterministic) || bn2S2NotTndLimit)). If deterministic=1 and layout BSH (not TND): bn2S2NotTndLimit needs s1<s2 → false for square. So bn2S2RouteLimit false → splitAxis = BN2GS1S2. Then DoSparse → dense path → fusedOuter=1024 → 40 blocks. Still not 4.
4. What if the s1Inner/s2Inner differ — e.g., if d=128 FP16 but the template selection... GetS1S2TemplateType for FP16, S=2048: returns (128, 128) → s1Inner=64, s2Inner=128 → s1Outer=16, s2Outer=16. Hmm.

Hmm wait — maybe I should reconsider: the user says "只有 4 个 AIC 在干活". Maybe the real scenario: B=1, N=4, S=2048 but with actualSeqQlen=2048, actualSeqKvlen=2048 in TND layout (TND is the default for the new arch35 framework when isAllSame). In that case, at line 692: layoutType == INPUT_FORMAT_TND → GetSparseUnpadBlockInfo() — a virtual that's overridden in varlen. GetSparseUnpadBlockInfo — for non-sparse TND, what does it do? Hmm — GetSparseUnpadBlockInfo probably computes per-batch per-core prefix sums with load balance. Let me check that too.

Actually wait — but before that, DoBn2s2Sparse: if splitAxis==BN2S2 and layoutType==TND → GetBlockInfoOfBNS4TND() (varlen:1216) — this is the BN2S2-TND path. Then gate blockOuter >= aicNum. For B=1, N=4, S=2048, DENSE TND: total weight 128 columns → let me compute BinarySearch. I need the rest of IsPossible.

Let me now read varlen 1389-1417 to complete IsPossible. Also look at GetSparseUnpadBlockInfo and CalcTschBlockDim. Also check where isAllSame gets set for BSH layout (ProcessOptionalInput probably sets isAllSame=true for non-TND).
Let me finish reading IsPossible and find GetSparseUnpadBlockInfo + `CalcTschBlockDim
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_varlen_regbase.cpp [limit=30, offset=1389]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GetSparseUnpadBlockInfo]
- Thought: 39.9s
Now I understand the varlen GetSparseUnpadBlockInfo: 
- fusedOuter = calculatedBlockInfob-1SUM_ALL — the total valid blocks across all b, n2g, s1Outers2Outer (via FillBlockInfo).
- blockFactor = ceil(fusedOuter / aicNum); blockOuter = ceil(fusedOuter / blockFactor).

For B=1, N=4, S=2048 dense TND: total valid blocks = b * n2g * s1Outer * s2Outer = 141616 = 1024 → same as before → 40 blocks. So not 4 either.

Hmm. So where would "4" come from? Let me reconsider. Maybe the user is running with causal mask (typical for flash attention!). With LEFT_UP_CAUSAL: GetParseS1S2OuterInfo computes s1s2oCount (valid S1S2 blocks under the mask). For causal S=2048: valid triangular blocks ≈ s1Outers2Outer/2 = 128 (of 256), so fusedOuter = bn2gs1s2oCount = 141*~128 = 512ish. blockFactor = ceil(512/40) = 13, blockOuter = ceil(512/13) = 40. Still 40.

Hmm, still not 4. So the only static path that yields ~4 cores with this shape is one where fusedOuter (BN-partition) = bn2g = 4 → blockOuter=4 — i.e., BN2S2/BN2-style partitioning by BN only, where the S1S2 dimension is NOT multiplied in (each core gets a full (b,n2,g) block covering ALL its s1Outers2Outer). That is exactly DoBn2MultiBlkSparse (lines 632-636: blockFactor = s1Outers2Outer, fusedOuter = s1Outers2Outer but blockOuter stays = ceil(bn2g / blockFactor) with blockFactor=ceil(bn2g/aicNum)=1 → blockOuter=4). But isBn2MultiBlk requires bnLimit: bn1 >= 256 → false for b=1,n1=4. And DoBn2MultiBlkSparse only runs if splitAxis==BN2 && isBn2MultiBlk. Not our case.

OK here's another thought — maybe the user's observation of "4 AIC" is actually from the BN2S2-TND load-balance path where the number of cores is determined by BinarySearch: with dense weights 2 per column and 64 columns (b=1, n2g=4, s2Outer=16): IsPossible(possibleMax) for the non-isBn2MultiBlk branch: needCoreNum counts greedily. For capacity c: each core can hold columns until currentSum + num > c. For c = 128: 1 core. c=64: 2 cores. c=32: 4 cores. c=16: 8 cores... wait: 64 columns of weight 2 → 2 columns per... hmm no: currentSum accumulates 2 per column; for capacity c, columns per core = floor(c/2). needCoreNum = ceil(64 / floor(c/2)). IsPossible returns needCoreNum <= aicNum (40) — always true for c>=2 (needCoreNum ≤ 64 ≤ 40? no: c=2 → 1 column per core → 64 cores > 40 → false). So the minimal c that satisfies needCoreNum ≤ 40: c=4 → 2 columns per core → 32 cores ≤ 40 ✓. Binary search range left=2 (min column weight), right=128 (total). Binary search finds minimal c with IsPossible true → c=4 → 32 cores. blockOuter = 32? No wait — CaclePerCoreBlockInfo is called with maxBlockNumPerCore = the found c (4). Then it greedily packs: each core gets columns until currentSum + num > 4 → 2 columns per core (weight 2 each) → 64 columns / 2 = 32 cores. blockOuter = 32. Hmm, that's 32, not 4.

Hmm wait, but is that right? Let me recheck: for c=4: IsPossible: currentSum=0, needCoreNum=1. Column weight 2: 2 <= 4 → currentSum=2; 2+2=4 <= 4 → currentSum=4; next column: 4+2=6 > 4 → needCoreNum=2, currentSum=2... so each core holds exactly 2 columns → 64 columns → 32 cores → needCoreNum=32 ≤ 40 → true. For c=3: 2<=3 → cs=2; 2+2=4>3 → new core... 1 column per core (since 2+2>3) → 64 cores > 40 → false. So minimal c = 4 → blockOuter=32. So BN2S2-TND dense would give 32 cores. Not 4.

OK so honestly, from the code, the expected number of busy cores for B=1 N=4 S=2048 dense FP16 is much more than 4 in every path. So the "4 AIC" observation likely comes from something else:
1. Actual aicNum at runtime = 4 (device/compile config, e.g., simulator with 4 AIC, or a 910B2 with 40 → no; or an environment where AIC count is limited, or the kernel binary compiled with -core-num 4?). With aicNum=4: dense path: blockFactor = ceil(1024/4)=256; blockOuter = ceil(1024/256) = 4! → 4 cores each taking 256 blocks. That EXACTLY matches "只有 4 个 AIC 在干活"! With aicNum=4, blockOuter=4 → 4 blocks, cores 4..39 (or 4..N-1 launched) have blockEnds=0 → return at kernel.h:502-503.

So the key insight for Q3: the number of busy cores = blockOuter = ceil(fusedOuter / ceil(fusedOuter/aicNum)). If the runtime's aicNum is 4 (or the blockOuter came out as 4 for another reason), only 4 cores do work. Since the user observed exactly 4 AIC busy and vector ~100%, the most plausible static explanation: aicNum (runtime) is small (likely 4) — e.g., the operator was compiled/launched with coreNum=4, or it's a simulation environment with 4 AIC — OR the split path landed on a BN-only partition (blockOuter = bn2g = 4). But the BN-only path is impossible here (isBn2=false for S=2048 > 128). So the aicNum=4 explanation is the leading hypothesis; the code formula cannot produce 4 blocks from fusedOuter=1024 with aicNum=40.

Wait — one more consideration: line 442: fBaseParams.enableSwizzle = (isExceedL2Cache || isLargeInvalidBlk) && fBaseParams.blockOuter == fBaseParams.aicNum; — the swizzle optimization requires blockOuter == aicNum (all cores busy). If only 4 cores busy, enableSwizzle=false → no swizzle.

Also — I should double check the CalcTschBlockDim launch count: numBlocks = CalcTschBlockDim(blockOuter * AICV_RATIO_DEFAULT, aicNum, coreNum). For non-deterministic: blockOuter*2. If blockOuter=4 → 8 → CalcTschBlockDim probably = min(max(8, ...), aicNum)... Actually CalcTschBlockDim(blockOuter2, aicNum, coreNum) — likely returns min(aicNum, max(blockOuter2, coreNum?)). Hmm, can't determine statically (framework code, not in KB). The launched cores ≥ blockOuter; only blockOuter of them have non-empty ranges. So the profiler shows only 4 cores busy. The launch likely uses aicNum=40 (or blockDim), but 36 cores get [0,0).

Let me quickly search for CalcTschBlockDim definition in the repo (it might be in this operator's repo under op_host/tiling_base.h or similar) using a quick windowed read of op_host/tiling_base.h. Let me also check the kernel side SetConstInfo (kernel_base.h:488) to confirm cBlockIdx = GetBlockIdx() and the blockEnds==0 early return, plus where blockEnds is read for the loop termination (GetNextValidIdx with blockEndscore).

Also I want to confirm where "cBlockIdx" is set and check GetNextValidIdx's termination using blockEnds. Let me read kernel_base.h around 488 and the GetNextValidIdx function.
Let me check the kernel-side SetConstInfo/cBlockIdx and GetNextValidIdx termination, plus search the repo for CalcTschBlockDim in the host tiling base
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=120, offset=460]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GetNextValidIdx]
- Thought: 34.1s
I have all the kernel-side details:
- kernel.h:502-503: if (blockEnds[cBlockIdx] == 0) return; — cores with empty ranges return immediately (idle).
- kernel.h:510-511: iteration starts at blockStartscBlockIdx.
- kernel_base.h:1388-1397: GetNextValidIdx returns -1 when nextValidBlockInnerIdx >= blockEndscBlockIdx → the per-core loop ends at its blockEnds.

Now I need to find:
1. cBlockIdx setting — probably in kernel_base Init: cBlockIdx = GetBlockIdx(). Let me quickly verify — but it's near the top of kernel_base.h. I can note it as GetBlockIdx() (ascendc standard), but let me verify with one search.
2. CalcTschBlockDim — it's used in PostTiling but not in the UO KB. It's probably in the framework (tiling_api.h / tiling_base.h). Let me search the repo machine-scope for it with a quick read of op_host/tiling_base.h or grep... I can't grep. I could use uo-query search with pattern CalcTschBlockDim — already returned empty (first_hit). It's probably declared in an external header. I'll mark the launch-core-count as PARTIAL (depends on CalcTschBlockDim semantics in the CANN framework, not in this repo's CodeMap). Actually — hmm, let me do one quick search on the whole repo via uo-query --mode search for "SetBlockDim" to see if there are other launch sites.

Actually, the key Q3 answer is now clear. Let me also double-check the actual "4 AIC" explanation: 

Given the formulas, with aicNum=40: any dense path gives blockOuter=40 for this shape; the BN2S2 load-balance gives ~32; causal gives 40. The ONLY way blockOuter=4 with fusedOuter=1024 is blockFactor=256 → aicNum=4. So either:
(a) runtime aicNum=4 (device/compile config reports 4 AIC), or
(b) user's actual case differs (e.g., B=1 N=4 but s1/s2 smaller, or a sparse mode with s1s2oCount=1, or the n2*gs1Outers2Outer product = 16, etc.)

Wait — hold on. Let me reconsider (b) with causal mask and GetSparseBlockInfo: fusedOuter = bn2gs1s2oCount where s1s2oCount = parseInfos2Outer-1 = valid (s1o,s2o) block count under the mask. For LEFT_UP_CAUSAL with S=2048: valid blocks = s1Outers2Outer - s2Outer*(s2Outer-1)/2 for s1<=s2... roughly triangular ≈ 256-120=136. blockFactor=ceil(136*4/40)=14, blockOuter=ceil(544/14)=39. Still ~40.

So (a) is the leading static explanation: blockOuter == aicNum == 4 → i.e., the runtime reports aicNum=4 (e.g., 4-AIC environment/simulator, or compiled with a 4-core config, or the framework caps the block dim). Then:
- blockFactor = ceil(fusedOuter/4)
- blockOuter = ceil(fusedOuter / blockFactor) = 4 when fusedOuter ≥ 4 (1024 → blockFactor=256, blockOuter=4).
- PostTiling: numBlocks = CalcTschBlockDim(blockOuter*2=8, aicNum=4, coreNum) → likely 4 (min(...)). Actually CalcTschBlockDim(8, 4, coreNum) — semantics unknown; likely returns min(aicNum, max(8, ...)) → 4. All 4 cores busy, each 256 blocks. Vector pipe fully utilized. That matches the user's observation exactly: 4 AIC busy, vector ~100%.

Also the alternative (b'): user runs with B=1, N=4, S=2048 but actualSeqQlen=2048 and the layout is TND, non-deterministic, sparseMode=NO_MASK: GetSparseUnpadBlockInfo: fusedOuter = 1024 → 40 cores with aicNum=40. So still not 4.

Hmm, wait, one more: what about isSparse with sparseMode = BAND? GetSparseBlockInfo: s1s2oCount for BAND with band width... could reduce blocks. But still ≥ 4. blockOuter = 4 requires fusedOuter ≤ 4*blockFactor where blockFactor=ceil(fusedOuter/40): for fusedOuter=16: blockFactor=1, blockOuter=16. For fusedOuter=4: blockFactor=1, blockOuter=4. So if s1s2oCounts2... no: fusedOuter = bn2gs1s2oCount = 4s1s2oCount. blockOuter=4 iff blockFactor=1 → s1s2oCount... fusedOuter ≤ 40 → s1s2oCount ≤ 10 → blockFactor=1 → blockOuter=fusedOuter=4s1s2oCount=4 → s1s2oCount=1! So if s1s2oCount==1 (only ONE valid (s1o,s2o) block — e.g., tiny band mask or s1Outer=s2Outer=1), blockOuter=4. Not our case with S=2048 (s1Outer=16, s2Outer=16).

So: the "4 AIC" almost certainly comes from aicNum=4 at runtime OR the user's N=4 coinciding with a BN-only partition (which requires isBn2, impossible here). I'll present this clearly with the formulas and mark runtime aicNum as the key unknown (PARTIAL).

Actually, wait — I should double-check one more possibility: maybe the user's kernel is the DETER_OLD path where numBlocks = aicNum (deterministic). In deterministic mode (fBaseParams.isDeterministic=true): numBlocks = aicNum = 40. And the split: SetSplitAxis: isBn2 requires tailZeroCount==0 etc — for deterministic BSH, splitAxis = BN2GS1S2 (bn2S2RouteLimit requires !isDeterministic → false). Then DoSparse → dense branch (704): fusedOuter=1024 → blockOuter=40. All 40 busy. Not 4.

OK so my conclusion for Q3: blockOuter = ceil(fusedOuter / ceil(fusedOuter / aicNum)). For this shape with aicNum=40, every path yields ≥ 32 cores; 4 busy cores means aicNum=4 at runtime (or blockOuter was forced to 4 via some config). Let me now also double check "isAllSame" and ProcessOptionalInput for BSH — to determine whether bn2S2RouteLimit is really taken for the user's config. Let me check ProcessOptionalInput quickly (search isAllSame). Also, one more thing to verify for Q2: the TILING_FIELD for fusedOuter — confirm it doesn't exist; the kernel reads blockOuter/blockStarts/blockEnds/maxValidBBLen. The tiling_data_regbase.h BlockNumListParamsRegbase (line 233-254) has blockStartsMAX_CORE_NUM, blockEndsMAX_CORE_NUM. MAX_CORE_NUM value — let me check it in the tiling_data header. Also confirm fusedOuter is NOT in the tiling data: search the tiling_data_regbase.h for "fused".
Let me verify a few final points: MAX_CORE_NUM in tiling_data header, isAllSame init, and whether fusedOuter appears anywhere in kernel-side
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern MAX_CORE_NUM]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode search --pattern isAllSame]
- Thought: 29.9s
Note: isAllSame is only set for TND (line 244, 278). For BSH, isAllSame remains its default (false). So for BSH layout:
- bn2S2RouteLimit: layoutType == INPUT_FORMAT_TND false; (isAllSame && !isDeterministic) false (isAllSame=false for BSH); bn2S2NotTndLimit: s1<s2 false for square S=2048 → false. So bn2S2RouteLimit = FALSE for BSH square. → splitAxis = BN2GS1S2 (since isBn2=false).
- DoSparse: DoBn2s2Sparse returns false (splitAxis != BN2S2). Then SupportTrans2BS2N2GD: sparseMode<=PREFIX_COMPRESS && isAllSame && layoutType==TND → isAllSame=false → false. So layout stays BSH, no conversion.
- splitAxis = BN2GS1S2; layoutType != TND; isSparse false → dense else branch (704-722): fusedOuter = 141s1Outers2Outer; blockFactor = ceil(fusedOuter/aicNum); blockOuter = ceil(fusedOuter/blockFactor).

With s1Outer=16, s2Outer=16: fusedOuter=1024. aicNum=40 → blockFactor=26, blockOuter=40. → 40 busy cores (assuming arrays fit — note CORE_LIST_NUM=36 but blockOuter=40! Potential overflow issue — blockStartsi for i in 36..39 writes past the array in fBaseParams.blockStarts36... Actually fBaseParams.blockStarts is int64_t blockStarts[CORE_LIST_NUM] (line 433 of common_regbase.h) = 36 entries. Writing blockStarts39 overflows into blockEnds0..3! And then copying 36 entries into tiling data. Interesting — but blockEnds39 would also be read in the kernel via MAX_CORE_NUM=36... The kernel launches with blockDim ≤ 36 presumably (CalcTschBlockDim caps). Hmm — this is a potential real issue for big dense cases: with aicNum=40, blockOuter can reach 40 > MAX_CORE_NUM=36, so cores 36-39 get garbage/overflowed ranges. But in practice, CalcTschBlockDim likely caps numBlocks at 36 or aicNum. I should flag this as PARTIAL/note, but the user's case is about only 4 cores, so the relevant point is: blockOuter == number of busy cores.

Wait — actually I realize I should double-check CalcTschBlockDim semantics: it's CalcTschBlockDim(blockOuter * AICV_RATIO_DEFAULT, aicNum, coreNum). AICV_RATIO_DEFAULT = 2. For blockOuter=4: 8, capped by aicNum. CalcTschBlockDim likely = min(aicNum, max(requested, ...)) or similar. This is a framework function (tiling_api.h) — not in the operator's UO KB. I'll note the launched core count as PARTIAL but explain: launched cores = CalcTschBlockDim(...); busy cores = blockOuter (only cores with blockEnds>0 do work; kernel.h:502-503).

Now let me also reconsider: maybe the user's S=2048 case is actually BSH + causal mask (sparse). Then: DoSparse → DoBn2s2Sparse false (splitAxis BN2GS1S2) → SupportTrans2BS2N2GD false → isSparse true → sparseMode: if causal → GetSparseBlockInfo() (line 699). fusedOuter = bn2gs1s2oCount. For LEFT_UP_CAUSAL S=2048: s1s2oCount = number of valid (s1o,s2o) block pairs ≈ 1616 - 1615/2 = 256-120 = 136. fusedOuter = 4136 = 544. blockFactor = ceil(544/40) = 14; blockOuter = ceil(544/14) = 39. Still ~40. Not 4.

So the ONLY way to get 4 busy cores from these formulas: aicNum ≈ 4 at runtime (fusedOuter=1024 → blockFactor=256 → blockOuter=4). OR the environment where n2g is small and the BN-partitioning path with blockOuter=bn2g=4... but that requires isBn2 (S≤128) or isBn2MultiBlk (bn1≥256) — impossible here.

So my answer for Q3: The tiling formula caps actual busy cores at blockOuter = ceil(fusedOuter / ceil(fusedOuter / aicNum)). For B=1 N=4 S=2048 with the standard FP16 dense/causal paths, fusedOuter = b·n2·g·s1Outer·s2Outer (or ·s1s2oCount) = 1024 (dense) with s1Outer=16, s2Outer=16; with aicNum=40 that yields 40 blocks/cores. Observing exactly 4 busy AIC means the effective aicNum seen by tiling was 4 (i.e., blockFactor = 256 = fusedOuter/4 → blockOuter=4), i.e., the runtime/compile info reported aicNum=4 — or the run actually took a path where fusedOuter=4 (BN-partition only, impossible for this shape). So: PARTIAL — need actual aicNum from device; but the mechanism (blockOuter as busy-core count, kernel early-return at kernel.h:502-503) is fully static.

Also relevant: with only blockOuter=4 and vector nearly 100% — each core does fusedOuter/4 = 256 basic blocks serially on the vector pipe → the vector pipe is saturated, matching the user's observation of "vector 几乎打满" — that's a symptom of too few cores, not slow VF per se.

Now Q2 detail — "写进哪个 TILING_FIELD": fusedOuter is NOT a tiling field. The host computes fusedOuter as a local; what's written is blockOuter (uint32_t), maxValidBBLen (uint32_t) into FlashAttentionScoreGradS1S2BNGS1S2SplitCoreParamsRegbase (tiling_data_regbase.h:204-205; write sites normal_regbase.cpp:1909-1910), and blockStarts/blockEnds (int64_tMAX_CORE_NUM) into BlockNumListParamsRegbase (tiling_data_regbase.h:235-236; write site normal_regbase.cpp:1907-1908). Kernel reads via tilingData->s1s2BNGS1S2SplitCoreParams.blockOuter (kernel_base.h:569 for deter, and blockStarts/blockEnds at kernel.h:502-503,510-511,1389-1397).

Q4: fusedOuter 在 tiling 结构里的声明 — Answer: 不存在。There's no fusedOuter field in tiling_data_regbase.h. The struct FlashAttentionScoreGradS1S2BNGS1S2SplitCoreParamsRegbase (line 194-231) declares: s1Outer(int64), s1Inner/s1CvInner/s1Tail/s1CvTail(uint32), s2Outer(int64), s2Inner/s2Tail(uint32), blockOuter(uint32), maxValidBBLen(uint32), bandIdx(int64). fusedOuter only exists as a host-local int64_t in the .cpp.

One more check for Q1: the "coreNum" usage — coreNum = aivNum (line 384/394), used in PostTiling CalcTschBlockDim(..., aicNum, coreNum) and enableSwizzle checks, and saved to tiling data (line 1839 set_coreNum). aicNum = GetCoreNumAic() (line 396 / compile info 385 / tiling.cpp:541). There's no explicit aicNum cap in the operator (no min(aicNum, 36)); the only constraint is CORE_LIST_NUM=36/MAX_CORE_NUM=36 for the block arrays.

Let me quickly verify one more detail for Q1 — the blockIndex → (b,n2,g,s1o,s2o) decode in GetSparseBlockInfo uses s1s2oCount from parseInfo, and blockStarts are "total indx in bngs1os2o". Good.

Also for kernel: cBlockIdx. Let me quickly find where cBlockIdx is assigned in kernel_base.h to cite it. Search "cBlockIdx".
One last check — where the kernel sets cBlockIdx (its own
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern cBlockIdx]
- Thought: 2.5s
cBlockIdx is a uint32_t field on FlashAttentionScoreGradKernelBase (kernel_base.h:137), and it's set in Init (probably cBlockIdx = GetBlockIdx()). Let me quickly verify where it's assigned — search for "GetBlockIdx" or just check the Init function near the beginning of kernel_base.h. Actually, I have enough. The typical pattern is cBlockIdx = GetBlockIdx(). Let me do one quick locate for GetBlockIdx to be precise.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GetBlockIdx]
- Thought: 45.9s
cBlockIdx is set via AscendC::GetBlockIdx() in the Init of kernel_base.h (line 186-201 area). The kernel's per-core loop uses blockStartscBlockIdx / blockEndscBlockIdx.

I now have everything needed to write a complete answer. Let me summarize all the evidence with file:line references:

Q1: host 分核机制
- aicNum 来源: 
  - GetPlatformInfo: normal_regbase.cpp:384-385 (compileInfoPtr->aivNum/aicNum) or :394-396 (GetCoreNumAiv / GetCoreNumAic)
  - TilingPrepare: op_host/flash_attention_score_grad_tiling.cpp:540-541
  - 无显式上限约束；CORE_INIT_NUM=40 只是初始值 (common_regbase.h:72)，CORE_LIST_NUM=36 (common_regbase.h:136)，MAX_CORE_NUM=36 (tiling_data_regbase.h:23)
- 切分轴决策: SetSplitAxis common_regbase.cpp:1581-1649
  - isBn2 (1583-1588): s1,s2<=128(BN2_MAX_S) && n1==n2 && d<=512(BN2_MAX_D) && 非FP32/FP8 && tailZeroCount==0
  - isBn2MultiBlk (1590-1606): bn1>=256 或 (bn1>=128 && s%128==0) 等
  - bn2S2RouteLimit (1631-1639)
  - splitAxis 决定 1641-1648
- 分块: DoOpTiling (430-476) → DoSplit (478-509) 算 s1Inner/s2Inner/s1Outer/s2Outer (FuzzyForBestSplit 1474-1481; GetS1S2TemplateType common:812-845 → FP16 128/128 → s1Inner=64, s2Inner=128; s1CvRatio=2 → s1Outer=ceil(s1/128); s2CvRatio=1 → s2Outer=ceil(s2/128))
- DoSparse (660-732) 分派:
  - BN2S2 + TND/稀疏 → GetBlockInfoOfBNS4TND (varlen 1216-1245; 用二分+贪心按核打包, varlen 1247-1313, 1373-1411; 仅当 blockOuter>=aicNum 才接受, normal:665)
  - BN2 + isBn2MultiBlk → DoBn2MultiBlkSparse (622-658; BN-partition: fusedOuter=b*n2g, blockFactor=ceil(fusedOuter/aicNum), blockOuter=ceil(fusedOuter/blockFactor); 每个核拿整个 s1Outers2Outer 块集合; 632-636)
  - 稀疏 → GetSparseBlockInfo (1553-1622; fusedOuter=b*n2gs1s2oCount) / GetSparsePrefixBlockInfo (1624-1683)
  - TND → GetSparseUnpadBlockInfo (varlen 953-...)
  - dense → 704-722 (fusedOuter=bn2gs1Outers2Outer; blockFactor=ceil(fusedOuter/aicNum); blockOuter=ceil(fusedOuter/blockFactor))
- 核数上限约束: 无显式 min(aicNum, 36)；blockStarts/blockEnds 数组为 CORE_LIST_NUM=36 (common_regbase.h:433-434)，tiling 字段 MAX_CORE_NUM=36 (tiling_data_regbase.h:23,235-236)。若 blockOuter>36 会越界（PARTIAL：需确认设备 aicNum）。正常 aicNum=40 时 blockOuter 可达 40。
- 启动核数: PostTiling (1483-1506): numBlocks = aicNum (确定性/FP8) 或 CalcTschBlockDim(blockOuter*2, aicNum, coreNum) (非确定性) → SetBlockDim。CalcTschBlockDim 在框架内，不在本仓 CodeMap（PARTIAL）。

B=1,N=4,S=2048 具体计算:
- BSH: g=1 (q/k H 轴相等), n2=headNum/g=4, n1=n2*g=4 (normal:138-151, 369)
- isBn2=false (S=2048>128); isBn2MultiBlk=false (b*n1=4<128); 
- bn2S2RouteLimit: BSH 下 isAllSame=false（isAllSame 只在 TND 设置, normal:244,278）→ layoutType==TND false, isAllSame&&!deterministic false, bn2S2NotTndLimit (s1<s2) false → false → splitAxis=BN2GS1S2
- s1Outer=ceil(2048/128)=16, s2Outer=ceil(2048/128)=16 (FP16: s1Inner=64→s1CvInner=128, s2Inner=128→cvS2Inner=128)
- dense: fusedOuter=1411616=1024; aicNum=40 → blockFactor=26, blockOuter=40 → 40 个核各 26 块（若 aicNum=4 → blockFactor=256, blockOuter=4 → 4 核各 256 块）
- causal: s1s2oCount≈136 → fusedOuter≈544 → blockOuter≈39-40

Q2: fusedOuter 定义
- 仅 host 局部变量，每个分块路径分别定义（不是结构体字段）:
  - DoBn2s2Sparse dense: normal:523 b*n2*g*s2Outer
  - GetSparseBlockInfoBn2: normal:557 b*n2*g，564 *= s1s2oCount
  - DoBn2MultiBlkSparse: normal:632 b*n2*g，636 *= (s1Outer*s2Outer)
  - DoSparse dense: normal:704 b*n2*g*s1Outer*s2Outer
  - GetSparseBlockInfo: normal:1561 b*n2*g*s1s2oCount
- 乘数即 b、n2、g、s1Outer/s2Outer（或 s1s2oCount）的乘积
- 不写进任何 TILING_FIELD（locate 显示 fused_outer_candidates_count=0，kernel 侧无 fused 字段）；写入的是 blockOuter (uint32)、maxValidBBLen (uint32)、blockStarts/blockEnds (int64MAX_CORE_NUM):
  - 写点: normal:1907-1910 (s1s2BNGS1S2BlockNumList_->set_blockStarts/blockEnds; s1s2BNGS1S2SplitCoreParams_->set_blockOuter/set_maxValidBBLen)
- kernel 读: kernel.h:502-503 (blockEndscBlockIdx==0 → return), 510-511 (从 blockStartscBlockIdx 开始), kernel_base.h:1389-1397 (>= blockEndscBlockIdx → -1 结束), SetConstInfo kernel_base.h:492-... (读 s1Outer/s2Outer 等), blockOuter 用于 deter (kernel_base.h:569)。

Q3: 为什么只有 4 个 AIC
- 干活的核数 = blockOuter（每个核处理 [blockStartsc, blockEndsc)，空的直接 return kernel.h:502-503）
- blockOuter 公式: ceil(fusedOuter / ceil(fusedOuter/aicNum))（704-706 等）
- 本 shape: fusedOuter=1024, blockOuter=40 (aicNum=40) 或 =4 (aicNum=4: blockFactor=256 → blockOuter=4)
- 观察 4 核 → 最可能 aicNum 运行时=4（或编译配置 4 核），即 blockFactor=256，每核 256 块 → vector 打满。另一种可能：真的走了 BN 维度切分（blockOuter=bn2g=4），但本 shape isBn2/isBn2MultiBlk 都不满足 → 排除。PARTIAL: 需要用户提供实际 aicNum（GetCoreNumAic 的设备信息）。
- 另外注意 enableSwizzle 要求 blockOuter==aicNum (442) 才开 swizzle；核多时才有机会开。
- 补充: 若 aicNum=40 而 fusedOuter 只有 4 的情况（如 s1Outer*s2Outer 很小）也会 4 核，但 S=2048 不满足。

Q4: fusedOuter 在 tiling 结构里的声明
- 不存在。tiling_data_regbase.h:194-231 FlashAttentionScoreGradS1S2BNGS1S2SplitCoreParamsRegbase: s1Outer(int64_t, 196), s1Inner(197), s1CvInner(198), s1Tail(199), s1CvTail(200), s2Outer(int64_t, 201), s2Inner(202), s2Tail(203), blockOuter(uint32_t, 204), maxValidBBLen(uint32_t, 205), bandIdx(int64_t, 206)；BlockNumListParamsRegbase: blockStarts/blockEnds int64_tMAX_CORE_NUM (235-236)。
- fusedOuter 仅存在于 host .cpp 局部（normal:523/557/632/704/1561; varlen:962 用 calculatedBlockInfo.. 等价物）。

Now, let me also double check the kernel Init location for cBlockIdx: kernel_base.h:186-201 has GetBlockIdx calls in Init — good enough, cBlockIdx = GetBlockIdx() in Init. I'll cite kernel_base.h:186/190/197/201.

One more thing to verify: 对 BSH 非 TND 的 isSparse 判定。isSparse is set from sparse mode: for BSH, if no atten mask → NO_MASK → isSparse=false probably. Fine, I'll mark as assumed (dense, no mask) — user didn't say mask. Actually the user just said B=1 N=4 S=2048 FP16; the run might include causal mask, but either way the core-count formula is the same ~40 for aicNum=40.

I think I have enough for a comprehensive Cursor-Explore style answer. Note the boundary: I'm a readonly_analyst; answer in final message; no answer.yaml, no finalize.
I have all the evidence needed. Here's the complete analysis.
flash_attention_score_grad（arch35, digest 211a7ec…）host 分核与 fusedOuter 排查
先说结论：*fusedOuter 不是 tiling 字段，只是 host 侧一个局部 int64，按 b·n2·g·(s1Outer·s2Outer 或 s1s2oCount) 现算；真正下发给 kernel 的是 blockOuter + 每核 blockStarts[core]/blockEnds[core]。干活的核数严格等于 blockOuter，其余核在 kernel 入口直接 return。B=1、N=4、S=2048（FP16, dense）时若 aicNum=40，公式给出 40 个核；观察到只有 4 个核干活，几乎必然是运行时 aicNum=4（blockFactor=256 → blockOuter=4）——而不是分核轴选错。*
1. Host 侧分核机制（按路径逐层拆）
aicNum/coreNum 来源
- GetPlatformInfo()：fBaseParams.coreNum = compileInfoPtr->aivNum; fBaseParams.aicNum = compileInfoPtr->aicNum;（normal_regbase.cpp:384-385）；platformInfo 可用时 coreNum = ascendcPlatform.GetCoreNumAiv(); fBaseParams.aicNum = ascendcPlatform.GetCoreNumAic();（:394-396）。TilingPrepare 里也把 compileInfoPtr->aicNum = GetCoreNumAic() 填好（op_host/flash_attention_score_grad_tiling.cpp:540-541）。默认初值 CORE_INIT_NUM = 40（common_regbase.h:72）。算子里没有显式 min(aicNum, …) 上限；唯一容量约束是 host 侧 block 数组 CORE_LIST_NUM = 36（common_regbase.h:136）与 tiling 字段 MAX_CORE_NUM = 36（tiling_data_regbase.h:23）。
切分轴决策 SetSplitAxis（common_regbase.cpp:1581-1649）
- isBn2：s1<=BN2_MAX_S(128) && s2<=128 && n1==n2 && d<=BN2_MAX_D(512) && 非FP32/FP8 && tailZeroCount==0（:1583-1588；常量 110/115 行）。
- isBn2MultiBlk：需要 b*n1 >= 256 或（b*n1 >= 128 且 s1,s2 128 对齐）（:1590-1591，常量 BN2_MULTIBLK_BN256=256 / BN2_MULTIBLK_BN128=128 / ALIGN128=128，common_regbase.h:113-114,109），再叠加 s1/s2∈(128, 640]、n1==n2、d<=512、d==d1 等（:1596-1606）。
- bn2S2RouteLimit：!hasRope && d<=512 && (layoutType==TND || (isAllSame && !isDeterministic) || bn2S2NotTndLimit) && … && n1==n2 && 非FP32/FP8（:1631-1639）。其中 bn2S2NotTndLimit = s1<s2 && s2<=BN2S2_MAX_S(1024) && s2-s1>=128 && d<=128 && !isSparse && !isDeterministic（:1625-1630）。
- 最终：BN2S2 > BN2 > BN2GS1S2 三选一（:1641-1648）。
S1/S2 外层切块 DoSplit（normal_regbase.cpp:478-509）
- FuzzyForBestSplit（:1474-1481）：s1Inner = GetS1S2TemplateType().first / 2; s2Inner = GetS1S2TemplateType().second。FP16 且 s1s2 ≥ 128128 时模板为 (128,128)（common_regbase.cpp:830-845）→ s1Inner=64, s2Inner=128。
- s1CvRatio=2, s2CvRatio=1（:480-481）→ s1CvInner=min(s1, 64*2)=128，s1Outer=ceil(s1/128)；cvS2Inner=min(s2,128)，s2Outer=ceil(s2/128)（:484-498）。
分块分派 DoSparse（normal_regbase.cpp:660-732）
- BN2S2 且非 DETER_OLD → DoBn2s2Sparse()（:511-547）：TND/稀疏走 GetBlockInfoOfBNS4TND()（varlen 的 load-balance 二分贪心版，varlen_regbase.cpp:1216-1411）；纯 BSH dense 走 inline 公式 fusedOuter = b*n2*g*s2Outer，bns2Factor=ceil(fusedOuter/aicNum)，blockOuter=ceil(fusedOuter/bns2Factor)，blockFactor=bns2Factor*s1Outer（:523-527）。关键门槛：DoBn2s2Sparse() && blockOuter >= aicNum 才接受（:665），否则 fallthrough。
- SupportTrans2BS2N2GD（common_regbase.cpp:1669-1672）会把 TND 改回 INPUT_FORMAT_BS2N2GD。
- splitAxis==BN2 && isBn2MultiBlk → DoBn2MultiBlkSparse()（:622-658）：按 BN 切，fusedOuter=b*n2*g，blockFactor=ceil(fusedOuter/aicNum)，blockOuter=ceil(fusedOuter/blockFactor)，再 blockFactor *= s1Outer*s2Outer（:632-636）——每个核拿到一整片 (b,n2,g) 的全部 S1S2 块。
- 稀疏（非 PREFIX）→ GetSparseBlockInfo()（:1553-1622）：fusedOuter=b*n2*g*s1s2oCount（:1561），其中 s1s2oCount = parseInfo[s2Outer-1][LENGTH_IDX] 是按掩码算出的有效 (s1o,s2o) 块数（:552-554）；随后把块索引解码回 (bIdx,n2Idx,gIdx,s2oIdx,s1oIdx) 生成各核区间（:1581-1611）。
- PREFIX/PREFIX_COMPRESS → GetSparsePrefixBlockInfo()（:1624-1683）：totalValidBaseBlock = Σ各batch有效块 × n2*g（:1650），同样 blockFactor=ceil(total/aicNum)、blockOuter=ceil(total/blockFactor)（:1651-1653）。
- TND → varlen GetSparseUnpadBlockInfo()（varlen:953-1041+）：fusedOuter = calculatedBlockInfo[b-1][0][SUM_ALL]（:962），公式同上。
- 剩余 dense 兜底（:701-722）：fusedOuter = b*n2*g*s1Outer*s2Outer（:704），blockFactor = ceil(fusedOuter/aicNum)（:705），blockOuter = ceil(fusedOuter/blockFactor)（:706），随后逐核 blockStarts[i]=blockFactor*i; blockEnds[i]=min(blockFactor*(i+1), fusedOuter)（:712-714），多余的核置 [0,0)（:716-718）。
启动核数 PostTiling（:1483-1506）
- 确定性/FP8：numBlocks = aicNum（:1490）；否则 numBlocks = CalcTschBlockDim(blockOuter * AICV_RATIO_DEFAULT(=2), aicNum, coreNum)（:1492-1493）→ SetBlockDim(numBlocks)（:1499）。CalcTschBlockDim 在本算子仓的 CodeMap 里不存在（框架函数）——启动核数语义 PARTIAL，但“实际干活的核数 = blockOuter”不受它影响（见 Q3）。
B=1、N=4、S=2048、FP16 按公式推算
- BSH 输入：g = query H / key H = 1，n2 = headNum/g = 4（normal:142-144），n1 = n2*g = 4（:369）。
- SetSplitAxis：isBn2=false（S=2048 > BN2_MAX_S=128）；isBn2MultiBlk=false（b*n1=4 < 128）；BSH 下 isAllSame=false（isAllSame 只在 TND 分支赋值，normal:244,278）→ bn2S2RouteLimit 三段条件全 false → splitAxis = BN2GS1S2。
- s1Outer=ceil(2048/128)=16，s2Outer=ceil(2048/128)=16。
- dense 兜底：fusedOuter=1*4*1*16*16=1024。aicNum=40 → blockFactor=ceil(1024/40)=26，blockOuter=ceil(1024/26)=40 → 40 个核，每核 26 块；若稀疏 causal：s1s2oCount≈136 → fusedOuter≈544 → blockOuter≈39~40。
2. fusedOuter 的确切定义与计算位置
它是一个宿主侧函数内局部变量，每个分块路径各自现算，乘积都是 b·n2·g·（s1Outer·s2Outer 或 s1s2oCount）：
位置	表达式
DoBn2s2Sparse（BSH dense 分支） normal:523	b * n2 * g * s2Outer
GetSparseBlockInfoBn2 normal:557,564	b * n2 * g，再 *= s1s2oCount
DoBn2MultiBlkSparse normal:632,636	b * n2 * g，再 *= (s1Outer * s2Outer)
DoSparse dense 兜底 normal:704	b * n2 * g * s1Outer * s2Outer
GetSparseBlockInfo normal:1561	b * n2 * g * s1s2oCount
不写进任何 TILING_FIELD：locate fusedOuter 的 fused_outer_candidates_count=0，全部命中都在 host .cpp；kernel 侧 tiling_data_regbase.h 无任何 fused* 字段。真正落盘的字段是：
- FlashAttentionScoreGradS1S2BNGS1S2SplitCoreParamsRegbase::blockOuter (uint32_t) 与 maxValidBBLen (uint32_t)（tiling_data_regbase.h:204-205）；写点 set_blockOuter(fBaseParams.blockOuter)、set_maxValidBBLen(...)（normal:1909-1910）。
- BlockNumListParamsRegbase::blockStarts / blockEnds (int64_t[MAX_CORE_NUM])（tiling_data_regbase.h:235-236）；写点 set_blockStarts(fBaseParams.blockStarts)、set_blockEnds(...)（normal:1907-1908）。
kernel 读取方式：tilingData->s1s2BNGS1S2BlockNumList.blockEnds[cBlockIdx]==0 → return（kernel.h:502-503）；从 blockStarts[cBlockIdx] 起逐个块循环（kernel.h:510-511），GetNextValidIdx 里 >= blockEnds[cBlockIdx] 返回 -1 结束（kernel_base.h:1388-1397）；cBlockIdx = GetBlockIdx()（kernel_base.h:186-201 / pre 阶段 :113）。blockOuter 还用于确定性旧模板的 usedCubeCoreNum（kernel_base.h:568-569）。
3. 为什么可能只有 4 个 AIC 干活
机制链（全部静态可证）：
1. 每个核只处理 [blockStarts[cBlockIdx], blockEnds[cBlockIdx])；host 把 core >= blockOuter 的区间全部置 [0,0)（如 normal:716-718、610-613、648-651、1612-1615、varlen:1237-1240）。
2. kernel 入口 if (blockEnds[cBlockIdx] == 0) return;（kernel.h:502-503）→ 干活的核数 = blockOuter，与启动 blockDim 无关（启动核数是 CalcTschBlockDim(blockOuter*2, aicNum, coreNum)，normal:1492-1493）。
3. blockOuter = ceil(fusedOuter / ceil(fusedOuter / aicNum))（normal:704-706 等）。对 B=1、N=4、S=2048：fusedOuter=1024；aicNum=40 → 40 核；aicNum=4 → blockFactor=256，blockOuter=4。blockOuter==4 在公式上只有“aicNum≈4”或“fusedOuter≤16 且 aicNum=40（需 s1s2oCount 或 s1Outer·s2Outer 缩到 ~1）”两种可能，后者在 S=2048 下不成立（s1Outer=s2Outer=16）。
4. 分核轴检查排除 BN-only 切法：isBn2（S≤128）与 isBn2MultiBlk（b·n1≥256）对本 shape 都不满足（common_regbase.cpp:1583-1606），所以不可能是“按 b·n2·g=4 切、每核拿整片 S1S2”的路径。
因此：观察到 4 核干活、vector 打满，最可能是运行时 aicNum=4（每核 256 个基本块在 vector 管线上串行，恰好解释 vector≈100%）。需要 GetCoreNumAic() 的设备值才能定案——PARTIAL，静态代码无法确定。另外注意副作用：enableSwizzle 只在 blockOuter == aicNum 时开启（normal:442），核少时 swizzle/nzOut 优化全部关闭；blockOuter 超过 36 时还会踩 CORE_LIST_NUM=36 的 host 数组边界（common_regbase.h:433-434），这是 aicNum=40 时 dense 大算子的潜在隐患（PARTIAL，需设备确认 aicNum 与 CalcTschBlockDim 行为）。
4. fusedOuter 在 tiling 结构里的声明
没有声明——它不存在于任何 tiling 结构。 FlashAttentionScoreGradS1S2BNGS1S2SplitCoreParamsRegbase（tiling_data_regbase.h:194-231）的完整字段：s1Outer(int64_t) :196、s1Inner/s1CvInner/s1Tail/s1CvTail(uint32_t) :197-200、s2Outer(int64_t) :201、s2Inner/s2Tail(uint32_t) :202-203、*blockOuter(uint32_t) :204、maxValidBBLen(uint32_t) :205*、bandIdx(int64_t) :206。BlockNumListParamsRegbase（:233-254）只含 blockStarts/blockEnds(int64_t[MAX_CORE_NUM])。fusedOuter 只是 host 局部量（Q2 表），varlen 的 GetSparseUnpadBlockInfo 用 calculatedBlockInfo[..][SUM_ALL] 充当同义量（varlen:962）。kernel 侧拿到的“块总数”信息其实隐含在 blockEnds 与 s1Outer/s2Outer/maxValidBBLen 里，不需要 fusedOuter 本身。
一句话给用户：核内 VF 不慢——是核太少。把 aicNum（GetCoreNumAic()，tiling.cpp:541）打印出来确认；若设备确实报 4，则这是环境/编译配置问题而非分核轴选错；若设备报 40 而 blockOuter=4，请抓 OP_LOGD("Sparse"/DoBn2s2Sparse…) 确认实际走了哪条 split 路径（尤其 SupportTrans2BS2N2GD 转换与 GetBlockInfoOfBNS4TND 的二分结果，varlen:1216-1313）。
（未写 answer.yaml，未 finalize。）
▣  Uo-Query · DeepSeek V4 Flash Free · 9m 25s
- Thought: 50.8s
Let me analyze the conversation to produce the structured summary.

The user wants me to investigate the flash_attention_score_grad operator's host-side tiling/core-splitting strategy, fusedOuter definition, why only 4 AIC cores are busy, and fusedOuter declaration in tiling structures. The user explicitly said "不要写 answer.yaml，不要 finalize" — this is an investigation task, not a finalize task. The assistant was doing this investigation.

Let me collect the key findings from the conversation:

1. fusedOuter definition — host-local variable in op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp, computed differently per path:
   - Line 523 (DoBn2s2Sparse): fBaseParams.b * fBaseParams.n2 * fBaseParams.g * fBaseParams.s2Outer
   - Line 557 (GetSparseBlockInfoBn2): fBaseParams.b * fBaseParams.n2 * fBaseParams.g then *= s1s2oCount at 564
   - Line 632 (DoBn2MultiBlkSparse): fBaseParams.b * fBaseParams.n2 * fBaseParams.g, then *= (s1Outer*s2Outer) at 636
   - Line 704 (DoSparse dense else): fBaseParams.b * fBaseParams.n2 * fBaseParams.g * fBaseParams.s1Outer * fBaseParams.s2Outer
   - Line 1561 (GetSparseBlockInfo): fBaseParams.b * fBaseParams.n2 * fBaseParams.g * s1s2oCount
   - NOT a TILING_FIELD — no fusedOuter field in tiling_data_regbase.h (locate showed fused_outer_candidates_count: 0, all 17 matches in host .cpp files)

2. Block splitting formula (the core pattern):
   - blockFactor = (fusedOuter + aicNum - 1) / aicNum (ceil division)
   - blockOuter = (fusedOuter + blockFactor - 1) / blockFactor (ceil division)
   - blockStarts[i] = blockFactor * i; blockEnds[i] = min(blockFactor*(i+1), fusedOuter) 
   - Cores i >= blockOuter get [0, 0) — kernel returns early (kernel.h:502-503)

3. Tiling fields written — tiling_data_regbase.h:
   - FlashAttentionScoreGradS1S2BNGS1S2SplitCoreParamsRegbase (line 194): s1Outer (int64_t), s1Inner, s1CvInner, s1Tail, s1CvTail, s2Outer (int64_t), s2Inner, s2Tail, blockOuter (uint32_t), maxValidBBLen (uint32_t), bandIdx (int64_t)
   - BlockNumListParamsRegbase (line 233): blockStartsMAX_CORE_NUM, blockEndsMAX_CORE_NUM; MAX_CORE_NUM=36 (line 23)
   - Write sites: normal_regbase.cpp:1898-1904 (s1Outer/s1Inner/.../s2Outer), and blockOuter/maxValidBBLen/blockStarts/blockEnds written via fBaseParams into s1s2BNGS1S2SplitCoreParams_/s1s2BNGS1S2BlockNumList

4. aicNum source: normal_regbase.cpp:384-385 fBaseParams.coreNum = compileInfoPtr->aivNum; fBaseParams.aicNum = compileInfoPtr->aicNum; (from compile info) or 392+ platform_ascendc::PlatformAscendC path (GetCoreNumAic presumably). CORE_INIT_NUM=40 default (line 375).

5. Split axis decision (SetSplitAxis, common_regbase.cpp:1581-1648):
   - isBn2 = (s1<=BN2_MAX_S=128 && s2<=BN2_MAX_S=128) && (n1==n2) && d<=BN2_MAX_D=512 && !FP32 && !FP8 && tailZeroCount==0 (1583-1588)
   - bnLimit = (b*n1 >= BN2_MULTIBLK_BN_256=256) || (b*n1 >= BN2_MULTIBLK_BN_128=128 && s1%128==0 && s2%128==0) (1590-1591)
   - isBn2MultiBlk = bnSparseLimit && (s1>128 || s2>128) && s1<=BN2_MULTIBLK_SEQ=640 && s2<=640 && n1==n2 && d<=512 && ... (1596-1606)
   - bn2S2RouteLimit = !hasRope && d<=512 && (layoutType==TND || (isAllSame && !isDeterministic) || bn2S2NotTndLimit) && (keepProb>=1 || (d<=128 && keepProb<1)) && n1==n2 && !FP32 && !FP8 (1631-1639)
   - Final: if (!isBn2 && bn2S2RouteLimit) { layoutType = isAllSame ? TND : layoutType; splitAxis = BN2S2; } else if (isBn2) { splitAxis = BN2; } else { splitAxis = BN2GS1S2; } (1641-1648)

6. DoSparse dispatch (normal_regbase.cpp:660-720):
   - if (DoBn2s2Sparse() && fBaseParams.blockOuter >= fBaseParams.aicNum) → accept BN2S2 path (line 665)
   - else: SupportTrans2BS2N2GD → splitAxis = isBn2 ? BN2 : BN2GS1S2 (line 691) → dispatch: TND→GetSparseUnpadBlockInfo; PREFIX/PREFIX_COMPRESS→GetSparsePrefixBlockInfo; isSparse→GetSparseBlockInfo; dense→inline formula (line 704: fusedOuter = bn2gs1Outers2Outer, blockFactor = ceil(fusedOuter/aicNum), blockOuter = ceil(fusedOuter/blockFactor))

7. BN2S2-TND path: GetBlockInfoOfBNS4TND (varlen_regbase.cpp:1216) → FillBlockInfoLoadBalance (acturalBlockInfo weights) → BinarySearchMaxBlockNumPerCore + IsPossible (needCoreNum <= aicNum, varlen:1390-1391, 1405-1406) → CaclePerCoreBlockInfo (greedy pack per core; blockOuter = coreIdx+1; varlen:1264-1312).

8. Kernel side:
   - kernel.h:502-503: if (tilingData->s1s2BNGS1S2BlockNumList.blockEnds[cBlockIdx] == 0) return;
   - kernel.h:510-511: starts iteration at blockStartscBlockIdx
   - kernel_base.h:1368+ GetNextValidIdx: returns -1 when idx >= blockEndscBlockIdx (terminates per-core loop)

9. PostTiling / launch dim (normal_regbase.cpp:1483-1506):
   - deterministic/FP8: numBlocks = aicNum
   - else: numBlocks = CalcTschBlockDim(blockOuter * AICV_RATIO_DEFAULT=2, aicNum, coreNum) — CalcTschBlockDim NOT in UO KB (framework code) — PARTIAL
   - context_->SetBlockDim(numBlocks)

10. Computed numbers for B=1, N=4, S=2048, FP16, d=128:
    - n2 = headNum/g = 4/1 = 4, g=1, n1 = n2*g = 4 (normal_regbase.cpp:369)
    - isBn2 = false (S=2048 > 128)
    - isBn2MultiBlk = false (b*n1 = 4 < 128)
    - bn2S2RouteLimit: TRUE (n1==n2, d=128<=512, isAllSame for BSH fixed shape, !hasRope) → splitAxis=BN2S2, layoutType→TND (if isAllSame)
    - GetS1S2TemplateType (common_regbase.cpp:812+): FP16 → s1TemplateType=128, s2TemplateType=128
    - FuzzyForBestSplit (1474-1481): s1Inner = 128/2 = 64, s2Inner = 128
    - s1CvInner = min(2048, 64*2=128) = 128 → s1Outer = ceil(2048/128) = 16
    - cvS2Inner = 128 → s2Outer = ceil(2048/128) = 16
    - Dense fusedOuter (BN2GS1S2) = 1411616 = 1024; blockFactor=ceil(1024/40)=26; blockOuter=ceil(1024/26)=40 (with aicNum=40)
    - BN2S2 load-balance (dense): 64 columns (b×n2g×s2Outer = 1×4×16) of weight 2 → minimal capacity 4 → 32 cores (blockOuter≈32)
    - Causal GetSparseBlockInfo: s1s2oCount≈136 → fusedOuter≈544 → blockOuter≈39
    - With aicNum=4: blockFactor=ceil(1024/4)=256, blockOuter=ceil(1024/256)=4 → exactly 4 busy cores → matches the user's observation

11. Q3 conclusion: only way blockOuter=4 for this shape is aicNum=4 at runtime (blockOuter = ceil(fusedOuter / ceil(fusedOuter/aicNum))). With aicNum=40 all paths yield ≥32 cores. Alternative BN-only partition (blockOuter=bn2g=4) is impossible here (isBn2=false for S=2048). So: runtime aicNum/compile config is the key unknown (PARTIAL). Also enableSwizzle requires blockOuter==aicNum (line 442), consistent with fewer active cores.

12. Q4: fusedOuter is NOT in tiling_data_regbase.h — it's a local host variable. The tiling structs use blockOuter (uint32_t, line 204), maxValidBBLen (uint32_t, line 205), blockStarts/blockEnds (int64_t36, lines 235-236). No fusedOuter field.

Also noted: CORE_LIST_NUM=36 (common_regbase.h:136) — blockStarts/blockEnds sized 36 while blockOuter can theoretically reach 40 (with aicNum=40, blockOuter up to 40 > 36 — potential overflow note, but practically aicNum seems ≤36 or this is a known quirk).

The task in the conversation was investigation only — the user asked "查清并回答" (investigate and answer) with file:line evidence, and explicitly said "不要写 answer.yaml，不要 finalize". The user also said "用 Cursor Explore 风格回答：完整散文 + file:line" — the final answer should be prose + file:line. So the next move is to produce the final prose answer with all the file:line evidence. The conversation shows the investigation is essentially complete; only the final prose write-up remains (which the assistant would compose as its next response). The summary should capture that as the next move.

Work State:
- Completed: full investigation — all queries done, all four questions answerable with file:line evidence.
- Active: none — the investigation is done; the final prose answer needs to be delivered.
- Blocked: uo-query --mode symbols is not a valid mode (valid modes listed); CalcTschBlockDim not in UO KB (framework code) — marked PARTIAL; runtime aicNum unknown (needs device/compile info) — PARTIAL. The search fused output was truncated to a cache file outside read scope but that was worked around with targeted queries.

Next Move: deliver the final Cursor-Explore-style prose answer (完整散文 + file:line) covering the 4 questions; explicitly mark PARTIAL for CalcTschBlockDim semantics and actual runtime aicNum; do NOT write answer.yaml, do NOT finalize.

Relevant Files:
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp (fusedOuter, block split, DoSparse dispatch, PostTiling, SetSplitAxis-related init, aicNum source)
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp (SetSplitAxis at 1581-1648, GetS1S2TemplateType at 812+)
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.h (constants: ALIGN128=128, BN2_MAX_S=128, BN2S2_MAX_S=1024, BN2_MULTIBLK_SEQ=640, BN2_MULTIBLK_BN128=128, BN2_MULTIBLK_BN256=256, BN2_MAX_D=512, BN2S2_WRITE_UB_D=128, CORE_LIST_NUM=36; blockStarts/blockEnds arrays at 433-434)
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_varlen_regbase.cpp (GetBlockInfoOfBNS4TND 1216, CaclePerCoreBlockInfo 1264-1312, IsPossible 1394-1412)
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_tiling_data_regbase.h (MAX_CORE_NUM=36 line 23, S1S2BNGS1S2SplitCoreParams 194-231, BlockNumListParamsRegbase 233-254)
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h (Process 497-511, early return 502-503)
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h (GetNextValidIdx 1367-1379+)
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\flash_attention_score_grad_tiling.cpp (Tiling entry 500-523)

Let me now write the summary in the required format. The conversation is in Chinese, so I should respond in Chinese per the rule "Respond in the same language as the conversation." The template headers are fixed English structure but content should be Chinese. The rules say keep the exact output structure requested — the template has English headers; I'll keep headers as-is and write content in Chinese (matching conversation language). Actually, the rule says "Respond in the same language as the conversation" — the conversation is Chinese. I'll write bullets in Chinese while keeping the Markdown headers as in the template.
Objective
- 查明 flash_attention_score_grad（arch35, digest 211a7ec…）host 侧分核策略与 fusedOuter 的定义/计算位置，解释 B=1、N=4、S=2048（FP16）下“只有 4 个 AIC 在干活、vector 打满”的原因，全部结论需带 file:line 证据；用户明确要求：不写 answer.yaml、不 finalize，最终以“完整散文 + file:line”的 Cursor Explore 风格作答。
Important Details
- 工具约束：只能用 uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...（locate/search/tiling_data 等）与对机器源码的 windowed Read；禁止 bash/Grep/MCP 替代。
- uo-query --mode symbols 非法，合法 mode 列表：search, constraints, neighbors, impact, field, branches, templates, tiling_key, tiling_data, kernel_branch, template_match, buffer, gaps, legal_key, locate, kernel_api, kernel_launch, compile。
- search --pattern fused 输出过大被截断到缓存文件（C:\Users\SunYe\.local\share\opencode\tool-output\tool_00b8c5e83001NOw5W5kNRaCC24），已改用更小粒度的定向查询绕开，不影响结论。
- CalcTschBlockDim 不在本算子 CodeMap 中（框架代码）→ 实际 launch blockDim 语义标 PARTIAL；实际运行时 aicNum 属设备/编译信息，静态无法确定 → PARTIAL。
- 关键常量（op_host/arch35/flash_attention_score_grad_tiling_common_regbase.h）：ALIGN128=128、BN2_MAX_S=128、BN2S2_MAX_S=1024、BN2_MULTIBLK_SEQ=640、BN2_MULTIBLK_BN128=128、BN2_MULTIBLK_BN256=256、BN2_MAX_D=512、BN2S2_WRITE_UB_D=128、CORE_LIST_NUM=36；tiling_data 头中 MAX_CORE_NUM=36。
- 计算示例（B=1、N=4、g=1、S=2048、d=128 FP16）：n2=4、n1=4（normal_regbase.cpp:369）；isBn2=false（S>128）；isBn2MultiBlk=false（b*n1=4<128）；bn2S2RouteLimit=true → splitAxis=BN2S2 且 layout 转 TND（isAllSame 时）；s1Inner=64、s2Inner=128 → s1Outer=16、s2Outer=16；dense fusedOuter=1411616=1024。
Work State
Completed
- fusedOuter 定位：纯 host 局部变量，共 5 处计算，均位于 op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp：DoBn2s2Sparse 第 523 行 b*n2*g*s2Outer；GetSparseBlockInfoBn2 第 557/564 行 b*n2*g 再 *= s1s2oCount；DoBn2MultiBlkSparse 第 632/636 行 b*n2*g 再 *= (s1Outer*s2Outer)；DoSparse dense 分支第 704 行 b*n2*g*s1Outer*s2Outer；GetSparseBlockInfo 第 1561 行 b*n2*g*s1s2oCount。
- fusedOuter 不是 TILING_FIELD：locate 结果 fused_outer_candidates_count: 0，17 处匹配全在 host .cpp；kernel 侧实际读取的是 blockOuter/maxValidBBLen/blockStarts/blockEnds。
- 通用分块公式（各路径一致）：blockFactor=(fusedOuter+aicNum-1)/aicNum；blockOuter=(fusedOuter+blockFactor-1)/blockFactor；blockStarts[i]=blockFactor*i、blockEnds[i]=min(blockFactor*(i+1),fusedOuter)；i>=blockOuter 的核取 [0,0)。证据：normal_regbase.cpp:558-560、633-636、704-706、1562-1563。
- aicNum 来源：normal_regbase.cpp:384-385 coreNum=compileInfoPtr->aivNum; aicNum=compileInfoPtr->aicNum;（无 platformInfo 时走 compileInfo），else 分支 392 行起走 PlatformAscendC；CORE_INIT_NUM=40（:375）。
- SetSplitAxis 决策链（common_regbase.cpp:1581-1648）：isBn2 条件 :1583-1588；bnLimit :1590-1591；isBn2MultiBlk :1596-1606；bn2S2NotTndLimit :1625-1630；bn2S2RouteLimit :1631-1639；最终 !isBn2 && bn2S2RouteLimit → splitAxis=BN2S2、isBn2 → BN2、否则 BN2GS1S2（:1641-1648）。
- DoSparse 主分发（normal_regbase.cpp:660-720）：if (DoBn2s2Sparse() && blockOuter >= aicNum) 才接受 BN2S2（:665）；否则 SupportTrans2BS2N2GD 后 splitAxis = isBn2 ? BN2 : BN2GS1S2（:691），再按 TND→GetSparseUnpadBlockInfo、PREFIX→GetSparsePrefixBlockInfo、isSparse→GetSparseBlockInfo、dense→内联公式（:704）。
- BN2S2-TND 负载均衡路径：GetBlockInfoOfBNS4TND（varlen_regbase.cpp:1216）→ FillBlockInfoLoadBalance（normal_regbase.cpp:1714-1738，权重=acturalS1Num/s1CvInner+acturalS2Num/cvS2Inner，:1733-1734）→ BinarySearchMaxBlockNumPerCore + IsPossible（needCoreNum > aicNum → false，varlen:1390-1391、1405-1406）→ CaclePerCoreBlockInfo 贪心装核，blockOuter=coreIdx+1（varlen:1264-1312）。
- Kernel 侧消费：kernel.h:502-503 if (blockEnds[cBlockIdx]==0) return;（空核直接退出）；:510-511 从 blockStartscBlockIdx 起迭代；kernel_base.h:1367+ GetNextValidIdx 到 blockEndscBlockIdx 终止。
- PostTiling/launch（normal_regbase.cpp:1483-1506）：deterministic/FP8 时 numBlocks=aicNum；否则 numBlocks=CalcTschBlockDim(blockOuter*2, aicNum, coreNum)（:1492-1493）→ SetBlockDim。
- 按公式推算各路径核数：dense BN2GS1S2（aicNum=40）：fusedOuter=1024 → blockFactor=26、blockOuter=40；BN2S2 负载均衡（dense）：64 列（b×n2g×s2Outer=1×4×16）每列权重 2 → 最小容量 4 → 约 32 核；causal GetSparseBlockInfo：s1s2oCount≈136 → blockOuter≈39。即 aicNum=40 时任何路径都 ≥32 核。
- “4 个 AIC”唯一合理解释：blockOuter=4 需 blockFactor=ceil(fusedOuter/aicNum)=256 → 即 aicNum=4 时 blockOuter=ceil(1024/256)=4，恰与观察一致；纯 BN 切分（blockOuter=bn2g=4）在此形状下不可能（isBn2=false）。故根因最可能是运行时 aicNum=4（编译/设备配置或受限环境），标 PARTIAL。
- 附加：enableSwizzle 需 blockOuter == aicNum（normal_regbase.cpp:442）；CORE_LIST_NUM=36 而 aicNum=40 时 blockOuter 理论上可达 40>36，存在数组写越界隐患（未验证，仅提示）。
Active
- 无——调查已完成，仅剩按用户要求输出最终散文式回答（完整散文 + file:line）。
Blocked
- CalcTschBlockDim 语义（框架代码，不在 UO KB）→ launch 核数上限的最终值 PARTIAL。
- 运行时实际 aicNum 无法静态确定（需设备/compileInfo 信息）→ “4 核”结论的最终确认依赖该项，PARTIAL。
Next Move
1. 输出最终 Cursor Explore 风格散文回答（中文、完整散文 + file:line），覆盖 4 问：① host 分核流程与 B=1/N=4/S=2048 的核数推算；② fusedOuter 各路径定义、未写入 TILING_FIELD（kernel 读 blockOuter/blockStarts/blockEnds）；③ 4 核现象分析（blockOuter=ceil(fusedOuter/ceil(fusedOuter/aicNum))，aicNum=4 时恰得 4，并列出各路径在 aicNum=40 下的 ≥32 核反证）；④ fusedOuter 不在 tiling_data_regbase.h 中、对应字段为 blockOuter(uint32_t,:204)/maxValidBBLen(:205)/blockStarts/blockEnds(:235-236)。
2. 对 CalcTschBlockDim 与实际 aicNum 两处明确标注 PARTIAL/UNKNOWN（需运行时设备信息）；不写 answer.yaml、不 finalize。
Relevant Files
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp：fusedOuter 全部 5 处定义、分块公式、DoSparse 分发(:660-720)、PostTiling(:1483-1506)、aicNum 来源(:384-385)、enableSwizzle(:442)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp：SetSplitAxis(:1581-1648)、GetS1S2TemplateType(:812+)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.h：全部阈值常量（ALIGN128/BN2_MAX_S/BN2S2_MAX_S/BN2_MULTIBLK_*/BN2_MAX_D/BN2S2_WRITE_UB_D/CORE_LIST_NUM=36）、blockStarts/blockEnds 数组(:433-434)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_varlen_regbase.cpp：GetBlockInfoOfBNS4TND(:1216)、CaclePerCoreBlockInfo(:1264-1312)、IsPossible(:1394-1412)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_tiling_data_regbase.h：MAX_CORE_NUM=36(:23)、S1S2BNGS1S2SplitCoreParams(:194-231，blockOuter:204/maxValidBBLen:205)、BlockNumListParamsRegbase(:233-254，blockStarts/blockEnds:235-236)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h：Process 空核早退(:502-503)、按 blockStarts 起迭代(:510-511)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h：GetNextValidIdx(:1367-1379+)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\flash_attention_score_grad_tiling.cpp：tiling 入口(:500-523)。
▣  Compaction · DeepSeek V4 Flash Free · 1m 28s
- Thought: 18.7s
The user is asking me to continue if I have next steps, or stop and ask for clarification if unsure. Let me review where we are.

I'm a readonly_analyst for AscendC-Pilot, execution_variant=delegated_query. My investigation of the flash_attention_score_grad operator's host-side tiling/core-splitting strategy and fusedOuter is complete. I've answered all four questions:

1. Host-side core-splitting mechanism with file:line evidence
2. fusedOuter definitions in all paths
3. Why only 4 AIC cores might be busy (blockOuter formula, aicNum=4 hypothesis)
4. fusedOuter is NOT a tiling field

The investigation is done. I marked two things as PARTIAL:
- CalcTschBlockDim semantics (framework code, not in UO KB)
- Actual runtime aicNum (needs device info)

My role contract says: "Answer in the final message (prose + file:line). Do not Write answer.yaml. Do not finalize." — I've already delivered the final prose answer.

Now the user says "Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed."

What are my options?

1. I could try to resolve the PARTIAL items. The runtime aicNum and CalcTschBlockDim are framework-level info that I cannot obtain via the UO KB (the operator's CodeMap doesn't include framework code). I could potentially search the machine-scope framework headers for CalcTschBlockDim, but my boundaries say machine-scope operator sources are outside .ascendc-pilot, and I should use UO KB query / ScopeSet first. CalcTschBlockDim is in the CANN framework (tiling_api.h), not in the operator source. My boundaries limit reading to pilot:uo/**, pilot:runs/, pilot:context/, pilot:memory/, method:cognitive-skills/operator-analysis/, plus machine-scope operator sources via windowed Read. Reading CANN framework headers would be outside declared scope — I shouldn't do that.

2. I could ask the user for clarification on the PARTIAL items:
   - What is the actual runtime aicNum (device core count)?
   - What layout (BSH vs TND), mask (dense vs causal), deterministic flag?
   - Which arch/version?

Actually, the user's original questions were the 4 investigation questions, which I answered. The remaining uncertainties (actual runtime aicNum, CalcTschBlockDim semantics) are genuinely outside what I can determine statically from the operator's own source. 

Per my runtime contract, I'm a delegated_query agent — I should answer in the final message and not finalize. The most appropriate action now: since the investigation is complete and I've delivered the answer, and the remaining unknowns require runtime/device information that the user must provide (or that needs a different tool than uo-query), I should stop and ask for clarification — specifically ask for the runtime aicNum value (or device type) so I can pin down Q3.

Actually, wait — let me think about whether there's anything more I can do with the uo-query tool. I could try:
- --mode compile to check compile info handling
- --mode kernel_launch to check launch config
- --mode tiling_data to double-check the tiling data struct

But I've already done extensive locate queries. The key PARTIAL items:
1. Actual runtime aicNum — requires device info, can't be determined from code. The user needs to provide it or run with logging.
2. CalcTschBlockDim semantics — framework function. I could try uo-query --mode locate --pattern CalcTschBlockDim — but I already noted it's not in the operator's CodeMap (I saw it referenced in normal_regbase.cpp:1492 but the UO KB is operator-scoped). Let me check if it exists in the KB... Actually I never explicitly queried it. I said "CalcTschBlockDim not in UO KB (framework code) — PARTIAL" based on my earlier work. Let me verify with one quick query to be thorough, since it's a small cost.

Actually, in my summary I noted CalcTschBlockDim isn't in the operator's CodeMap. But did I actually run that query in this conversation? Looking at the visible conversation, I don't see that query explicitly. My summary states it as a fact from prior work (the conversation I was asked to summarize). To be rigorous, I could run one quick locate query to confirm. That's within my remit and could add value.

Also I could check AICV_RATIO_DEFAULT — where is it defined? It's used at normal_regbase.cpp:1492. Let me check that too — if it's in the operator's headers, I can cite it.

Let me do a couple of targeted queries to tie up loose ends, then either continue with next steps or stop and ask for clarification.

Next steps I could take:
1. Verify CalcTschBlockDim absence in UO KB (quick locate).
2. Find AICV_RATIO_DEFAULT definition (quick locate).
3. Possibly query tiling.cpp TilingPrepare lines around 540-541 to confirm aicNum handling (I cited tiling.cpp:540-541).
4. Then ask user for the runtime aicNum / device info to finalize Q3.

Let me run these queries in parallel since they're independent.
I'll tie up the two PARTIAL loose ends with a few targeted queries before deciding
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern CalcTschBlockDim]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern AICV_RATIO_DEFAULT]
- Thought: 8.1s
Both queries confirm: CalcTschBlockDim and AICV_RATIO_DEFAULT are not in the operator's UO KB (they're framework/tiling_api symbols used in normal_regbase.cpp:1492). The hint says "Retry a shorter name" — but these are genuinely framework symbols. Let me try shorter patterns to be thorough: "CalcTsch", "AICV_RATIO". Actually, since they're used at normal_regbase.cpp:1492-1493, let me just check the context around that line with a windowed read of the machine source to confirm how they're used, plus check where AICV_RATIO_DEFAULT might be defined in operator headers (maybe common_regbase.h). Let me do a quick windowed read of normal_regbase.cpp around 1483-1506 and search common_regbase.h for AICV_RATIO.

Actually the values: AICV_RATIO_DEFAULT is likely defined in the operator headers. Let me grep via read tool on the machine-scope sources (allowed: machine-scope operator sources with windowed Read — but grep tool isn't listed in my tools... I only have acp and read. The instructions say "Machine-scope operator sources (op_host/, op_kernel/, …) are outside .ascendc-pilot. Locate with UO KB query / ScopeSet first, then machine-scope windowed Read — never whole-file dumps." I have the read tool which can read files; I can read common_regbase.h. But finding AICV_RATIO_DEFAULT would need searching; I can read the file in windows. common_regbase.h is large though. Let me just do targeted reads: normal_regbase.cpp around 1483-1506 to confirm exact usage, and check the tiling.cpp around 540-541 for aicNum. And maybe read common_regbase.h constants region (lines 60-150) where CORE_INIT_NUM etc. were.

Actually — I should be careful about scope. My job as delegated_query is complete: the answer was delivered. The remaining PARTIAL items are genuinely runtime/framework questions. The reasonable next step: confirm the two unresolved bits are truly out of KB scope (done: both empty), give the user the definitive "what to check at runtime" list, and ask for the one piece of data I need (actual aicNum / device core count, layout, mask, deterministic flag) to pin down Q3. That's the honest, boundary-respecting move.

But before stopping, one quick windowed read of normal_regbase.cpp:1483-1506 and common_regbase.h constants to confirm the exact lines I cited (since these are my evidence anchors), and maybe tiling.cpp:530-545 for aicNum. Let me do those reads in parallel.
Both framework symbols are confirmed absent from the operator's UO KB — as expected. Let me verify my cited evidence lines with windowed reads of the machine-scope sources (allowed: locate via UO KB first, then windowed Read
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [offset=1483, limit=30]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\flash_attention_score_grad_tiling.cpp [offset=525, limit=30]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.h [offset=60, limit=90]
- Thought: 7.8s
All evidence is now verified:
- PostTiling() at normal_regbase.cpp:1483-1507 confirms numBlocks logic and CalcTschBlockDim / AICV_RATIO_DEFAULT usage at :1492-1493. AICV_RATIO_DEFAULT = 2 is defined in common_regbase.h:104 (so it's in the operator, but CalcTschBlockDim is framework).
- TilingPrepare confirms aicNum = GetCoreNumAic() at tiling.cpp:540-541.
- Constants confirmed at common_regbase.h:72 (CORE_INIT_NUM=40), :104-106 (AICV/S1CV/S2CV ratios), :109-116 (ALIGN128/BN2_MAX_S/BN2S2_MAX_S/BN2_MULTIBLK_*/BN2_MAX_D/BN2S2_WRITE_UB_D), :136 (CORE_LIST_NUM=36), :137 (ARRAY_LENGTH=3).

So the only remaining PARTIAL item is the runtime aicNum value. CalcTschBlockDim is framework (confirmed not in UO KB; empty result with hint "Empty is not proof the symbol is absent" — but I've verified it's called from operator code, and it's a tiling_api.h framework function; the operator's own source doesn't define it — that's fine).

Now, per my contract: I'm a delegated_query readonly analyst. The investigation is complete; the final answer has been delivered. The remaining unknown is a runtime value (aicNum from device). I cannot determine that statically. The correct move per the user's instruction ("Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed") is:

- I've tied up the loose ends I could (verified CalcTschBlockDim absence in KB, confirmed AICV_RATIO_DEFAULT=2 in common_regbase.h:104, confirmed tiling.cpp aicNum source).
- The one genuinely blocking unknown is the actual runtime aicNum. I should stop and ask for clarification: what's the runtime aicNum / device core config? Or provide the exact runtime log line to check (tiling.cpp:550-554 logs aivNum/aicNum).

Actually wait — I should double check whether the kernel launch even respects blockOuter as "busy cores". Actually I've established that. Let me also verify one thing: with aicNum=40 and blockOuter=40, the blockStarts/blockEnds arrays are written for 40 entries but the host arrays are only CORE_LIST_NUM=36! That was a potential overflow note I made. Let me check that write site at normal_regbase.cpp:1907-1910 to verify whether there's a clamp. Actually let me quickly read that region to be precise — the array overflow claim is important (blockOuter=40 > 36 → writing blockStarts36..39 into fBaseParams.blockStarts36 would overflow into other fields... unless fBaseParams.blockStarts is declared bigger, or there's a clamp, or aicNum is always ≤36 in practice).

Let me check:
1. fBaseParams struct — where is blockStarts declared? I said common_regbase.h:433-434. Let me verify.
2. The write loop at 1898-1910.
Two facts to verify before I conclude — the blockStarts/blockEnds array sizes (I flagged a possible 40 > 36 overflow) and the exact write site
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=40, offset=1875]
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.h [limit=40, offset=410]
- Thought: 12.6s
Now I've verified all the key claims:

1. fBaseParams.blockStarts/blockEnds are declared as int64_t [CORE_LIST_NUM] (36) at common_regbase.h:433-434. So if blockOuter were 40 (which it can be when aicNum=40 and fusedOuter=1024), writing blockStarts[i] for i in 36..39 would overflow the arrays in the host struct! Wait — actually let me check the loop that fills them. In the dense branch at normal_regbase.cpp:712-718, they loop for (i = 0; i < blockOuter; i++) and write fBaseParams.blockStarts[i], fBaseParams.blockEnds[i]. If blockOuter=40 > 36, that's an out-of-bounds write into adjacent struct fields (sparseMode, prefixN, isAllSame, actualSeqQlen vector, ...). This is a real potential bug worth flagging — but wait, is it possible that aicNum is never > 36 in practice? The kernel tiling data MAX_CORE_NUM=36 and kernel arrays int64_t dqOffset[36] etc. also use 36. And PostTiling uses CalcTschBlockDim(blockOuter*2, aicNum, coreNum) to decide the launch blockDim. Hmm, so blockOuter can indeed reach 40 while arrays are 36. But actually — maybe the framework ensures blockOuter ≤ aicNum ≤ 36? No, the operator doesn't clamp aicNum. Actually, note that on many Ascend parts aicNum is 40 (Atlas 800T A2: 40 AIC? Actually A2 has 48 or 24...). The point: the operator assumes aicNum ≤ 36 effectively (or has a latent bug for larger aicNum). But for the user's question — observed only 4 AIC busy — the analysis stands.

Wait, but also let me reconsider: the user observed "only 4 AIC busy, vector ~100%". Another possible explanation I should double check: maybe the run is deterministic mode? In deterministic mode, numBlocks = aicNum (PostTiling :1490) — that doesn't reduce busy cores; blockOuter still governs. Or maybe the launch dim from CalcTschBlockDim(blockOuter*2, aicNum, coreNum) could be small? CalcTschBlockDim is a framework function (not in KB). Typically it's min(aicNum, max(requested, minimum))-ish. If it returns a small number like 4... no, that's unlikely to produce exactly 4.

Actually, let me reconsider the whole picture. If the user is running with aicNum=40 (typical), and only 4 AIC are busy — maybe the run is BSH dense with s1Outer*s2Outer... hmm, I calculated blockOuter=40 for aicNum=40. Unless... wait, did I miss a cap on blockOuter by aicNum? Let me re-check DoSparse dense branch and the blockOuter clamp. From my earlier reads: 704-706 fusedOuter/blockFactor/blockOuter. Let me actually look at 700-722 to double check whether there's a blockOuter = min(blockOuter, aicNum) or a reduction of blockFactor when blockOuter > CORE_LIST_NUM. Let me read that region to be precise. Also the kernel loop uses blockEnds[cBlockIdx] — and Process at kernel.h:497-511 — busy cores = number of cBlockIdx with blockEnds>0, i.e. blockOuter.

Actually, in the interest of being precise, let me read normal_regbase.cpp 660-730 to confirm the dense branch and any clamps. I already have substantial evidence, but this is a key detail for the "why 4" question. Let me read it.
One more precision pass — the exact dense fallthrough branch and any blockOuter clamp (this is the crux of the "why 4 cores" question
→Read D:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=75, offset=658]
- Thought: 24.3s
Very important finding at lines 702-719! The dense fallthrough branch uses local stack arrays blockStarts[CORE_LIST_NUM] and blockEnds[CORE_LIST_NUM] (line 702-703), NOT fBaseParams arrays directly. And critically:

- Loop at 712: for (int64_t i = 0; i < blockOuter; i++) — writes to local blockStarts[i]/blockEnds[i]. If blockOuter > CORE_LIST_NUM (36), this writes out of bounds of the local stack array! With aicNum=40, fusedOuter=1024: blockFactor=26, blockOuter=40 > 36 → stack buffer overflow at lines 713-714 for i=36..39!
- Line 716: for (uint32_t i = blockOuter; i < CORE_LIST_NUM; i++) — zero-fills the rest.
- Then copies into fBaseParams.blockStarts (line 721-722) which is also [CORE_LIST_NUM] = 36.

So with aicNum=40, the dense path (B=1,N=4,S=2048) computes blockOuter=40 but writes 40 entries into 36-sized arrays — a genuine stack overflow / OOB on host. But wait — would the kernel actually get 40 cores? The CalcTschBlockDim(blockOuter * 2, aicNum, coreNum) caps the launch dim. And set_blockStarts(fBaseParams.blockStarts) copies only 36 entries into tiling data (which is also MAX_CORE_NUM=36). So cores 36-39 in the kernel read garbage... actually the kernel only reads blockEnds[cBlockIdx] where cBlockIdx = GetBlockIdx() < numBlocks (launch dim). If launch dim ≤ 36, cores 0-35 are fine (with zero-filled tail for those ≥ blockOuter). Actually wait — the local arrays at 702-703 are 36 entries, and the loop at 712 writes indices 0..39 → OOB write of 4 entries past the stack array. That's undefined behavior on host (may corrupt the stack, could even crash). But the values for indices 0..35 are still correctly filled, then copied to fBaseParams (36 entries), then to tiling data (36 entries). So the tiling data is consistent for cores 0..35 — the OOB writes to stack (indices 36..39) are pure UB that happens not to corrupt the copied values in practice... but still a real bug flag worth mentioning. Hmm, actually — could the observed "only 4 cores" be explained by UB from the stack overflow? Unlikely to produce exactly 4; the tiling data still has 36 entries with blockOuter=40, and blockEnds0..35 are all non-zero (blockFactor=26), so all cores 0..35 would be busy. So that doesn't explain 4 cores.

So my conclusion stands: 4 busy cores ⇒ blockOuter=4 ⇒ blockFactor=256 ⇒ aicNum=4 (or the BN2S2 route was taken with blockOuter≥aicNum and load-balancing gave 4 cores — but for BSH dense, DoBn2s2Sparse only applies to BN2S2 splitAxis which requires bn2S2RouteLimit; for BSH with s1==s2, bn2S2NotTndLimit = s1<s2 = false, isAllSame=false, layoutType!=TND → bn2S2RouteLimit=false → splitAxis=BN2GS1S2. So no BN2S2 for this shape).

Wait — actually, I need to double check whether the user's shape could be TND. The user said B=1, N=4, S=2048, FP16 — didn't specify layout. If layout is TND with isAllSame, then bn2S2RouteLimit is true → splitAxis=BN2S2 → DoBn2s2Sparse() → TND path → GetBlockInfoOfBNS4TND load-balancing (varlen). In that path blockOuter is computed by binary search on per-core capacity with needCoreNum ≤ aicNum. If aicNum=40, it would try to pack into ~40 cores. Could it yield 4? BinarySearchMaxBlockNumPerCore finds the max blocks per core such that cores needed ≤ aicNum. For fusedOuter=1024 with aicNum=40, it would find per-core cap such that ceil(total/cap) ≤ 40 → cap ≥ 26 → blockOuter = ceil(1024/26) = 40 (approx, with load imbalance maybe 32-40). Not 4.

If aicNum=4: binary search would pack into 4 cores → blockOuter=4. Consistent again: aicNum=4.

So the conclusion is robust: the "4 AIC" observation implies runtime aicNum≈4 (or CalcTschBlockDim caps launch to 4... but busy cores = blockOuter regardless of launch dim, since kernel returns early for empty blocks; launch dim ≥ blockOuter presumably).

Actually one more possibility: if this ran on a device where GetCoreNumAic() returns 4 (e.g., some platforms report only 4 AIC cores, or the environment sets coreNum). That's a runtime/env matter — PARTIAL, requires user confirmation.

I now have complete evidence. Let me write the final consolidated answer in Cursor-Explore prose style with file:line. This is the continuation. I should not write answer.yaml, not finalize — I'm readonly_analyst; the instruction says "Answer in the final message (prose + file:line). Do not Write answer.yaml. Do not finalize."

Actually the previous message already gave a full answer. The user says "Continue if you have next steps, or stop and ask for clarification if you are unsure how to proceed." — So this is a continuation: I've now verified the remaining loose ends (CalcTschBlockDim absence from KB, AICV_RATIO_DEFAULT=2 in common_regbase.h:104, exact PostTiling lines, TilingPrepare aicNum, and the crucial dense-branch stack arrays + OOB issue). I should now deliver the final consolidated prose answer with file:line, and ask the one clarifying question (actual aicNum / device core count) needed to nail Q3 definitively.

Let me compose the final answer now — full prose, Cursor Explore style, covering all 4 questions with updated line numbers, plus the newly discovered OOB note, plus the clarification request for the runtime aicNum.
I've verified every remaining loose end. The picture is now complete — here is the consolidated final analysis.
最终结论：flash_attention_score_grad 分核机制与「只有 4 个 AIC 干活」的根因
1. Host 侧分核机制（B=1, N=4, S=2048, FP16 全链路）
aicNum 从哪来：TilingPrepareForFlashAttentionScoreGrad 里 compileInfoPtr->aicNum = ascendcPlatform.GetCoreNumAic()（op_host/flash_attention_score_grad_tiling.cpp:541）；运行时 fBaseParams.aicNum = compileInfoPtr->aicNum，coreNum = aivNum（normal_regbase.cpp:384-385，或 platformInfo 路径 :394-396）。算子里没有任何 min(aicNum, 36) 之类的截断。
切分轴决策（SetSplitAxis, common_regbase.cpp:1581-1648）：本 shape s1=s2=2048、n1=n2=4、d=128、FP16 → isBn2=false（S>BN2_MAX_S=128）；isBn2MultiBlk=false（b·n1=4 < BN2_MULTIBLK_BN_128=128）；BSH 下 isAllSame=false（仅在 TND 分支赋值，normal:244/278）→ bn2S2RouteLimit 的 layoutType==TND、(isAllSame && !isDeterministic)、bn2S2NotTndLimit(s1<s2) 三段全不成立（common:1631-1639）→ 最终 splitAxis = BN2GS1S2（common:1641-1648）。
外层分块：FP16 模板 (128,128)（common:830-845）→ s1Inner=64, s2Inner=128（normal:1474-1481）；s1CvRatio=2, s2CvRatio=1（common:105-106）→ s1Outer=ceil(2048/128)=16, s2Outer=16。
DoSparse 分派（normal:660-732）：BN2S2 优化因 splitAxis≠BN2S2 不满足 DoBn2s2Sparse()（:665 门槛 blockOuter >= aicNum 是它的接受条件）；BN2 multi-blk 分支不满足（:674）；splitAxis=BN2GS1S2（:691）；BSH 非稀疏 → dense 兜底分支（:701-723）：
- fusedOuter = b * n2 * g * s1Outer * s2Outer = 1*4*1*16*16 = 1024（:704）
- blockFactor = ceil(1024 / aicNum)（:705）；blockOuter = ceil(1024 / blockFactor)（:706）
- 逐核 blockStarts[i]=blockFactor*i; blockEnds[i]=min(blockFactor*(i+1), fusedOuter)（:712-714）；i ≥ blockOuter 的核区间填 [0,0)（:716-719）
关键数字：
- aicNum=40 → blockFactor=26 → blockOuter=40 → 40 个核各分 26 个基本块（vector 各约 26 块）
- aicNum=4 → blockFactor=256 → blockOuter=4 → 4 个核各分 256 个基本块（vector 串行 256 块，几乎打满）
- causal 稀疏路径同理：fusedOuter=b*n2*g*s1s2oCount≈544（normal:1561）→ aicNum=40 时 blockOuter≈39；aicNum=4 时 blockOuter≈4
2. fusedOuter 的定义与位置（4 处，全是 host 局部量）
位置	表达式
DoBn2s2Sparse（BSH dense）normal:523	b * n2 * g * s2Outer
GetSparseBlockInfoBn2 normal:557,564	b * n2 * g * s1s2oCount
DoBn2MultiBlkSparse normal:632,636	b * n2 * g * s1Outer * s2Outer
DoSparse dense 兜底 normal:704	b * n2 * g * s1Outer * s2Outer（本 case 走这条）
fusedOuter 不写进任何 TILING_FIELD（locate 的 fused_outer_candidates_count=0；tiling_data_regbase.h 无 fused 字段）。真正落盘的是 blockOuter(uint32_t) / maxValidBBLen(uint32_t)（tiling_data_regbase.h:204-205；写点 normal:1909-1910）与 blockStarts/blockEnds(int64_t[MAX_CORE_NUM=36])（tiling_data_regbase.h:235-236；写点 normal:1907-1908）。Kernel 端 cBlockIdx=GetBlockIdx()（kernel_base.h:186-201），blockEnds[cBlockIdx]==0 → return（kernel.h:502-503），从 blockStarts[cBlockIdx] 迭代到 blockEnds[cBlockIdx]（kernel.h:510-511；GetNextValidIdx 终止于 kernel_base.h:1388-1397）。干活的核数 = blockOuter，与启动 blockDim 无关。
3. 为什么只有 4 个 AIC 干活
公式 blockOuter = ceil(fusedOuter / ceil(fusedOuter / aicNum)) 是单调的：blockOuter=4 只可能在两种情况下出现：
1. 运行时 aicNum=4（blockFactor=256）——与「vector 打满」完全自洽：每核 256 个基本块在 V 管线上串行；
2. BN-only 切法（blockOuter=b·n2·g=4）——但本 shape isBn2=false、isBn2MultiBlk=false，不可能；
3. BN2S2 load-balance 二分压到 4 核——但 BSH 下 bn2S2RouteLimit=false，不可能（TND+isAllSame 才会走）。
而 aicNum=40 时所有路径都给出 ≥39 个核。所以观察到 4 核，几乎可以断定运行时 GetCoreNumAic() 返回的是 4（例如设备/环境把 AIC 核数报成 4，或受限运行配置）。这是运行时信息，静态代码无法定案（PARTIAL） —— 需要你确认实际环境的 aicNum。
4. fusedOuter 在 tiling 结构里的声明
没有声明。 FlashAttentionScoreGradS1S2BNGS1S2SplitCoreParamsRegbase 字段为 s1Outer(int64_t):196、s1Inner/s1CvInner/s1Tail/s1CvTail:197-200、s2Outer(int64_t):201、s2Inner/s2Tail:202-203、blockOuter(uint32_t):204、maxValidBBLen(uint32_t):205、bandIdx(int64_t):206；BlockNumListParamsRegbase 只有 blockStarts/blockEnds(int64_t[MAX_CORE_NUM]):235-236。fusedOuter 只在 host .cpp 里作为局部 int64 现算，varlen 路径用 calculatedBlockInfo[..][SUM_ALL] 充当同义量（varlen:962）。
5. 新发现的一个隐患（顺带提醒）
dense 兜底分支用的是局部栈数组 int64_t blockStarts[CORE_LIST_NUM]（normal:702-703，CORE_LIST_NUM=36），但写循环是 for (i=0; i<blockOuter; i++)（:712）。当 aicNum=40 且 fusedOuter=1024 时 blockOuter=40 > 36，会对栈数组越界写 4 个元素（UB）；随后 std::copy 只拷 36 个进 fBaseParams（:721-722），再拷 36 个进 tiling 数据。tiling 数据本身对核 0-35 仍是自洽的（每核 26 块），所以这不解释 4 核现象，但 aicNum=40 的大 dense 场景存在真实越界风险，值得单独修（应 clamp blockOuter 或把数组扩到 ≥aicNum）。
待确认的最后一环（需要你提供）
要 100% 定案 Q3，请提供任一：
1. 运行日志里 TilingPrepare 打印的 aivNum/aicNum（op_host/flash_attention_score_grad_tiling.cpp:550-554 有 OP_LOGI 输出）；
2. 或实际设备型号/核数（GetCoreNumAic() 返回值）；
3. 或该次运行是否确定性模式（PostTiling 里 deterministic/FP8 直接 numBlocks=aicNum，normal:1487-1490，不影响 blockOuter 但影响启动核数）。
拿到 aicNum 我就能把结论从「几乎必然」钉死为「确定」。在那之前：结论 = 分核轴没选错，是运行时 aicNum 太小导致 blockOuter=4；vector 打满是核少、每核串行块多（256 块）的直接后果，不是 kernel 内计算慢。
（未写 answer.yaml，未 finalize。）
▣  Uo-Query · DeepSeek V4 Flash Free · 1m 59s
Subagent(8 of 9)43.6K (22%)


# subagent 9
算子目录：d:\TEST\ops-transformer\attention\flash_attention_score_grad（arch35，.uo CodeMap 已建好，digest 211a7ec…）。

立即调用 acp 工具：command=`uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...`（按需选 locate/symbols/callers/fields 等）。禁止 bash、Grep、MCP 替代。

背景：用户跑 B=1、N=4、S=2048 的 flash_attention_score_grad（FP16，arch35），只有 4 个 AIC 干活、vector 几乎打满。要查 fusedOuter 在 kernel 侧三条路径（BN2GS1S2 / BN2 / BN2S2）的消费差异，以及核内 VF（vector）负载。

请查清并回答（全部带 file:line 证据）：
1. fusedOuter 在 kernel 侧的消费：搜 kernel（op_kernel/arch35/）里读 fusedOuter（或 fusedOuter 相关字段）的位置——`FagConstInfo`/SetConstInfo（kernel_base.h:492-700）、block_vec.h / block_cube.h / kernel.h 的循环里怎么用，它控制哪个循环的外层迭代（fused 的哪几个维度：b*n1*g*s1Outer*s2Outer？）。
2. 三条路径的 outer 循环结构差异：BN2GS1S2（kernel.h ProcessBn2gs1s2LastVec/ComputeDqkvBn2gs1s2）、BN2（ComputeDqkvBn2）、BN2S2（ComputeDqkvBn2s2）各自的 outer 迭代变量怎么构成、fusedOuter 在每条路径里分别「乘了什么」（即 fused 的维度组合是否不同）。
3. 核内 VF 负载：vector 侧（block_vec.h 的 ProcessVec1-4、softmax grad、cast、dropout）每轮循环的处理量；FP16、S=2048、D=80 场景 vector 每核要算多少；是否明显重于 cube（matmul）。有没有证据表明 VF 是主循环瓶颈（如 vector 循环在 inner 层、量级大）。
4. 结论：fusedOuter 在三条路径里分别乘了什么（用公式），以及「4 AIC 干活 + VF 打满」更可能是分核轴（outer 只切了 N=4 个核、每核内 S 循环巨大）还是核内 VF 本身重。

用 Cursor Explore 风格回答：完整散文 + file:line。静态无法确定处标 PARTIAL/UNKNOWN。不要写 answer.yaml，不要 finalize。
- Thought: 7.5s
Let me start by querying the UO KB for this operator. The task says to use the uo-query command via the acp tool, with --project d:\TEST\ops-transformer\attention\flash_attention_score_grad.

Let me first explore the structure with locate/symbols modes.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern fusedOuter]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode symbols --pattern fusedOuter]
- Thought: 53ms
The locate mode worked. The symbols mode isn't a valid choice. Let me use the valid modes. Let me search for kernel-side consumption of fusedOuter / FagConstInfo / SetConstInfo, and the three paths: BN2GS1S2, BN2, BN2S2.

Let me do several queries in parallel:
1. locate pattern FagConstInfo
2. locate pattern SetConstInfo
3. locate pattern ProcessBn2gs1s2LastVec / ComputeDqkvBn2gs1s2
4. locate pattern ComputeDqkvBn2
5. locate pattern ComputeDqkvBn2s2
symbols 不是合法 mode；locate 已返回 host 侧 17 处。继续查 kernel 侧消费与
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern FagConstInfo]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern SetConstInfo]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ProcessBn2gs1s2LastVec]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ComputeDqkvBn2gs1s2]
- Thought: 2.8s
Good progress. Now I need:
1. ComputeDqkvBn2 and ComputeDqkvBn2s2 full bodies — I saw ComputeDqkvBn2s2 begins at kernel.h:182. Need ComputeDqkvBn2.
2. The outer loop structure: ProcessBn2gs1s2, ProcessBn2, ProcessBn2s2 loops in kernel.h — what outer iteration variables (blockIdx, etc.).
3. block_vec.h ProcessVec1-4, softmax grad etc.
4. How fusedOuter is consumed in kernel side — search for "fused" or "blockFactor"/"blockOuter" usage in kernel files, plus FagRunInfo / RunInfo fields.

Let me query more:
- locate ComputeDqkvBn2
- locate ProcessBn2
- locate ProcessBn2s2
- locate ProcessVec1..4 / ProcessVec in block_vec.h
继续查 ComputeDqkvBn2、三条路径的外层循环函数与 block_vec 的 Process
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ComputeDqkvBn2]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ProcessBn2gs1s2]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ProcessVec2]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern blockFactor]
- Thought: 17.9s
Now I have the key method definitions. I need to look at the actual outer loop structure — the main loops that iterate over blocks (blockIdx), i.e., Process / ProcessBn2gs1s2 / ProcessBn2s2 loops in kernel.h, and how they compute b/n2/g/s1o/s2o indices from blockIdx / blockStarts / blockEnds. Also I need to check whether "fusedOuter" concept appears on kernel side — likely as constInfo.blockOuter/blockFactor or via s1s2BNGS1S2SplitCoreParams... Actually, on the kernel side the relevant fields are blockStarts/blockEnds in the tiling data, and the loops iterate over taskId/blockIdx range.

The user asks specifically about "fusedOuter" consumption in the kernel side. In the host, fusedOuter = bn2g (* s1s2oCount or * s1Outer*s2Outer depending on path). On the kernel side, the loop structure is in kernel.h. Let me find the main Process functions:
- ProcessBn2gs1s2 (kernel.h)
- ProcessBn2 (kernel.h)
- ProcessBn2s2 (kernel.h)

Let me query locate for "ProcessBn2s2", "ProcessBn2\b", and also look for kernel loop functions using "blockStarts", "blockIdx". Also I should look at FagRunInfo to see how outer indices (bIdx, n2Idx, gIdx, s1oIdx, s2oIdx) are computed in the loop.

The locate mode gives snippets. I should read the actual files from the machine scope — the boundaries say "Machine-scope operator sources (op_host/, op_kernel/, …) are outside .ascendc-pilot. Locate with UO KB query / ScopeSet first, then machine-scope windowed Read". So I can use the read tool with windowed offsets on the actual operator files at d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\...

Let me get the file paths from UO query first. The UO KB gives relative paths op_kernel/arch35/... The absolute path should be d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h etc.

Let me first do a couple more UO queries to locate the loop bodies (ProcessBn2s2, Process / loop), then read windows of kernel.h.

Actually let me be efficient: read kernel.h fully (or at least the relevant sections). Let me check its size first — read with limit. I'll read in windows: kernel.h from line 1 to ~700 maybe. Let me first query locate for "ProcessBn2s2" and "Process" to find loop functions, and also check tiling_data for blockStarts/blockEnds usage in kernel.

Also need block_vec.h ProcessVec1/3/4 and vector_api files (softmax grad etc.) for VF load evidence. And kernel_base.h SetConstInfo lines 492-700 (user mentioned 492-700; we saw SetConstInfo at 488-...). 

Plan:
1. uo-query locate ProcessBn2s2, locate ProcessBn2\b variants, locate blockStarts in kernel side (tiling data or kernel_base).
2. Read kernel.h relevant windows (lines ~1-900).
3. Read block_vec.h windows (ProcessVec1-4).
4. Read kernel_base.h SetConstInfo window (488-700).
5. Read vector_api pse_atten_mask_muls_simple_softmax.h for softmax / reduce load sizes (VECTOR_BASEM/VECTOR_BASEN).
6. Read FagRunInfo definition (common.h) to see outer index fields.

Let me run the queries and reads in parallel where independent.
拿到三条路径入口。现在定位 kernel 侧主循环（Process/外层迭代）与 RunInfo 索引构成，并直接窗口读 kernel.h / block_vec.h / kernel
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern ProcessBn2s2]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern blockStarts]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern s1s2BNGS1S2SplitCoreParams]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern FagRunInfo]
- Thought: 5.8s
Now I need to read the kernel.h main loop functions: Process (line 493), ProcessPreloadTwoTimes (line 589), and the ComputeDqkvBn2gs1s2 / ComputeDqkvBn2s2 / ComputeDqkvBn2 full bodies. Let me read kernel.h from the beginning to get the whole picture. The file is in the machine scope; I'll read a windowed portion: first ~40 lines to see class header, then lines 42-900 to see the process functions. Let me read in windows.

Also read block_vec.h ProcessVec1-4 (need ProcessVec1, ProcessVec3, ProcessVec4 — ProcessVec2 at 458). And vector_api files for softmax grad. And kernel_base.h SetConstInfo 488-700.

Let me find absolute paths:
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h
- ...\op_kernel\arch35\flash_attention_score_grad_block_vec.h
- ...\op_kernel\arch35\flash_attention_score_grad_kernel_base.h
- ...\op_kernel\arch35\flash_attention_score_grad_common.h
- ...\op_kernel\arch35\vector_api\pse_atten_mask_muls_simple_softmax.h

Let me read kernel.h first (whole file likely < 2000 lines). I'll read with limit 2000.
现在直接窗口读 kernel 源码：先读 kernel.h 主循环全文
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h [limit=700]
- Thought: 41.9s
Now I have kernel.h main loops. Key observations:

- Process() (kernel.h:496-590) — the main loop. Iteration over blockInnerIdx via GetNextValidIdx starting from blockStarts[cBlockIdx], bounded by blockEnds[cBlockIdx]. Each iteration:
  - ProcessVec1 (softmaxGrad) — kernel.h:522
  - GetNextValidIdx / SetRunInfo (kernel.h:527-530)
  - IterateMmQK (mm2, c2) — kernel.h:557
  - IterateMmDyV (mm1, c1) — kernel.h:565
  - CopyMaxSum — kernel.h:571
  - ComputeDqkvBn2gs1s2 (SPLIT_AXIS == BN2GS1S2) — kernel.h:576
  - ComputeDqkvBn2s2 (SPLIT_AXIS == BN2S2) — kernel.h:578
  - ComputeDqkvBn2 (else / BN2) — kernel.h:580

So the outer loop is per block (blockInnerIdx), and blockStarts/blockEnds per core decide the range. In host side, for BN2: blockStarts are over fusedOuter = bn2g (GetSparseBlockInfoBn2) or bn2gs1Outers2Outer (DoBn2MultiBlkSparse non-sparse path), or bn2gs2Outers1Outer (BN2S2: 523-527). For BN2GS1S2: the host path with s1s2BNGS1S2SplitCoreParams — the block split... I need to check the host's BN2GS1S2 split function (GetS1S2BlockInfo / split) to see what the fused outer is for BN2GS1S2.

The user's question focuses on the "fusedOuter" per path — "fusedOuter 在每条路径里分别乘了什么（即 fused 的维度组合是否不同）". From the host locate output we have:

1. BN2S2 path (GetS1S2BlockInfo? line 523): fusedOuter = b * n2 * g * s2Outer (line 523) then blockFactor = ceil(fusedOuter/aicNum), blockOuter = ceil(fusedOuter/blockFactor), totalBlock = fusedOuter * s1Outer (line 526), blockFactor = bns2Factor * s1Outer (line 527). So BN2S2 splits on bn2gs2Outers1Outer with s1Outer innermost within a block.

Wait — actually for BN2S2, fusedOuter = bn2gs2Outer, and totalBlock = fusedOuters1Outer. So block index enumerates bn2gs2Outers1Outer in the order (b,n2,g,s2o,s1o)? blockEnds = min(blockFactor*(i+1), totalBlock) where blockFactor = bns2Factors1Outer. Hmm, so each core gets a contiguous range of (bngs2o)s1o blocks. So fused dimension combination = bn2gs2Outers1Outer — i.e. outer fused = bn2g*s2Outer, with s1Outer blocked contiguously.

Wait but the question says BN2S2 — S2 outer fused? Let me check more carefully: line 523 int64_t fusedOuter = fBaseParams.b * fBaseParams.n2 * fBaseParams.g * fBaseParams.s2Outer; — this is in some function at line ~510-547. Need to check function name. The UO locate output earlier had "HOSTDEF::...::524::bns2Factor::0" in GetS1S2...? Actually the snippet at 521-547 shows a function whose name we don't know yet. Let me query the function name around line 500-550 of the host file. And lines 622-658 is DoBn2MultiBlkSparse: fusedOuter = b*n2g, then blockFactor = s1Outers2Outer; fusedOuter = s1Outers2Outer. So BN2 multiblk: fused = bn2g then per-block contiguous s1Outers2Outer.

2. BN2 sparse path (GetSparseBlockInfoBn2, line 549-620): fusedOuter = b*n2g (line 557), then fusedOuter = s1s2oCount (line 564) where s1s2oCount is parseInfos2Outer-1 — the count of valid (s1o,s2o) pairs (sparse). blockStarts computed via index decode: currentIdx / n2gs1s2o → b, n2, g, then GetCommonS1S2OuterIndex for s1o,s2o. blockStartsc = (((bn2+n2)g+gIdx)s2Outer+s2oIdx)s1Outer+s1oIdx+1 (line 604-606). So the index order is b, n2, g, s2o, s1o — meaning s1o is innermost, s2o next, then g, n2, b. Fused = bn2gvalid(s1o,s2o) pairs. Hmm wait: line 586 blockEndsblockOuter-1 = bn2gs1Outers2Outer — the max total index in the block list = full product (not just valid count), because blockStarts are computed with full s1Outers2Outer stride.

3. BN2GS1S2 path: that's the main s1s2 BNGS1S2 tiling with SplitCoreParams. In host, there must be a different split function for the BN2GS1S2 template — maybe DoBn2gs1s2MultiBlk / GetS1S2BlockInfo... Let me search host for "s1s2BNGS1S2SplitCoreParams" writes — i.e., how blockStarts/blockEnds are set for the BN2GS1S2 template. The kernel reads s1s2BNGS1S2BlockNumList.blockStarts/blockEnds (kernel.h:502, 511, 595, 604). Host writes at line 1907: fBaseParams.blockStarts → s1s2BNGS1S2BlockNumList. Need to see the function around line 1907 and the split that fills blockStarts for BN2GS1S2 — likely a function computing split over bn2gs1Outers2Outer with some fused combination.

Also key: the user says "4 AIC 干活" — with B=1, N=4, S=2048, D=80. If the split is over BN (bn2g=4), then aicNum=... arch35 has many AICs (like 40+?). If fusedOuter = 4 and blockFactor = ceil(4/aicNum)=1, blockOuter = 4 → only 4 cores get non-empty blocks (blockStarts0..3 non-empty, others 0). That matches "只有 4 个 AIC 干活"! And each core then loops over ALL S (s1Outers2Outer) blocks inside: for BN2 multiblk, blockFactor = s1Outers2Outer... wait no: in DoBn2MultiBlkSparse, blockFactor = ceil(4/aicNum)=1, then blockFactor = s1Outers2Outer — so each block covers 1 BN unit * full s1s2. blockOuter=4, each core gets blockFactor=1s1Outers2Outer blocks. So each core loops s1Outers2Outer iterations internally — the S loop is inside each core. That means "4 AIC 干活 + VF 打满" is because the split axis is BN (4 heads, N=4), giving only 4 blocks → 4 AICs; each AIC then does the entire S=2048 loop (s1Outers2Outer iterations), and within each iteration the vector work (softmaxGrad + V2 + V3 + V4 + muls/cast) is heavy.

Now, for BN2GS1S2 path — the kernel SPLIT_AXIS == BN2GS1S2 template. Need host function that fills blockStarts for that. Let me look at host lines ~1800-1950 and the split functions. Also need to check which template gets selected for B=1,N=4,S=2048,FP16,D=80. The tiling decides SPLIT_AXIS. The kernel template is chosen by tiling data (e.g., get split axis). The user says "fusedOuter 在 kernel 侧三条路径（BN2GS1S2 / BN2 / BN2S2）的消费差异". 

Let me now:
1. Read host file around lines 480-720 (GetS1S2? / DoBn2s2Sparse / DoSparse) and around 1850-1960 (blockStarts write for BN2GS1S2).
2. Read kernel.h remainder (701-757).
3. Read GetNextValidIdx / SetRunInfo in kernel_base.h (to see how blockInnerIdx maps to b/n2/g/s1o/s2o indices — this is where "fusedOuter 乘了什么" shows on kernel side).
4. Read block_vec.h ProcessVec1/3/4 and CopyMaxSum.
5. Read vector_api pse_atten_mask_muls_simple_softmax.h for VECTOR_BASEM/BASEN and loop structure.
6. Read SetConstInfo kernel_base.h 488-700 (the part after 528 we haven't seen: lines 529-700).

Let me do host reads and kernel_base reads in parallel. First find the host function names: query locate for "GetBlockInfoOfTNDForBn2", "DoBn2s2Sparse", "GetS1S2", "SplitCoreParams" writes. Actually let me just read host file windows directly — windowed read is allowed after UO locate. I'll read host 480-720 and 1800-1960.

Also need to check kernel_base.h GetNextValidIdx/SetRunInfo — locate first, then read.
kernel.h 主循环已明。现在读 host 分核函数（BN2S2/BN2/BN2GS1S2 三条 split）、kernel_base 的 GetNextValidIdx/SetRunInfo/SetConstInfo，以及 kernel.h
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h [offset=700, limit=60]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GetNextValidIdx]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern SetRunInfo]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [offset=430, limit=180]
- Thought: 9.4s
Now I have host-side picture for BN2S2 (DoBn2s2Sparse line 511-547: fusedOuter = b*n2gs2Outer, totalBlock = fusedOuters1Outer → per-core contiguous runs over (b,n2,g,s2o,s1o)) and BN2 sparse (GetSparseBlockInfoBn2: fusedOuter = bn2gs1s2oCount (valid pairs), block index decode order b,n2,g, then s2o,s1o).

Now I need the BN2GS1S2 host split — that's likely in a different place: when splitAxis == BN2GS1S2, the block split is probably in DoSparse → DoBn2gs1s2Sparse or a "GetBlockInfoOfBNS4TND" / "GetS1S2BlockInfo..." Also possibly the "main" s1s2 tiling splits with blockOuter == aicNum (the DoSplit → ... ). Let me continue reading host 610-760 (DoSparse) to see the BN2GS1S2 branch, and also check around lines 1800-1949 for InitTilingData writing s1s2BNGS1S2SplitCoreParams / BlockNumList.

Also need to look at kernel_base.h SetConstInfo 488-700 (rest after 528), SetRunInfo full body (831-1000?), GetNextValidIdxForSwizzle, and IsValid — to see how index → (b,n2,g,s1o,s2o) mapping works on the kernel side. Let me read kernel_base.h windows: 480-720 (SetConstInfo), 740-1100 (IsValid/SetRunInfo), 1360-1560 (GetNextValidIdx + swizzle).

Also block_vec.h ProcessVec1/3/4 + CopyMaxSum — need to read. And vector_api pse_atten_mask_muls_simple_softmax.h for the softmax loops. And check VECTOR_BASEM/VECTOR_BASEN definitions (common.h?) to compute per-loop vector load for S=2048, D=80, FP16.

Let me do host read 610-760 + 1800-1949 and kernel_base reads in parallel.
Host BN2S2/BN2 分核已明。继续读 host DoSparse 的 BN2GS1S2 分支与 InitTilingData 写 blockStarts，以及 kernel_base 的 SetConstInfo/SetRunInfo/Is
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=160, offset=610]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=220, offset=488]
- Thought: 20.6s
Now I have:
- Host DoSparse: for non-sparse non-TND with splitAxis == BN2GS1S2 (the fallback after BN2 failed, line 691-723): fusedOuter = b * n2 * g * s1Outer * s2Outer (line 704) — the FULL product. So BN2GS1S2 fused outer = b*n2gs1Outers2Outer (all five dims!), and blockStartsi = blockFactori contiguous.

Note the kernel-side SetRunInfo computes indices from index (blockInnerIdx) — need to see how index decomposes into (bIdx, n2Idx, gIdx, s1oIdx, s2oIdx). It's in SetRunInfo body — the part I saw only covers TND swizzle branch at the beginning (lines 838-870). Need the rest — the non-TND branch — lines ~870-1050. Let me read kernel_base.h 831-1100.

Also SetConstInfo confirmed kernel-side fields: n2GS1oS2o = n2G * s1Outer * s2Outer (line 563), gS1oS2o = g * s1Outer * s2Outer (564), s1oS2o = s1Outer * s2Outer (565). These are used in index decomposition. Also constInfo.aicCoreNum = coreNum >> 1 (line 685) — AIC count is half of coreNum.

Now the key remaining pieces:
1. SetRunInfo full body — how blockInnerIdx decomposes into b/n2/g/s1o/s2o (kernel_base.h ~831-1100).
2. IsValid — validation per (s1oIdx, s2oIdx) sparse check (kernel_base.h ~770-831).
3. block_vec.h ProcessVec1 (softmaxGrad), ProcessVec3, ProcessVec4, CopyMaxSum — vector work per iteration.
4. vector_api/pse_atten_mask_muls_simple_softmax.h — the softmax/v2 work sizes (VECTOR_BASEM/BASEN, sfmg loops).
5. DetermineMode / which template is selected for the user's case: B=1 N=4 S=2048 D=80 FP16. The SPLIT_AXIS is a template parameter chosen at kernel launch. Which one? The user's report says "4 AIC 干活" — consistent with blockOuter=4 when fusedOuter=4 (bn2g = 141). For BN2GS1S2 non-sparse, fusedOuter = 141s1Outers2Outer. With S=2048, D=80: s1Inner/s2Inner from FuzzyForBestSplit. Hmm, for the split to yield exactly 4 AICs in BN2GS1S2 path, we'd need blockOuter=4, i.e., blockFactor = fusedOuter/4. But blockFactor = ceil(fusedOuter/aicNum) — with aicNum large (e.g., 40), blockFactor would be small, giving many blocks. Actually "4 AIC 干活" fits BN2 path (fusedOuter = bn2g = 4, blockFactor = ceil(4/aicNum) = 1 → blockOuter = 4 → cores 0-3 get blocks, cores 4+ get empty (blockEnds=0)). For BN2GS1S2 path, fusedOuter = 4s1Outers2Outer — if that's >= aicNum, blockOuter would be > 4. So the "4 AIC" symptom strongly suggests the BN2 split (isBn2MultiBlk) was chosen: fusedOuter = bn2g = 4 → 4 non-empty cores. But wait — the user asks specifically about three paths and wants me to determine. Let me check DetermineMode and SetSplitAxis to see when BN2 is chosen vs BN2GS1S2.

Also need to check host functions around line 1500-1620 (GetSparsePrefixBlockInfo / GetSparseBlockInfo uses fusedOuter? No — 1561-1564 shows fusedOuter = b*n2gs1s2oCount for TND? line 1561: fusedOuter = fBaseParams.b * fBaseParams.n2 * fBaseParams.g * s1s2oCount). And 1549-1600 is GetBlockInfoOfTNDForBn2 probably. That's TND BN2 sparse.

Priority: read kernel_base.h SetRunInfo body (831-1120) and IsValid (around 750-830). Then block_vec.h ProcessVec1/3/4 + CopyMaxSum, and vector_api softmax file. Then host SetSplitAxis / DetermineMode / FuzzyForBestSplit to confirm the chosen path for B=1,N=4,S=2048.

Let me read kernel_base.h 708-1130.
SetConstInfo 已读（含 kernel 侧轴乘积 n2GS1oS2o/gS1oS2o/s1oS2o）。继续读 SetRunInfo 全文与 IsValid——blockInnerIdx 如何拆成 b/n2/g/s1
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=330, offset=740]
- Thought: 19.8s
Excellent! This is the crucial part. SetRunInfo (kernel_base.h:835-1048):

Non-TND, non-TND-swizzle branch (line 1007-1048):
- For IS_DETER_NEW only: decomposes index into boIdx/n2oIdx/goIdx/s2oIdx/s1oIdx using n2GS1oS2o = n2G * s1Outer * s2Outer (line 1009-1016): 
  - boIdx = index / n2GS1oS2o
  - n2oIdx = (index % n2GS1oS2o) / gS1oS2o
  - goIdx = (index % gS1oS2o) / s1oS2o
  - s2oIdx = (index % s1oS2o) / s1Outer
  - s1oIdx = index % s1Outer

Wait — this decomposition only happens under if constexpr (IS_DETER_NEW(DETER_SPARSE_TYPE)). For non-deterministic paths (the user's FP16 case — assume non-deterministic), where does the decomposition happen? Note that GetNextValidIdx → IsValid → CheckIsValidBlock — CheckIsValidBlock decomposes baseIdx at kernel_base.h:780-783:
- bDimTail = baseIdx % n2GS1oS2o
- n2DimTail = bDimTail % gS1oS2o
- SetAxisRunInfo(runInfo, ..., baseIdx / n2GS1oS2o (bIdx), bDimTail / gS1oS2o (n2Idx), n2DimTail / s1oS2o (gIdx), s1oDimIdx, s2oDimIdx)

So in the NON-deterministic path, the index → (b, n2, g) decomposition happens inside CheckIsValidBlock (via SetAxisRunInfo), while s1oDimIdx and s2oDimIdx are passed separately (the swizzle iterates over s1o/s2o). Hmm — but wait, for non-sparse (DENSE), what does the outer iteration look like? GetNextValidIdx non-swizzle path: loops blockInnerIdx from blockStartscBlockIdx to blockEndscBlockIdx, calls IsValid(runInfo, taskId, nextValidBlockInnerIdx) to skip invalid (s1o,s2o) blocks. But for DENSE non-sparse, all blocks valid? Let me look at IsValid — around kernel_base.h 700-740. Let me read that part (kernel_base.h 700-743).

Also need to see SetAxisRunInfo — where bIdx/n2Idx/gIdx/s1oIdx/s2oIdx are set into runInfo.commonRunInfo (queryOffset, keyOffset etc.). That's the mapping "fusedOuter 乘了什么" on kernel side: bIdx = index / n2GS1oS2o — meaning index enumerates b first, then n2, then g, then s1o*s2o (or s2o then s1o). SetAxisRunInfo probably sets offsets.

Also key: CheckIsValidBlock computes s2oDimIdx separately, suggesting the index passed to IsValid covers (b, n2, g, s2o?, s1o?) — for non-swizzle dense path, IsValid probably derives s1oIdx/s2oIdx from the index. Let me read IsValid and the loop for swizzle too (GetNextValidIdxForSwizzle) — which iterates curLoopIdx differently.

Let me also note: SetRunInfo non-TND non-deter branch does NOT decompose index in SetRunInfo itself — it assumes the indices were already set by IsValid/CheckIsValidBlock during GetNextValidIdx (the same runInfo object is passed to both GetNextValidIdx and SetRunInfo). CheckIsValidBlock sets them via SetAxisRunInfo.

For the DENSE non-sparse case: is there still an IsValid call? GetNextValidIdx non-swizzle: while (!IsValid(...)) — for dense, IsValid returns true for all (no sparse skip). Need to see IsValid to confirm dense → always valid → so blockInnerIdx runs from blockStarts to blockEnds-1.

Now for the question "fusedOuter 在 kernel 侧三条路径分别乘了什么": on the kernel side there's no variable named fusedOuter; the fused product is materialized as blockStarts/blockEnds ranges (host-side) and the index decomposition constants n2GS1oS2o / gS1oS2o / s1oS2o (kernel_base.h:563-565). The "multiplication" is exactly:
- BN2GS1S2 (dense fallback, host DoSparse line 704): fusedOuter = bn2gs1Outers2Outer; blockStarts/blockEnds split that product over cores. Index order: b (outer), n2, g, s2o, s1o (s1o innermost per CheckIsValidBlock: s1oDimIdx = index % s1Outer presumably). Wait — CheckIsValidBlock receives s1oDimIdx and s2oDimIdx as parameters — where are they computed from baseIdx? Need to see IsValid. Let me read kernel_base.h 700-743 (IsValid) and 1070-1364 (SetAxisRunInfo, GetNextValidIdxForSwizzle, IsValid helpers).

Actually, wait — the important nuance for the three paths:

1. BN2GS1S2: host DoSparse line 702-723 (dense) — fusedOuter = bn2gs1Outers2Outer. BUT there's ALSO the s1s2 BNGS1S2 split core params and possibly a different split when isSplitByBlockIdx (swizzle). Let me check host functions GetBlockInfo... Actually DoSparse line 691 sets splitAxis = BN2GS1S2 (after BN2 multiblk fails), then the else branch (line 701-723) sets blockStarts/blockEnds with fusedOuter = bn2gs1Outers2Outer. And with enableSwizzle (line 442: isExceedL2Cache && blockOuter == aicNum), SetSwizzleConstInfo and GetNextValidIdxForSwizzle handle the s1o/s2o iteration differently — via GetS1S2SwizzleInfo perhaps. Hmm, need to check what happens in kernel when IS_NORMAL_SWIZZLE && isSplitByBlockIdx — GetNextValidIdxForSwizzle. Let me read that (kernel_base.h ~1364-1531).

2. BN2 (DoBn2MultiBlkSparse dense path line 628-655): fusedOuter = bn2g, blockFactor = s1Outers2Outer → block i covers [blockFactori, blockFactor(i+1)) in index space of bn2gs1Outers2Outer. So each core's block contains a whole BN unit's S loop (blockFactor = bns2Factor * s1Outer*s2Outer means each block spans bns2Factor BN units and within them all s1os2o blocks). With B=1,N=4,G=1: fusedOuter=4, aicNum large → blockFactor=1, blockOuter=4 → core c gets [cS, (c+1)S) where S = s1Outers2Outer. So each of 4 cores loops over ALL of the S blocks for one head — the S loop is inside each core, and the vector work per iteration is proportional to CUBE_BASEM × CUBE_BASEN etc.

3. BN2S2 (DoBn2s2Sparse line 511-547): fusedOuter = bn2gs2Outer; blockFactor = bns2Factors1Outer; totalBlock = fusedOuters1Outer. blockStartsi=blockFactori — so index space is (b,n2,g,s2o,s1o): within a block, s1Outer blocks are contiguous. So each core covers bns2Factor (b,n2,g,s2o) units × all s1o. Fused = bn2g*s2Outer (with s1o contiguous inside).

So formulas:
- BN2GS1S2: fused = b·n2·g·s1Outer·s2Outer — full 5-dim product; cores partition the whole product.
- BN2: fused = b·n2·g then multiplied by s1Outer·s2Outer inside each block (i.e., block = ceil(bng/aicNum) BN units, each with full S= s1Outer*s2Outer inner).
- BN2S2: fused = b·n2·g·s2Outer, then × s1Outer inside block (block = ceil(bngs2o/aicNum) units each with all s1Outer).

Now VF load. Need block_vec.h ProcessVec1/3/4 + CopyMaxSum + ProcessMulsAndCast, and vector_api/pse_atten_mask_muls_simple_softmax.h to quantify per-iteration vector work: softmaxGrad operates on CUBE_BASEM (128) × CUBE_BASEN (128) region? Let's read the vector files.

Let me also read kernel_base.h 1070-1364 for SetAxisRunInfo and the swizzle helpers, plus IsValid (before 740 — read 600-743? IsValid is probably right before CheckIsValidBlock at ~700). Let me read 1070-1364 now, plus block_vec.h.
SetRunInfo/CheckIsValidBlock 已明（index→b/n2/g/s1o/s2o 拆解）。继续读 IsValid、SetAxisRunInfo、swizzle 索引函数与 block_vec 的 VF 处理量
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=300, offset=1070]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h [limit=60, offset=695]
- Thought: 29.9s
Now I have the full index decomposition on kernel side:

IsValid (kernel_base.h:1262-1317), non-TND branch:
- gDimTail = index % constInfo.s1oS2o
- s2oDimIdx = gDimTail / constInfo.s1Outer  (line 1270)
- s1oDimIdx = gDimTail % constInfo.s1Outer  (line 1271)
- bDimTail = index % constInfo.n2GS1oS2o
- n2DimTail = bDimTail % constInfo.gS1oS2o
- SetAxisRunInfo: boIdx = index / n2GS1oS2o, n2oIdx = bDimTail / gS1oS2o, goIdx = n2DimTail / s1oS2o

So the block index space is: b (outermost) × n2 × g × s2o × s1o (s1o innermost). The "fused" product on the kernel side is n2GS1oS2o = n2·g·s1Outer·s2Outer (kernel_base.h:563), gS1oS2o = g·s1Outer·s2Outer (564), s1oS2o = s1Outer·s2Outer (565). These come from SetConstInfo (kernel_base.h:492-700). For DENSE (no atten mask), IsValid returns true always (kernel_base.h:1310-1314) — so every index in [blockStartsc, blockEndsc) is processed.

Now for the three paths, host formulas:
1. BN2GS1S2 (dense): host DoSparse else branch (line 702-723) → fusedOuter = b·n2·g·s1Outer·s2Outer; blockStartsi = blockFactor·i with blockFactor = ceil(fusedOuter/aicNum). Kernel loop: index ∈ [blockStartscBlockIdx, blockEndscBlockIdx) decomposed as b·n2·g·s2o·s1o.
   - BUT WAIT: this is the fallback inside DoSparse. But there's also enableSwizzle / isSplitByBlockIdx: when swizzle enabled, the kernel uses GetNextValidIdxForSwizzle with curLoopIdx — the block start/end would be over b·n2·g? Need to see GetNextValidIdxForSwizzle (kernel_base.h ~1440+). Also host might fill blockStarts differently when swizzle. Hmm — actually enableSwizzle requires blockOuter == aicNum; with the user's case blockOuter likely == 4 ≠ aicNum so swizzle off. Let me check GetNextValidIdxForSwizzle anyway, and SetSwizzleConstInfo.

2. BN2 multiblk dense (host DoBn2MultiBlkSparse else branch line 628-655): fusedOuter = b·n2·g (line 632); blockFactor = ceil(bng/aicNum) then ×= s1Outer·s2Outer (line 635); blockOuter = ceil(bng/blockFactor) = number of cores with work. Kernel: same index decomposition, but each block covers bns2Factor BN units × full S inner.

3. BN2S2 (host DoBn2s2Sparse else branch line 519-544): fusedOuter = b·n2·g·s2Outer (line 523); totalBlock = fusedOuter·s1Outer (line 526); blockFactor = bns2Factor·s1Outer (line 527). Kernel: index decomposes b·n2·g·s2o·s1o — same decomposition, but core ranges are aligned so that a core covers whole s1Outer run for its (b,n2,g,s2o) units.

Wait, actually all three use the same kernel-side decomposition — the difference is only in what the host packs into blockStarts/blockEnds per core, i.e., what "unit" the fused product is and how many cores are used:
- BN2GS1S2 dense: block over full 5-dim product (b·n2·g·s1Outer·s2Outer). 
- BN2: block over b·n2·g, with s1Outer·s2Outer fused inside each block (per-core inner S loop).
- BN2S2: block over b·n2·g·s2Outer, with s1Outer fused inside each block.

So "fusedOuter 乘了什么"：
- BN2GS1S2: ×(s1Outer·s2Outer) — full
- BN2: 不乘 S 维度（s1Outer·s2Outer 是 block 内连续，blockFactor 乘上它）— actually in code line 635-636 blockFactor = s1Outers2Outer and fusedOuter = s1Outers2Outer, so the blockEnds are computed in the full 5-dim index space; the "split unit" is bng.
- BN2S2: ×s2Outer，block 内再带 s1Outer。

Now for the user's scenario: B=1, N=4 (n2=4, g=1), S=2048, D=80, FP16, arch35. Which path? "4 个 AIC 干活" — strongly suggests split on BN only: fusedOuter = b·n2·g = 4 → blockOuter = 4 → cores 0-3 work. For BN2GS1S2 dense: fusedOuter = 4·s1Outer·s2Outer. For S=2048, D=80: FuzzyForBestSplit determines s1Inner/s2Inner (probably 128 each?), s1Outer = ceil(2048/cvS2Inner)... let's see: DoSplit computes s1Outer = (s1 + s1CvInner - 1)/s1CvInner where s1CvInner = s1Inner·ratio. If s1Inner ~ 128, ratio 1, s1Outer = 16, s2Outer = 16 → fusedOuter = 4·16·16 = 1024 → blockOuter = 1024/ceil(1024/aicNum)... with aicNum ~ 40, blockFactor = 26, blockOuter = 40 → all 40 cores work. That does NOT match "only 4 AIC". So the user's case is NOT BN2GS1S2 with the dense fallback... unless the template is BN2.

Hmm, but wait — BN2 multiblk requires isBn2MultiBlk — need to check SetSplitAxis to see when BN2 is chosen. Also note the user's task explicitly asks to check all three paths' differences — they want a comparison, and the conclusion about which matches "4 AIC + VF 打满". 

Actually wait — BN2S2: fusedOuter = b·n2·g·s2Outer = 4·s2Outer. If s2Outer = 16 → fusedOuter = 64 → blockFactor = ceil(64/aicNum). If aicNum=40 → 2, blockOuter = 32 → 32 cores. Not 4 either.

So "4 AIC 干活" is most consistent with BN2 (split on b·n2·g = 4 → blockOuter=4), with each core doing the full S loop inside. But hold on — the user might be running with N=4 as "num heads" → n2=4? In flash attention, N is typically the number of heads (batch of heads). Actually for attention, shape is B, N(heads), S, D with N=4. In the tiling code, n2 is the head count N. g=1 (GQA groups). So b·n2·g = 1·4·1 = 4. Yes.

But wait — the kernel-side also has the "BN2GS1S2" name for the s1s2 template — in the kernel the SPLIT_AXIS == BN2GS1S2 template is used for the standard (non-BN2-multiblk) path. And the host DoSparse at line 691 sets splitAxis = BN2GS1S2 as the DEFAULT for non-BN2. Hmm, so "BN2GS1S2" is the default template and it partitions over the full 5-dim product. For the user's case that would give blockOuter = aicNum (all cores busy) — not 4.

Unless... aicNum is small? arch35 has typically 40 AICs? Actually Ascend 910B has 20 AIC + 40 AIV or 40 AIC? arch35 = Ascend 910C? 910C has 40 AIC and 40 AIV? Hmm. Let me not speculate; the user says only 4 AIC 干活. 

Actually, wait: reconsider — maybe with S=2048, D=80, the s1s2 split yields s1Outer·s2Outer such that... no. Let me think about what makes 4 blocks:
- BN2 multiblk: fusedOuter = b·n2·g = 4 → blockOuter = 4 (blockFactor=1). 4 cores work, each does s1Outer·s2Outer inner iterations. ✓ matches.
- BN2GS1S2 dense: blockOuter = aicNum (all cores) — unless aicNum is small (e.g., 4?). Not likely on arch35.
- BN2S2: blockOuter = ceil(bng·s2Outer / ceil(bng·s2Outer / aicNum)) → with bng=4, s2Outer≥1 → at least 4·s2Outer blocks... e.g. s2Outer=8, aicNum=40: blockFactor=1, blockOuter=32. Not 4. Unless s2Outer = 1 (s2 < CUBE_BASEN·ratio)? s2=2048 so no.

Hmm wait, actually there's another possibility: N=4 in the user's scenario might mean the total number of (b·n2) is 4, and the split axis is BN2GS1S2 BUT the "4 AIC" report comes from... Actually the user's question says "只有 4 个 AIC 干活、vector 几乎打满" — that's their observation. My conclusion should present which path is consistent.

But hold on — the user also said "fusedOuter 在 kernel 侧三条路径（BN2GS1S2 / BN2 / BN2S2）的消费差异，以及核内 VF（vector）负载". The three paths correspond to SPLIT_AXIS template values. The kernel side has no "fusedOuter" variable — the fused product appears as:
1. host blockStarts/blockEnds (tiling data) — s1s2BNGS1S2BlockNumList;
2. constInfo.n2GS1oS2o / gS1oS2o / s1oS2o (kernel_base.h:563-565) — used in IsValid decomposition.

For question 1: "fusedOuter 控制哪个循环的外层迭代" — the kernel main loop Process() (kernel.h:496-590) iterates blockInnerIdx from blockStartscBlockIdx to blockEndscBlockIdx (kernel_base.h GetNextValidIdx line 1388-1397 / IsValid per index). Each index = one (b,n2,g,s2o,s1o) basic block. That's the outer loop. The fused dims: b·n2·g·s1Outer·s2Outer (for BN2GS1S2 dense), b·n2·g for BN2 split (S inner), b·n2·g·s2Outer for BN2S2 split (s1 inner).

Wait — but for BN2 multiblk, the kernel still decomposes index the same way (b, n2, g, s2o, s1o) via IsValid/CheckIsValidBlock — with multiBlkInfo.s2OuterTmp = constInfo.s2Outer etc. But there's also the BN2 multiblk S1 loop: CheckS1RangeInBn2(taskId) and isLastS1Outer[taskId&1] (kernel_base.h:1051-1054). For BN2 multiblk, the block is one BN unit; inside, the S loop is processed... hmm — actually for BN2 multiblk the taskId index ranges over s1Outer·s2Outer within a single BN. So the "inner S loop" IS the main loop taskId iterations — each taskId = one (s1o,s2o) block of the same BN unit. The isLastS1Outer / isFirstS1Outer flags and ProcessMulsAndCast batching confirm: for BN2 multiblk, consecutive taskIds within a core belong to the same BN and differ in s1o/s2o (ComputeDqkvBn2 IS_BN2_MULTIBLK branch, kernel.h:440-493).

OK. So on kernel side, for all three paths, the loop variable is the flat block index, decomposed as (b, n2, g, s2o, s1o); the "fusedOuter 乘了什么"差异 = what host packs per core:
- BN2GS1S2: blockFactor = ceil(b·n2·g·s1Outer·s2Outer / aicNum) — a contiguous slice of the FULL product.
- BN2: blockFactor = ceil(b·n2·g / aicNum) · s1Outer·s2Outer — slice aligned to BN units; s1o/s2o fully inside each core.
- BN2S2: blockFactor = ceil(b·n2·g·s2Outer / aicNum) · s1Outer — slice aligned to (b,n2,g,s2o) units; s1o inside each core.

Now VF load. Need block_vec.h: ProcessVec1 (softmaxGrad), ProcessVec2 (pse+attenMask+softmax), ProcessVec3 (dropout+cast+nd2nz), ProcessVec4 (cast+nd2nz), CopyMaxSum, ProcessMulsAndCast. And the sizes: VECTOR_BASEM/VECTOR_BASEN — need to find their definitions. SetConstInfo line 695: sfmgMaxLoopSize = VECTOR_BASEM·VECTOR_BASEN / HEAD_DIM_ALIGN. Let me find VECTOR_BASEM/VECTOR_BASEN definitions (probably in flash_attention_score_grad_common.h or a template config header, maybe op_kernel/flash_attention_score_grad.h or template data). Let me query locate for VECTOR_BASEM.

Also HEAD_DIM_ALIGN, CUBE_BASEM/CUBE_BASEN. For D=80, D < HEAD_DIM_ALIGN (128?) so dAlign... the mm is padded to 128.

Then read block_vec.h ProcessVec1/3/4 + CopyMaxSum, and vector_api/pse_atten_mask_muls_simple_softmax.h to quantify per-iteration VF work: softmaxGrad per (s1o,s2o) block = s1RealSize × s2RealSize ops... let me look.

Also — for the conclusion: "4 AIC + VF 打满" — I should also verify DetermineMode / SetSplitAxis to see which path is actually selected for B=1,N=4,S=2048,FP16 dense. Let me query the host for SetSplitAxis and DetermineMode. Also FuzzyForBestSplit to get s1Inner/s2Inner values for S=2048, D=80. These determine s1Outer/s2Outer. Let me read those host functions. First locate SetSplitAxis / DetermineMode / FuzzyForBestSplit in host.
Index 拆解已确认（IsValid/SetAxisRunInfo）。现在查 host 的 SetSplitAxis/DetermineMode/FuzzyForBestSplit（决定 B=1,N=4,S=2048 走哪条路径），以及 VECTOR_BASEM 定义与 block_vec 处理量
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern SetSplitAxis]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern DetermineMode]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern VECTOR_BASEM]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern FuzzyForBestSplit]
- Thought: 27.8s
Very useful. Key findings:

1. SetSplitAxis (tiling_common_regbase.cpp:1581-1647):
   - isBn2 = s1<=BN2_MAX_S && s2<=BN2_MAX_S && n1==n2 && d<=BN2_MAX_D && not FP32/FP8 && tailZeroCount==0 (line 1583-1588).
   - isBn2MultiBlk = bnLimit && (s1>BN2_MAX_S || s2>BN2_MAX_S) && s1<=BN2_MULTIBLK_SEQ && s2<=BN2_MULTIBLK_SEQ && n1==n2 && d<=BN2_MAX_D && !FP32/FP8 && d==d1 && !hasRope (line 1596-1606), where bnLimit = bn1 >= 256 || (bn1 >= 128 && s1%128==0 && s2%128==0) (line 1590-1591).
   
   For the user's case B=1, N=4: bn1 = 14 = 4 < 128 → bnLimit = false → isBn2MultiBlk = false. isBn2 = (s1<=BN2_MAX_S && s2<=BN2_MAX_S && ...). BN2_MAX_S is probably 128? or 256? For S=2048 > BN2_MAX_S → isBn2 = false. So the user's case is NOT BN2 and NOT BN2S2 (unless...). splitAxis = BN2GS1S2 (from DoSparse line 691: fBaseParams.splitAxis = isBn2 ? BN2 : BN2GS1S2).

   Wait — but then DoBn2s2Sparse requires splitAxis == BN2S2 — how does splitAxis become BN2S2? Probably in some other function (DoSplit? or a template adjustment). Hmm. Let me check where SplitAxisEnum::BN2S2 is set. It might be set in InitTilingData / or in SaveToTilingData based on template type. Actually the SPLIT_AXIS is a kernel template parameter (from tiling key). Let me search for "BN2S2" assignments in host. Actually wait — the user says "三条路径 BN2GS1S2 / BN2 / BN2S2" — the three template paths in kernel.h Process() (line 575-581). The selection among them happens via the compile-time template SPLIT_AXIS which is chosen from the tiling key. So I should determine which one applies for this shape. Given isBn2=false, isBn2MultiBlk=false → likely BN2GS1S2 (the default non-BN2 template).

   Hmm, but the "4 AIC" observation conflicts with BN2GS1S2 dense (which would use all AICs)... unless the s1s2 split gives blockOuter = 4? fusedOuter = b·n2·g·s1Outer·s2Outer = 4·s1Outer·s2Outer. For blockOuter == 4 we'd need blockFactor = fusedOuter/4 = s1Outer·s2Outer → blockFactor = ceil(fusedOuter/aicNum) → s1Outer·s2Outer = ceil(4·s1Outer·s2Outer/aicNum) → aicNum = 4? No. Hmm — aicNum could be small if the device has fewer cores... but arch35 is 910C with 48-64 cores.

   WAIT. Let me reconsider: fBaseParams.aicNum — the actual AIC count used. If the user runs on a simulated environment or with limited cores... Not knowable statically. But there's another consideration: CalcTschBlockDim(blockOuter * AICV_RATIO_DEFAULT, aicNum, coreNum) (PostTiling line 1492-1493) — block dim = blockOuter·2 typically (AICV ratio 2). Hmm.

   Actually — hold on. Let me reconsider the fusedOuter for BN2GS1S2 with enableSwizzle. In DoOpTiling line 442: enableSwizzle = (isExceedL2Cache || isLargeInvalidBlk) && blockOuter == aicNum. isExceedL2Cache: for B=1,N=4,S=2048,D=80, the L2 usage = ... probably not exceeding. And blockOuter == aicNum only when fusedOuter >= aicNum... 

   Hmm, wait — actually I realize I should double check: does the BN2GS1S2 path use the DoSparse else branch (line 701-723) with fusedOuter = b·n2·g·s1Outer·s2Outer? That sets blockStarts/blockEnds over the FULL 5-dim product. Yes — for dense non-TND non-sparse, splitAxis==BN2GS1S2 → this branch. So blockOuter = ceil(fusedOuter / ceil(fusedOuter/aicNum)).

   For the "4 AIC" symptom with BN2GS1S2: blockOuter == 4 would require ceil(fusedOuter/aicNum) = fusedOuter/4, i.e. aicNum ≥ fusedOuter·3/4+... Actually blockFactor = ceil(fusedOuter/aicNum). blockOuter = ceil(fusedOuter/blockFactor) = aicNum when blockFactor = ceil(fusedOuter/aicNum) and fusedOuter ≥ aicNum... roughly blockOuter ≈ min(fusedOuter, aicNum). So blockOuter = 4 ⟺ min(fusedOuter, aicNum) = 4 ⟺ fusedOuter = 4 (with aicNum ≥ 4) — meaning s1Outer·s2Outer = 1 — impossible for S=2048.

   So BN2GS1S2 dense does NOT give 4 AIC for this shape (assuming aicNum ≥ 16 or so). Hmm.

   But WAIT — what about BN2S2? When is splitAxis == BN2S2? It must be set somewhere. Let me search the host for "SplitAxisEnum::BN2S2" writes. In DoBn2s2Sparse it only READS splitAxis == BN2S2. So there must be another place that sets it — maybe in InitTilingData or SaveToTilingData based on... Let me search. Actually, maybe in varlen/normal regbase there's a function that adjusts splitAxis for S1S2 templates when deterministic... Let me query "SplitAxisEnum::BN2S2" and "SplitAxisEnum::BN2".

   Also for the kernel template choice: the tiling key selects template. The three ComputeDqkv* are selected by constexpr SPLIT_AXIS. Which SPLIT_AXIS is instantiated for a given run depends on the tiling key / compile template set. Not statically determinable without the tiling key of the user's run. I'll present it as: BN2 path requires isBn2/isBn2MultiBlk (B*N≥128 — so NOT for B=1,N=4); BN2S2 requires splitAxis==BN2S2 (set elsewhere, need to find); default is BN2GS1S2.

   Actually — I recall in these operators the template dispatch is: for non-deterministic non-TND → BN2GS1S2 template with dTemplateType/s1TemplateType/s2TemplateType combos; BN2S2 is a variant used for S1S2 "split by s2" cases (TND mostly); BN2 for small S. So for the user's FP16 dense B=1,N=4,S=2048,D=80, the likely template is BN2GS1S2 (non-swizzle, since blockOuter≠aicNum), and blockOuter = min(b·n2·g·s1Outer·s2Outer, aicNum). For S=2048: FuzzyForBestSplit → GetS1S2TemplateType → s1Inner = template.first/2, s2Inner = template.second. Template first/second depend on S size and D — for S=2048, likely s1Inner=128, s2Inner=128 (or 64?). s1CvInner = 128·ratio. S1CV_RATIO_DEFAULT — probably 1. s1Outer = 2048/128 = 16, s2Outer = 16. fusedOuter = 4·16·16 = 1024. blockOuter = 40 (aicNum) if aicNum=40 → all cores get work. So "4 AIC" wouldn't match BN2GS1S2 unless aicNum is 4.

   Hmm, so maybe the user's "4 AIC" observation comes from aicNum=4 (e.g., they're profiling on a 4-AIC device or the launched blockDim is small), OR the tiling actually picked a different path. This is exactly why the question asks to distinguish "分核轴只切了 N=4 个核" vs "核内 VF 本身重".

   The most important kernel-side evidence: in ALL three paths the per-core work = (blockEnds - blockStarts) iterations, each iteration does 5 vector phases (v1 softmaxGrad, v2 pse+mask+softmax, v3 dropout+cast+nd2nz, v4 cast+nd2nz, +v5/v6 dq/dk/dv muls+cast) over a CUBE_BASEM×CUBE_BASEN tile, plus 5 matmuls. If the block count per core is large (S loop inside), vector work is the inner-loop dominant factor.

2. VECTOR_BASEM = CUBE_BASEM / CV_CORE_RATIO (kernel_base.h:88). CV_CORE_RATIO — probably 2 (AIC:AIV ratio). Need to confirm. If CUBE_BASEM=128 → VECTOR_BASEM=64 (each vector core handles half the S1 rows?). Hmm — actually VECTOR_BASEM=64 means each AIV core processes 64×128 = 8192 elements per tile... Wait — vSubBlockIdx (0/1) splits S1 in half across two AIVs? SetRunInfo: vSubBlockIdx==1 → halfS1RealSize adjustments. So each AIV core handles HALF of CUBE_BASEM rows (64 rows) and all CUBE_BASEN columns (128), i.e., 64×128 FP16 = 16KB per tile. With D=80: HEAD_DIM_ALIGN = GetDTemplateType → for D=80, dTemplateType = 128 (align up)? HEAD_DIM_ALIGN=128.

   So per (s1o,s2o) iteration:
   - mm1 (mmDyV): S2×D... in cube terms CUBE_BASEM×HEAD_DIM_ALIGN?... matmul: mm1 = Dy(128×128?) @ V(...) etc. Not needed precisely.
   - vector: softmaxGrad on S1×S2 tile: per AIV, 64×128 = 8192 elements (FP16) — reduce over S2 axis (128), exp, mul, etc. V2: pse+mask+softmax on 64×128. V3: dropout+cast+nd2nz on 64×128 + cast 128×80?; V4 similar. dq/dk/dv muls+cast on 128×128 or 64×128...
   
   Total vector elements per iteration per AIV ≈ several × 8K-16K elements. With s1Outer·s2Outer = 16·16 = 256 iterations per head (if split were by head) — but under BN2GS1S2 with 40 cores, each core handles ~26 blocks. Under BN2-style split (bng=4), each core handles 256 blocks.

   So if the actual run has 4 AICs each doing 256 S-blocks, the vector work per core = 256 × (v1..v6) ≈ huge; that matches "VF 打满" (vector busy) while cube has 5 mm's per block that are relatively small (128×128×128 matmuls) — with D=80 (pad to 128), each matmul is 128×128×128 FP16. Cube on arch35 AIC is much faster per element than vector softmax/exp. So VF becomes the bottleneck per iteration and with few cores doing all S iterations, it's both "分核轴只切了 N" AND "核内 VF 重" — but the more actionable statement: the split axis (BN-only, 4 blocks) forces 4 AICs to serialize the entire S loop, and within each iteration VF is the heavy phase (softmax grad/exp/div + dropout + casts in FP32), so both factors combine; the fix is to split the S axis across cores (BN2GS1S2 full 5-dim split or BN2S2) so more AICs get work.

   Let me verify CV_CORE_RATIO and GetS1S2TemplateType / GetDTemplateType values for S=2048,D=80. Also check where BN2S2 is set. Also check CheckExceedL2Cache (for enableSwizzle). Also block_vec ProcessVec1/3/4 + CopyMaxSum to quantify.

Let me do the reads:
1. tiling_common_regbase.cpp: GetS1S2TemplateType (812-860), GetDTemplateType (847-?), CV_CORE_RATIO definition, BN2_MAX_S/BN2_MAX_D/BN2_MULTIBLK_* definitions (probably in common header).
2. Search host for "SplitAxisEnum::BN2S2" assignments (locate query).
3. block_vec.h: ProcessVec1, ProcessVec3, ProcessVec4, CopyMaxSum, ProcessMulsAndCast.
4. vector_api pse_atten_mask_muls_simple_softmax.h + softmax_grad file.

Let me batch: locate BN2S2 assignment, locate CV_CORE_RATIO, locate BN2_MAX_S, and read tiling_common 800-880.
SetSplitAxis 关键结论已拿到（BN2 需要 BN≥128，B=1/N=4 不满足）。现在查 BN2S2 在哪被设置、CV_CORE_RATIO/BN2 阈值、GetS1S2TemplateType 对 S=2048 的切分
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern BN2S2]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern CV_CORE_RATIO]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern BN2_MAX_S]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp [limit=90, offset=800]
- Thought: 15.1s
Excellent. Now I have all the routing logic:

SetSplitAxis (tiling_common_regbase.cpp:1581-1649):
- isBn2: s1<=BN2_MAX_S && s2<=BN2_MAX_S && n1==n2 && d<=BN2_MAX_D && not FP32/FP8 && tailZeroCount==0 (1583-1588)
- isBn2MultiBlk: bnSparseLimit (needs b*n1>=128/256!) && (s1>BN2_MAX_S || s2>BN2_MAX_S) && s1,s2 <= BN2_MULTIBLK_SEQ && ... (1590-1606)
- splitAxis = BN2S2 if !isBn2 && bn2S2RouteLimit (1641-1643)
- splitAxis = BN2 if isBn2 (1644-1645)
- splitAxis = BN2GS1S2 otherwise (1646-1647)

bn2S2RouteLimit (1631-1639): !hasRope && d <= BN2_MAX_D && (layoutType==TND || (isAllSame && !isDeterministic) || bn2S2NotTndLimit) && (keepProb>=1 || (d<=128 && keepProb<1)) && n1==n2 && not FP32/FP8.

bn2S2NotTndLimit (1625-1630): s1 < s2 && s2 <= BN2S2_MAX_S && s2-s1 >= BN2_MAX_S && d <= BN2S2_WRITE_UB_D && !isSparse && !isDeterministic.

For the user's case: B=1, N=4 (n1==n2==4), S=2048 (s1==s2==2048), D=80, FP16, dense (assume no atten mask), non-deterministic (typical). 

- s1==s2, so bn2S2NotTndLimit requires s1 < s2 → false. bn2S2RouteLimit = ... (isAllSame && !isDeterministic) — hmm, isAllSame: for BSND layout with equal S1/S2? isAllSame likely means s1==s2 (all sequences equal). If layout is BSNGD (dense 4D), isAllSame might be true. Then bn2S2RouteLimit = !hasRope && d<=BN2_MAX_D && (TND || (isAllSame && !deterministic) || ...) && ... — could be TRUE for the user's case! If so, splitAxis = BN2S2!

Hmm interesting. So for B=1,N=4,S=2048,D=80 FP16 dense, the splitAxis could be BN2S2 (via isAllSame && !isDeterministic), because DoBn2s2Sparse's else branch (normal_regbase.cpp:519-544) gives fusedOuter = b·n2·g·s2Outer = 4·s2Outer.

Then blockOuter = ceil(fusedOuter/blockFactor) where blockFactor = ceil(fusedOuter/aicNum). If s2Outer = 16 (cvS2Inner = 128 → s2Outer = 2048/128 = 16), fusedOuter = 4·16 = 64. blockFactor = ceil(64/aicNum). With aicNum = 20 (typical for 910B arch35? Actually 910C arch35 has 40 AIC? Hmm) — if aicNum=20 → blockFactor=4, blockOuter=16. Not 4.

For blockOuter == 4 with BN2S2: need blockFactor = 16 = ceil(64/aicNum) → aicNum ≤ 4... no: ceil(64/aicNum) = 16 → aicNum in (64/17, 64/15] ≈ (3.76, 4.26] → aicNum=4. Hmm — if aicNum == 4! Maybe the user's device reports aicNum=4?? Or maybe they're on a platform where coreNum is small.

Hmm wait — actually I need to double-check aicNum. Let me search where fBaseParams.aicNum is set. It's probably coreNum/2 or from context_. In arch35, coreNum = 40? aicNum = 20? Actually MAX_CUBE_CORE_NUM = 36 (common.h:112). Hmm, interesting — MAX_CUBE_CORE_NUM = 36 in common.h. aicNum might be capped at 36. Let me not over-speculate.

Also there's CalcTschBlockDim and coreNum... I could look for where aicNum is assigned. Let me check.

Actually — WAIT. There's an important subtlety I should double check: for the user's case with s1==s2==2048, BN2S2 route requires isAllSame && !isDeterministic. isAllSame probably means all b have same s1/s2 (for TND) or s1==s2. For standard BSND (non-TND), isAllSame likely = true always? I don't know exactly. This affects which path. But since the user asks "三条路径" and wants the fusedOuter formulas for each, plus a conclusion about which matches the symptom, I should present:
- If BN2S2 route: fusedOuter = b·n2·g·s2Outer = 4·s2Outer blocks; s1Outer inner per block. For S=2048, D=80: s1Outer = s2Outer = 16 (with 128-base blocks). fusedOuter = 64; with aicNum=20 → blockFactor = 4 → blockOuter = 16 → 16 AICs. NOT 4.
- If BN2GS1S2 route (default): fusedOuter = 4·16·16 = 1024; blockOuter ≈ 20. NOT 4.
- If BN2 multiblk (needs b·n1 ≥ 128): NOT applicable for B=1,N=4.

Hmm, so with the standard arch35 aicNum (~20-36), none of the three paths give exactly 4 AICs for this shape... unless the actual s1s2 split uses larger inner blocks: e.g., if s1Inner=256? GetS1S2TemplateType for FP16 dense: s1=2048, s2=2048 → AlignTo16(2048)·AlignTo16(2048) >= 128·128 → s1TemplateType = s2TemplateType = 128 → s1Inner = 128/2 = 64! Wait — FuzzyForBestSplit: s1Inner = template.first / 2 = 128/2 = 64; s2Inner = 128. Then DoSplit: s1CvInner = s1Inner·s1CvRatio; s1CvRatio = S1CV_RATIO_DEFAULT. What is S1CV_RATIO_DEFAULT? Probably 1? Then s1Outer = ceil(2048/64) = 32. s2Outer = ceil(2048/(s2Inner·s2CvRatio)) = 2048/128 = 16 (if s2CvRatio=1). Hmm.

Actually wait — FuzzyForBestSplit: s1Inner = s1s2TemplateSize.first / 2 = 64 (because template 128 is the CUBE_BASEM; inner block for CV is half). s2Inner = 128. s1CvInner = min(64·ratio, 2048)... with ratio 1: s1CvInner = 64 → s1Outer = 32; s2CvInner = 128 → s2Outer = 16.

Hmm OK — so exact numbers depend on S1CV_RATIO_DEFAULT / S2CV_RATIO_DEFAULT and CV ratios. This is getting deep. The user asked "FP16、S=2048、D=80 场景 vector 每核要算多少" — I need the per-core VF work. Let me now focus on block_vec.h to quantify per-iteration vector work, and check where aicNum is set, plus CV ratio defaults.

Let me read:
1. tiling_common_regbase.cpp around aicNum assignment — search "aicNum" locate.
2. S1CV_RATIO_DEFAULT define — search.
3. block_vec.h ProcessVec1 (softmaxGrad), ProcessVec3, ProcessVec4, CopyMaxSum — read block_vec.h relevant windows.
4. vector_api/pse_atten_mask_muls_simple_softmax.h — the VF2 core: CalculatePseMulsSelSimpleSoftMax.

Let me do these.
路由逻辑已完整（BN2S2 需要 s1<s2 或 TND/allSame；BN2 需要 BN≥128）。现在定位 aicNum 赋值、CV 比率，并读 block_vec.h 的 VF 各阶段处理量
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern aicNum]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern S1CV_RATIO_DEFAULT]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_vec.h [limit=240, offset=150]
- Thought: 8.9s
Excellent — ProcessVec1 (softmaxGrad) details:
- block_vec.h:355-385. Each AIV processes halfS1RealSize rows (half of CUBE_BASEM = 64 for a 128 template; VECTOR_BASEM = CUBE_BASEM/2 = 64) × HEAD_DIM_ALIGN columns. When HEAD_DIM_ALIGN > VECTOR_BASEN (i.e., > 64 when template s2=128?) — wait VECTOR_BASEN = CUBE_BASEN = 128; HEAD_DIM_ALIGN = 128 → HEAD_DIM_ALIGN <= VECTOR_BASEN → simple path (line 364). So for D=80 → HEAD_DIM_ALIGN=128, VECTOR_BASEN=128: CopyInSoftmaxGrad with 64 rows × 128 cols; CalculateCastSoftmaxGrad.

So per iteration per AIV: VF1 processes halfS1RealSize(64) × HEAD_DIM_ALIGN(128) = 8192 elements (FP16→FP32 cast + softmax grad calc). Plus VF2 (pse+mask+softmax), VF3 (dropout+cast+nd2nz — over dSOut 64×128 or 128×80?), VF4 (cast+nd2nz — pOut), and v5/v6 dq/dk/dv muls+cast (each 128×128 or 128×80 output...).

Now let me read block_vec.h ProcessVec3/ProcessVec4/CopyMaxSum/ProcessMulsAndCast — read 390-600. Also vector_api/pse_atten_mask_muls_simple_softmax.h to see the softmax reduce structure. And also the entry/kernel dispatch to confirm template selection via tiling key (SplitAxis dim). I have enough on that front (entry_regbase.h:230: splitAxis == BN2S2 → INVOKE...; BN2GS1S2 at 227; BN2 at 236).

Let me read block_vec.h 390-620.
VF1 已量化（每核每轮 64×128）。继续读 block_vec 的 CopyMaxSum/ProcessVec3/ProcessVec4/ProcessMulsAnd
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_vec.h [limit=330, offset=390]
- Thought: 1m 1s
I now have detailed VF work per iteration:

Per iteration (per AIV core):
- VF1 ProcessVec1 (block_vec.h:355-385): softmaxGrad front: CopyInSoftmaxGrad 64(halfS1)×128(HEAD_DIM_ALIGN) rows of y/dy (FP16→FP32), CalculateCastSoftmaxGrad on 64×128. Data = 8192 elements.
- CopyMaxSum (388-400): copy max/sum (64×32 floats?).
- VF2 ProcessVec2 (458-471): CopyInAttenMask + CopyInPse + CalculatePseMulsSelSimpleSoftMax on VECTOR_BASEM(64)×VECTOR_BASEN(128) mm2Res (the S1×S2 score matrix): pse add, mask, muls, softmax (exp, reduce over S2=128, div). 8192 elements.
- VF3 ProcessVec3 (545-627): GenerateDropMask / CopyInDropOuter, CalculateDropout (IS_DROP), BroadcastSubMul (softmaxGrad×score - dropout mm1res over 64×128), Muls (FP32), CastTransdataDeconflict (FP32→FP16 + nd2nz), CopyUB2L1 (64×128 → L1 for cube). 
- VF4 ProcessVec4 (631-652): CalculateDropout on mm2Res (64×128), CastTransdataDeconflict (FP32→FP16 p matrix), CopyUB2L1 (p to L1).
- VF5/6 ProcessMulsAndCast (655-718): dq/dk/dv muls + cast + DataCopyPad to GM: for DQ: halfS1RealSize(64) rows × dSize(80) FP16 = 5120 elements; DK/DV: halfS2RealSize(64) × 80 = 5120.

So per iteration per AIV vector core: ~4 passes over 64×128 (8192) FP32/FP16 tiles (softmaxGrad, pse+mask+softmax, dropout+sub+mul+cast, cast+nd2nz) + 3 small muls/casts of 64×80. That's about 4×8192 + 3×5120 ≈ 48K element-ops per iteration per AIV core, with transcendental ops (exp) and reductions in softmax.

Cube per iteration: mm1 = Dy(64?) ... actually cube handles mmQK (S1×D @ D×S2 = 128×128×128), mmDyV, mmDsK (dq = ds @ K: 128×128×128), mmDsQ (dk), mmPDy (dv): 5 matmuls of 128×128×128 each = 5×2M MACs = 10M MACs per iteration. On AIC with ~256 MACs/cycle... these are big but AIC throughput is high; the VF work with exp/div/softmax is latency-bound.

Now let me quickly confirm a couple remaining pieces:
1. GetS1S2TemplateType: FP16, S=2048 → s1TemplateType=128, s2TemplateType=128 (lines 830-841). FuzzyForBestSplit: s1Inner = 128/2 = 64; s2Inner = 128 (1477-1478). S1CV_RATIO_DEFAULT/S2CV_RATIO_DEFAULT — need values. They're defines; S1CV_RATIO_DEFAULT appears at line 480. The values are likely in a header (maybe flash_attention_score_grad_tiling_common_regbase.h or the normal regbase header). Let me check the tiling_data_regbase.h or the params header. Actually, from varlen 1014: s1Outer = (actualSeqQlen + s1Inner·S1CV_RATIO_DEFAULT - 1)/(s1Inner·S1CV_RATIO_DEFAULT) — ratio multiplies s1Inner to get CV inner. CV ratio probably = 1 for S=2048 (or 2?). If ratio=1: s1Outer=32, s2Outer=16. If ratio=2: s1CvInner=128 → s1Outer=16; s2Outer = 2048/(128·2)=8.

Let me find the actual #define values. They might be in a .h file — the UO locate showed only .cpp uses. Let me search the codebase headers via UO locate "RATIO_DEFAULT". Or read the header where FuzzyBaseInfoParamsRegbase is defined. Let me query locate "S2CV_RATIO_DEFAULT".

2. The kernel dispatch entry (entry_regbase.h) — confirmed three splitAxis branches (227 BN2GS1S2, 230 BN2S2, 236 BN2). The tiling key selects.

3. CheckExceedL2Cache — for enableSwizzle — worth a quick check? Not critical.

4. Verify the conclusion about which path the user's case takes. Given:
- isBn2: S=2048 > BN2_MAX_S (which is likely 128 or 256 — BN2_MAX_S used in isBn2 check s1<=BN2_MAX_S; BN2 multiblk needs S > BN2_MAX_S... The values BN2_MAX_S/BN2_MAX_D/BN2_MULTIBLK_SEQ are defines probably in the same file or a header. Let me find their values: search "BN2_MAX_D" and "BN2_MULTIBLK_SEQ" and "BN2S2_MAX_S" and "BN2S2_WRITE_UB_D" and "BN2_MULTIBLK_BN_256" values. These are #define constants likely in a header included by tiling_common_regbase.cpp. UO locate shows them at "line 1596/1625" as HOSTCONST — the definitions might be from a macro or include. Let me query locate for "BN2_MAX_D" and "BN2_MULTIBLK_SEQ".

Let me also double-check CalcTschBlockDim to understand blockDim (launched cores) — user said "4 AIC 干活" which likely means blockDim observed or profiling shows 4 AIC busy. blockDim = CalcTschBlockDim(blockOuter·AICV_RATIO_DEFAULT, aicNum, coreNum). AICV_RATIO_DEFAULT likely 2 — so blockDim ≈ blockOuter·2? Actually CalcTschBlockDim maps cube blocks to cores with ratio... The kernel cBlockIdx for cube = block id. If blockOuter=4 → blockDim=8 (4 AIC + 4 AIV)? Or blockOuter·2 = 8 blocks each... Hmm — "4 个 AIC 干活" would then = 4 cube blocks. For BN2GS1S2 with fusedOuter=1024, blockOuter=20 (aicNum=20)... 20 AIC. Doesn't match.

Hmm wait — I should reconsider. What if aicNum for this user's arch35 environment is small — e.g., 20 AIC (910B), and for BN2GS1S2 dense with S=2048: s1Outer·s2Outer depends on CV ratios. If s1Inner=64 and ratio=1 → s1Outer=32; s2Inner=128 ratio=1 → s2Outer=16; fusedOuter = 4·32·16 = 2048; blockFactor = ceil(2048/20)=103; blockOuter=20 → 20 AICs busy. Still not 4.

So for "4 AIC 干活" to happen with this code, we need fusedOuter (as packed into blockStarts) = 4 or a few, i.e., the BN-only split (b·n2·g=4) — which requires isBn2MultiBlk (BN2) — but BN2 multiblk needs b·n1 ≥ 128/256 → B=1,N=4 fails! OR the BN2S2 path where fusedOuter = b·n2·g·s2Outer — if s2Outer=1... s2=2048 → s2Outer ≥ 1; s2Outer=1 only if cvS2Inner=2048. Unlikely.

Hmm, so statically, for B=1, N=4, S=2048, D=80 FP16 dense NON-TND, the expected routing is: isBn2=false, isBn2MultiBlk=false. splitAxis: bn2S2RouteLimit = !hasRope(true) && d(80)<=BN2_MAX_D && (layoutType==TND? no → isAllSame && !isDeterministic? — depends on isAllSame) && keepProb condition && n1==n2(4==4 ✓) && not FP32/FP8 ✓. If isAllSame (s1==s2 → likely true for BSND with equal S? not sure) → splitAxis=BN2S2! Then DoBn2s2Sparse else-branch (dense) sets blockStarts over fusedOuter = b·n2·g·s2Outer = 4·s2Outer.

Then blockOuter = ceil(fusedOuter / ceil(fusedOuter/aicNum)). If aicNum=20 and s2Outer=16: fusedOuter=64 → blockFactor=4 → blockOuter=16. If aicNum=40: blockFactor=2 → blockOuter=32. Never 4.

Hmm — unless... wait, maybe the user's "4 AIC" comes from profiling where they limited cores or it's a small simulator. OR maybe the s2Outer is much smaller: e.g., if s2Inner is large. s2Inner = s1s2TemplateSize.second = 128 → s2Outer = ceil(2048/(128·s2CvRatio)). If S2CV_RATIO_DEFAULT = 2 → s2Outer = 8 → fusedOuter = 32 → blockFactor=ceil(32/aicNum) → aicNum=20 → 2 → blockOuter=16. Still not 4.

OK — the honest static answer: with the given shape and typical arch35 aicNum (≥20), the tiling spreads S across cores; "4 AIC 干活" is NOT consistent with the dense BN2GS1S2/BN2S2 split (which would use ~16-40 cores), but IS consistent with (a) BN2 multiblk split on b·n2·g=4 — which however requires b·n1≥128, so B=1,N=4 wouldn't enter it, or (b) an environment where aicNum is effectively small, or (c) the run actually being TND/sparse with a different split, or (d) user observed only 4 AIC from another measurement artifact. I must mark this PARTIAL/UNKNOWN and present the formulas for all three paths, then state the most probable interpretation.

Actually, wait — let me reconsider once more. There's GetSparseUnpadBlockInfo for TND... user says "arch35" FP16 — probably standard dense attention with 4D inputs (BNSD?) or 3D (TND?). "B=1、N=4、S=2048" — with layout BNSD (batch, heads, seq, dim) typical. Non-TND.

Hmm, one more angle: bn2S2RouteLimit includes (fBaseParams.layoutType == INPUT_FORMAT_TND || (fBaseParams.isAllSame && !fBaseParams.isDeterministic) || bn2S2NotTndLimit). For non-TND dense, isAllSame — let me find where isAllSame is set. It's probably set in the fuzzy params init: isAllSame = (s1==s2)? or (all batches same length). For non-TND, s1==s2=2048 → isAllSame=true likely. If deterministic=0 → BN2S2 route → fusedOuter = 4·s2Outer blocks.

Given the user reports only 4 AIC active: if s2Outer turned out small (e.g., 2?) — no...

Hmm hold on — actually let me reconsider whether "4 AIC 干活" could come from blockOuter = 4 in BN2S2. blockOuter = ceil(fusedOuter/blockFactor). For blockOuter=4 with fusedOuter=4·s2Outer: blockFactor = fusedOuter/4 = s2Outer → ceil(fusedOuter/aicNum) = s2Outer → 4·s2Outer ≤ aicNum·s2Outer and aicNum ≥ 4 → true whenever aicNum ≥ 4·... wait: blockFactor = ceil(4·s2Outer/aicNum). blockOuter = ceil(4·s2Outer / blockFactor). For blockOuter = 4: need blockFactor ≥ s2Outer → ceil(4·s2Outer/aicNum) ≥ s2Outer → aicNum ≤ 4 (approx). So only if aicNum ≤ 4. For arch35 (910C has 40 AIC? or 20?), aicNum is ≥ 20. So no.

Therefore, "4 AIC 干活" cannot be explained by the block split of BN2GS1S2/BN2S2 dense at aicNum≥20. It CAN be explained by BN2-multiblk-style split (b·n2·g=4), which requires BN≥128 — not the case here. OR the observed "4 AIC" might be from a different part of the pipeline, OR the tiling key resolved to a template where the split is on N only (e.g., varlen TND BN2S2 with b=1,n2=4: GetBlockInfoOfTNDForBn2 line 1561-1564: fusedOuter = b·n2·g·s1s2oCount... hmm for TND sparse).

Actually — WAIT. I should look at GetBlockInfoOfTNDForBn2 (host 1549-1610) which I saw earlier at line 1561: fusedOuter = b·n2·g·s1s2oCount with blockStarts over that — for TND BN2. And there's the BN2S2 TND path: GetBlockInfoOfBNS4TND. For TND with b=1,n2=4,s=2048... if layout TND and splitAxis BN2S2: GetBlockInfoOfBNS4TND → block split over b·n2·g·s2Outer? Not read yet.

I think I've gathered enough to write a thorough, evidence-backed answer with PARTIAL/UNKNOWN markers where static analysis can't determine the runtime tiling key. But let me do two more quick reads to firm up:
1. The #define values for BN2_MAX_S / BN2_MAX_D / BN2_MULTIBLK_SEQ / BN2S2_MAX_S / S1CV_RATIO_DEFAULT / S2CV_RATIO_DEFAULT / AICV_RATIO_DEFAULT — likely in a header. Let me read the top of tiling_common_regbase.cpp (1-120) where defines/includes live, plus the normal_regbase.h or the fuzzy params header. Actually UO said BN2_MAX_S is at line 1596 of tiling_common_regbase.cpp as HOSTCONST — meaning the constant may be defined via macro in included header. Let me read the file top.

2. GetBlockInfoOfBNS4TND (host, for TND BN2S2) — to complete the BN2S2 fused formula for TND. And GetSparseUnpadBlockInfo (TND BN2GS1S2) at 1561 area? Actually 1561 was in GetBlockInfoOfTNDForBn2.

Let me read tiling_common_regbase.cpp head (1-130) for defines, and host 1500-1680 for the TND BN2 / BN2S2 block info functions.
VF 各阶段已量化。最后补两块：比率/阈值宏定义值，以及 TND 下 BN2/BN2S2 的 blockInfo 函数
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp [limit=130, offset=1]
→Read d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp [limit=120, offset=1540]
- Thought: 2.2s
The #defines for BN2_MAX_S etc. are not in the cpp — they come from a header (flash_attention_score_grad_tiling_common_regbase.h presumably). Let me quickly locate BN2_MAX_D / BN2_MULTIBLK_SEQ / S1CV_RATIO_DEFAULT definitions in headers via locate. Actually — locate for "BN2_MAX_D" and "S2CV_RATIO_DEFAULT" and "BN2S2_MAX_S" to find the header with values. Let me just do one query for the constants in the header.

Actually I have enough for the report. The exact threshold values (BN2_MAX_S etc.) are nice-to-have; let me try one quick query to get BN2_MAX_D/BN2_MULTIBLK_SEQ values, and also check GetBlockInfoOfBNS4TND briefly. Let me do a couple of targeted queries then write the answer.
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern BN2_MULTIBLK_SEQ]
⚙acp [command=uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode locate --pattern GetBlockInfoOfBNS4TND]
- Thought: 47.0s
Let me create the structured summary from the conversation. The user is investigating flash_attention_score_grad on arch35 (Ascend), querying about fusedOuter consumption in kernel-side three paths (BN2GS1S2 / BN2 / BN2S2), vector (VF) load, and why only 4 AIC cores work with VF saturated.

Key findings so far:

1. Tool: uo-query via acp with --project d:\TEST\ops-transformer\attention\flash_attention_score_grad. Valid modes: search, constraints, neighbors, impact, field, branches, templates, tiling_key, tiling_data, kernel_branch, template_match, buffer, gaps, legal_key, locate, kernel_api, kernel_launch, compile. (symbols is invalid.)

2. Host-side fusedOuter:
   - BN2S2 (DoBn2s2Sparse, flash_attention_score_grad_tiling_normal_regbase.cpp:511-547): fusedOuter = bn2gs2Outer (line 523); totalBlock = fusedOuters1Outer (526); blockFactor = bns2Factors1Outer (527); blockStartsi=blockFactori; index order b,n2,g,s2o,s1o.
   - BN2 sparse (GetSparseBlockInfoBn2, line 549-620): fusedOuter = bn2g (557), *= s1s2oCount (564); blockStarts decode b/n2/g then s1o/s2o.
   - BN2 dense multiblk (DoBn2MultiBlkSparse else branch, line 622-655): fusedOuter = b*n2g (632); blockFactor = ceil(bng/aicNum) then = s1Outers2Outer (635); fusedOuter = s1Outers2Outer (636); blockOuter = ceil(bng/blockFactor) → for B=1,N=4: fusedOuter=4, blockFactor=1, blockOuter=4 → only 4 cores work, each core loops full s1Outers2Outer inner.
   - BN2GS1S2 dense (DoSparse else branch, lines ~701-723): fusedOuter = bn2gs1Outers2Outer (full 5-dim product), blockStarts contiguous.

3. Kernel-side (no variable named fusedOuter; fused product materialized as blockStarts/blockEnds ranges + constInfo axis products):
   - kernel.h:496-590 Process() main loop: iterates blockInnerIdx from blockStartscBlockIdx to blockEndscBlockIdx; each iteration = one (b,n2,g,s2o,s1o) block; calls ProcessVec1 (softmaxGrad, 522), IterateMmQK (557), IterateMmDyV (565), CopyMaxSum (571), then ComputeDqkvBn2gs1s2 (576, SPLIT_AXIS==BN2GS1S2), ComputeDqkvBn2s2 (578, BN2S2), ComputeDqkvBn2 (580, BN2).
   - SetConstInfo (kernel_base.h:492-700): reads s1Outer/s1CvTail/s2Tail/s2Outer from s1s2BNGS1S2SplitCoreParams (495-498); computes axis products: n2GS1oS2o = n2gs1Outers2Outer (563), gS1oS2o (564), s1oS2o (565); sfmgMaxLoopSize = VECTOR_BASEMVECTOR_BASEN/HEAD_DIM_ALIGN (695).
   - IsValid/CheckIsValidBlock (kernel_base.h:743-831): non-TND decompose: s2oDimIdx = (index % s1oS2o)/s1Outer (1270), s1oDimIdx = index % s1Outer (1271); SetAxisRunInfo: boIdx = index/n2GS1oS2o, n2oIdx = bDimTail/gS1oS2o, goIdx = n2DimTail/s1oS2o. So flat index order: b (outermost) × n2 × g × s2o × s1o (s1o innermost).
   - VECTOR_BASEM = CUBE_BASEM/CV_CORE_RATIO (kernel_base.h:88); CV_CORE_RATIO=2 (common.h:115); VECTOR_BASEN = CUBE_BASEN.

4. Routing (which path chosen):
   - SetSplitAxis (tiling_common_regbase.cpp:1581-1649): isBn2 needs s1<=BN2_MAX_S && s2<=BN2_MAX_S && n1==n2 && d<=BN2_MAX_D && not FP32/FP8 && tailZeroCount==0 (1583-1588); isBn2MultiBlk needs bnSparseLimit: bn1>=256 || (bn1>=128 && s1%128==0 && s2%128==0) (1590-1591) — B=1,N=4 → 4 < 128 → NOT BN2 multiblk; bn2S2RouteLimit (1625-1639): needs !hasRope && d<=BN2_MAX_D && (TND || (isAllSame && !isDeterministic) || bn2S2NotTndLimit) && ...; bn2S2NotTndLimit (1625-1630): s1<s2 && s2<=BN2S2_MAX_S && s2-s1>=BN2_MAX_S && ... — for s1==s2==2048, s1<s2 false; splitAxis = BN2S2 if !isBn2 && bn2S2RouteLimit (1641-1643); BN2 if isBn2 (1644-1645); else BN2GS1S2 (1646-1647).
   - DetermineMode (tiling_common_regbase.cpp:1651): FP16 → inputDtype FP16 (not FLOAT32).
   - DoOpTiling (normal_regbase.cpp:430-459): SetSplitAxis, DoSplit, DoSparse; enableSwizzle = (isExceedL2Cache || isLargeInvalidBlk) && blockOuter == aicNum (442); isNzOut for BN2GS1S2 with 64<d<128 (444-451).
   - DoSplit (normal_regbase.cpp:478-502): s1CvRatio=S1CV_RATIO_DEFAULT, s2CvRatio=S2CV_RATIO_DEFAULT; s1Inner from FuzzyForBestSplit (s1Inner = s1s2TemplateSize.first/2); s1Outer = ceil(s1/s1CvInner); s2Outer = ceil(s2/cvS2Inner).
   - FuzzyForBestSplit (1474-1481): s1Inner = template.first/2, s2Inner = template.second, dInner = GetDTemplateType.
   - GetS1S2TemplateType (812-829): FP32 d>256 → 64/128; FP8 → 64/256; HIFLOAT8 → 512/512; FP16 path → need lines 829+ (not read; likely 128/128 for S=2048).
   - aicNum from compileInfoPtr->aicNum (normal_regbase.cpp:385); coreNum = aivNum (384).
   - PostTiling (1483-1493): numBlocks = blockOuter * AICV_RATIO_DEFAULT → CalcTschBlockDim.
   - Kernel template dispatch (entry_regbase.h:230-238): splitAxis BN2GS1S2 → INVOKE...BN2GS1S2; BN2S2 → INVOKE...BN2S2; BN2 → INVOKE...BN2 (FP16: half, float, half).

5. VF load:
   - ProcessVec2 (block_vec.h:458-471): VF2 pse+attenMask+muls+simpleSoftmax on mm2ResTensor.
   - VF1 softmaxGrad: per AIV processes halfS1RealSize (≈64 rows for 128 template) × HEAD_DIM_ALIGN (128 for D=80); 8192 elements/iter; copyIn+cast+calc; VECTOR_BASEM=64, VECTOR_BASEN=128, HEAD_DIM_ALIGN=128 (D=80 padded to 128).
   - CopyMaxSum (390-400); CopyUB2L1 (403-418) — VECTOR_BASEN/FRACTAL_NZ_C0_SIZE blocks, halfS1RealSize rows.
   - Not yet read: ProcessVec3/4 bodies, ProcessMulsAndCast, vector_api/pse_atten_mask_muls_simple_softmax.h.

6. Conclusion direction: "4 AIC 干活" most consistent with a split where fusedOuter = bn2g = 4 (BN2-style split → blockOuter=4, each core does all S blocks). But SetSplitAxis says isBn2MultiBlk requires bn1 >= 128 — so for B=1,N=4 the BN2 multiblk path is NOT selected; the default for this shape is BN2GS1S2 (or possibly BN2S2 via isAllSame route, which would fuse bn2gs2Outer). Unknowns: whether BN2S2 route is taken (isAllSame value, determinism), actual aicNum for the device, and actual s1Outer/s2Outer numbers (S1CV_RATIO_DEFAULT/S2CV_RATIO_DEFAULT values not read), GetS1S2TemplateType FP16 branch (lines 829+) not read.

The final answer hasn't been written yet. The next moves:
1. Read block_vec.h ProcessVec3/ProcessVec4/ProcessMulsAndCast bodies + vector_api pse_atten_mask_muls_simple_softmax.h to quantify per-iteration VF work (elements per AIV per block).
2. Read tiling_common_regbase.cpp:829-900 (GetS1S2TemplateType FP16 branch) and bn2S2NotTndLimit/bn2S2RouteLimit full bodies (lines ~1620-1650), BN2_MAX_S/BN2_MAX_D/BN2_MULTIBLK_SEQ/BN2S2_MAX_S constants.
3. Read DoSparse full body (normal_regbase.cpp:660-723) to confirm BN2GS1S2 dense branch.
4. Read SetSplitAxis full (1581-1649) to nail the exact routing for B=1,N=4,S=2048,D=80 FP16.
5. Then write the final prose answer (Cursor Explore style with file:line evidence), marking PARTIAL/UNKNOWN where statically undetermined. No answer.yaml, no finalize.

Relevant files:
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_vec.h
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_common.h
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_tiling_data_regbase.h

Also note: UO KB digest 211a7ec308c399739f9d27e3175c75bc1c95664d6482061656278ad1e99c12ad.

Constraint: must use acp uo-query for location; reading machine-scope operator sources via read tool is allowed after UO locate. Final answer must be full prose with file:line, mark PARTIAL/UNKNOWN, no answer.yaml, no finalize. Response language: the user wrote in Chinese — so the summary should probably be in Chinese to match. The template says "Respond in the same language as the conversation." The conversation is mostly Chinese with English technical terms. I'll write the summary in Chinese (with English terms preserved).

Let me draft the summary in Chinese.
Objective
- 查清 flash_attention_score_grad（arch35，digest 211a7ec…）三条 kernel 路径 BN2GS1S2 / BN2 / BN2S2 中 fusedOuter 的消费差异（各路径 fused 维度组合、控制的外层循环），核内 VF 负载量级，以及 B=1、N=4、S=2048、D=80、FP16 场景「只有 4 个 AIC 干活 + vector 打满」的根因（分核轴只切 N=4 vs 核内 VF 本身重）。
- 交付 Cursor Explore 风格散文答案，全部带 file:line；静态无法确定处标 PARTIAL/UNKNOWN；不写 answer.yaml、不 finalize。
Important Details
- 工具约束：必须用 acp 调 uo-query --project d:\TEST\ops-transformer\attention\flash_attention_score_grad --mode ...；symbols 不是合法 mode（合法：search/constraints/neighbors/impact/field/branches/templates/tiling_key/tiling_data/kernel_branch/template_match/buffer/gaps/legal_key/locate/kernel_api/kernel_launch/compile）；禁止 bash/Grep/MCP 替代。UO locate 之后可用 read 工具窗口读机器域源文件（绝对路径见 Relevant Files）。
- 关键已证实事实：
- kernel 侧没有名为 fusedOuter 的变量；fused 乘积以 host 的 blockStarts/blockEnds（tiling 数据 s1s2BNGS1S2BlockNumList，tiling_data_regbase.h:235-236）＋ kernel 侧轴乘积 constInfo.n2GS1oS2o / gS1oS2o / s1oS2o（kernel_base.h:563-565）体现。
- flat block index 拆解顺序固定为 b（最外）× n2 × g × s2o × s1o（s1o 最内）：IsValid kernel_base.h:1270-1271（s2oDimIdx=(index%s1oS2o)/s1Outer、s1oDimIdx=index%s1Outer）；SetAxisRunInfo boIdx=index/n2GS1oS2o 等（kernel_base.h:780-783、1009-1016）。三路径差异只在 host 往每个 core 塞什么范围。
- host 三条路径 fusedOuter 公式：BN2S2（DoBn2s2Sparse，normal_regbase.cpp:523）= b·n2·g·s2Outer，totalBlock=×s1Outer（526），blockFactor=bns2Factor·s1Outer（527）；BN2 非稀疏（DoBn2MultiBlkSparse else，:632-636）= b·n2·g，blockFactor=ceil(bng/aicNum) 再 ×(s1Outer·s2Outer)；BN2GS1S2 非稀疏（DoSparse else，:701-723）= b·n2·g·s1Outer·s2Outer 全乘积。
- 路由：SetSplitAxis（tiling_common_regbase.cpp:1581-1649）——isBn2 需 s1,s2≤BN2_MAX_S 且 n1==n2 等（1583-1588）；isBn2MultiBlk 需 bnSparseLimit（b·n1≥256，或 ≥128 且 s1,s2%128==0，1590-1591）——B=1、N=4 时 b·n1=4<128，故 BN2 multiblk 不选；splitAxis=BN2S2 需 !isBn2 && bn2S2RouteLimit（1631-1639，含 isAllSame&&!isDeterministic 或 bn2S2NotTndLimit：s1<s2 等 1625-1630——s1==s2==2048 时 s1<s2 为假）；否则 BN2GS1S2（1646-1647）。BN2 模板需要 BN≥128，B=1/N=4 不可能选。
- kernel 主循环：kernel.h Process() 496-590，blockInnerIdx 从 blockStartscBlockIdx 到 blockEndscBlockIdx（GetNextValidIdx kernel_base.h:1367-1397）；每块调用 ProcessVec1（softmaxGrad，kernel.h:522）、IterateMmQK（557）、IterateMmDyV（565）、CopyMaxSum（571）、然后按 SPLIT_AXIS 选 ComputeDqkvBn2gs1s2（576）/ ComputeDqkvBn2s2（578）/ ComputeDqkvBn2（580）。模板派发：entry_regbase.h:230-238（FP16：half,float,half）。
- VF 量化基础：VECTOR_BASEM=CUBE_BASEM/CV_CORE_RATIO（kernel_base.h:88），CV_CORE_RATIO=2（common.h:115），VECTOR_BASEN=CUBE_BASEN（89）；HEAD_DIM_ALIGN=GetDTemplateType（D=80→128）；sfmgMaxLoopSize=VECTOR_BASEM·VECTOR_BASEN/HEAD_DIM_ALIGN（kernel_base.h:695）。VF1（ProcessVec1，block_vec.h:355-385）：每 AIV 每轮处理 halfS1RealSize（≈64 行）× HEAD_DIM_ALIGN(128)=8192 元素，加 cast/copy。ProcessVec2（block_vec.h:458-471）：pse+attenMask+muls+simpleSoftmax。
- aicNum/coreNum 来自 compileInfoPtr（normal_regbase.cpp:384-385）；PostTiling numBlocks=blockOuter·AICV_RATIO_DEFAULT→CalcTschBlockDim（1483-1493）。
- DoSplit：s1Outer=ceil(s1/s1CvInner)、s2Outer=ceil(s2/cvS2Inner)（normal_regbase.cpp:478-502）；FuzzyForBestSplit s1Inner=template.first/2（1474-1481）；GetS1S2TemplateType FP16 分支（tiling_common_regbase.cpp:829+）尚未读到。
Work State
Completed
- uo-query locate：fusedOuter（host 17 处，normal_regbase.cpp:557 等）、FagConstInfo（common.h:389）、SetConstInfo（kernel_base.h:492）、ProcessBn2gs1s2LastVec（kernel.h:47）、ComputeDqkvBn2gs1s2（kernel.h:164）、ComputeDqkvBn2（kernel.h:315）、ProcessVec2（block_vec.h:458）、blockFactor（32 处）、blockStarts（tiling_data_regbase.h:235）、s1s2BNGS1S2SplitCoreParams（tiling_data_regbase.h:615）、FagRunInfo（common.h:504）、GetNextValidIdx（kernel_base.h:1368）、SetRunInfo（kernel_base.h:835）、SetSplitAxis（tiling_common_regbase.cpp:1581）、DetermineMode（1651）、VECTOR_BASEM（kernel_base.h:88）、FuzzyForBestSplit（normal_regbase.cpp:1474）、BN2S2 派发（entry_regbase.h:230）、CV_CORE_RATIO（common.h:115）、BN2_MAX_S 等（tiling_common_regbase.cpp:1596）、aicNum 赋值（normal_regbase.cpp:385）、S1CV_RATIO_DEFAULT（normal_regbase.cpp:480）。
- 读文件：kernel.h:1-760（Process 主循环全貌、ComputeDqkv* 三段、ProcessPreloadTwoTimes VF3/VF4 调用点 700-708）；kernel_base.h:488-707（SetConstInfo 轴乘积、sfmgMaxLoopSize）；kernel_base.h:740-1070（CheckIsValidBlock/IsValid 索引拆解、SetRunInfo）；kernel_base.h:1070-1370（offset 计算、TND 分支）；block_vec.h:150-390（VF1 softmaxGrad 64×128、CopyMaxSum 390-400、CopyUB2L1 403-418）；block_vec.h:390-720（ProcessVec2 458-471、ProcessVec3 700 行附近）；normal_regbase.cpp:430-610（DoOpTiling、DoSparse 前半）；normal_regbase.cpp:610-660（DoBn2MultiBlkSparse 非稀疏分支 622-655）；tiling_common_regbase.cpp:800-890（GetS1S2TemplateType FP32/FP8/HIFLOAT8 分支 814-829）；tiling_common_regbase.cpp:1581-1649（SetSplitAxis 全路由）。
Active
- 尚未写出最终散文答案；还差以下证据：
- block_vec.h ProcessVec3/ProcessVec4/ProcessMulsAndCast（VF3 dropout+cast+nd2nz、VF4 cast+nd2nz、v5/v6 dq/dk/dv muls+cast）具体处理量（元素数/核/轮）。
- vector_api/pse_atten_mask_muls_simple_softmax.h 的 softmax/simpleSoftmax 循环结构（每核 reduce 量）。
- GetS1S2TemplateType FP16 分支（tiling_common_regbase.cpp:829-860）→ S=2048 的 s1Inner/s2Inner；S1CV_RATIO_DEFAULT/S2CV_RATIO_DEFAULT 值 → s1Outer/s2Outer 具体数。
- bn2S2RouteLimit/bn2S2NotTndLimit/BN2S2_MAX_S 常量全文（tiling_common_regbase.cpp:1620-1650）；isAllSame 定义（决定 S=2048 是否可能走 BN2S2）。
- DoSparse 的 BN2GS1S2 非稀疏 else 分支全文（normal_regbase.cpp:660-723，确认 fusedOuter=b·n2·g·s1Outer·s2Outer 及 blockStarts 填充）。
Blocked
- 无硬阻塞。静态无法确定项（需标 PARTIAL/UNKNOWN）：用户运行实际 splitAxis（依赖 isAllSame/isDeterministic/BN2S2 路由判定）、实际 aicNum（设备相关）、S1CV/S2CV_RATIO 默认值与 FP16 模板分支未读全、swizzle（enableSwizzle 需 blockOuter==aicNum，normal_regbase.cpp:442）是否生效。
Next Move
1. 读 block_vec.h ProcessVec3/ProcessVec4/ProcessMulsAndCast 本体（约 720-1100 行）+ vector_api 的 pse_atten_mask_muls_simple_softmax.h，量化每核每轮 VF 元素量。
2. 读 tiling_common_regbase.cpp:829-900（GetS1S2TemplateType FP16）与 1620-1650（bn2S2RouteLimit/常量），normal_regbase.cpp:660-723（DoSparse BN2GS1S2 分支），以及 S1CV_RATIO_DEFAULT/S2CV_RATIO_DEFAULT 宏值。
3. 汇总成 Cursor Explore 风格中文散文答案（file:line 齐全，含三路径 fusedOuter 公式、每核 VF 量、4-AIC 根因判定：BN 分核轴只有 b·n2·g=4 块 → blockOuter=4 核内串行整条 S 循环，且每轮 VF（softmaxGrad/softmax/dropout/cast）元素量级≥立方 mm 每核负载；同时指出 BN2 模板需 BN≥128 对该 shape 不选，BN2S2/BN2GS1S2 会给更多核分块，故「4 AIC」更可能是分核轴/路由而非纯 VF），不确定处标 PARTIAL/UNKNOWN。
Relevant Files
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_normal_regbase.cpp：DoSparse(660-723)、DoBn2s2Sparse(511-547)、DoBn2MultiBlkSparse(622-655)、GetSparseBlockInfoBn2(549-620)、DoSplit(478-502)、FuzzyForBestSplit(1474)、PostTiling(1483)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_host\arch35\flash_attention_score_grad_tiling_common_regbase.cpp：SetSplitAxis(1581-1649)、DetermineMode(1651)、GetS1S2TemplateType(812-860)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel.h：Process 主循环(496-590)、ProcessBn2gs1s2LastVec(47)、ComputeDqkvBn2gs1s2(164)、ComputeDqkvBn2s2(182+)、ComputeDqkvBn2(315)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_kernel_base.h：SetConstInfo(492-700)、IsValid/CheckIsValidBlock(743-831)、SetRunInfo(835-1086)、GetNextValidIdx(1364-1397)、VECTOR_BASEM/VECTOR_BASEN/HEAD_DIM_ALIGN(86-93)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_block_vec.h：VF1/ProcessVec1(355-385)、CopyMaxSum(390-400)、ProcessVec2(458-471)、ProcessVec3/Vec4/CopyUB2L1(403-418、700 附近)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_common.h：FagConstInfo(389)、FagRunInfo(504)、CV_CORE_RATIO(115)、MAX_CUBE_CORE_NUM(112)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_entry_regbase.h：三模板派发(227-238)。
- d:\TEST\ops-transformer\attention\flash_attention_score_grad\op_kernel\arch35\flash_attention_score_grad_tiling_data_regbase.h：BlockNumListParamsRegbase blockStarts/blockEnds(235-236)、s1s2BNGS1S2SplitCoreParams(615)。
▣  Compaction · DeepSeek V4 Flash Free · 1m 44s
- Thought: 39.7s
I now have enough evidence to write the final answer. Let me consolidate everything into a Cursor Explore-style prose answer in Chinese with file:line evidence, marking PARTIAL/UNKNOWN where static analysis can't determine the runtime tiling key.

Key facts to include:

1. fusedOuter 在 host 侧的含义与三路径公式：
   - fusedOuter 不是 kernel 变量，host 侧三个 split 函数各自计算：
     - BN2GS1S2 dense（DoSparse else 分支，normal_regbase.cpp:701-723）：fusedOuter = b·n2·g·s1Outer·s2Outer（全 5 维乘积），blockStarts 连续
     - BN2 dense multiblk（DoBn2MultiBlkSparse else 分支，normal_regbase.cpp:622-655）：fusedOuter = b·n2·g（:632），blockFactor = ceil(bng/aicNum) 再 ×(s1Outer·s2Outer)（:635），blockOuter = ceil(bng/blockFactor)（:636）——B=1、N=4 → fusedOuter=4、blockFactor=1、blockOuter=4，只有 4 个 AIC 干活，每核内循环全 s1Outer·s2Outer
     - BN2S2 dense（DoBn2s2Sparse，normal_regbase.cpp:511-547）：fusedOuter = b·n2·g·s2Outer（:523），totalBlock = fusedOuter·s1Outer（:526），blockFactor = bns2Factor·s1Outer（:527），blockStartsi = blockFactor·i
     - BN2 sparse（GetSparseBlockInfoBn2，:549-620）：fusedOuter = b·n2·g（:557）×s1s2oCount（:564）
     - TND sparse（GetSparseBlockInfo，:1553-1622）：fusedOuter = b·n2·g·s1s2oCount（:1561），blockStarts 通过 bIdx/n2Idx/gIdx/s1oIdx/s2oIdx 拆解（:1592-1608）
     - TND BN2S2（GetBlockInfoOfBNS4TND，varlen_regbase.cpp:1216-1245）：负载均衡二分

2. kernel 侧消费（block 索引拆解固定顺序 b×n2×g×s2o×s1o）：
   - Process() 主循环 kernel.h:496-590，blockInnerIdx 从 blockStartscBlockIdx 到 blockEndscBlockIdx
   - IsValid/CheckIsValidBlock（kernel_base.h:743-831），索引拆解：s2oDimIdx = (index % s1oS2o)/s1Outer（1270），s1oDimIdx = index % s1Outer（1271）
   - SetAxisRunInfo：boIdx = index/n2GS1oS2o，n2oIdx = bDimTail/gS1oS2o，goIdx = n2DimTail/s1oS2o（kernel_base.h:780-783/1009-1016）
   - SetConstInfo 轴乘积：n2GS1oS2o = n2·g·s1Outer·s2Outer（563），gS1oS2o（564），s1oS2o（565）
   - 每块调 ProcessVec1（softmaxGrad，kernel.h:522）、IterateMmQK（557）、IterateMmDyV（565）、CopyMaxSum（571）、ComputeDqkvBn2gs1s2（576）/Bn2s2（578）/Bn2（580）
   - 模板派发 entry_regbase.h:227-238

3. 路由判定（tiling_common_regbase.cpp:1581-1649）：
   - isBn2 初判 :1583-1588；isBn2MultiBlk = bnSparseLimit && (s1>BN2_MAX_S||s2>BN2_MAX_S) && s1,s2<=BN2_MULTIBLK_SEQ && n1==n2 && d<=BN2_MAX_D && 非FP32/FP8 && d==d1 && !hasRope（1596-1606）；bnSparseLimit = (b·n1≥256) || (b·n1≥128 && s1,s2%128==0)（1590-1591）——B=1、N=4 → b·n1=4，不满足 → isBn2MultiBlk=false
   - bn2S2RouteLimit（1631-1639）：!hasRope && d<=BN2_MAX_D && (TND || (isAllSame && !isDeterministic) || bn2S2NotTndLimit) && ...；bn2S2NotTndLimit（1625-1630）：s1<s2 && s2<=BN2S2_MAX_S && s2-s1>=BN2_MAX_S && d<=BN2S2_WRITE_UB_D && !isSparse && !isDeterministic
   - 对 s1==s2==2048：s1<s2 为假 → bn2S2NotTndLimit=false；BN2S2 只能走 isAllSame && !isDeterministic 分支
   - 否则 splitAxis = BN2GS1S2（1646-1647）
   - BN2 模板需要 BN≥128（kernel 侧），B=1/N=4 时 BN=4，永远进不了 BN2

4. VF 量化（每核每迭代）：
   - VECTOR_BASEM = CUBE_BASEM/CV_CORE_RATIO（kernel_base.h:88），CV_CORE_RATIO=2（common.h:115）；VECTOR_BASEN=CUBE_BASEN（kernel_base.h:89）；HEAD_DIM_ALIGN 由 GetDTemplateType 定（D=80→128，block_vec.h 某处 / kernel_base.h:695 sfmgMaxLoopSize = VECTOR_BASEM·VECTOR_BASEN/HEAD_DIM_ALIGN）
   - VF1 ProcessVec1（block_vec.h:355-385）：softmaxGrad 64×128=8192 元素（y/dy copyIn+cast+计算）
   - VF2 ProcessVec2（458-471）：pse+attenMask+muls+simpleSoftmax 64×128=8192（exp、reduce、div）
   - VF3 ProcessVec3（545-627）：dropout+sub+mul（64×128）+ FP32→FP16 cast+nd2nz + CopyUB2L1
   - VF4 ProcessVec4（631-652）：dropout on p + cast + CopyUB2L1
   - VF5/6 ProcessMulsAndCast（655-718）：dq/dk/dv muls+cast+写 GM：64×80=5120 元素（DQ halfS1RealSize 行，DK/DV halfS2RealSize 行）
   - 每迭代每核 VF ≈ 4×8192 + 3×5120 ≈ 4.8 万元素操作，含 exp/div/软归约

5. 4 AIC 结论：
   - 「只有 4 个 AIC 干活」最可能是分核轴只切到 b·n2·g=4 的路径（BN2 multiblk dense：blockOuter=4）——但该路径需要 BN≥128（isBn2MultiBlk 的 bnSparseLimit 要求 b·n1≥256 或 ≥128），B=1/N=4 不满足！
   - 因此静态上 B=1、N=4、S=2048、D=80、FP16 应该走 BN2GS1S2（或 BN2S2 若 isAllSame && !deterministic），fusedOuter = 4·s1Outer·s2Outer（或 4·s2Outer）——正常会切出 ≥aicNum 块，不应该是 4 个 AIC
   - PARTIAL/UNKNOWN：需要实际 tiling key / aicNum / isAllSame / isDeterministic / 实际 s1Outer·s2Outer 才能定论。可能的解释：
     a) 用户运行环境的 aicNum 实际为 4（小核数模拟器/受限核数）→ BN2GS1S2 blockOuter=4
     b) 实际走的是 TND 稀疏/prefix 路径
     c) BN2S2 路径 s2Outer 很小
     d) 用户观察的是 profiling 中只有 4 个 AIC 有 cube 活动（如 BN2GS1S2 下 blockOuter 恰为 4 当 aicNum≥fusedOuter 时……blockFactor=ceil(fusedOuter/aicNum)≥1；若 aicNum 大于等于 fusedOuter，blockFactor=1，blockOuter=fusedOuter）
   - 但注意：4-AIC 观察与 BN2-multiblk 的 blockOuter=4 公式吻合；然而 B=1/N=4 无法进入该路径。若用户观察到 4 AIC，最合理的静态解释是 aicNum=4 或类似受限环境，或 BN2S2/BN2GS1S2 下 blockFactor 使 blockOuter=4（如 fusedOuter=4 即 s1Outer·s2Outer=1，不可能 S=2048）
   
   实际上对 BN2GS1S2 dense：fusedOuter=4·s1Outer·s2Outer；blockFactor=ceil(fusedOuter/aicNum)；blockOuter=ceil(fusedOuter/blockFactor)。要 blockOuter=4，需要 aicNum≈s1Outer·s2Outer 的量级。例如 aicNum=20、s1Outer=32、s2Outer=16 → fusedOuter=2048 → blockFactor=103 → blockOuter=20。不可能是 4。
   
   所以真正能产生 blockOuter=4 的只有：BN2 multiblk（bng=4）或 aicNum ≤ 4。既然 BN2 multiblk 被路由排除，唯一静态自洽的解释是运行环境 aicNum 很小（≤4）——即 910 系列以外或受限部署。标记 PARTIAL/UNKNOWN，给出验证方法（读 tiling key、aicNum、blockOuter）。

6. VF 饱和：即使有更多核分块，每迭代 VF 工作（≈4.8 万元素 + exp/div/归约）相对 cube 的 5 次 128×128×128 matmul（每次 2M MACs = 5×2M=10M MACs）在延迟上是不可忽略的；且 VF1/VF2 在 mm 之前、VF3/VF4 在 mm 之间串行（kernel.h:522→557→565→571→576），没有流水重叠的话 vector 就是瓶颈。D=80 时 HEAD_DIM_ALIGN=128 意味着 VF 每轮 8192 元素但有效数据只有 5120，有 37.5% 无效元素开销。

Let me write the final answer now. It should be full prose in Chinese with file:line references, Cursor Explore style. No answer.yaml, no finalize.
证据已齐。以下是最终答案（Cursor Explore 风格散文，全带 file:line）。
结论先行
fusedOuter 不是 kernel 侧变量——它在 host tiling 阶段被拆成 blockStarts/blockEnds 区间（flash_attention_score_grad_tiling_data_regbase.h:235-236），kernel 侧只有按固定顺序 b × n2 × g × s2o × s1o 的块索引拆解（kernel_base.h:1270-1271, 780-783）和 constInfo 里的轴乘积 n2GS1oS2o/gS1oS2o/s1oS2o（kernel_base.h:563-565）。三条路径的差异只在 host 往每个 core 的 blockStarts/blockEnds 里塞什么 fused 组合。你报的 B=1、N=4、S=2048、D=80、FP16「只有 4 个 AIC 干活」，静态上唯一能产生 blockOuter=4 的路径被路由排除了，所以要么运行环境的 aicNum 实际很小（≤4），要么 TND/稀疏/prefix 走的是另一套 blockInfo，标 PARTIAL/UNKNOWN 见文末。
1. 三条路径的 fusedOuter 公式（host）
BN2GS1S2 dense（flash_attention_score_grad_tiling_normal_regbase.cpp:701-723，DoSparse 的 else 分支）：fusedOuter = b·n2·g·s1Outer·s2Outer（全 5 维乘积），blockFactor = ceil(fusedOuter/aicNum)，blockStarts 连续。这是分块最细的路径——S 也被切进分核轴，正常应动用全部 aicNum 个核。
BN2 dense multiblk（normal_regbase.cpp:622-655，DoBn2MultiBlkSparse 的 else 分支）：
- fusedOuter = b·n2·g（:632）
- blockFactor = ceil(bng/aicNum)，再 ×= s1Outer·s2Outer（:635）
- fusedOuter ×= s1Outer·s2Outer（:636）
- blockOuter = ceil(bng/blockFactor)（:635 附近）
代入 B=1、N=4：fusedOuter=4、blockFactor=1、*blockOuter=4*——每核只分到 1 个 bng 块，核内串行跑完整 s1Outer·s2Outer 循环。这正是「4 个 AIC 干活」的公式来源。
BN2S2 dense（normal_regbase.cpp:511-547，DoBn2s2Sparse）：fusedOuter = b·n2·g·s2Outer（:523），totalBlock = fusedOuter·s1Outer（:526），blockFactor = bns2Factor·s1Outer（:527），blockStarts[i] = blockFactor·i——s1Outer 留在核内，s2Outer 进分核轴。
BN2 sparse（normal_regbase.cpp:549-620，GetSparseBlockInfoBn2）：fusedOuter = b·n2·g（:557）再 ×= s1s2oCount（:564），blockStarts 按 b/n2/g 拆解（:565-576）。
TND 稀疏（normal_regbase.cpp:1553-1622，GetSparseBlockInfo）：fusedOuter = b·n2·g·s1s2oCount（:1561），blockStarts 由 bIdx/n2Idx/gIdx/s1oIdx/s2oIdx 拆解（:1592-1608）；TND 的 BN2S2 走负载均衡二分 GetBlockInfoOfBNS4TND（varlen_regbase.cpp:1216-1245）。
2. kernel 侧消费方式
主循环 Process()（flash_attention_score_grad_kernel.h:496-590）：blockInnerIdx 从 blockStarts[cBlockIdx] 到 blockEnds[cBlockIdx]（:508 附近，GetNextValidIdx 在 kernel_base.h:1364-1397），每个 blockInnerIdx = 一个 (b,n2,g,s2o,s1o) 块，依次执行 ProcessVec1（softmaxGrad，:522）→ IterateMmQK（:557）→ IterateMmDyV（:565）→ CopyMaxSum（:571）→ 按 SPLIT_AXIS 三选一 ComputeDqkvBn2gs1s2（:576）/ ComputeDqkvBn2s2（:578）/ ComputeDqkvBn2（:580）。模板派发在 entry_regbase.h:227-238（FP16：half,float,half）。
索引拆解顺序固定：s2oDimIdx = (index % s1oS2o)/s1Outer、s1oDimIdx = index % s1Outer（kernel_base.h:1270-1271）；boIdx = index/n2GS1oS2o、n2oIdx = bDimTail/gS1oS2o、goIdx = n2DimTail/s1oS2o（kernel_base.h:780-783/1009-1016）。所以对同一 flat index，三路径的 (b,n2,g,s2o,s1o) 拆解结果一致；区别只是某个 core 的 [blockStarts, blockEnds) 覆盖多少块。
3. 路由判定（为什么 B=1/N=4 进不了 BN2 multiblk）
SetSplitAxis（tiling_common_regbase.cpp:1581-1649）：
- isBn2MultiBlk 需要 bnSparseLimit && (s1>BN2_MAX_S||s2>BN2_MAX_S) && (s1,s2 ≤ BN2_MULTIBLK_SEQ) && n1==n2 && d≤BN2_MAX_D && 非FP32/FP8 && d==d1 && !hasRope（:1596-1606）；
- bnSparseLimit = (b·n1≥256) || (b·n1≥128 && s1,s2%128==0)（:1590-1591）。B=1、N=4 → b·n1=4 < 128，直接排除。
- bn2S2RouteLimit（:1631-1639）：!hasRope && d≤BN2_MAX_D && (TND || (isAllSame && !isDeterministic) || bn2S2NotTndLimit) && …；bn2S2NotTndLimit（:1625-1630）要求 s1<s2 && s2≤BN2S2_MAX_S && s2-s1≥BN2_MAX_S && d≤BN2S2_WRITE_UB_D && !isSparse && !isDeterministic——s1==s2==2048 时 s1<s2 为假，此路不通，BN2S2 只剩 isAllSame && !isDeterministic 这一条。
- 否则 splitAxis = BN2GS1S2（:1646-1647）。
另外 BN2 模板自身要求 BN≥128（kernel 侧分块前提），B=1/N=4 的 BN=4 永远进不了 BN2 模板。
4. VF 每核每迭代负载（为何 vector 饱和）
- VECTOR_BASEM = CUBE_BASEM/CV_CORE_RATIO（kernel_base.h:88），CV_CORE_RATIO=2（common.h:115）→ VECTOR_BASEM=64；VECTOR_BASEN=CUBE_BASEN（kernel_base.h:89）=128；D=80 → HEAD_DIM_ALIGN=128；sfmgMaxLoopSize = VECTOR_BASEM·VECTOR_BASEN/HEAD_DIM_ALIGN（kernel_base.h:695）。
- VF1 ProcessVec1（block_vec.h:355-385）：softmaxGrad，每轮 halfS1RealSize(≈64) × 128 = 8192 元素（y/dy copyIn + FP16→FP32 cast + 计算）。
- VF2 ProcessVec2（block_vec.h:458-471）：pse + attenMask + muls + simpleSoftmax 作用在 64×128 的 mm2Res 上 = 8192 元素，含 exp、跨 128 维 reduce、div（softmax 全流程）。
- VF3 ProcessVec3（block_vec.h:545-627）：dropout + sub/mul（softmaxGrad×score - mm1res，64×128）+ FP32→FP16 cast + nd2nz + CopyUB2L1（block_vec.h:403-418，按 VECTOR_BASEN/FRACTAL_NZ_C0_SIZE 块搬）。
- VF4 ProcessVec4（block_vec.h:631-652）：p 矩阵 dropout + cast + CopyUB2L1。
- VF5/6 ProcessMulsAndCast（block_vec.h:655-718）：dq/dk/dv 的 muls+cast+写 GM，DQ 是 halfS1RealSize×dSize(80)、DK/DV 是 halfS2RealSize×80，各 ≈5120 元素。
合计每迭代每 AIV ≈ 4×8192 + 3×5120 ≈ 4.8 万元素操作，且 VF1/VF2 在两次 mm 之前、VF3/VF4 夹在 mm 之间串行（kernel.h:522→557→565→571），无跨核流水时 vector 天然是延迟瓶颈。D=80 被对齐到 128，VF 还有 37.5% 的无效元素开销。
5. 为什么「4 个 AIC 干活」与代码不完全自洽（PARTIAL/UNKNOWN）
- blockOuter=4 的公式只出现在 BN2 multiblk dense（b·n2·g=4），但该路径要求 b·n1≥128，B=1/N=4 被路由排除（tiling_common_regbase.cpp:1590-1591, 1596-1606）。
- 对 BN2GS1S2 dense：fusedOuter = 4·s1Outer·s2Outer；S=2048 下 s1Outer·s2Outer ≥ 32（FuzzyForBestSplit s1Inner=template.first/2，normal_regbase.cpp:1474-1481），blockOuter 正常应 ≥ aicNum，不可能只有 4 个核。
- 因此静态上无法解释用户观察，需要运行期信息才能定论：
1. 实际 splitAxis：是否走了 BN2S2（取决于 isAllSame 与 isDeterministic，tiling_common_regbase.cpp:1631-1639）还是 BN2GS1S2；
2. 实际 aicNum（normal_regbase.cpp:384-385，compileInfoPtr 下发）：若运行环境 aicNum=4（小核数/受限部署），BN2GS1S2 也会 blockOuter=4；
3. 是否实际是 TND 稀疏 / prefix（GetSparseBlockInfo/GetSparsePrefixBlockInfo，normal_regbase.cpp:1553-1622/1624+）而非非稀疏 BNSD；
4. enableSwizzle 只在 blockOuter == aicNum 时开（normal_regbase.cpp:442），可借此验证 blockOuter 是否真等于 aicNum。
最可能的合理解释：你看到的「4 AIC」来自分核轴只切到 b·n2·g=4 的核数上限（即该次运行 blockOuter=4），而 vector 打满则是因为每迭代 VF 的 ~4.8 万元素（含 exp/div/归约）在 64×128 tile 上无法被 cube 的 5 次 128×128×128 matmul（每次 2M MACs）掩盖——二者共同造成「AIC 空闲、AIV 满载」的表象。要坐实，请提供实际 tiling key（splitAxis）、aicNum、blockOuter 三个值。
▣  Uo-Query · DeepSeek V4 Flash Free · 1m 25s
Subagent(9 of 9)32.1K (16%)