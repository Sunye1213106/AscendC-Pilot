
        void T::DoOpTiling() {
          fBaseParams.isNzOut = context_->GetInputDesc(0)->GetDataType() == ge::DT_FLOAT;
        }
        uint64_t T::GetTilingKey() const {
          return GET_TPL_TILING_KEY(fBaseParams.isNzOut);
        }
        