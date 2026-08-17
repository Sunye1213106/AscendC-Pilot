
        void T::DoOpTiling() {
          local = x;
          fBaseParams.x = local;
        }
        uint64_t T::GetTilingKey() const {
          return GET_TPL_TILING_KEY(fBaseParams.x);
        }
        