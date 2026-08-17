
        class InnerParams { public: int scale; };
        class OuterTiling {
         public:
          InnerParams base;
          typename std::conditional<A, InnerParams, std::nullptr_t>::type opt;
        };
        inline __aicore__ void RunKernel(
            __gm__ uint8_t *q, __gm__ uint8_t *out, __gm__ uint8_t *tiling_data) {
          OuterTiling *tilingData = (OuterTiling *)tiling_data;
          int v = tilingData->base.scale;
          (void)v;
        }
        