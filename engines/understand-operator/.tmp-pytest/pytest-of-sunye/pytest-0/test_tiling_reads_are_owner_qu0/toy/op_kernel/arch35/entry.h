
        class AData { public: int x; };
        class BData { public: int x; };
        template <bool A, bool B>
        inline __aicore__ void
        RegbaseFAG(__gm__ uint8_t *q, __gm__ uint8_t *out, __gm__ uint8_t *tiling_data) {
          ReadA((AData *)tiling_data);
        }
        inline __aicore__ void ReadA(AData *tilingData) {
          int v = tilingData->x;
          (void)v;
        }
        