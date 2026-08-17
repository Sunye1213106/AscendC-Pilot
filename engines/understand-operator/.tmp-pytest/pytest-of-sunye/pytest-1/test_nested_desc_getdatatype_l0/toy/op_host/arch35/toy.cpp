
        void T::DoOpTiling() {
          inputQType_ = ctx.query.desc->GetDataType();
        }
        uint64_t T::GetTilingKey() const {
          return GET_TPL_TILING_KEY(inputQType_);
        }
        