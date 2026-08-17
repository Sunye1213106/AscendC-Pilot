
        void T::DoOpTiling() {
          obj.flag = input != nullptr;
        }
        uint64_t T::GetTilingKey() const {
          return GET_TPL_TILING_KEY(obj.flag);
        }
        