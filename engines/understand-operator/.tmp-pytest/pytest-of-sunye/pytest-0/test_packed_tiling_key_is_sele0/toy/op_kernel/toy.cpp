__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, __gm__ uint8_t *tiling) {
  TILING_KEY_IS(QF16_NOCACHE_BSA_TILING);
  TILING_KEY_IS(QBF16_NOCACHE_BSA_TILING);
}
