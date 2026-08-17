#include "arch35/entry.h"
template <bool Flag>
__global__ __aicore__ void toy(__gm__ uint8_t *query, __gm__ uint8_t *out, __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {
  REGISTER_TILING_DEFAULT(PackAlias);
}
