
        uint64_t T::GetTilingKey() const {
          Mode flag = Mode::OFF;
          if (cond) {
            flag = Mode::ON;
          }
          return GET_TPL_TILING_KEY(static_cast<uint8_t>(flag));
        }
        