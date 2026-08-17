
        void T::DoOpTiling() {
          obj.flag = parseInfo.foo;
        }
        uint64_t T::GetTilingKey() const {
          return GET_TPL_TILING_KEY(obj.flag);
        }
        