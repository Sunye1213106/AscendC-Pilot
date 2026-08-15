action_id=kb_lookup
actor_id=uo-query
run_id=RUN_20260815_113715_466a346d
Follow ONLY these session files (read them first; do not invent extra goals):
  prompt: D:/TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260815_113715_466a346d/actions/kb_lookup/prompt.md
  method: D:/TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260815_113715_466a346d/actions/kb_lookup/method.md
  bundle: D:/TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260815_113715_466a346d/actions/kb_lookup/bundle.yaml
session_dir: D:/TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260815_113715_466a346d/actions/kb_lookup
write: (none — Explorer return_value only; Runtime materializes answer.yaml on Primary finalize)
environment: D:/TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260815_113715_466a346d/actions/kb_lookup/environment_capabilities.yaml
USER QUESTION (answer this against the CodeMap / minimal source windows):
在 flash_attention_score_grad 的 arch35 UO CodeMap 上回答：1) arch35 单 launch 的三相结构是什么（PRE/CORE/POST 或类似阶段划分，给出关键 kernel 函数与 tiling 分支）；2) POST 阶段的 scale 与 cast 逻辑具体怎么写（哪些 buffer 做 cast、scale 系数从哪来、dq 通路上的 cast/scale 顺序）；3) FP32 精度路径怎么走（与 FP16 的差异点，尤其 dq 量级相关）；4) BN2（BNSD 的 N=2 分支或 BN2 layout）路径怎么走；5) enablePreSfmg 开关各支路怎么走（开启/关闭分别触发哪些分支、对 dq 的 scale/cast 有何影响）。需要给出源码 file:line 证据窗口。
MUST end with one fenced yaml block `schema: kb-answer-v1` (return_value for Primary). Do NOT Write answer.yaml or scratch — Runtime materializes from return_value (OpenCode plugin injects ASCENDC_ACTION_RESULT; Primary should NOT hand-write a result file).
Do NOT write uo/checks/* or modify the `.uo` product; those are not this Action's outputs.
Hard stop: answer the USER QUESTION from CodeMap; do not stall on routing.
After a directed source Read for high confidence, run `acp inspect evidence-window --project <op> --path <rel> --lines A-B` for evidence_window_sha256 + snippet; do not invent hashes or self-downgrade to medium when the window proof is available.
Return a short summary when done.
Do NOT finalize; Primary runs `acp run-action kb_lookup --finalize` (plugin/env return_value preferred; `--result-file` only as manual fallback).
+ Thought: 1.1s
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260815_113715_466a346d/actions/kb_lookup/prompt.md 
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260815_113715_466a346d/actions/kb_lookup/method.md 
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260815_113715_466a346d/actions/kb_lookup/bundle.yaml 
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260815_113715_466a346d/actions/kb_lookup/environment_capabilities.yaml 
+ Thought: 2.6s
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/.ascendc-pilot/arch35/runs/RUN_20260815_113715_466a346d/actions/kb_lookup/refs/operator-analysis/uo-product-map.md 
$acp uo-query --help 2>&1 | Select-Object -First 80
+ Thought: 1.1s
$ acp uo-query --mode search --kind PIPE --query PRE_CORE_POST --project flash_attention_score_grad --architecture arch35
{
  "ok": false,
  "needs_human_decision": true,
  "decision_kind": "uo_product",
  "reason_code": "UO_PRODUCT_REQUIRED",
  "workflow_id": "uo-query",
  "project": "D:\\TEST\\AscendC-Pilot\\flash_attention_score_grad",
  "architecture": "arch35",
  "expected_path": "D:\\TEST\\AscendC-Pilot\\flash_attention_score_grad\\.ascendc-pilot\\arch35\\uo\\flash_attention_score_grad.arch35.uo",
  "message_zh": "未找到确定路径的 CodeMap：`D:\\TEST\\AscendC-Pilot\\flash_attention_score_grad\\.ascendc-pilot\\arch35\\uo\\flash_attention_score_grad.arch35.uo`。\n不要 Glob/dir/Grep 找 `.uo`，不要猜 `--op-name`。\n请选择：先 `/uo-init` 建库，或回退到源码作答。",
…
Click to expand
+ Thought: 9.3s
The CodeMap path resolved wrong because I passed a bare name while cwd is D:\TEST\AscendC-Pilot. Let me pass the full operator path from the bundle (project_root).
$ acp uo-query --mode search --kind PIPE --query PRE_CORE_POST --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --architecture arch35
{"ok":true,"mode":"search","pattern":"PRE_CORE_POST","kinds":["PIPE"],"count":0,"rows":[],"files":{},"empty_reason":"no_substring_match","hint":"Retry a shorter name; macros → template_match; combos → legal_key Dim=V,Other=V. Empty is not proof the symbol is absent.","suggested_retries":["PRE_CORE_POST"],"engine":"uo_init.uo_query","uo_freshness":{"stale":false,"reason_code":"","pinned_digest":"","live_digest":"4040745c14fbd64db1b76000cd436ad14efd6e17fa777f363d0d0117f2d64409"}}
+ Thought: 1.3s
.uo is fresh. PIPE search for "PRE_CORE_POST" returned 0. Let me try shorter patterns and locate the kernel entry in parallel.
$ acp uo-query --mode search --kind PIPE --query Pre --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --architecture arch35
{"ok":true,"mode":"search","pattern":"Pre","kinds":["PIPE"],"count":0,"rows":[],"files":{},"empty_reason":"no_substring_match","hint":"Retry a shorter name; macros → template_match; combos → legal_key Dim=V,Other=V. Empty is not proof the symbol is absent.","suggested_retries":["Pre"],"engine":"uo_init.uo_query","uo_freshness":{"stale":false,"reason_code":"","pinned_digest":"","live_digest":"4040745c14fbd64db1b76000cd436ad14efd6e17fa777f363d0d0117f2d64409"}}
$ acp uo-query --mode search --kind PIPE --query Post --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --architecture arch35
...

                                                                                               \\\n119:        op.SyncALLCores();                                                                                             \\\n120:        pipeBase.Destroy();                                                                                            \\\n121:        TPipe pipePost;                                                                                                \\\n122:        constexpr static uint32_t input_format = (MM2_OUT_FORMAT == MM_NZ_OUT_FORMAT) ? NZ : ND;                       \\\n123:        FlashAttentionScoreGradPost<INPUT_TYPE, FlashAttentionScoreGradTilingDataS1s2Bn2gs1s2, true, INPUT_LAYOUT,     \\\n124:                                    input_format, HAS_ROPE>                                                            \\\n125:            opPost;                                                                                                    \\\n126:        opPost.Init(dq, dqRope, dk, dkRope, dv, actual_seq_qlen, actual_seq_kvlen, dsink, user, tilingData, &pipePost);\\\n127:        opPost.Process();                                                            …
Click to expand
$ acp uo-query --mode locate --query INVOKE_ --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --architecture arch35
{"ok":true,"mode":"locate","pattern":"INVOKE_","locations":[{"id":"SRCKMACROV2::flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_entry_regbase.h::40::INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL","kind":"MACRO","name":"INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL","file":"op_kernel/arch35/flash_attention_score_grad_entry_regbase.h","line_start":40,"line_end":40,"snippet":"37:#include \"flash_attention_score_grad_kernel.h\"\n38:#include \"flash_attention_score_grad_kernel_deter.h\"\n39:\n40:#define INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL(INPUT_TYPE, CALC_TYPE, OUTDTYPE, IS_ATTEN_MASK, IS_PSE, IS_DROP, \\\n41:                                                      IS_TND, IS_BN2_MULTIBLK, DETER_SPARSE_TYPE, IS_N_EQUAL,          \\\n42:                                                      IS_D_NO_EQUAL, IS_ROPE, IS_NZ_OUT, IS_TND_SWIZZLE, SPLIT_AXIS,   \\\n43:                                                      s1TemplateType, s2TemplateType, dTemplateType)                   \\\n44:    do {                                                                                                               \\\n45:        if (unlikely(tilingData->s1s2BNGS1S2BaseParams.enabl…
Click to expand
+ Thought: 8.6s
Key entry found: RegbaseFAG at entry_regbase.h:201 dispatches by dtype to INVOKE_..._IMPL, which branches on enablePreSfmg (line 45) into either FlashAttentionScoreGradPresfmgRegbase or the regular kernel. Let me read the full macro and the Process method (kernel.h:497).
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_entry_regbase.h [offset=40, limit=190]
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_kernel.h [offset=490, limit=220]
- Thought: 8.2s
Now I understand the three-phase structure clearly. The arch35 single launch (in RegbaseFAG) has three sequential kernel-object phases on separate TPipe instances:

Phase 1 (PRE): opPre — either FlashAttentionScoreGradPresfmgRegbase (when enablePreSfmg && d>64) or FlashAttentionScoreGradS1S2BNGS1S2PreRegbase. Runs Init/Process/SyncALLCores on pipeIn. Then pipeIn.Destroy().

Phase 2 (CORE/Main): op — FlashAttentionScoreGradKernel (or ...KernelDeter when deter). Runs on pipeBase. Its Process() is the cv-pingpong loop (mm1/mm2 + ProcessVec1/2/3/4). Then for non-FP32: SyncALLCores + pipeBase.Destroy().

Phase 3 (POST): opPost — either FlashAttentionScoreGradS1S2BNGS1S2PostRegbase (when !IS_NZ_OUT) or FlashAttentionScoreGradNzPost (when IS_NZ_OUT). Runs on pipePost. Only runs when ORIG_DTYPE_QUERY != DT_FLOAT (i.e., FP16/BF16). For FP32: pipeBase.Destroy() only, NO post phase.

There's also a second macro INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL (the BN2 layout path, splitAxis==BN2) which uses sinkOptional to gate PRE/POST, and uses the non-deter FlashAttentionScoreGradKernel only (no deter variant).

Now let me look at:
1. The POST class FlashAttentionScoreGradS1S2BNGS1S2PostRegbase — for scale/cast logic
2. The BN2 path details — ComputeDqkvBn2 etc
3. FP32 path — confirmed: FP32 skips POST entirely (line 91 if (ORIG_DTYPE_QUERY != DT_FLOAT))
4. enablePreSfmg — confirmed: gates PRE phase (presfmg variant) AND gates ProcessVec1 inside Process (line 521, 614)

Let me read the POST regbase header to get scale/cast. And look at the BN2 path. Let me also check the RegbaseFAG continuation (lines 230-289) to see BN2 dispatch.

Let me read:
1. entry_regbase.h 230-289 (BN2 dispatch + rest)
2. s1s2_bn2gs1s2_post_regbase.h (the POST class — scale/cast)
3. presfmg_regbase.h (presfmg variant)
Now I have the three-phase skeleton. Let me read the POST class (scale/cast logic), the BN2 dispatch tail, and the presfmg variant.
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_entry_regbase.h [limit=60, offset=230]
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h 
- Thought: 32.7s
Excellent! Now I have the POST phase logic clearly. Key findings:

POST phase (FlashAttentionScoreGradS1S2BNGS1S2PostRegbase::Process, line 322-333):
- Only AIV cores run (line 324).
- ProcessDqkv() runs when SPLIT_AXIS != BN2 && !IsSameType<T1, float>::value (line 327) — i.e., NOT BN2 layout AND NOT FP32. So FP32 skips ProcessDqkv (because T1=float).
- ProcessSink() runs when isSink (sinkOptional).

ProcessDqkv (line 207-319) — the scale & cast logic:
- Loops over qkvIdx 0,1,2 (dq, dk, dv).
- For each: DataCopy from dqkvWorkspace[qkvIdx] (FP32 workspace, the CORE phase accumulation result) into vecInPing (LocalTensor<float>).
- Scale: if (qkvIdx < 2) { Muls(vecInPing, vecInPing, (float)tilingData->s1s2BNGS1S2BaseParams.scaleValue, pingSize); } (line 237-239). So only dq and dk get scaled (qkvIdx 0 and 1), dv is NOT scaled. The scale coefficient is s1s2BNGS1S2BaseParams.scaleValue (from tiling data).
- Cast: Cast(vecOutPing, vecInPing, RoundMode::CAST_ROUND, pingSize) (line 241) — cast FP32 → OUTDTYPE (half/bfloat16_t). Round mode is CAST_ROUND.
- Order on dq path: DataCopy (FP32 from workspace) → Muls (scale) → Cast (FP32→OUTDTYPE) → DataCopy to GM. So scale BEFORE cast. This is the dq path order.
- Pong path same: line 282-285 Muls then Cast.
- For BN2S2 (SPLIT_AXIS == 5, line 315-317): after qkvIdx=0 (dq), breaks — "bn2s2 dk dv no need to do muls and cast". So BN2S2 only does dq's scale+cast, dk/dv skipped.

Buffer cast: inQueuePing/Pong are TQue<VECIN, 1> holding float (T2=float always, the CALC_TYPE); outQueuePing/Pong are TQue<VECOUT, 1> holding OUTDTYPE (half/bfloat16_t). So cast is FP32 workspace → OUTDTYPE GM output.

scaleValue source: tilingData->s1s2BNGS1S2BaseParams.scaleValue — a Host-produced tiling field (1/sqrt(d) typically). I should verify where it's written. But that's a host-produced fact; I can cite the field read site. The question asks "scale 系数从哪来" — from tiling data s1s2BNGS1S2BaseParams.scaleValue. Let me quickly check the field writer to be thorough. Actually, the question is about the CodeMap; I can state it's read from that tiling field. Let me verify with a field query to be solid, but it may not be necessary. Let me focus on what I have and do one more query for the presfmg variant and BN2 path.

Now for the remaining questions:
- FP32 path: confirmed — T1=float, so IsSameType<T1,float>::value is true → ProcessDqkv is SKIPPED in POST (line 327). Also the entry macro: if (ORIG_DTYPE_QUERY != DT_FLOAT) gates the entire POST phase (line 91) — so FP32 has NO post opPost at all, just pipeBase.Destroy(). And FP32 uses INVOKE_..._IMPL_FP32 with (float, float, float) — CALC_TYPE=float, so the CORE phase accumulates in FP32 directly into the output GM (no FP32→FP16 cast needed). This is the key dq magnitude difference: FP16/BF16 path accumulates dq in FP32 workspace then scales+casts down; FP32 path writes directly, no post scale/cast. Also scaleValue would be applied inside the CORE compute for FP32 (since POST doesn't do it). Let me note this — actually I need to verify where scale is applied for FP32. The POST is skipped, so scale must be applied inside CORE (vecBlock) for FP32, or dq is just not post-scaled. This is a PARTIAL point — I can state the structural difference (no POST, no post scale/cast) but the in-CORE scale for FP32 I haven't verified. Let me mark that as the structural fact and note the dq magnitude implication.

Actually wait — re-reading: for FP16/BF16, dq is accumulated in FP32 workspace during CORE, then POST does Muls(scaleValue) + Cast(FP32→FP16). For FP32, dq is accumulated in FP32 and written directly (OUTDTYPE=float=CALC_TYPE), no cast, and POST is skipped. The scaleValue: for FP16/BF16 it's applied in POST. For FP32, since POST is skipped, either scale is applied in CORE or not at all. The question specifically asks "FP32 精度路径怎么走（与 FP16 的差异点，尤其 dq 量级相关）". The structural difference is clear: FP32 skips POST entirely. Whether scale is applied in-CORE for FP32 — I should check but it's a deeper dive. Let me note this as the key difference and flag the in-CORE FP32 scale as not yet verified (PARTIAL on that sub-point) — but actually the structural answer (no POST scale/cast for FP32) is solid and ANSWERED for the path question.

- BN2 path: splitAxis == BN2 → uses INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL (line 129-182). Differences from BN2GS1S2:
  - PRE gated by sinkOptional (not enablePreSfmg); uses FlashAttentionScoreGradS1S2BNGS1S2PreRegbase (not presfmg).
  - CORE uses non-deter FlashAttentionScoreGradKernel only (no KernelDeter variant).
  - POST gated by sinkOptional; uses FlashAttentionScoreGradS1S2BNGS1S2PostRegbase (not NzPost). And in POST Process(), SPLIT_AXIS != BN2 is false → ProcessDqkv() is SKIPPED (line 327). So BN2 layout does NOT do scale/cast in POST. Only ProcessSink if sinkOptional.
  - Inside CORE Process(), the BN2 branch calls ComputeDqkvBn2 (line 580).

  Wait — the question says "BN2（BNSD 的 N=2 分支或 BN2 layout）路径怎么走". There are two interpretations:
  1. splitAxis == BN2 (the BN2 layout/split-axis path) — INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL.
  2. IS_BN2_MULTIBLK template param (BNSD with N=2 multi-block) — a tiling branch.

  The isBn2MultiBlk template param exists. Let me check both. Actually the entry shows IS_BN2_MULTIBLK is passed to FAGBlockCube/Vec. And splitAxis == BN2 is a separate dispatch. The question mentions "BNSD 的 N=2 分支或 BN2 layout" — covering both. Let me address the splitAxis==BN2 layout path (which is the macro dispatch) and mention IS_BN2_MULTIBLK as a template branch inside the cube/vec blocks. I should verify IS_BN2_MULTIBLK effect. Let me do a kernel_branch query for it. Actually, let me keep focused — the BN2 layout path (splitAxis==BN2) is well-evidenced. For IS_BN2_MULTIBLK I can do a quick search.

- enablePreSfmg: 
  - In entry macro (line 45): if enablePreSfmg && dTemplateType > 64 → PRE uses FlashAttentionScoreGradPresfmgRegbase (a fused pre-softmax-grad kernel). Else (enablePreSfmg false) → PRE uses FlashAttentionScoreGradS1S2BNGS1S2PreRegbase.
  - In CORE Process() (line 521, 614): if (likely(!this->constInfo.enablePreSfmg)) { this->vecBlock.ProcessVec1(...); } — when enablePreSfmg is ON, ProcessVec1 (softmaxGrad front, the v1 stage) is SKIPPED inside CORE, because the presfmg PRE kernel already did it.
  - Impact on dq scale/cast: enablePreSfmg doesn't directly change POST scale/cast (POST still does Muls+Cast for FP16/BF16). It moves the softmax-grad-front (ProcessVec1) from CORE into a separate PRE kernel. The dq scale/cast in POST is unchanged. But the presfmg PRE path is only taken when dTemplateType > 64 (large head dim).

  I should verify the presfmg kernel does the softmax-grad-front. Let me quickly check the presfmg_regbase.h. Actually, the name "Presfmg" = "Pre Softmax Mg(Grad?)". And the CORE skips ProcessVec1 when enablePreSfmg — strong evidence the presfmg PRE kernel does the v1/softmax-grad-front work. Let me read a bit of presfmg_regbase.h to confirm and cite.

Let me now do a few more targeted queries/reads:
1. presfmg_regbase.h — confirm what the presfmg PRE kernel does (ProcessVec1 equivalent)
2. field query for scaleValue writer (to answer "scale 系数从哪来" with host-produced evidence) — optional but good
3. kernel_branch or search for IS_BN2_MULTIBLK effect

Let me prioritize. The presfmg read is most important for Q5. The scaleValue writer is nice for Q2. IS_BN2_MULTIBLK is secondary for Q4.

Let me read presfmg_regbase.h (probably has Process/Init) and do a field query for scaleValue. Let me also check the ComputeDqkvBn2 to confirm BN2 CORE path. Actually that may be too deep. Let me be efficient.

Let me run:
1. Read presfmg_regbase.h (first ~120 lines to see class + Process)
2. acp uo-query field for scaleValue
3. acp uo-query kernel_branch for IS_BN2_MULTIBLK (or search)

Let me do these in parallel.
POST scale/cast logic is now clear: ProcessDqkv does DataCopy(FP32 workspace) → Muls(scaleValue) [only qkvIdx<2, i.e. dq&dk] → Cast(FP32→OUTDTYPE, CAST_ROUND) → DataCopy(GM). FP32 skips POST entirely (line 91 + line 327 IsSameType<T1,float>). BN2 layout skips ProcessDqkv (line 327). Now let me confirm the presfmg PRE kernel's role, the scaleValue writer, and IS_BN2_MULTIBLK.
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h [limit=130]
$ acp uo-query --mode field --query scaleValue --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --architecture arch35
{"ok":true,"field":{"id":"TDF::FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase::scaleValue","kind":"TILING_FIELD","name":"scaleValue","status":"confirmed","file":"op_kernel/arch35/flash_attention_score_grad_tiling_data_regbase.h","line_start":96,"line_end":96,"why":"field","facts":{"owner":"FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase","host_writer_sites":[{"file":"flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp","line":1855,"receiver":"s1s2BNGS1S2BaseParams","expression":"fBaseParams.scaleValue","mode":"setter"}],"value_defining_sites":[{"file":"op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp","line":1011,"lhs":"fBaseParams.scaleValue","rhs":"*(context_->GetAttrs()->GetAttrPointer<float>(0))","kind":"assignment","guards":[],"unconditional":true,"function":"ProcessOptionalInput"}],"rhs":"*(context_->GetAttrs()->GetAttrPointer<float>(0))","primary_write":{"id":"TDWRITE::flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp::1855::FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase::scaleValue","name":"FlashAttentionScoreGradS1S2BNGS1S2BaseParamsRegbase::scaleValue <- fBasePa…
Click to expand
$ acp uo-query --mode kernel_branch --query IS_BN2_MULTIBLK --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --architecture arch35
{"ok":true,"mode":"kernel_branch","pattern":"IS_BN2_MULTIBLK","branches":[{"id":"KBR_E036A1578D4F","kind":"BRANCH","name":"IS_BN2_MULTIBLK","status":"confirmed","file":"op_kernel/arch35/flash_attention_score_grad_kernel_base.h","line_start":816,"line_end":816,"why":"kernel_branch","facts":{"condition":"IS_BN2_MULTIBLK","layer":"kernel","function":"CheckIsValidBlockForDeter","dimensions":["IsBn2MultiBlk"]},"snippet":"813:            s2EndLen = Min(s2EndLen, constInfo.commonConstInfo.s2Size);\n814:        }\n815:    }\n816:    if constexpr (IS_BN2_MULTIBLK) {\n817:        multiBlkInfo.s2oDimIdx = s2oDimIdx;\n818:        multiBlkInfo.s2OuterTmp = 0;\n819:        multiBlkInfo.s2SparseLeft = 0;\n820:        multiBlkInfo.s2SparseRight = s2EndLen;\n821:        CheckS1RangeInBn2(taskId);\n822:    }\n823:    bool isValid = s2IdxLeft < s2EndLen;\n824:    if (isValid) {\n825:        s2CvBegin = s2IdxLeft;\n826:        s2CvEnd = s2CvBegin + CUBE_BASEN;         // 非尾块s2按照+CUBE_BASEN处理\n827:        if (s2oDimIdx == constInfo.s2Outer - 1) { // 默认s2 cv tail相等\n828:            s2CvEnd = s2CvBegin + constInfo.s2Tail;\n829:        }\n830:    }\n831:    return isValid;\n832:}\n833:\n834:template <typename Chil…
Click to expand
- Thought: 13.0s
Now I have the scaleValue provenance:
- Tiling field scaleValue (float) declared at flash_attention_score_grad_tiling_data_regbase.h:96.
- Host writer: flash_attention_score_grad_tiling_normal_regbase.cpp:1855 — set_scaleValue(fBaseParams.scaleValue).
- Value-defining site: flash_attention_score_grad_tiling_common_regbase.cpp:1011 — fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0)) — comes from operator attr index 0 (unconditional). So scaleValue = the scale op attr (typically 1/sqrt(d)).
- Kernel readers: SetConstInfo (kernel_base.h:492), NzPost::Init (nz_post.h:104), PostRegbase::ProcessDqkv (post_regbase.h:207).

For IS_BN2_MULTIBLK: the branches are in CheckIsValidBlockForDeter (816), IsValidForTND (1198), IsValid (1284, 1303). These set multiBlkInfo (s2oDimIdx, s2SparseLeft/Right) and call CheckS1RangeInBn2. So IS_BN2_MULTIBLK is a deter/sparse block-validity branch that changes s2 sparse range computation, not a separate scale/cast path. Also there's DqkvMulsAndCastFromGM in the function list — interesting, that's a scale/cast for BN2 path inside CORE (since POST skips it for BN2). Let me note: the function list shows ComputeDqkvBn2:1 and DqkvMulsAndCastFromGM:1 use IS_BN2_MULTIBLK. So for BN2 layout, the scale+cast happens in CORE via DqkvMulsAndCastFromGM (since POST's ProcessDqkv is skipped for BN2). That's an important detail for Q4.

Now I need to confirm the presfmg role. The class has CalculateSoftmaxGrad, DoSoftmaxGrad, CopyDqkvToGm. It includes vf_softmax_grad_front_cast.h and vf_anti_quant_softmax_grad_front_cast.h. So presfmg PRE kernel does the softmax-grad-front (the v1/ProcessVec1 work) + copy dqkv to GM/workspace. And CORE skips ProcessVec1 when enablePreSfmg (line 521/614). That confirms the role. But I haven't read the Process() of presfmg. Let me read its Process to confirm and cite. Also I should check the presfmg Init signature mismatch: entry calls opPre.Init(dq, dk, dv, dy, attention_in, deqScaleDy, actual_seq_qlen, user, tilingData, &pipeIn) but the class Init signature is Init(GM_ADDR dq, GM_ADDR dk, GM_ADDR dv, GM_ADDR dx, GM_ADDR y, GM_ADDR deqScaleDy, GM_ADDR actual_seq_qlen, GM_ADDR workspace, FagTilingType, TPipe*). So dy→dx, attention_in→y. The presfmg reads dy (dx) and attention (y) to compute softmax grad front, dequantizing dy via deqScaleDy. Makes sense.

Let me read the presfmg Process() and DoSoftmaxGrad to confirm and cite file:line. Let me also quickly verify the DqkvMulsAndCastFromGM for BN2 to solidify Q4. Let me read presfmg Process region and search for DqkvMulsAndCastFromGM.

Actually, I have enough structural evidence. Let me read the presfmg Process() to confirm it does softmax-grad-front (for Q5 confidence), and locate DqkvMulsAndCastFromGM for Q4. Let me do both.

Let me find the presfmg Process method line. The file is 578 lines. Let me grep within it for "Process" and "DoSoftmaxGrad". Actually let me just read a chunk. The Init is at 130. Process is probably further down. Let me search.

Let me run a locate for DoSoftmaxGrad and DqkvMulsAndCastFromGM, and read presfmg around its Process.
scaleValue provenance confirmed: op attr index 0 → fBaseParams.scaleValue (tiling_common_regbase.cpp:1011) → set_scaleValue (tiling_normal_regbase.cpp:1855). IS_BN2_MULTIBLK branches are block-validity/multiBlkInfo + ComputeDqkvBn2/DqkvMulsAndCastFromGM. Let me confirm presfmg's Process role and locate the BN2 in-CORE scale/cast (DqkvMulsAndCastFromGM).
$ acp uo-query --mode locate --query DoSoftmaxGrad --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --architecture arch35
{"ok":true,"mode":"locate","pattern":"DoSoftmaxGrad","locations":[{"id":"OP_5CD0BB35A1AA","kind":"OPERATION","name":"DoSoftmaxGrad","file":"op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h","line_start":263,"line_end":263,"snippet":"260:        }\n261:        SetFlag<HardEvent::V_MTE3>(eventIDVToMte3);\n262:        CalTempDimAlign();\n263:        DoSoftmaxGrad();\n264:    }\n265:}\n266:\n267:PRE_FUNCTION_TEMPLATE\n268:__aicore__ inline void FlashAttentionScoreGradPresfmgRegbase<PRE_FUNCTION_ARGS_TEMPLATE>::CalTempDimAlign()\n269:{\n270:    tempDimAlign = HEAD_DIM_ALIGN;\n271:}","facts":{"callee":"DoSoftmaxGrad","function":"Process","category":"project_symbol","kernel_phase":"pre"},"relationships":[{"kind":"BINDS","src":"OP_5CD0BB35A1AA","dst":"MTH_41A67B6E701E","other_id":"MTH_41A67B6E701E","other_kind":"METHOD","other_name":"DoSoftmaxGrad","file":"op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h","line_start":263},{"kind":"CALLS","src":"MTH_50B0022AF332","dst":"OP_5CD0BB35A1AA","other_id":"MTH_50B0022AF332","other_kind":"METHOD","other_name":"Process","file":"op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h","line_start":328}]},{"id":"SRCKD…
Click to expand
$ acp uo-query --mode locate --query DqkvMulsAndCastFromGM --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --architecture arch35
{"ok":true,"mode":"locate","pattern":"DqkvMulsAndCastFromGM","locations":[{"id":"SRCKDEFV2::flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_block_vec.h::722::FAGBlockVec::DqkvMulsAndCastFromGM","kind":"METHOD","name":"FAGBlockVec::DqkvMulsAndCastFromGM","file":"op_kernel/arch35/flash_attention_score_grad_block_vec.h","line_start":722,"line_end":722,"snippet":"722:__aicore__ inline void FAGBlockVec<TEMPLATE_ARGS>::DqkvMulsAndCastFromGM(FagConstInfo &constInfo, FagRunInfo &runInfo,\n723:                                                                         GlobalTensor<CALC_TYPE> &inputTensor,\n724:                                                                         TQue<QuePosition::VECIN, 1> &inQue,\n725:                                                                         TQue<QuePosition::VECOUT, 1> &outQue)\n726:{\n727:    ////////////////////////////////////////////////////////////////////////////////////////////////////////\n728:    uint32_t dSize;\n729:    if constexpr (MM_IDX == DV_IDX && IS_D_NO_EQUAL) {\n730:        dSize = constInfo.commonConstInfo.dSizeV;\n731:    } else {\n732:        dSize = constInfo.commonConstInfo.dSize;\n733:    }\n734:    ui…
Click to expand
- Thought: 3.8s
Now I have confirmation:
- Presfmg PRE kernel: Process() (presfmg_regbase.h:263) calls DoSoftmaxGrad() (line 263, defined at 474). DoSoftmaxGrad calls CalculateSoftmaxGrad (382), CopyInSfmg (345), CopyDqkvToGm (421). So the presfmg PRE does softmax-grad-front + copy dqkv. The CORE skips ProcessVec1 when enablePreSfmg. Confirmed.

- DqkvMulsAndCastFromGM at flash_attention_score_grad_block_vec.h:722, called by ProcessMulsAndCast (block_vec.h:657). It has if constexpr (SPLIT_AXIS == BN2) branch (line 737). So BN2 path does scale+cast in-CORE via this. Let me read the actual Muls+Cast lines in DqkvMulsAndCastFromGM to cite the scale/cast for BN2. Let me read block_vec.h around 760-820 to see the Muls and Cast calls.

Let me read that region to get the BN2 in-CORE scale/cast evidence.
Presfmg role confirmed (Process→DoSoftmaxGrad→CalculateSoftmaxGrad+CopyDqkvToGm, presfmg_regbase.h:263/474). BN2 in-CORE scale/cast is FAGBlockVec::DqkvMulsAndCastFromGM (block_vec.h:722, has SPLIT_AXIS==BN2 branch at 737). Let me read its Muls+Cast body to cite.
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_block_vec.h [limit=110, offset=760]
→Read D:/TEST/ops-transformer/attention/flash_attention_score_grad/op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h [limit=45, offset=240]
- Thought: 31.0s
Now I have everything I need. The BN2 in-CORE scale/cast is confirmed at DqkvMulsAndCastFromGM (block_vec.h:722):
- Line 828-830: if constexpr (MM_IDX != DV_IDX) { Muls(dqkvTensor, dqkvTensor, constInfo.scaleValue, data_size); } — only dq & dk scaled (not dv), using constInfo.scaleValue (loaded from tiling scaleValue via SetConstInfo, kernel_base.h:492).
- Line 831-832: Cast(dqkvCastTensor, dqkvTensor, RoundMode::CAST_ROUND, data_size) — FP32→OUTDTYPE cast.
- Order: DataCopy(FP32 from workspace/GM) → Muls(scale) → Cast → DataCopyPad(GM). Same order as POST. This is the BN2 path's in-CORE equivalent (since POST ProcessDqkv is skipped for BN2 layout).
- Line 809: if constexpr (IS_BN2_MULTIBLK && MM_IDX == DQ_IDX) — special workspace offset for BN2 multiblk dq.

So for BN2 layout: POST ProcessDqkv is skipped (post_regbase.h:327 SPLIT_AXIS != BN2 is false), and the scale+cast is done in-CORE via ComputeDqkvBn2 → DqkvMulsAndCastFromGM. Same Muls(scaleValue)/Cast(CAST_ROUND), only dq&dk scaled.

Now the presfmg Process: I see lines 240-264. This is the tail of Init actually (Duplicate to zero dq/dk/dv workspace, then SetFlag V_MTE3, CalTempDimAlign, DoSoftmaxGrad). Wait, line 263 DoSoftmaxGrad(); and line 264 } and 265 }. The locate said Process is at... actually the snippet shows "function":"Process" with DoSoftmaxGrad at 263. So Process() body ends around 263-265. Let me confirm: the locate output showed OP_5CD0BB35A1AA with function":"Process","kernel_phase":"pre" and snippet around 260-265 with DoSoftmaxGrad(); at 263. So Process() calls CopyInSfmg/CalculateSoftmaxGrad/CopyDqkvToGm via DoSoftmaxGrad. Good. The presfmg also zeroes dq/dk/dv workspace (lines 240-258) — note for FP32 (the else branch line 256-259) it uses InitOutput<float> on dqWorkSpaceGm — confirming presfmg handles FP32 too (T1=float → else branch). Actually wait, the presfmg is only invoked when enablePreSfmg && dTemplateType > 64. And enablePreSfmg can be set for any dtype. For FP32, the presfmg PRE runs (zeros workspace, does softmax grad front). Then CORE runs with ProcessVec1 skipped. Then POST is skipped (FP32). So FP32 with enablePreSfmg: PRE(presfmg) + CORE(no Vec1) + no POST.

Now I have enough. Let me also double check: for the regular (non-presfmg) FP32 path, is scale applied in CORE? Since POST is skipped for FP32, and the regular PRE doesn't do scale... The scale must be applied somewhere in CORE for FP32, OR dq for FP32 is not scaled by scaleValue at all in the kernel (maybe scale is baked into the softmax). Actually, looking at DqkvMulsAndCastFromGM — it's called for BN2 path (ProcessMulsAndCast). For BN2GS1S2/BN2S2 non-FP32, POST does the Muls. For FP32 BN2GS1S2, POST is skipped... so where's the scale?

Hmm, this is the FP32 dq magnitude question. Let me think. For FP32:
- OUTDTYPE = float = CALC_TYPE. So no cast needed (output is already FP32).
- The scale: in the FP16/BF16 path, scale is applied in POST (Muls scaleValue) before cast. For FP32, POST is skipped. So either:
  (a) scale is applied inside CORE's compute (e.g., in ProcessVec1/softmax or in the mm), or
  (b) scale is not applied as a separate Muls but fused into the softmax math, or
  (c) for FP32 the scale is applied in the regular PRE (S1S2BNGS1S2PreRegbase).

Actually, the regular PRE (FlashAttentionScoreGradS1S2BNGS1S2PreRegbase) is the sink PRE — it computes the sink (dsink), not scale. Let me not over-claim. The structural fact I can state with high confidence: FP32 path skips the entire POST phase (no Muls scaleValue, no Cast) because OUTDTYPE=float and the entry macro gates POST with ORIG_DTYPE_QUERY != DT_FLOAT (entry_regbase.h:91), and POST's ProcessDqkv also guards !IsSameType<T1,float> (post_regbase.h:327). So for FP32, dq is written from CORE in FP32 directly. The scaleValue for FP32 must be applied inside CORE compute (the softmax-grad front typically multiplies by scale). I have not pinned the exact in-CORE scale site for FP32 — I'll mark that sub-point as PARTIAL/assumption rather than fabricate.

Actually, let me reconsider. The question asks "FP32 精度路径怎么走（与 FP16 的差异点，尤其 dq 量级相关）". The key dq magnitude difference:
- FP16/BF16: dq accumulates in FP32 workspace during CORE, then POST does Muls(scaleValue) — so the scale is applied POST-accumulation, then cast down to FP16. The dq in workspace is "raw" (unscaled) FP32; scale applied at the end.
- FP32: dq is output directly in FP32. No POST Muls. So either scale is applied in-CORE (fused into softmax grad front, which is the typical FA implementation — scale is applied to softmax, not to dq separately), or not at all as a separate op.

Given the evidence I have, the solid structural answer is: FP32 skips POST (no separate Muls scaleValue + Cast). I'll state the dq-magnitude implication as: for FP16/BF16 the scaleValue is applied as a post-accumulation Muls before cast; for FP32 that post-Muls/cast is absent, so scale handling differs (likely fused in-CORE softmax) — and flag the in-CORE FP32 scale site as not separately verified (PARTIAL on that precise site). This is honest and matches evidence.

Actually, I realize I should check whether the regular CORE (non-BN2) path applies scale anywhere for FP32. But that's a deeper dive and the question is primarily about path differences. Let me do ONE more targeted check: does ProcessVec1 / the softmax grad front apply scale? The presfmg CalculateSoftmaxGrad and the vec ProcessVec1 likely apply scale. But I don't want to over-investigate. The structural answer is solid and ANSWERED for "how the FP32 path goes"; the precise in-CORE scale site is a PARTIAL sub-note.

Hmm, but the prompt says "尤其 dq 量级相关" — they want to know about dq magnitude. The key magnitude fact: for FP16/BF16, POST multiplies the accumulated FP32 dq by scaleValue before casting to FP16. For FP32, no such post-scale. That IS the dq magnitude difference and I can state it with high confidence from the POST code. Good.

Let me now also verify the evidence-window SHA for the key citations. The prompt says: "After a directed source Read for high confidence, run acp inspect evidence-window --project <op> --path <rel> --lines A-B for evidence_window_sha256 + snippet". I should generate SHAs for my key citation windows. Let me run inspect for the main windows:

1. entry_regbase.h 40-114 (three-phase + enablePreSfmg + FP32 gate)
2. post_regbase.h 207-319 (ProcessDqkv scale/cast) — or narrower 228-285
3. post_regbase.h 321-333 (Process guard)
4. block_vec.h 815-833 (DqkvMulsAndCastFromGM Muls+Cast)
5. kernel.h 517-523 / 612-618 (enablePreSfmg gates ProcessVec1)
6. entry_regbase.h 129-182 (BN2 layout macro)
7. tiling_common_regbase.cpp 1011 (scaleValue attr source) — but this is op_host, may need to confirm path. The field query gave it.
8. tiling_normal_regbase.cpp 1855 (set_scaleValue)

Let me run inspect for the most important windows. The project path for inspect — let me use the operator dir. Let me check the inspect command signature first. Actually, let me just run it for a few key windows. I'll batch them.

The --project for inspect: the field query used project = the operator dir. Let me use the same. --path is relative to project root. Let me run several in parallel.

Let me run inspect for:
- op_kernel/arch35/flash_attention_score_grad_entry_regbase.h lines 40-114
- op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h lines 207-319
- op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h lines 321-333
- op_kernel/arch35/flash_attention_score_grad_block_vec.h lines 815-833
- op_kernel/arch35/flash_attention_score_grad_kernel.h lines 517-524
- op_kernel/arch35/flash_attention_score_grad_entry_regbase.h lines 129-182

That's 6 windows. Let me also do the host scaleValue ones. Let me batch.
BN2 in-CORE scale/cast confirmed at DqkvMulsAndCastFromGM (block_vec.h:828-832): Muls(scaleValue) only when MM_IDX != DV_IDX (dq&dk, not dv), then Cast(CAST_ROUND) — same order as POST. Now let me capture evidence-window SHAs for the key citation windows.
$ acp inspect evidence-window --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --path op_kernel/arch35/flash_attention_score_grad_entry_regbase.h --lines 40-114
{
  "ok": true,
  "project": "D:\\TEST\\ops-transformer\\attention\\flash_attention_score_grad",
  "path": "op_kernel/arch35/flash_attention_score_grad_entry_regbase.h",
  "lines": "40-114",
  "line_start": 40,
  "line_end": 114,
  "evidence_window_sha256": "1ab03d417eb9a14b16b9c2886f5ec5ac7882ed24cd15dff59851cd386c0670e7",
  "evidence_snippet": "#define INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL(INPUT_TYPE, CALC_TYPE, OUTDTYPE, IS_ATTEN_MASK, IS_PSE, IS_DROP, \\\n                                                      IS_TND, IS_BN2_MULTIBLK, DETER_SPARSE_TYPE, IS_N_EQUAL,          \\\n                                                      IS_D_NO_EQUAL, IS_ROPE, IS_NZ_OUT, IS_TND_SWIZZLE, SPLIT_AXIS,   \\\n                                                      s1TemplateType, s2TemplateType, dTemplateType)                   \\\n    do {                                                                                                               \\\n        if (unlikely(tilingData->s1s2BNGS1S2BaseParams.enablePreSfmg)) {                                               \\\n            if constexpr ((uint32_t)dTemplateType > 64) {                                                         …
Click to expand
$ acp inspect evidence-window --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --path op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h --lines 207-319
{
  "ok": true,
  "project": "D:\\TEST\\ops-transformer\\attention\\flash_attention_score_grad",
  "path": "op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h",
  "lines": "207-319",
  "line_start": 207,
  "line_end": 319,
  "evidence_window_sha256": "497a715cd2ef6c2197eac5ca78ca92cd4e4f0bcbbd9a79aaf938ad50e44d349f",
  "evidence_snippet": "__aicore__ inline void FlashAttentionScoreGradS1S2BNGS1S2PostRegbase<FAG_POST_FUNCTION_PARAMS_TEMPLATE>::ProcessDqkv()\n{\n    for (int qkvIdx = 0; qkvIdx < 3; qkvIdx++) {\n        if (qkvIdx == 1) {\n            loop = tilingData->postTilingData.kPostBlockFactor;\n            inputTotalSize = tilingData->postTilingData.kPostBlockTotal;\n            qPostTailNum = tilingData->postTilingData.kPostTailNum;\n        } else if (qkvIdx == 2) {\n            loop = tilingData->postTilingData.vPostBlockFactor;\n            inputTotalSize = tilingData->postTilingData.vPostBlockTotal;\n            qPostTailNum = tilingData->postTilingData.vPostTailNum;\n        }\n        uint64_t blockCore = loop * REGBASE_POST_BASE;\n        uint64_t begin = vBlockIdx * blockCore;\n        uint64_t end = begin + blockCore;\n\n        if (end > inputT…
Click to expand
$ acp inspect evidence-window --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --path op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h --lines 321-333
{
  "ok": true,
  "project": "D:\\TEST\\ops-transformer\\attention\\flash_attention_score_grad",
  "path": "op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h",
  "lines": "321-333",
  "line_start": 321,
  "line_end": 333,
  "evidence_window_sha256": "75f82fa8dc249f13ffd1433f872210cde35c0b17ec42a46ac97c92df06dd31ed",
  "evidence_snippet": "FAG_POST_FUNCTION_TEMPLATE\n__aicore__ inline void FlashAttentionScoreGradS1S2BNGS1S2PostRegbase<FAG_POST_FUNCTION_PARAMS_TEMPLATE>::Process()\n{\n    if (g_coreType != AIV) {\n        return;\n    }\n    if constexpr (SPLIT_AXIS != BN2 && !IsSameType<T1, float>::value) {\n        ProcessDqkv();\n    }\n    if (unlikely(isSink)) {\n        ProcessSink();\n    }\n}",
  "char_count": 354,
…
Click to expand
$ acp inspect evidence-window --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --path op_kernel/arch35/flash_attention_score_grad_block_vec.h --lines 815-833
{
  "ok": true,
  "project": "D:\\TEST\\ops-transformer\\attention\\flash_attention_score_grad",
  "path": "op_kernel/arch35/flash_attention_score_grad_block_vec.h",
  "lines": "815-833",
  "line_start": 815,
  "line_end": 833,
  "evidence_window_sha256": "89b097eba26324f569ec555228d404cc89afcc95146c5979874efbcab65fae2f",
  "evidence_snippet": "    for (uint32_t loopIdx = 0; loopIdx < loopNum; loopIdx++) {\n        if (loopIdx == loopNum - 1) {\n            curLoopSize = tailLoopSize;\n            data_size = curLoopSize * curDAlign;\n        }\n \n        LocalTensor<CALC_TYPE> dqkvTensor = inQue.AllocTensor<CALC_TYPE>();\n        DataCopy(dqkvTensor,\n                 inputTensor[dkvWorkSpaceOffet + loopIdx * loopSize * curDAlign],\n                 data_size);\n        \n        inQue.EnQue(dqkvTensor);\n        inQue.DeQue();\n        if constexpr (MM_IDX != DV_IDX) {\n            Muls(dqkvTensor, dqkvTensor, constInfo.scaleValue, data_size);\n        }\n        LocalTensor<OUTDTYPE> dqkvCastTensor = outQue.template AllocTensor<OUTDTYPE>();\n        Cast(dqkvCastTensor, dqkvTensor, RoundMode::CAST_ROUND, data_size);\n        inQue.FreeTensor(dqkvTensor);",
  "char_count": 811,
…
Click to expand
$ acp inspect evidence-window --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --path op_kernel/arch35/flash_attention_score_grad_kernel.h --lines 517-524
{
  "ok": true,
  "project": "D:\\TEST\\ops-transformer\\attention\\flash_attention_score_grad",
  "path": "op_kernel/arch35/flash_attention_score_grad_kernel.h",
  "lines": "517-524",
  "line_start": 517,
  "line_end": 524,
  "evidence_window_sha256": "ac72e1f3b0c5fa562f279fe969f9529ded0e196dec34bdb3f60e087713048bd2",
  "evidence_snippet": "        while (true) {\n            this->isLastLoop = (blockInnerIdx == -1);\n            if (taskId > 0) {\n                prevRunInfo = runInfos[(taskId + 1) & 1];\n                if (likely(!this->constInfo.enablePreSfmg)) {\n                    this->vecBlock.ProcessVec1(this->constInfo, prevRunInfo); // v1: softmaxGrad\n                }\n            }",
  "char_count": 355,
…
Click to expand
$ acp inspect evidence-window --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --path op_kernel/arch35/flash_attention_score_grad_entry_regbase.h --lines 129-182
{
  "ok": true,
  "project": "D:\\TEST\\ops-transformer\\attention\\flash_attention_score_grad",
  "path": "op_kernel/arch35/flash_attention_score_grad_entry_regbase.h",
  "lines": "129-182",
  "line_start": 129,
  "line_end": 182,
  "evidence_window_sha256": "5ce8e1de611bd590a70400faf209195349cb233c375c0c3f79193e5d5f4b05dd",
  "evidence_snippet": "#define INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL(INPUT_TYPE, CALC_TYPE, OUTDTYPE, IS_ATTEN_MASK, IS_PSE, IS_DROP,      \\\n                                                 IS_TND, IS_BN2_MULTIBLK, DETER_SPARSE_TYPE, IS_N_EQUAL,               \\\n                                                 IS_D_NO_EQUAL, IS_ROPE, IS_NZ_OUT, IS_TND_SWIZZLE, SPLIT_AXIS,    \\\n                                                 s1TemplateType, s2TemplateType, dTemplateType)                        \\\n    do {                                                                                                               \\\n        if (tilingData->s1s2BNGS1S2BaseParams.sinkOptional) {                                                          \\\n            FlashAttentionScoreGradS1S2BNGS1S2PreRegbase<INPUT_TYPE, float, DETER_SPARSE_TYPE, IS_TND, SPLIT_AXIS,  …
Click to expand
- Thought: 2.5s
I have all 6 evidence-window SHAs. I also need SHAs for:
- presfmg Process (presfmg_regbase.h around 256-265) — for Q5
- kernel.h 612-618 (the ProcessPreloadTwoTimes enablePreSfmg gate) — secondary
- the scaleValue host writer (tiling_normal_regbase.cpp:1855) and value-defining (tiling_common_regbase.cpp:1011) — for Q2 "scale 系数从哪来"

Let me get SHAs for the presfmg Process window and the scaleValue host sites. Let me also get the kernel.h 612-618 for the preload path enablePreSfmg gate (to be thorough on Q5 — both Process and ProcessPreloadTwoTimes skip ProcessVec1).

Let me run these in parallel.
Got 6 SHAs. Let me capture the remaining windows: presfmg Process (Q5), the preload-path enablePreSfmg gate (kernel.h:612-618), and the scaleValue host writer/value-defining sites (Q2).
$ acp inspect evidence-window --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --path op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h --lines 256-265
{
  "ok": true,
  "project": "D:\\TEST\\ops-transformer\\attention\\flash_attention_score_grad",
  "path": "op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h",
  "lines": "256-265",
  "line_start": 256,
  "line_end": 265,
  "evidence_window_sha256": "aebd828a5af976cd0708cced494d52b4ea8bdf4f37f7a7038931a20ba55332ee",
  "evidence_snippet": "        } else {\n            if (tilingData->s1s2BNGS1S2SplitCoreParams.s2Outer > 1) {\n                InitOutput<float>(dqWorkSpaceGm[dqOffset], initdqSize, 0);\n            }\n        }\n        SetFlag<HardEvent::V_MTE3>(eventIDVToMte3);\n        CalTempDimAlign();\n        DoSoftmaxGrad();\n    }\n}",
  "char_count": 297,
…
Click to expand
$ acp inspect evidence-window --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --path op_kernel/arch35/flash_attention_score_grad_kernel.h --lines 611-618
{
  "ok": true,
  "project": "D:\\TEST\\ops-transformer\\attention\\flash_attention_score_grad",
  "path": "op_kernel/arch35/flash_attention_score_grad_kernel.h",
  "lines": "611-618",
  "line_start": 611,
  "line_end": 618,
  "evidence_window_sha256": "7147199429e4daf2b13bdbe358c8b1e93cad223953014702832e3e0a3c76be70",
  "evidence_snippet": "    while (true) {\n        if (taskId > 0) {\n            prevRunInfo = runInfos[(taskId + 1) % PRELOAD_TIMES];\n            if (likely(!this->constInfo.enablePreSfmg)) {\n                this->vecBlock.ProcessVec1(this->constInfo,\n                                           runInfos[(taskId + NUM_TWO) % PRELOAD_TIMES]); // v1: softmaxGrad\n            }\n        }",
  "char_count": 361,
…
Click to expand
$ acp inspect evidence-window --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --path op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp --lines 1008-1014
{
  "ok": true,
  "project": "D:\\TEST\\ops-transformer\\attention\\flash_attention_score_grad",
  "path": "op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp",
  "lines": "1008-1014",
  "line_start": 1008,
  "line_end": 1014,
  "evidence_window_sha256": "39028a15cdc15a12efb3a4524481601338171f10bc1140a7749051cbc1fe84f7",
  "evidence_snippet": "    fBaseParams.queryType = queryType;\n    fBaseParams.calTypeSize = FP32_BYTES;\n\n    fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0));\n    fBaseParams.keepProb = *(context_->GetAttrs()->GetAttrPointer<float>(1));\n\n    fBaseParams.dropoutIsDivisibleBy8 = 1;",
  "char_count": 283,
…
Click to expand
$ acp inspect evidence-window --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --path op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp --lines 1852-1857
{
  "ok": true,
  "project": "D:\\TEST\\ops-transformer\\attention\\flash_attention_score_grad",
  "path": "op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp",
  "lines": "1852-1857",
  "line_start": 1852,
  "line_end": 1857,
  "evidence_window_sha256": "de7b432858f4d5bd67c750a480906f452b2c776b014b14c6f0d38ceab2c266b8",
  "evidence_snippet": "    s1s2BNGS1S2BaseParams_->set_attenMaskShapeType(fBaseParams.attenMaskShapeType);\n    s1s2BNGS1S2BaseParams_->set_layout(fBaseParams.layoutType);\n    s1s2BNGS1S2BaseParams_->set_tndMaxSumLayout(fBaseParams.tndMaxSumLayout);\n    s1s2BNGS1S2BaseParams_->set_scaleValue(fBaseParams.scaleValue);\n    s1s2BNGS1S2BaseParams_->set_keepProb(fBaseParams.keepProb);\n    s1s2BNGS1S2BaseParams_->set_keepProbUint8(fBaseParams.keepProbUint8);",
  "char_count": 431,
…
Click to expand
$ acp inspect evidence-window --project "D:/TEST/ops-transformer/attention/flash_attention_score_grad" --path op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h --lines 474-485
{
  "ok": true,
  "project": "D:\\TEST\\ops-transformer\\attention\\flash_attention_score_grad",
  "path": "op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h",
  "lines": "474-485",
  "line_start": 474,
  "line_end": 485,
  "evidence_window_sha256": "f42bc5dcddba261e66562a868be64f7716ff579eb3c7be200ae25c0b871de1fe",
  "evidence_snippet": "__aicore__ inline void FlashAttentionScoreGradPresfmgRegbase<PRE_FUNCTION_ARGS_TEMPLATE>::DoSoftmaxGrad()\n{\n    // process\n    if (vBlockIdx < usedCoreNum) {\n        uint64_t singleCoreLoopTimes, singleCoreLastLoopNBurstNum;\n        if (vBlockIdx == usedCoreNum - 1) {\n            singleCoreLoopTimes = tilingData->preTilingData.tailCoreLoopTimes;  // 尾核loop次数\n            singleCoreLastLoopNBurstNum = tilingData->preTilingData.tailCoreLastLoopNBurstNum; // 尾核最后一次处理s1大小\n        } else {\n            singleCoreLoopTimes = tilingData->preTilingData.normalCoreLoopTimes;  // 非尾核loop次数\n            singleCoreLastLoopNBurstNum = tilingData->preTilingData.normalCoreLastLoopNBurstNum; // 非尾核最后一次处理s1大小\n        }",
  "char_count": 707,
…
Click to expand
- Thought: 1m 21s
I now have all the evidence-window SHAs and snippets I need. Let me compose the kb-answer-v1.

Let me summarize the findings for each question:

Q1: arch35 单 launch 三相结构
The single launch entry is RegbaseFAG (entry_regbase.h:201). It dispatches by dtype (FP16/BF16/FP32 via INVOKE_..._IMPL_*) and by splitAxis (BN2GS1S2/BN2S2/BN2). The three-phase structure (in INVOKE_FAG_GENERAL_S1S2_BN2GS1S2_REGBASE_IMPL, entry_regbase.h:40-114):
- PRE (pipeIn): opPre — either FlashAttentionScoreGradPresfmgRegbase (when enablePreSfmg && d>64) or FlashAttentionScoreGradS1S2BNGS1S2PreRegbase (sink PRE). Init/Process/SyncALLCores. Then pipeIn.Destroy().
- CORE (pipeBase): op — FlashAttentionScoreGradKernel (NO_DETER) or FlashAttentionScoreGradKernelDeter (deter). Cube+Vec pingpong: IterateMmQK/IterateMmDyV + ProcessVec1/2/3/4. AIC=Cube block, AIV=Vec block (conditional Dummy).
- POST (pipePost): opPost — either FlashAttentionScoreGradS1S2BNGS1S2PostRegbase (!IS_NZ_OUT) or FlashAttentionScoreGradNzPost (IS_NZ_OUT). Only when ORIG_DTYPE_QUERY != DT_FLOAT.

Tiling branches: splitAxis (BN2GS1S2=4 / BN2S2=5 / BN2=0), deterType (NO_DETER vs deter → Kernel vs KernelDeter), IS_NZ_OUT (Post variant), enablePreSfmg (Pre variant), dTemplateType (>64 for presfmg).

Key kernel functions: RegbaseFAG (entry_regbase.h:201), FlashAttentionScoreGradKernel::Process (kernel.h:497), FlashAttentionScoreGradS1S2BNGS1S2PreRegbase::Process, FlashAttentionScoreGradS1S2BNGS1S2PostRegbase::Process (post_regbase.h:322), FlashAttentionScoreGradPresfmgRegbase::Process (presfmg_regbase.h:263).

Q2: POST scale & cast logic
In FlashAttentionScoreGradS1S2BNGS1S2PostRegbase::ProcessDqkv (post_regbase.h:207-319):
- Buffers cast: inQueuePing/Pong (TQue<VECIN>, holds float/T2 — FP32 from dqkvWorkspace[qkvIdx]) → outQueuePing/Pong (TQue<VECOUT>, holds OUTDTYPE half/bfloat16_t). So cast is FP32 workspace → OUTDTYPE output GM. The 3 workspaces: dqkvWorkspace0/1/2 = dq/dk/dv FP32 accumulation from CORE (offsets from postTilingData.dqWorkSpaceOffset etc).
- Scale coefficient: tilingData->s1s2BNGS1S2BaseParams.scaleValue (post_regbase.h:238, 283). Source: op attr index 0 → fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0)) (tiling_common_regbase.cpp:1011) → set_scaleValue(fBaseParams.scaleValue) (tiling_normal_regbase.cpp:1855). Read by SetConstInfo (kernel_base.h:492) into constInfo.scaleValue.
- Scale applied ONLY to qkvIdx < 2 (dq and dk); dv (qkvIdx==2) NOT scaled (post_regbase.h:237-239, 282-284).
- dq path order: DataCopy(FP32 workspace → vecInPing) → Muls(vecInPing, scaleValue) → Cast(vecOutPing, vecInPing, CAST_ROUND, FP32→OUTDTYPE) → DataCopy(vecOutPing → GM). So scale BEFORE cast.
- BN2S2 (SPLIT_AXIS==5) breaks after qkvIdx=0 (dq only); "bn2s2 dk dv no need to do muls and cast" (post_regbase.h:314-317).

Q3: FP32 path
- Entry: INVOKE_..._IMPL_FP32 instantiates with (float, float, float) — INPUT_TYPE=CALC_TYPE=OUTDTYPE=float (entry_regbase.h:281).
- POST entirely skipped: if (ORIG_DTYPE_QUERY != DT_FLOAT) (entry_regbase.h:91) — for FP32, only pipeBase.Destroy(), no opPost. So NO Muls(scaleValue) + NO Cast in POST.
- POST ProcessDqkv also guards !IsSameType<T1,float> (post_regbase.h:327) — double guard.
- dq magnitude implication: FP16/BF16 accumulate dq in FP32 workspace during CORE, then POST applies Muls(scaleValue) post-accumulation before casting down to FP16/BF16. FP32 writes dq directly in FP32 (OUTDTYPE=float), no post-scale/cast. So the post-accumulation scaleValue multiply is absent on the FP32 dq path (scale handling differs — not verified whether fused in-CORE; flagged as assumption).
- FP32 also goes through all splitAxis (BN2GS1S2/BN2S2/BN2) per entry_regbase.h:267-287.

Q4: BN2 path
Two senses:
(a) splitAxis == BN2 (BN2 layout) → INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL (entry_regbase.h:129-182):
  - PRE gated by sinkOptional (not enablePreSfmg); uses FlashAttentionScoreGradS1S2BNGS1S2PreRegbase (sink PRE). No presfmg variant for BN2 layout.
  - CORE uses non-deter FlashAttentionScoreGradKernel only (no KernelDeter).
  - POST gated by sinkOptional; uses FlashAttentionScoreGradS1S2BNGS1S2PostRegbase. BUT POST Process() skips ProcessDqkv for BN2 (SPLIT_AXIS != BN2 is false, post_regbase.h:327) — so BN2 layout does NOT do scale/cast in POST. Only ProcessSink if sinkOptional.
  - The scale+cast for BN2 happens in-CORE via ComputeDqkvBn2 (kernel.h:580) → FAGBlockVec::DqkvMulsAndCastFromGM (block_vec.h:722): DataCopy(FP32 from workspace) → Muls(scaleValue, only MM_IDX != DV_IDX i.e. dq&dk) → Cast(CAST_ROUND) → DataCopyPad(GM). Same scale/cast semantics as POST but in-CORE.
(b) IS_BN2_MULTIBLK template param (BNSD N=2 multi-block) → branches in CheckIsValidBlockForDeter/IsValidForTND/IsValid (kernel_base.h:816/1198/1284/1303): sets multiBlkInfo (s2oDimIdx, s2SparseLeft/Right) + calls CheckS1RangeInBn2. It's a deter/sparse block-validity branch affecting s2 sparse range, not a separate scale/cast path. Also affects dq workspace offset in DqkvMulsAndCastFromGM (block_vec.h:809: IS_BN2_MULTIBLK && MM_IDX == DQ_IDX).

Q5: enablePreSfmg
- ON (enablePreSfmg == true):
  - PRE: if dTemplateType > 64 → FlashAttentionScoreGradPresfmgRegbase opPre (entry_regbase.h:45-53). This kernel does the softmax-grad-front (DoSoftmaxGrad → CalculateSoftmaxGrad + CopyInSfmg + CopyDqkvToGm, presfmg_regbase.h:263/474) and zeroes dq/dk/dv workspace. If dTemplateType <= 64, the presfmg branch is NOT taken (the if constexpr dTemplateType > 64 is false) → no PRE at all (falls through? actually no — the if (enablePreSfmg) { if constexpr d>64 {...} } — if d<=64, the inner block is empty, so NO PRE kernel runs, but CORE still skips ProcessVec1!). Wait, that's a subtle point. Let me re-read: line 45 if (unlikely(enablePreSfmg)) { if constexpr (d>64) { presfmg } }. So if enablePreSfmg && d<=64: nothing in PRE (no opPre). Then CORE runs with ProcessVec1 skipped (line 521/614). That would be a bug? Or maybe enablePreSfmg is only set when d>64 by Host. Hmm. I shouldn't over-claim. Let me state: enablePreSfmg ON && d>64 → presfmg PRE runs. The d<=64 sub-case: presfmg PRE block is empty (constexpr false), but CORE still skips ProcessVec1 — this combination's correctness depends on Host only setting enablePreSfmg for d>64 (host-produced fact, not verified here). I'll note this as an assumption/edge.
  
  Actually, let me be careful. I'll state the verified branch and note the d>64 guard.
  
  - CORE: ProcessVec1 (v1: softmaxGrad) is SKIPPED inside both Process() (kernel.h:521) and ProcessPreloadTwoTimes() (kernel.h:614) when enablePreSfmg — because presfmg PRE already did the softmax-grad-front.
  - POST: unchanged for FP16/BF16 (still Muls+Cast). For FP32, POST still skipped (independent of enablePreSfmg).
  - Impact on dq scale/cast: enablePreSfmg does NOT change POST scale/cast. It relocates softmax-grad-front (ProcessVec1) from CORE to a separate PRE kernel. dq's scale/cast in POST (or in-CORE for BN2) is unaffected. The presfmg PRE writes into dqkvWorkspace (FP32) which POST then scales+casts.
- OFF (enablePreSfmg == false):
  - PRE: FlashAttentionScoreGradS1S2BNGS1S2PreRegbase (sink PRE) runs always (for BN2GS1S2/BN2S2) — computes sink (dsink) reduction setup. Actually wait — for the BN2GS1S2 macro, the else branch (line 54-61) ALWAYS runs the sink PRE (not gated by sinkOptional). Hmm, let me re-read. Line 54-61: else { FlashAttentionScoreGradS1S2BNGS1S2PreRegbase opPre; opPre.Init(...); opPre.Process(); opPre.SyncALLCores(); }. So when enablePreSfmg is OFF, the sink PRE always runs (for BN2GS1S2/BN2S2). For BN2 layout macro (line 134), the sink PRE is gated by sinkOptional. Slight difference between the two macros.
  - CORE: ProcessVec1 runs normally (the likely(!enablePreSfmg) is true).
  - POST: unchanged.

So enablePreSfmg OFF: sink PRE (S1S2BNGS1S2PreRegbase) + CORE(with ProcessVec1) + POST(FP16/BF16 scale+cast).

Let me also note: the sinkOptional field gates ProcessSink in POST (post_regbase.h:330) and gates the sink PRE for BN2 layout. enablePreSfmg is separate from sinkOptional.

Now, about FP32 + enablePreSfmg: For FP32, POST is skipped regardless. So FP32 + enablePreSfmg: presfmg PRE (if d>64) + CORE(no Vec1) + no POST. The dq output for FP32 is written... where? The presfmg PRE zeroes dqWorkSpaceGm and copies dqkv. The CORE writes to dq GM directly (OUTDTYPE=float=workspace). Since POST is skipped, dq must be finalized in CORE. This is the FP32 path. I'll note the structural flow.

Now completeness: This is a multi-part structural question. I've checked siblings (both macros, both Process variants, both PRE variants). For the FP32 in-CORE scale site, I have a small gap — I'll mark that sub-point as an assumption. Overall: ANSWERED with one assumption noted. claim_layer = kernel_consumed (mostly) + host_produced (scaleValue). I'll use claim_layer: kernel_consumed (the primary answers are about kernel branch structure). Actually it spans domain/template/kernel/host. The dominant is kernel-consumed + host-produced. Let me pick "kernel_consumed" since most is kernel branch logic, and note host-produced for scaleValue.

completeness: coverage_checked (I checked both macros, both process variants, both dtype paths, both enablePreSfmg branches, IS_BN2_MULTIBLK branches). Not first_hit.

Let me write the answer. I need to include citations with path/lines and the evidence windows with sha + snippet. Let me structure citations with the SHA.

The output format:
schema: kb-answer-v1
status: ANSWER
question: "..."
answer_zh: |
  ...
claim_layer: kernel_consumed
completeness: coverage_checked
assumptions:
  - "..."
citations:
  - path: ...
    lines: "..."
    evidence_window_sha256: "..."
    evidence_snippet: "..."
  ...
adequacy: ANSWERED

Let me write a thorough but focused answer_zh. I'll write in Chinese as required.

Let me draft the answer_zh:

---
总览：arch35 单 launch 入口为 RegbaseFAG（entry_regbase.h:201），按 ORIG_DTYPE_QUERY（FP16/BF16/FP32）和 splitAxis（BN2GS1S2/BN2S2/BN2）分派到 INVOKE_FAG_GENERAL_S1S2_*_REGBASE_IMPL_* 宏。三相 = PRE(pipeIn) → CORE(pipeBase) → POST(pipePost)，三段分别建/拆独立 TPipe。

1) 三相结构与关键 kernel/tiling 分支（entry_regbase.h:40-114）：
- PRE：opPre。enablePreSfmg 且 dTemplateType>64 → FlashAttentionScoreGradPresfmgRegbase（presfmg_regbase.h:263）；否则 → FlashAttentionScoreGradS1S2BNGS1S2PreRegbase（sink PRE）。Init/Process/SyncALLCores 后 pipeIn.Destroy()。
- CORE：op。DETER_SPARSE_TYPE==NO_DETER → FlashAttentionScoreGradKernel，否则 FlashAttentionScoreGradKernelDeter（entry_regbase.h:84-86）。AIC 取 FAGBlockCube、AIV 取 FAGBlockVec（互为 Dummy，entry_regbase.h:64-82）。Process()（kernel.h:497）是 cv pingpong：IterateMmQK/IterateMmDyV + ProcessVec1/2/3/4；按 SPLIT_AXIS 分派 ComputeDqkvBn2gs1s2/ComputeDqkvBn2s2/ComputeDqkvBn2（kernel.h:575-581）。IS_PRELOAD_TWO_TIMES 走 ProcessPreloadTwoTimes（小 headDim<=128，kernel.h:499）。
- POST：opPost。!IS_NZ_OUT → FlashAttentionScoreGradS1S2BNGS1S2PostRegbase（post_regbase.h:322）；IS_NZ_OUT → FlashAttentionScoreGradNzPost。仅当 ORIG_DTYPE_QUERY != DT_FLOAT 才跑（entry_regbase.h:91）。
- tiling 分支键：splitAxis、deterType(NO_DETER/ deter)、IS_NZ_OUT、enablePreSfmg、dTemplateType(>64)、IS_BN2_MULTIBLK。

2) POST 的 scale 与 cast（post_regbase.h:207-319，Process::322-333）：
- cast 的 buffer：inQueuePing/Pong(TQue<VECIN>, float=T2) ← dqkvWorkspace[0/1/2]（dq/dk/dv 的 FP32 累加 workspace，偏移来自 postTilingData.{dq,dk,dv}WorkSpaceOffset）；outQueuePing/Pong(TQue<VECOUT>, OUTDTYPE=half/bfloat16_t) → GM dqkv[0/1/2]。即 FP32 workspace → OUTDTYPE 输出 GM 的下采样 cast。
- scale 系数来源：tilingData->s1s2BNGS1S2BaseParams.scaleValue（post_regbase.h:238、283 读取）。Host 端：算子 attr0 → fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0))（tiling_common_regbase.cpp:1011，无条件）→ s1s2BNGS1S2BaseParams_->set_scaleValue(fBaseParams.scaleValue)（tiling_normal_regbase.cpp:1855）。kernel 端经 SetConstInfo（kernel_base.h:492）装入 constInfo.scaleValue。
- scale 只作用于 dq 与 dk（if (qkvIdx < 2) Muls(...)，post_regbase.h:237-239、282-284）；dv（qkvIdx==2）不 scale。
- dq 通路顺序：DataCopy(FP32 ws→vecInPing) → Muls(vecInPing, scaleValue) → Cast(vecOutPing, vecInPing, RoundMode::CAST_ROUND) → DataCopy(vecOutPing→GM)。即 先 scale 后 cast，cast 舍入模式 CAST_ROUND。
- BN2S2(SPLIT_AXIS==5) 在 qkvIdx==0(dq) 后 break（post_regbase.h:314-317，“bn2s2 dk dv no need to do muls and cast”）。

3) FP32 路径（entry_regbase.h:91、267-287；post_regbase.h:327）：
- 实例化 (float, float, float)：INPUT_TYPE=CALC_TYPE=OUTDTYPE=float（entry_regbase.h:281）。
- POST 整段跳过：if (ORIG_DTYPE_QUERY != DT_FLOAT) 为假 → 只 pipeBase.Destroy()，无 opPost（entry_regbase.h:91,111-113）。POST 的 ProcessDqkv 还有 !IsSameType<T1,float>::value 双保险（post_regbase.h:327）。
- 与 FP16 差异（dq 量级）：FP16/BF16 在 CORE 把 dq 累加到 FP32 workspace，POST 先 Muls(scaleValue) 再 Cast 下采样到 B16；FP32 直接以 FP32 写出（OUTDTYPE=float），无 POST 的 Muls(scaleValue) 与 Cast。因此 FP32 dq 通路上没有那次“累加后再乘 scaleValue”的后处理（该 scale 在 FP32 下是否在 CORE 内融合未在本窗体验证，见 assumptions）。
- FP32 同样覆盖 BN2GS1S2/BN2S2/BN2 三个 splitAxis（entry_regbase.h:267-287）。

4) BN2 路径：
- (a) splitAxis==BN2（BN2 layout）走 INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL（entry_regbase.h:129-182）：PRE 由 sinkOptional 门控（非 enablePreSfmg），用 sink PRE；CORE 只用非 deter 的 FlashAttentionScoreGradKernel（无 KernelDeter）；POST 由 sinkOptional 门控。但 POST::Process 对 BN2 跳过 ProcessDqkv（SPLIT_AXIS != BN2 为假，post_regbase.h:327）——即 BN2 layout 不在 POST 做 scale/cast，只在 isSink 时 ProcessSink。
- BN2 的 scale+cast 移到 CORE 内：ComputeDqkvBn2（kernel.h:580）→ FAGBlockVec::DqkvMulsAndCastFromGM（block_vec.h:722）。其顺序与 POST 一致：DataCopy(FP32 ws) → if (MM_IDX != DV_IDX) Muls(..., constInfo.scaleValue)（只 dq&dk，block_vec.h:828-830）→ Cast(..., CAST_ROUND)（block_vec.h:832）→ DataCopyPad(GM)。
- (b) IS_BN2_MULTIBLK（BNSD 的 N=2 多块）是 deter/sparse 块有效性分支，见于 CheckIsValidBlockForDeter/IsValidForTND/IsValid（kernel_base.h:816/1198/1284/1303）：设置 multiBlkInfo(s2oDimIdx/s2SparseLeft/s2SparseRight) 并调 CheckS1RangeInBn2，影响 s2 稀疏范围；不是独立 scale/cast 通路。它在 DqkvMulsAndCastFromGM 里只改 dq 的 workspace 偏移（block_vec.h:809：IS_BN2_MULTIBLK && MM_IDX == DQ_IDX）。

5) enablePreSfmg 各支路：
- 开启（enablePreSfmg==true）：
  - PRE：dTemplateType>64 → FlashAttentionScoreGradPresfmgRegbase opPre（entry_regbase.h:45-53），该核做 softmax-grad-front（Process→DoSoftmaxGrad→CalculateSoftmaxGrad+CopyInSfmg+CopyDqkvToGm，presfmg_regbase.h:263/474）并对 dq/dk/dv workspace 清零（presfmg_regbase.h:240-259）。
  - CORE：ProcessVec1(v1: softmaxGrad) 被跳过——if (likely(!constInfo.enablePreSfmg)) ProcessVec1 在 Process（kernel.h:521）和 ProcessPreloadTwoTimes（kernel.h:614）两处均成立。因 softmax-grad-front 已由 presfmg PRE 完成。
  - POST：对 FP16/BF16 仍跑 Muls+Cast（不变）；FP32 仍跳过 POST。
  - 对 dq scale/cast 的影响：enablePreSfmg 不改变 POST/BN2-CORE 的 scale/cast 语义；它只是把 ProcessVec1 从 CORE 搬到独立 PRE 核，dq 仍经 FP32 workspace → POST(或 BN2-CORE) 做 Muls(scaleValue)+Cast。
- 关闭（enablePreSfmg==false）：
  - PRE：BN2GS1S2/BN2S2 宏里 else 分支无条件跑 sink PRE FlashAttentionScoreGradS1S2BNGS1S2PreRegbase（entry_regbase.h:54-61）；BN2 宏里由 sinkOptional 门控（entry_regbase.h:134）。
  - CORE：ProcessVec1 正常执行（kernel.h:521/614 的 likely 分支为真）。
  - POST：不变。

assumptions:
- FP32 路径下 scaleValue 是否在 CORE 内（softmax-grad-front/MM）融合应用，未在本证据窗内定位（POST 整段跳过是确证的；仅“FP32 的等价 scale 落点”未单独验证）。
- enablePreSfmg==true 且 dTemplateType<=64 时，presfmg PRE 的 if constexpr (d>64) 为空（entry_regbase.h:46），但 CORE 仍跳过 ProcessVec1——该组合的正确性依赖 Host 仅在 d>64 时置 enablePreSfmg（host-produced，未在本窗体验证）。

---

That's comprehensive. Let me now also double-check: did I get the BN2S2 break direction right? post_regbase.h:314-317: if constexpr (SPLIT_AXIS == 5) { break; } — SPLIT_AXIS==5 is BN2S2. The break is inside the for (qkvIdx...) loop, after the ping/pong processing for qkvIdx=0. So after dq (qkvIdx=0), it breaks → dk/dv not processed. "bn2s2 dk dv no need to do muls and cast". Correct. So BN2S2 only does dq's scale+cast in POST. Good — I should state that precisely. Let me adjust: BN2S2 (SPLIT_AXIS==5) only processes dq (qkvIdx=0) in POST, skips dk/dv.

Wait, this means BN2S2 DOES run ProcessDqkv (since SPLIT_AXIS != BN2 is true for BN2S2), but only for dq. Let me re-check post_regbase.h:327: if constexpr (SPLIT_AXIS != BN2 && !IsSameType<T1,float>::value). BN2 is presumably 0. BN2S2 is 5. So for BN2S2, SPLIT_AXIS != BN2 is true → ProcessDqkv runs. And inside, the break after qkvIdx=0 means only dq. Good. So:
- BN2 layout (SPLIT_AXIS==BN2==0): ProcessDqkv skipped entirely; scale/cast in CORE via DqkvMulsAndCastFromGM.
- BN2S2 (SPLIT_AXIS==5): ProcessDqkv runs but only dq (break before dk/dv).
- BN2GS1S2 (SPLIT_AXIS==4): ProcessDqkv runs full dq/dk/dv.

I need to correct my Q4 statement. Let me make sure BN2 constant value. The entry uses splitAxis == BN2GS1S2, BN2S2, BN2. From kernel.h:575 SPLIT_AXIS == BN2GS1S2, 577 BN2S2, 579 else (BN2). And post_regbase.h:315 SPLIT_AXIS == 5. So BN2S2==5. BN2 is likely 0 (default). Let me not assert the exact numeric for BN2/BN2GS1S2 unless verified — I'll refer by name. Actually the constexpr in post uses SPLIT_AXIS == 5 for BN2S2 and SPLIT_AXIS != BN2 (BN2 symbolic). Good.

Let me finalize. I'll write the answer concisely but with all evidence. I'll attach evidence windows to the most important citations.

Given the volume, I'll attach SHA+snippet to the key citations (entry 40-114, post 207-319, post 321-333, block_vec 815-833, kernel 517-524, entry 129-182, presfmg 256-265, presfmg 474-485, kernel 611-618, tiling_common 1008-1014, tiling_normal 1852-1857). That's 11 citations. Good coverage.

Let me write the final YAML. The answer_zh will be long but that's appropriate for a 5-part question.

One more consideration on status: The question is structural (5 parts). All 5 answered with source windows. One assumption (FP32 in-CORE scale site) is a sub-point of Q3, not the whole Q3. Q3's main ask (path + dq magnitude difference) is answered (POST skipped, no post Muls/cast for FP32). So status: ANSWERED. adequacy: ANSWERED. I'll keep the assumption explicit.

Let me write it.
All evidence windows captured. I have full coverage for all 5 sub-questions. Composing the answer.
Summary of what I found against the arch35 UO CodeMap:
- Three-phase: RegbaseFAG (entry_regbase.h:201) → INVOKE_..._IMPL macro = PRE(pipeIn/opPre) → CORE(pipeBase/FlashAttentionScoreGradKernel[|Deter]) → POST(pipePost/...PostRegbase|...NzPost), POST gated by ORIG_DTYPE_QUERY != DT_FLOAT.
- POST scale/cast: ProcessDqkv (post_regbase.h:207) — DataCopy(FP32 workspace)→Muls(scaleValue) only for qkvIdx<2 (dq,dk; not dv)→Cast(CAST_ROUND)→GM. scaleValue = op attr0 (tiling_common_regbase.cpp:1011) → set_scaleValue (tiling_normal_regbase.cpp:1855).
- FP32: (float,float,float), POST entirely skipped (entry:91 + post:327 IsSameType<T1,float>), no post Muls/cast.
- BN2: layout (splitAxis==BN2) skips POST ProcessDqkv, does scale/cast in-CORE via DqkvMulsAndCastFromGM (block_vec.h:722, same Muls-then-Cast); IS_BN2_MULTIBLK is a deter block-validity branch.
- enablePreSfmg: ON+d>64 → presfmg PRE kernel does softmax-grad-front; CORE skips ProcessVec1 (kernel.h:521/614). POST scale/cast unchanged.
schema: kb-answer-v1
status: ANSWERED
question: "在 flash_attention_score_grad 的 arch35 UO CodeMap 上回答：1) arch35 单 launch 的三相结构是什么（PRE/CORE/POST 或类似阶段划分，给出关键 kernel 函数与 tiling 分支）；2) POST 阶段的 scale 与 cast 逻辑具体怎么写（哪些 buffer 做 cast、scale 系数从哪来、dq 通路上的 cast/scale 顺序）；3) FP32 精度路径怎么走（与 FP16 的差异点，尤其 dq 量级相关）；4) BN2（BNSD 的 N=2 分支或 BN2 layout）路径怎么走；5) enablePreSfmg 开关各支路怎么走（开启/关闭分别触发哪些分支、对 dq 的 scale/cast 有何影响）。需要给出源码 file:line 证据窗口。"
answer_zh: |
  入口 `RegbaseFAG`（op_kernel/arch35/flash_attention_score_grad_entry_regbase.h:201）按 `ORIG_DTYPE_QUERY`(FP16/BF16/FP32) 与 `splitAxis`(BN2GS1S2/BN2S2/BN2) 分派到 `INVOKE_FAG_GENERAL_S1S2_*_REGBASE_IMPL_*` 宏。三相 = PRE(pipeIn) → CORE(pipeBase) → POST(pipePost)，三段各自建/拆独立 TPipe。

  1) 三相结构与关键 kernel/tiling 分支（entry_regbase.h:40-114）：
   - PRE：`opPre`。enablePreSfmg 且 dTemplateType>64 → `FlashAttentionScoreGradPresfmgRegbase`（presfmg_regbase.h:263）；否则 → `FlashAttentionScoreGradS1S2BNGS1S2PreRegbase`（sink PRE）。Init/Process/SyncALLCores 后 `pipeIn.Destroy()`（entry_regbase.h:50-62）。
   - CORE：`op`。`(DETER_SPARSE_TYPE)==NO_DETER` → `FlashAttentionScoreGradKernel`，否则 `FlashAttentionScoreGradKernelDeter`（entry_regbase.h:84-86）。AIC 取 `FAGBlockCube`、AIV 取 `FAGBlockVec`（互为 Dummy，entry_regbase.h:64-82）。`Process()`（flash_attention_score_grad_kernel.h:497）为 cv pingpong：IterateMmQK/IterateMmDyV + ProcessVec1/2/3/4；按 SPLIT_AXIS 分派 ComputeDqkvBn2gs1s2 / ComputeDqkvBn2s2 / ComputeDqkvBn2（kernel.h:575-581）。`IS_PRELOAD_TWO_TIMES` 走 `ProcessPreloadTwoTimes`（小 headDim<=128，kernel.h:499）。
   - POST：`opPost`。`!IS_NZ_OUT` → `FlashAttentionScoreGradS1S2BNGS1S2PostRegbase`（post_regbase.h:322）；`IS_NZ_OUT` → `FlashAttentionScoreGradNzPost`。仅当 `ORIG_DTYPE_QUERY != DT_FLOAT` 才执行（entry_regbase.h:91）。
   - tiling 分支键：splitAxis、deterType(NO_DETER/deter)、IS_NZ_OUT、enablePreSfmg、dTemplateType(>64)、IS_BN2_MULTIBLK。

  2) POST 的 scale 与 cast（post_regbase.h:207-319，Process 于 322-333）：
   - cast 的 buffer：`inQueuePing/Pong`(TQue<VECIN>, float=T2) ← `dqkvWorkspace[0/1/2]`（dq/dk/dv 的 FP32 累加 workspace，偏移来自 postTilingData.{dq,dk,dv}WorkSpaceOffset，post_regbase.h:95-97）；`outQueuePing/Pong`(TQue<VECOUT>, OUTDTYPE=half/bfloat16_t) → GM `dqkv[0/1/2]`。即 FP32 workspace → OUTDTYPE 输出 GM 的下采样 cast。
   - scale 系数来源：`tilingData->s1s2BNGS1S2BaseParams.scaleValue`（post_regbase.h:238、283 读取）。Host 端：算子 attr[0] → `fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0))`（tiling_common_regbase.cpp:1011，无条件）→ `s1s2BNGS1S2BaseParams_->set_scaleValue(fBaseParams.scaleValue)`（tiling_normal_regbase.cpp:1855）。kernel 端经 `SetConstInfo`（kernel_base.h:492）装入 `constInfo.scaleValue`。
   - scale 只作用于 dq 与 dk（`if (qkvIdx < 2) Muls(...)`，post_regbase.h:237-239、282-284）；dv(qkvIdx==2) 不 scale。
   - dq 通路顺序：DataCopy(FP32 ws→vecInPing) → Muls(vecInPing, scaleValue) → Cast(vecOutPing, vecInPing, RoundMode::CAST_ROUND) → DataCopy(vecOutPing→GM)。即 先 scale 后 cast，cast 舍入模式 CAST_ROUND。
   - BN2S2(SPLIT_AXIS==5) 在 qkvIdx==0(dq) 处理完后 `break`（post_regbase.h:314-317，“bn2s2 dk dv no need to do muls and cast”）：即 BN2S2 在 POST 只对 dq 做 scale+cast。

  3) FP32 路径（entry_regbase.h:91、267-287；post_regbase.h:327）：
   - 实例化 `(float, float, float)`：INPUT_TYPE=CALC_TYPE=OUTDTYPE=float（entry_regbase.h:281）。
   - POST 整段跳过：`if (ORIG_DTYPE_QUERY != DT_FLOAT)` 为假 → 只 `pipeBase.Destroy()`，无 opPost（entry_regbase.h:91,111-113）。POST::ProcessDqkv 还有 `!IsSameType<T1,float>::value` 双保险（post_regbase.h:327）。
   - 与 FP16 差异（dq 量级）：FP16/BF16 在 CORE 把 dq 累加进 FP32 workspace，POST 先 Muls(scaleValue) 再 Cast 下采样到 B16；FP32 直接以 FP32 写出（OUTDTYPE=float），无 POST 的 Muls(scaleValue) 与 Cast。因此 FP32 dq 通路上没有那次“累加后再乘 scaleValue”的后处理（该 scale 在 FP32 下是否在 CORE 内融合未在本窗体验证，见 assumptions）。
   - FP32 覆盖 BN2GS1S2/BN2S2/BN2 三个 splitAxis（entry_regbase.h:267-287）。

  4) BN2 路径：
   - (a) splitAxis==BN2（BN2 layout）走 `INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL`（entry_regbase.h:129-182）：PRE 由 `sinkOptional` 门控（非 enablePreSfmg），用 sink PRE；CORE 只用非 deter 的 `FlashAttentionScoreGradKernel`（无 KernelDeter，entry_regbase.h:165）；POST 由 `sinkOptional` 门控。但 POST::Process 对 BN2 跳过 ProcessDqkv（`SPLIT_AXIS != BN2` 为假，post_regbase.h:327）——BN2 layout 不在 POST 做 scale/cast，只在 isSink 时 ProcessSink。
   - BN2 的 scale+cast 移到 CORE 内：`ComputeDqkvBn2`（kernel.h:580）→ `FAGBlockVec::DqkvMulsAndCastFromGM`（block_vec.h:722）。顺序与 POST 一致：DataCopy(FP32 ws) → `if constexpr (MM_IDX != DV_IDX) Muls(dqkvTensor, dqkvTensor, constInfo.scaleValue, ...)`（只 dq&dk，block_vec.h:828-830）→ `Cast(dqkvCastTensor, dqkvTensor, RoundMode::CAST_ROUND, ...)`（block_vec.h:832）→ DataCopyPad(GM)。
   - (b) IS_BN2_MULTIBLK（BNSD 的 N=2 多块）是 deter/sparse 块有效性分支，见于 `CheckIsValidBlockForDeter`/`IsValidForTND`/`IsValid`（kernel_base.h:816/1198/1284/1303）：设置 `multiBlkInfo`(s2oDimIdx/s2SparseLeft/s2SparseRight) 并调 `CheckS1RangeInBn2`，影响 s2 稀疏范围；不是独立 scale/cast 通路。在 `DqkvMulsAndCastFromGM` 里只改 dq 的 workspace 偏移（block_vec.h:809：`IS_BN2_MULTIBLK && MM_IDX == DQ_IDX`）。

  5) enablePreSfmg 各支路：
   - 开启（enablePreSfmg==true）：
     · PRE：dTemplateType>64 → `FlashAttentionScoreGradPresfmgRegbase` opPre（entry_regbase.h:45-53），该核做 softmax-grad-front（`Process`→`DoSoftmaxGrad`→`CalculateSoftmaxGrad`+`CopyInSfmg`+`CopyDqkvToGm`，presfmg_regbase.h:263/474）并对 dq/dk/dv workspace 清零（presfmg_regbase.h:240-259）。
     · CORE：`ProcessVec1`(v1: softmaxGrad) 被跳过——`if (likely(!constInfo.enablePreSfmg)) ProcessVec1(...)` 在 `Process`（kernel.h:521）与 `ProcessPreloadTwoTimes`（kernel.h:614）两处均生效，因 softmax-grad-front 已由 presfmg PRE 完成。
     · POST：FP16/BF16 仍跑 Muls+Cast（不变）；FP32 仍跳过 POST。
     · 对 dq scale/cast 的影响：enablePreSfmg 不改变 POST/BN2-CORE 的 scale/cast 语义；只把 ProcessVec1 从 CORE 搬到独立 PRE 核，dq 仍经 FP32 workspace → POST(或 BN2-CORE) 做 Muls(scaleValue)+Cast。
   - 关闭（enablePreSfmg==false）：
     · PRE：BN2GS1S2/BN2S2 宏的 `else` 分支无条件跑 sink PRE `FlashAttentionScoreGradS1S2BNGS1S2PreRegbase`（entry_regbase.h:54-61）；BN2 宏里由 `sinkOptional` 门控（entry_regbase.h:134）。
     · CORE：ProcessVec1 正常执行（kernel.h:521/614 的 likely 分支为真）。
     · POST：不变。

  证据窗 SHA 见 citations；未自降置信度。
claim_layer: kernel_consumed
completeness: coverage_checked
assumptions:
  - "FP32 路径下 scaleValue 是否在 CORE 内（softmax-grad-front/MM）融合应用，未在本证据窗内定位：POST 整段跳过已确证（entry_regbase.h:91、post_regbase.h:327），仅‘FP32 的等价 scale 落点’未单独验证。"
  - "enablePreSfmg==true 且 dTemplateType<=64 时，presfmg PRE 的 `if constexpr (d>64)` 为空（entry_regbase.h:46），但 CORE 仍跳过 ProcessVec1；该组合的正确性依赖 Host 仅在 d>64 时置 enablePreSfmg（host-produced，未在本窗体验证）。"
citations:
  - path: op_kernel/arch35/flash_attention_score_grad_entry_regbase.h
    lines: "40-114"
    evidence_window_sha256: 1ab03d417eb9a14b16b9c2886f5ec5ac7882ed24cd15dff59851cd386c0670e7
    evidence_snippet: "if (unlikely(tilingData->s1s2BNGS1S2BaseParams.enablePreSfmg)) { if constexpr ((uint32_t)dTemplateType > 64) { FlashAttentionScoreGradPresfmgRegbase<...> opPre; opPre.Init(...); opPre.Process(); opPre.SyncALLCores(); } } else { FlashAttentionScoreGradS1S2BNGS1S2PreRegbase<...> opPre; ... } pipeIn.Destroy(); TPipe pipeBase; ... FlashAttentionScoreGradKernel<CubeBlockType, VecBlockType> op; op.Init(...); op.Process(); if (ORIG_DTYPE_QUERY != DT_FLOAT) { op.SyncALLCores(); pipeBase.Destroy(); TPipe pipePost; if constexpr (!IS_NZ_OUT) { FlashAttentionScoreGradS1S2BNGS1S2PostRegbase<...> opPost; ... } else { FlashAttentionScoreGradNzPost<...> opPost; ... } } else { pipeBase.Destroy(); }"
  - path: op_kernel/arch35/flash_attention_score_grad_entry_regbase.h
    lines: "129-182"
    evidence_window_sha256: 5ce8e1de611bd590a70400faf209195349cb233c375c0c3f79193e5d5f4b05dd
    evidence_snippet: "#define INVOKE_FAG_GENERAL_S1S2_BN2_REGBASE_IMPL(...) do { if (tilingData->s1s2BNGS1S2BaseParams.sinkOptional) { FlashAttentionScoreGradS1S2BNGS1S2PreRegbase<...> opPre; opPre.Init(dq, dk, dv, actual_seq_kvlen, drop_mask, user, tilingData, &pipeIn); opPre.Process(); opPre.SyncALLCores(); } pipeIn.Destroy(); TPipe pipeBase; ... FagBaseApi::FlashAttentionScoreGradKernel<CubeBlockType, VecBlockType> op; op.Init(...); op.Process(); if (tilingData->s1s2BNGS1S2BaseParams.sinkOptional) { op.SyncALLCores(); pipeBase.Destroy(); TPipe pipePost; FlashAttentionScoreGradS1S2BNGS1S2PostRegbase<...> opPost; ... opPost.Process(); } else { pipeBase.Destroy(); } } while (0)"
  - path: op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h
    lines: "207-319"
    evidence_window_sha256: 497a715cd2ef6c2197eac5ca78ca92cd4e4f0bcbbd9a79aaf938ad50e44d349f
    evidence_snippet: "void ...::ProcessDqkv() { for (int qkvIdx = 0; qkvIdx < 3; qkvIdx++) { ... DataCopy(vecInPing, dqkvWorkspace[qkvIdx][pingIdx], ...); inQuePing.EnQue(vecInPing); inQuePing.DeQue<float>(); if (qkvIdx < 2) { Muls(vecInPing, vecInPing, (float)tilingData->s1s2BNGS1S2BaseParams.scaleValue, pingSize); } LocalTensor<OUTDTYPE> vecOutPing = outQueuePing.AllocTensor<OUTDTYPE>(); Cast(vecOutPing, vecInPing, RoundMode::CAST_ROUND, pingSize); ... if (qkvIdx < 2) { Muls(vecInPong, vecInPong, (float)tilingData->s1s2BNGS1S2BaseParams.scaleValue, pongSize); } Cast(vecOutPong, vecInPong, RoundMode::CAST_ROUND, pongSize); ... if constexpr (SPLIT_AXIS == 5) { break; } } }"
  - path: op_kernel/arch35/flash_attention_score_grad_s1s2_bn2gs1s2_post_regbase.h
    lines: "321-333"
    evidence_window_sha256: 75f82fa8dc249f13ffd1433f872210cde35c0b17ec42a46ac97c92df06dd31ed
    evidence_snippet: "void ...::Process() { if (g_coreType != AIV) { return; } if constexpr (SPLIT_AXIS != BN2 && !IsSameType<T1, float>::value) { ProcessDqkv(); } if (unlikely(isSink)) { ProcessSink(); } }"
  - path: op_kernel/arch35/flash_attention_score_grad_block_vec.h
    lines: "815-833"
    evidence_window_sha256: 89b097eba26324f569ec555228d404cc89afcc95146c5979874efbcab65fae2f
    evidence_snippet: "for (uint32_t loopIdx = 0; loopIdx < loopNum; loopIdx++) { ... LocalTensor<CALC_TYPE> dqkvTensor = inQue.AllocTensor<CALC_TYPE>(); DataCopy(dqkvTensor, inputTensor[dkvWorkSpaceOffet + loopIdx * loopSize * curDAlign], data_size); inQue.EnQue(dqkvTensor); inQue.DeQue(); if constexpr (MM_IDX != DV_IDX) { Muls(dqkvTensor, dqkvTensor, constInfo.scaleValue, data_size); } LocalTensor<OUTDTYPE> dqkvCastTensor = outQue.template AllocTensor<OUTDTYPE>(); Cast(dqkvCastTensor, dqkvTensor, RoundMode::CAST_ROUND, data_size); ..."
  - path: op_kernel/arch35/flash_attention_score_grad_kernel.h
    lines: "517-524"
    evidence_window_sha256: ac72e1f3b0c5fa562f279fe969f9529ded0e196dec34bdb3f60e087713048bd2
    evidence_snippet: "while (true) { this->isLastLoop = (blockInnerIdx == -1); if (taskId > 0) { prevRunInfo = runInfos[(taskId + 1) & 1]; if (likely(!this->constInfo.enablePreSfmg)) { this->vecBlock.ProcessVec1(this->constInfo, prevRunInfo); // v1: softmaxGrad } } }"
  - path: op_kernel/arch35/flash_attention_score_grad_kernel.h
    lines: "611-618"
    evidence_window_sha256: 7147199429e4daf2b13bdbe358c8b1e93cad223953014702832e3e0a3c76be70
    evidence_snippet: "while (true) { if (taskId > 0) { prevRunInfo = runInfos[(taskId + 1) % PRELOAD_TIMES]; if (likely(!this->constInfo.enablePreSfmg)) { this->vecBlock.ProcessVec1(this->constInfo, runInfos[(taskId + NUM_TWO) % PRELOAD_TIMES]); // v1: softmaxGrad } } }"
  - path: op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h
    lines: "256-265"
    evidence_window_sha256: aebd828a5af976cd0708cced494d52b4ea8bdf4f37f7a7038931a20ba55332ee
    evidence_snippet: "} else { if (tilingData->s1s2BNGS1S2SplitCoreParams.s2Outer > 1) { InitOutput<float>(dqWorkSpaceGm[dqOffset], initdqSize, 0); } } SetFlag<HardEvent::V_MTE3>(eventIDVToMte3); CalTempDimAlign(); DoSoftmaxGrad(); } }"
  - path: op_kernel/arch35/flash_attention_score_grad_presfmg_regbase.h
    lines: "474-485"
    evidence_window_sha256: f42bc5dcddba261e66562a868be64f7716ff579eb3c7be200ae25c0b871de1fe
    evidence_snippet: "void ...::DoSoftmaxGrad() { if (vBlockIdx < usedCoreNum) { uint64_t singleCoreLoopTimes, singleCoreLastLoopNBurstNum; if (vBlockIdx == usedCoreNum - 1) { singleCoreLoopTimes = tilingData->preTilingData.tailCoreLoopTimes; ... } else { singleCoreLoopTimes = tilingData->preTilingData.normalCoreLoopTimes; ... } }"
  - path: op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp
    lines: "1008-1014"
    evidence_window_sha256: 39028a15cdc15a12efb3a4524481601338171f10bc1140a7749051cbc1fe84f7
    evidence_snippet: "fBaseParams.queryType = queryType; fBaseParams.calTypeSize = FP32_BYTES; fBaseParams.scaleValue = *(context_->GetAttrs()->GetAttrPointer<float>(0)); fBaseParams.keepProb = *(context_->GetAttrs()->GetAttrPointer<float>(1)); fBaseParams.dropoutIsDivisibleBy8 = 1;"
  - path: op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp
    lines: "1852-1857"
    evidence_window_sha256: de7b432858f4d5bd67c750a480906f452b2c776b014b14c6f0d38ceab2c266b8
    evidence_snippet: "s1s2BNGS1S2BaseParams_->set_attenMaskShapeType(fBaseParams.attenMaskShapeType); s1s2BNGS1S2BaseParams_->set_layout(fBaseParams.layoutType); s1s2BNGS1S2BaseParams_->set_tndMaxSumLayout(fBaseParams.tndMaxSumLayout); s1s2BNGS1S2BaseParams_->set_scaleValue(fBaseParams.scaleValue); s1s2BNGS1S2BaseParams_->set_keepProb(fBaseParams.keepProb); s1s2BNGS1S2BaseParams_->set_keepProbUint8(fBaseParams.keepProbUint8);"
  - path: op_kernel/arch35/flash_attention_score_grad_kernel.h
    lines: "575-581"
    note: "SPLIT_AXIS 分派 ComputeDqkv*：BN2GS1S2→ComputeDqkvBn2gs1s2；BN2S2→ComputeDqkvBn2s2；else(BN2)→ComputeDqkvBn2。"
    evidence_snippet: "if constexpr (SPLIT_AXIS == BN2GS1S2) { ComputeDqkvBn2gs1s2(prevRunInfo, needSyncDkMM, taskId); } else if constexpr (SPLIT_AXIS == BN2S2) { ComputeDqkvBn2s2(prevRunInfo, needSyncDkMM, needSyncDkDvFixUb, taskId); } else { ComputeDqkvBn2(prevRunInfo, needSyncDkMM, taskId); }"
adequacy: ANSWERED
Done. The kb-answer-v1 block above is the return_value for Primary to finalize. I did not write answer.yaml/scratch or modify the .uo product; all claims are backed by disk source windows with evidence_window_sha256 + continuous evidence_snippet substrings. Two non-fabricated assumptions flag the only un-pinned sub-points (FP32 in-CORE scale fusion site; enablePreSfmg+d<=64 host guard).
▣  Uo-Query · GLM-5.2 · 5m 56s
Subagent(1 of 1)84.9K (8%)