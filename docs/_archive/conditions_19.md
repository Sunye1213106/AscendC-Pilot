# 19 TilingKey 条件化简（探针派生）

> **非契约。** 探针快照；真值以 `uo/ir/host_derivation.yaml` / `chk_19_align` 为准。

- encode scope: `GetTilingKey`
- encode site: `flash_attention_score_grad_tiling_normal_regbase.cpp:1460`

## 0. `IsEmptyTensor`

- **host_expr**: `((IsEmptyOutput(context)) ? (TILING_KEY_1) : (0))`
- **domain**: ['0', '1']
- **value_leaves**: ['0', 'False', 'TILING_KEY_1', 'True']
- **roots**: ['INPUT_SHAPE']
- **undecided**: 0
- **cond_tokens**: GetShapeSize×5
- **def_sites**: (none / merged literal)

## 1. `SplitAxis`

- **host_expr**: `static_cast<uint8_t>(splitAxis)`
- **domain**: ['0', '1', '5']
- **value_leaves**: ['0', '1', '2', 'ALL_MASK', 'BN2', 'BN2GS1S2', 'BN2S2', 'DETER_BAND', 'DETER_CAUSAL', 'DETER_DENSE', 'DETER_OLD', 'False', 'INPUT_FORMAT_BN2GS2D', 'INPUT_FORMAT_BS2N2GD', 'INPUT_FORMAT_S2BN2GD', 'INPUT_FORMAT_TND', 'NO_DETER', 'NO_MASK', 'ROPE_D_192', 'True']
- **roots**: ['ATTRIBUTE', 'INPUT_DTYPE', 'INPUT_SHAPE', 'INPUT_VALUE', 'OPTIONAL_INPUT_PRESENCE', 'PLATFORM_ARCH', 'PLATFORM_CORE_COUNT', 'TILING_DATA']
- **undecided**: 27
- **cond_tokens**: strcmp×156, BN2×34, GRAPH_SUCCESS×29, isDeterministic×20, INPUT_FORMAT_TND×16, deterSparseType×13, layoutType×12, isBn2×12, splitAxis×11, __reached_×11, BN2S2×10, GetDataType×8
- **def_sites**:
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:1443` `GetTilingKey` ← `fBaseParams.splitAxis`

## 2. `InputDType`

- **host_expr**: `static_cast<uint8_t>(fBaseParams.inputDtype)`
- **domain**: ['0', '1', '2', '3', '4', '5', '6']
- **value_leaves**: ['0', 'BFLOAT16', 'DTYPE_ENUM_INDEX_4', 'DTYPE_ENUM_INDEX_5', 'DTYPE_ENUM_INDEX_6', 'FLOAT16_PRECISION', 'FLOAT32']
- **roots**: ['INPUT_DTYPE']
- **undecided**: 0
- **cond_tokens**: GetDataType×20, DT_FLOAT×13, DT_BF16×5
- **def_sites**:
  - `flash_attention_score_grad_tiling_common_regbase.cpp:1651` `DetermineMode` ← `DtypeEnum::FLOAT32`
    guards: `fBaseParams.queryType == ge::DT_FLOAT`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:1653` `DetermineMode` ← `DtypeEnum::BFLOAT16`
    guards: `!(fBaseParams.queryType == ge::DT_FLOAT); fBaseParams.queryType == ge::DT_BF16`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:1655` `DetermineMode` ← `static_cast<optiling::DtypeEnum>(DTYPE_ENUM_INDEX_4)`
    guards: `!(fBaseParams.queryType == ge::DT_FLOAT); !(fBaseParams.queryType == ge::DT_BF16); fBaseParams.queryType == ge::DT_FLOAT8_E5M2`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:1657` `DetermineMode` ← `static_cast<optiling::DtypeEnum>(DTYPE_ENUM_INDEX_5)`
    guards: `!(fBaseParams.queryType == ge::DT_FLOAT); !(fBaseParams.queryType == ge::DT_BF16); !(fBaseParams.queryType == ge::DT_FLOAT8_E5M2)`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:1659` `DetermineMode` ← `static_cast<optiling::DtypeEnum>(DTYPE_ENUM_INDEX_6)`
    guards: `!(fBaseParams.queryType == ge::DT_FLOAT); !(fBaseParams.queryType == ge::DT_BF16); !(fBaseParams.queryType == ge::DT_FLOAT8_E5M2)`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:1661` `DetermineMode` ← `DtypeEnum::FLOAT16_PRECISION`
    guards: `!(fBaseParams.queryType == ge::DT_FLOAT); !(fBaseParams.queryType == ge::DT_BF16); !(fBaseParams.queryType == ge::DT_FLOAT8_E5M2)`

