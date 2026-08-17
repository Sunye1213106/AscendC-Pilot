
        #include "arch35/entry.h"
        template <bool A, bool B>
        __global__ __aicore__ void toy_kernel(
            __gm__ uint8_t *q, __gm__ uint8_t *out,
            __gm__ uint8_t *workspace, __gm__ uint8_t *tiling_data) {
          RunKernel(q, out, tiling_data);
        }
        