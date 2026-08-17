__global__ __aicore__ void toy(__gm__ uint8_t *query, __gm__ uint8_t *out, __gm__ uint8_t *workspace, __gm__ uint8_t *tiling) {
  GET_TILING_DATA_WITH_STRUCT(QLIV2TilingData, tiling_data_in, tiling);
  (void)tiling_data_in.bSize;
}
