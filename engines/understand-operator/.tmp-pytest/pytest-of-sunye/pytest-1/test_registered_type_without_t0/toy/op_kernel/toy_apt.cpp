#include "arch35/layout_types.h"
template <bool Flag>
__global__ __aicore__ void toy(__gm__ uint8_t *query, __gm__ uint8_t *out, __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {
  REGISTER_TILING_FOR_TILINGKEY("(TILING_KEY_VAR & 0x1)", PackedLayout);
}
