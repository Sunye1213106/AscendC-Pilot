#define TILING_KEY_1111 1111
#define TILING_KEY_1110 1110
#define TILING_KEY_BRANCH(tilingKey, flag) { \
    if (TILING_KEY_IS(tilingKey)) { (void)flag; } \
}
__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, __gm__ uint8_t *tiling) {
  TILING_KEY_BRANCH(TILING_KEY_1111, true)
  TILING_KEY_BRANCH(TILING_KEY_1110, false)
}
