# FlashAttentionScoreGrad arch35 fresh UO audit

- ok: `True`
- mode: `fresh-current-source-structural-compiler`
- historical archive used: `False`
- cold analysis: `53.918s / 300s`
- product: `flash_attention_score_grad.arch35.uo`
- entities / relations: `3431` / `4346`
- TilingKey declaration / packing / producer / root: `19/19` / `19/19` / `19/19` / `19/19`
- dependency skeleton complete: `12/19`
- Kernel entry / template args / ABI: `1` / `19` / `34`
- Kernel reachable scopes / call boundaries / unclassified calls: `277` / `117` / `0`
- TilingData classes / fields: `11` / `163`
- TilingData reachable read fields / unresolved reads: `136` / `0`
- TilingData consumed-field producer coverage: `136/136`
- strict Kernel/TilingData closure: `True`
- blocking: `0`
- warnings: `2`

## Critical producer sites

- `DTemplateNum`: producer=`True`, rooted=`True`, sites=`[{'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 848, 'function': 'GetDTemplateType', 'lhs': 'fBaseParams.dTemplateType'}, {'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 852, 'function': 'GetDTemplateType', 'lhs': 'fBaseParams.dTemplateType'}, {'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 855, 'function': 'GetDTemplateType', 'lhs': 'fBaseParams.dTemplateType'}, {'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 858, 'function': 'GetDTemplateType', 'lhs': 'fBaseParams.dTemplateType'}, {'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 861, 'function': 'GetDTemplateType', 'lhs': 'fBaseParams.dTemplateType'}, {'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 864, 'function': 'GetDTemplateType', 'lhs': 'fBaseParams.dTemplateType'}]`
- `IsNzOut`: producer=`True`, rooted=`True`, sites=`[{'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp', 'line': 444, 'function': 'FlashAttentionScoreGradTilingNormalRegbase::DoOpTiling', 'lhs': 'fBaseParams.isNzOut'}]`
- `IsTndSwizzle`: producer=`True`, rooted=`True`, sites=`[{'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp', 'line': 461, 'function': 'FlashAttentionScoreGradTilingNormalRegbase::DoOpTiling', 'lhs': 'tndBaseInfo.isTndSwizzle'}]`
- `S1TemplateNum`: producer=`True`, rooted=`True`, sites=`[{'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 813, 'function': 'GetS1S2TemplateType', 'lhs': 'fBaseParams.s1TemplateType'}, {'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 819, 'function': 'GetS1S2TemplateType', 'lhs': 'fBaseParams.s1TemplateType'}, {'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 824, 'function': 'GetS1S2TemplateType', 'lhs': 'fBaseParams.s1TemplateType'}, {'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 836, 'function': 'GetS1S2TemplateType', 'lhs': 'fBaseParams.s1TemplateType'}]`
- `S2TemplateNum`: producer=`True`, rooted=`True`, sites=`[{'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 814, 'function': 'GetS1S2TemplateType', 'lhs': 'fBaseParams.s2TemplateType'}, {'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 820, 'function': 'GetS1S2TemplateType', 'lhs': 'fBaseParams.s2TemplateType'}, {'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 825, 'function': 'GetS1S2TemplateType', 'lhs': 'fBaseParams.s2TemplateType'}, {'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_common_regbase.cpp', 'line': 837, 'function': 'GetS1S2TemplateType', 'lhs': 'fBaseParams.s2TemplateType'}]`
- `SplitAxis`: producer=`True`, rooted=`True`, sites=`[{'file': 'flash_attention_score_grad/op_host/arch35/flash_attention_score_grad_tiling_normal_regbase.cpp', 'line': 1443, 'function': 'FlashAttentionScoreGradTilingNormalRegbase::GetTilingKey', 'lhs': 'splitAxis'}]`

## Blocking

- none

## Binary warnings

- `PARTIAL_TILINGKEY_DEPENDENCY_SKELETON`: 7/19 TilingKeys retain unresolved runtime dependency leaves
- `UNRESOLVED_FACTS`: entities=13 relations=54
