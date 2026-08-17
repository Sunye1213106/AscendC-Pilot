#include "arch35/types.h"
__global__ __aicore__ void kernel_b(__gm__ uint8_t *x, __gm__ uint8_t *y, __gm__ uint8_t *tiling) {
  GET_TILING_DATA_WITH_STRUCT(BData, td, tiling);
}
