__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, __gm__ uint8_t *tiling) {
  TILING_KEY_IS(QF16_KVF16_TND_TND_NOCACHE_FLOATSM_NOMASK_BSA_TILING);
  TILING_KEY_IS(QBF16_KVBF16_BNSD_BNSD_NOCACHE_HALFSM_NOMASK_BSA_TILING);
}
