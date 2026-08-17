struct Info { int x; };
inline __aicore__ void RunKernel(
    __gm__ uint8_t *q, __gm__ uint8_t *out, __gm__ uint8_t *tiling_data) {
  Info info;
  int v = info.x;
  (void)v;
}
