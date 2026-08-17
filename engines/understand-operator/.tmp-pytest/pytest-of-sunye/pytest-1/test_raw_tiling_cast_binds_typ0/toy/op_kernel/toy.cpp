#include "arch35/toy_tiling_data.h"
__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, __gm__ uint8_t *tiling) {
  auto *td = reinterpret_cast<WireAbi*>(tiling);
  (void)td->blockDim;
}
