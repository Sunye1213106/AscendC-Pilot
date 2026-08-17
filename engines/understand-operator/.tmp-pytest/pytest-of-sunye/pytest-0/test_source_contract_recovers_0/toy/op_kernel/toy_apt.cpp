#include "arch35/toy_template_tiling_key.h"
template <bool IsEmptyTensor, uint8_t SplitAxis, uint8_t InputDType, bool IsTnd, bool IsDrop, bool IsPse, bool IsAttenMask, uint8_t S1TemplateNum, uint8_t S2TemplateNum, uint8_t DTemplateNum, uint8_t DeterType, bool IsNEqual, bool IsBn2MultiBlk, bool IsDNoEqual, bool IsRope, uint8_t OutDType, bool IsNzOut, bool IsTndSwizzle, bool IsRegbase>
__global__ __aicore__ void toy(__gm__ uint8_t *query, __gm__ uint8_t *queryRope, __gm__ uint8_t *dq, __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {
  GET_TILING_DATA_WITH_STRUCT(ToyTilingData, td, tiling_data);
}
