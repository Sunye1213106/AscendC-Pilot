REGISTER_TILING_DEFAULT(ToyTilingData);
__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, __gm__ uint8_t *tiling) {
  __gm__ ToyTilingData *td = reinterpret_cast<__gm__ ToyTilingData *>(tiling);
  uint64_t k = td->tilingKey;
}
