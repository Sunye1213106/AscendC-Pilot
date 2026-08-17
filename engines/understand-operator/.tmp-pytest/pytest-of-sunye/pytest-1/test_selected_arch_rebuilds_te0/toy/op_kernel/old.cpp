
        #include "arch22/entry.h"
        template <bool X, bool Y, bool Z>
        __global__ __aicore__ void toy_kernel(__gm__ uint8_t *q) { OldOnly(q); }
        