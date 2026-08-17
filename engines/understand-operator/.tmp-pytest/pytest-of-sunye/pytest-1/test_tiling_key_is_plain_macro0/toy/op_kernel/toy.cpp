#define NORMAL_INT32_FULLY_LOAD 141
#define NORMAL_INT32_NOT_FULLY_LOAD 140
__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, __gm__ uint8_t *tiling) {
  if TILING_KEY_IS(NORMAL_INT32_FULLY_LOAD) { return; }
  else if TILING_KEY_IS(NORMAL_INT32_NOT_FULLY_LOAD) { return; }
}