## 3. `IsTnd`

- **host_expr**: `static_cast<uint8_t>(isTnd)`
- **domain**: ['0', '1']
- **value_leaves**: ['0', '1', '2', 'ALL_MASK', 'BN2', 'BN2GS1S2', 'BN2S2', 'DETER_BAND', 'DETER_CAUSAL', 'DETER_DENSE', 'DETER_OLD', 'False', 'INPUT_FORMAT_BN2GS2D', 'INPUT_FORMAT_BS2N2GD', 'INPUT_FORMAT_S2BN2GD', 'INPUT_FORMAT_TND', 'NO_DETER', 'NO_MASK', 'ROPE_D_192', 'True']
- **roots**: ['ATTRIBUTE', 'INPUT_DTYPE', 'INPUT_SHAPE', 'INPUT_VALUE', 'OPTIONAL_INPUT_PRESENCE', 'PLATFORM_ARCH', 'PLATFORM_CORE_COUNT', 'TILING_DATA']
- **undecided**: 26
- **cond_tokens**: strcmp×156, BN2×34, GRAPH_SUCCESS×29, isDeterministic×21, isBn2×18, INPUT_FORMAT_TND×17, layoutType×15, deterSparseType×13, __reached_×11, BN2S2×10, isBn2MultiBlk×8, GetDataType×8
- **def_sites**:
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:1442` `GetTilingKey` ← `(fBaseParams.layoutType == INPUT_FORMAT_TND)`

## 4. `IsDrop`

- **host_expr**: `static_cast<uint8_t>(dropValue)`
- **domain**: ['0', '1']
- **value_leaves**: ['DISABLE', 'ENABLE']
- **roots**: ['ATTRIBUTE']
- **undecided**: 0
- **def_sites**:
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:1440` `GetTilingKey` ← `fBaseParams.keepProb<1 ? OptionEnum::ENABLE : OptionEnum::DISABLE`

## 5. `IsPse`

- **host_expr**: `static_cast<uint8_t>(pseValue)`
- **domain**: ['0', '1']
- **value_leaves**: ['0', 'DISABLE', 'EMPTY_TENSOR', 'ENABLE', 'NORMAL_TENSOR']
- **roots**: ['INPUT_SHAPE', 'OPTIONAL_INPUT_PRESENCE']
- **undecided**: 0
- **cond_tokens**: NORMAL_TENSOR×2, EMPTY_TENSOR×1
- **def_sites**:
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:1439` `GetTilingKey` ← `fBaseParams.pseOptional == NORMAL_TENSOR ? OptionEnum::ENABLE : OptionEnum::DISA`

## 6. `IsAttenMask`

- **host_expr**: `static_cast<uint8_t>(attenMaskCfg)`
- **domain**: ['0', '1']
- **value_leaves**: ['0', 'DISABLE', 'EMPTY_TENSOR', 'ENABLE', 'NORMAL_TENSOR']
- **roots**: ['INPUT_SHAPE', 'OPTIONAL_INPUT_PRESENCE']
- **undecided**: 0
- **cond_tokens**: EMPTY_TENSOR×2, NORMAL_TENSOR×1
- **def_sites**:
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:1437` `GetTilingKey` ← `fBaseParams.attenMaskOptional == EMPTY_TENSOR ? OptionEnum::DISABLE : OptionEnum`

## 7. `S1TemplateNum`

