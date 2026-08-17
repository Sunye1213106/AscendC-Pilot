__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, __gm__ uint8_t *tiling) {
  if (TILING_KEY_IS(0)) { return; }
  if (TILING_KEY_IS(4)) { return; }
  if (TILING_KEY_IS(8)) { return; }
}
