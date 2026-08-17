
        void T::DoOpTiling() {
          qDesc = ctx.query.desc;
          inputQType_ = qDesc->GetDataType();
        }
        uint64_t T::GetTilingKey() const {
          return GET_TPL_TILING_KEY(inputQType_);
        }
        