
#if (ORIG_DTYPE_QUERY == DT_FLOAT16) && (ORIG_DTYPE_KEY == DT_FLOAT16)
#if TILING_KEY_VAR == F16_PATH
#endif
#endif
#if defined(ORIG_DTYPE_X) && defined(ORIG_DTYPE_WEIGHT) && defined(ORIG_DTYPE_SCALE)
#if ORIG_DTYPE_X == DT_INT8 && ORIG_DTYPE_WEIGHT == DT_INT4 && ORIG_DTYPE_SCALE == DT_UINT64
#include "quant.h"
#endif
#endif