- **host_expr**: `static_cast<uint16_t>(fBaseParams.s1TemplateType)`
- **domain**: ['0', '64', '128', '512']
- **value_leaves**: ['0', 'NUM128', 'NUM512', 'NUM64', 'ROPE_D_192']
- **roots**: ['ATTRIBUTE', 'INPUT_DTYPE', 'INPUT_SHAPE', 'INPUT_VALUE', 'OPTIONAL_INPUT_PRESENCE']
- **undecided**: 0
- **cond_tokens**: strcmp×42, GetDataType×12, DT_FLOAT×10, ROPE_D_192×5, NUM128×3, QUERY_ROPE×2, NUM64×2
- **def_sites**:
  - `flash_attention_score_grad_tiling_common_regbase.cpp:813` `GetS1S2TemplateType` ← `ConstAxisTemplateNum::NUM64`
    guards: `fBaseParams.queryType == ge::DT_FLOAT && fBaseParams.d>static_cast<uint32_t>(ConstAxisTemplateNum::NUM256)`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:819` `GetS1S2TemplateType` ← `ConstAxisTemplateNum::NUM64`
    guards: `!(fBaseParams.queryType == ge::DT_FLOAT && fBaseParams.d>static_cast<uint32_t>(ConstAxisTemplateNum::NUM256)); fBaseParams.queryType == ge::DT_FLOAT8_E5M2 || fBaseParams.queryType == ge::DT_FLOAT8_E4M`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:824` `GetS1S2TemplateType` ← `ConstAxisTemplateNum::NUM512`
    guards: `!(fBaseParams.queryType == ge::DT_FLOAT && fBaseParams.d>static_cast<uint32_t>(ConstAxisTemplateNum::NUM256)); !(fBaseParams.queryType == ge::DT_FLOAT8_E5M2 || fBaseParams.queryType == ge::DT_FLOAT8_E`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:836` `GetS1S2TemplateType` ← `ConstAxisTemplateNum::NUM128`
    guards: `!(fBaseParams.queryType == ge::DT_FLOAT && fBaseParams.d>static_cast<uint32_t>(ConstAxisTemplateNum::NUM256)); !(fBaseParams.queryType == ge::DT_FLOAT8_E5M2 || fBaseParams.queryType == ge::DT_FLOAT8_E`

## 8. `S2TemplateNum`

- **host_expr**: `static_cast<uint16_t>(fBaseParams.s2TemplateType)`
- **domain**: ['0', '128', '256', '512']
- **value_leaves**: ['0', 'NUM128', 'NUM256', 'NUM512', 'ROPE_D_192']
- **roots**: ['ATTRIBUTE', 'INPUT_DTYPE', 'INPUT_SHAPE', 'INPUT_VALUE', 'OPTIONAL_INPUT_PRESENCE']
- **undecided**: 0
- **cond_tokens**: strcmp×42, GetDataType×12, DT_FLOAT×10, ROPE_D_192×5, NUM128×4, QUERY_ROPE×2
- **def_sites**:
  - `flash_attention_score_grad_tiling_common_regbase.cpp:814` `GetS1S2TemplateType` ← `ConstAxisTemplateNum::NUM128`
    guards: `fBaseParams.queryType == ge::DT_FLOAT && fBaseParams.d>static_cast<uint32_t>(ConstAxisTemplateNum::NUM256)`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:820` `GetS1S2TemplateType` ← `ConstAxisTemplateNum::NUM256`
    guards: `!(fBaseParams.queryType == ge::DT_FLOAT && fBaseParams.d>static_cast<uint32_t>(ConstAxisTemplateNum::NUM256)); fBaseParams.queryType == ge::DT_FLOAT8_E5M2 || fBaseParams.queryType == ge::DT_FLOAT8_E4M`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:825` `GetS1S2TemplateType` ← `ConstAxisTemplateNum::NUM512`
    guards: `!(fBaseParams.queryType == ge::DT_FLOAT && fBaseParams.d>static_cast<uint32_t>(ConstAxisTemplateNum::NUM256)); !(fBaseParams.queryType == ge::DT_FLOAT8_E5M2 || fBaseParams.queryType == ge::DT_FLOAT8_E`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:837` `GetS1S2TemplateType` ← `ConstAxisTemplateNum::NUM128`
    guards: `!(fBaseParams.queryType == ge::DT_FLOAT && fBaseParams.d>static_cast<uint32_t>(ConstAxisTemplateNum::NUM256)); !(fBaseParams.queryType == ge::DT_FLOAT8_E5M2 || fBaseParams.queryType == ge::DT_FLOAT8_E`

## 9. `DTemplateNum`

- **host_expr**: `static_cast<uint16_t>(fBaseParams.dTemplateType)`
- **domain**: ['0', '64', '128', '192', '256', '768']
- **value_leaves**: ['0', 'NUM128', 'NUM192', 'NUM256', 'NUM64', 'NUM768', 'ROPE_D_192']
- **roots**: ['ATTRIBUTE', 'INPUT_SHAPE', 'OPTIONAL_INPUT_PRESENCE']
- **undecided**: 0
- **cond_tokens**: strcmp×14, NUM64×6, NUM128×5, NUM192×5, ROPE_D_192×5, QUERY_ROPE×2
- **def_sites**:
  - `flash_attention_score_grad_tiling_common_regbase.cpp:848` `GetDTemplateType` ← `ConstAxisTemplateNum::NUM192`
    guards: `fBaseParams.hasRope`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:852` `GetDTemplateType` ← `ConstAxisTemplateNum::NUM64`
    guards: `!(fBaseParams.hasRope); fBaseParams.d<= static_cast<uint32_t>(ConstAxisTemplateNum::NUM64)`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:855` `GetDTemplateType` ← `ConstAxisTemplateNum::NUM128`
    guards: `!(fBaseParams.hasRope); !(fBaseParams.d<= static_cast<uint32_t>(ConstAxisTemplateNum::NUM64)); fBaseParams.d<= static_cast<uint32_t>(ConstAxisTemplateNum::NUM128)`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:858` `GetDTemplateType` ← `ConstAxisTemplateNum::NUM192`
    guards: `!(fBaseParams.hasRope); !(fBaseParams.d<= static_cast<uint32_t>(ConstAxisTemplateNum::NUM64)); !(fBaseParams.d<= static_cast<uint32_t>(ConstAxisTemplateNum::NUM128))`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:861` `GetDTemplateType` ← `ConstAxisTemplateNum::NUM256`
    guards: `!(fBaseParams.hasRope); !(fBaseParams.d<= static_cast<uint32_t>(ConstAxisTemplateNum::NUM64)); !(fBaseParams.d<= static_cast<uint32_t>(ConstAxisTemplateNum::NUM128))`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:864` `GetDTemplateType` ← `ConstAxisTemplateNum::NUM768`
    guards: `!(fBaseParams.hasRope); !(fBaseParams.d<= static_cast<uint32_t>(ConstAxisTemplateNum::NUM64)); !(fBaseParams.d<= static_cast<uint32_t>(ConstAxisTemplateNum::NUM128))`

## 10. `DeterType`

- **host_expr**: `static_cast<uint8_t>(fBaseParams.deterSparseType)`
- **domain**: ['0', '1', '2', '3', '4']
- **value_leaves**: ['0', '1', '2', 'ALL_MASK', 'BN2', 'BN2GS1S2', 'BN2S2', 'DETER_BAND', 'DETER_CAUSAL', 'DETER_DENSE', 'DETER_OLD', 'False', 'INPUT_FORMAT_BN2GS2D', 'INPUT_FORMAT_BS2N2GD', 'INPUT_FORMAT_S2BN2GD', 'INPUT_FORMAT_TND', 'NO_DETER', 'NO_MASK', 'ROPE_D_192', 'True']
- **roots**: ['ATTRIBUTE', 'INPUT_DTYPE', 'INPUT_SHAPE', 'INPUT_VALUE', 'OPTIONAL_INPUT_PRESENCE', 'PLATFORM_ARCH', 'PLATFORM_CORE_COUNT', 'TILING_DATA']
- **undecided**: 21
- **cond_tokens**: strcmp×156, BN2×34, deterSparseType×32, GRAPH_SUCCESS×29, isDeterministic×17, INPUT_FORMAT_TND×16, layoutType×12, isBn2×12, __reached_×11, BN2S2×10, GetDataType×8, BN2GS1S2×7
- **def_sites**:
  - `flash_attention_score_grad_tiling_common_regbase.cpp:745` `CalcleCausalDeterParam` ← `static_cast<uint32_t>(DeterSparseType::DETER_BAND)`
    guards: `!(fBaseParams.sparseMode == static_cast<uint32_t>(SparseMode::RIGHT_DOWN_CAUSAL)&& m>n); !((fBaseParams.sparseMode == static_cast<uint32_t>(SparseMode::NO_MASK)|| fBaseParams.sparseMode == static_cast`
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:663` `DoSparse` ← `GetDeterSparseTilingKey()`

## 11. `IsNEqual`

- **host_expr**: `static_cast<uint8_t>(isDeterNEqual)`
- **domain**: ['0', '1']
- **value_leaves**: ['0', '1', '2', 'ALL_MASK', 'BN2', 'BN2GS1S2', 'BN2S2', 'DETER_BAND', 'DETER_CAUSAL', 'DETER_DENSE', 'DETER_OLD', 'False', 'INPUT_FORMAT_BN2GS2D', 'INPUT_FORMAT_BS2N2GD', 'INPUT_FORMAT_S2BN2GD', 'INPUT_FORMAT_TND', 'NO_DETER', 'NO_MASK', 'ROPE_D_192', 'True']
- **roots**: ['ATTRIBUTE', 'INPUT_DTYPE', 'INPUT_SHAPE', 'INPUT_VALUE', 'OPTIONAL_INPUT_PRESENCE', 'PLATFORM_ARCH', 'PLATFORM_CORE_COUNT', 'TILING_DATA']
- **undecided**: 21
- **cond_tokens**: strcmp×156, BN2×34, deterSparseType×32, GRAPH_SUCCESS×29, isDeterministic×17, INPUT_FORMAT_TND×16, layoutType×12, isBn2×12, __reached_×11, BN2S2×10, GetDataType×8, BN2GS1S2×7
- **def_sites**:
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:1444` `GetTilingKey` ← `fBaseParams.deterSparseType != static_cast<uint32_t>(DeterSparseType::DETER_OLD)`

## 12. `IsBn2MultiBlk`

- **host_expr**: `static_cast<uint8_t>(fBaseParams.isBn2MultiBlk)`
- **domain**: ['0', '1']
- **value_leaves**: ['0', '1', '2', 'ALL_MASK', 'BN2', 'BN2GS1S2', 'BN2S2', 'DETER_BAND', 'DETER_CAUSAL', 'DETER_DENSE', 'DETER_OLD', 'False', 'INPUT_FORMAT_BN2GS2D', 'INPUT_FORMAT_BS2N2GD', 'INPUT_FORMAT_S2BN2GD', 'INPUT_FORMAT_TND', 'NO_DETER', 'NO_MASK', 'ROPE_D_192', 'True']
- **roots**: ['ATTRIBUTE', 'INPUT_DTYPE', 'INPUT_SHAPE', 'INPUT_VALUE', 'OPTIONAL_INPUT_PRESENCE', 'PLATFORM_ARCH', 'PLATFORM_CORE_COUNT', 'TILING_DATA']
- **undecided**: 28
- **cond_tokens**: strcmp×156, BN2×34, GRAPH_SUCCESS×29, isDeterministic×21, isBn2×21, INPUT_FORMAT_TND×16, deterSparseType×13, layoutType×12, isBn2MultiBlk×12, __reached_×11, BN2S2×10, GetDataType×8
- **def_sites**:
  - `flash_attention_score_grad_tiling_common_regbase.cpp:1592` `SetSplitAxis` ← `bnSparseLimit &&(fBaseParams.s1>BN2_MAX_S || fBaseParams.s2>BN2_MAX_S)&&(fBasePa`
  - `flash_attention_score_grad_tiling_common_regbase.cpp:1616` `SetSplitAxis` ← `false`
    guards: `fBaseParams.isBn2MultiBlk; fBaseParams.dropMaskOuter`
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:682` `DoSparse` ← `false`
    guards: `!(DoBn2s2Sparse()&& fBaseParams.blockOuter>= fBaseParams.aicNum); fBaseParams.splitAxis == SplitAxisEnum::BN2 && fBaseParams.isBn2MultiBlk; (fBaseParams.isInvalidCol || fBaseParams.isInvalidRow)`

## 13. `IsDNoEqual`

- **host_expr**: `static_cast<uint8_t>(dNoEqual)`
- **domain**: ['0', '1']
- **value_leaves**: ['0', 'ROPE_D_192']
- **roots**: ['ATTRIBUTE', 'INPUT_SHAPE', 'OPTIONAL_INPUT_PRESENCE']
- **undecided**: 0
- **cond_tokens**: strcmp×56, ROPE_D_192×5, QUERY_ROPE×2
- **def_sites**:
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:1438` `GetTilingKey` ← `(fBaseParams.d1 != fBaseParams.d)|| fBaseParams.hasRope`

## 14. `IsRope`

- **host_expr**: `static_cast<uint8_t>(fBaseParams.hasRope)`
- **domain**: ['0', '1']
- **value_leaves**: []
- **roots**: ['INPUT_SHAPE', 'OPTIONAL_INPUT_PRESENCE']
- **undecided**: 0
- **cond_tokens**: QUERY_ROPE×2
- **def_sites**:
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:95` `GetShapeAttrsInfo` ← `hasQueryRope && hasKeyRope`

## 15. `OutDType`

- **host_expr**: `static_cast<uint8_t>(fBaseParams.outDtype)`
- **domain**: ['0', '1', '2', '3']
- **value_leaves**: ['0', 'BFLOAT16', 'DTYPE_ENUM_INDEX_4', 'DTYPE_ENUM_INDEX_5', 'DTYPE_ENUM_INDEX_6', 'FLOAT16_PRECISION', 'FLOAT32']
- **roots**: ['INPUT_DTYPE']
- **undecided**: 0
- **cond_tokens**: GetDataType×20, DT_FLOAT×13, DT_BF16×5
- **def_sites**:
  - `flash_attention_score_grad_tiling_common_regbase.cpp:1180` `ProcessQuantInfo` ← `fBaseParams.inputDtype`

## 16. `IsNzOut`

- **host_expr**: `static_cast<uint8_t>(fBaseParams.isNzOut)`
- **domain**: ['0', '1']
- **value_leaves**: ['0', '1', '2', 'ALL_MASK', 'BN2', 'BN2GS1S2', 'BN2S2', 'DETER_BAND', 'DETER_CAUSAL', 'DETER_DENSE', 'DETER_OLD', 'False', 'INPUT_FORMAT_BN2GS2D', 'INPUT_FORMAT_BS2N2GD', 'INPUT_FORMAT_S2BN2GD', 'INPUT_FORMAT_TND', 'NO_DETER', 'NO_MASK', 'ROPE_D_192', 'True']
- **roots**: ['ATTRIBUTE', 'COMPILE_INFO', 'INPUT_DTYPE', 'INPUT_SHAPE', 'INPUT_VALUE', 'OPTIONAL_INPUT_PRESENCE', 'PLATFORM_ARCH', 'PLATFORM_CORE_COUNT', 'TILING_DATA']
- **undecided**: 28
- **cond_tokens**: strcmp×156, BN2×35, GRAPH_SUCCESS×33, isDeterministic×20, INPUT_FORMAT_TND×16, deterSparseType×13, layoutType×12, isBn2×12, GetDataType×12, splitAxis×11, __reached_×11, BN2S2×10
- **def_sites**:
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:444` `DoOpTiling` ← `(fBaseParams.splitAxis == SplitAxisEnum::BN2GS1S2 && fBaseParams.d>static_cast<u`
    guards: `!(ret != ge::GRAPH_SUCCESS)`

## 17. `IsTndSwizzle`

- **host_expr**: `static_cast<uint8_t>(tndBaseInfo.isTndSwizzle)`
- **domain**: ['0', '1']
- **value_leaves**: ['0', '1', '2', 'ALL_MASK', 'BAND', 'BN2', 'BN2GS1S2', 'BN2S2', 'CASUAL', 'DENSE', 'DETER_BAND', 'DETER_CAUSAL', 'DETER_DENSE', 'DETER_OLD', 'False', 'INPUT_FORMAT_BN2GS2D', 'INPUT_FORMAT_BS2N2GD', 'INPUT_FORMAT_S2BN2GD', 'INPUT_FORMAT_TND', 'NO_DETER', 'NO_MASK', 'ROPE_D_192', 'True', 'UNSUPPORTED']
- **roots**: ['ATTRIBUTE', 'COMPILE_INFO', 'INPUT_DTYPE', 'INPUT_SHAPE', 'INPUT_VALUE', 'OPTIONAL_INPUT_PRESENCE', 'PLATFORM_ARCH', 'PLATFORM_CORE_COUNT', 'TILING_DATA']
- **undecided**: 26
- **cond_tokens**: strcmp×188, BN2×36, INPUT_FORMAT_TND×27, isDeterministic×21, GRAPH_SUCCESS×20, deterSparseType×15, isBn2×12, BN2S2×11, __reached_×11, BN2GS1S2×8, GetDataType×8, DT_FLOAT×6
- **def_sites**:
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:461` `DoOpTiling` ← `fBaseParams.enableSwizzle && fBaseParams.layoutType == INPUT_FORMAT_TND && templ`
    guards: `!(ret != ge::GRAPH_SUCCESS)`

## 18. `IsRegbase`

- **host_expr**: `static_cast<uint8_t>(isRegbasePlatformValue)`
- **domain**: ['0', '1']
- **value_leaves**: ['ENABLE']
- **roots**: []
- **undecided**: 0
- **def_sites**:
  - `flash_attention_score_grad_tiling_normal_regbase.cpp:1441` `GetTilingKey` ← `OptionEnum::ENABLE`
