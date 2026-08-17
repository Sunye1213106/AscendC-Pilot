__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, __gm__ uint8_t *tiling) {
  if (TILING_KEY_IS(0)) { return; }
  if (TILING_KEY_IS(10)) { return; }
  if (TILING_KEY_IS(100)) { return; }
  if (TILING_KEY_IS(110)) { return; }
  if (TILING_KEY_IS(200)) { return; }
  if (TILING_KEY_IS(100000)) { return; }
  if (TILING_KEY_IS(100010)) { return; }
  if (TILING_KEY_IS(200000)) { return; }
}
