class ATiling { public: int a; };
class BTiling { public: int b; };
__global__ __aicore__ void toy(__gm__ uint8_t *x, __gm__ uint8_t *y, __gm__ uint8_t *tiling) {
  GET_TILING_DATA(td, tiling);
}
