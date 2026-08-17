#define TILING_KEY_DIVIDE_BS_FP16 100
#define TILING_KEY_DIVIDE_BS_BF16 101
__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, __gm__ uint8_t *tiling) {
  if (TILING_KEY_IS(TILING_KEY_DIVIDE_BS_FP16)) { return; }
  if (TILING_KEY_IS(TILING_KEY_DIVIDE_BS_BF16)) { return; }
}
