
        ge::graphStatus T::DoOpTiling() {
          auto gating = context_->GetInputDesc(0);
          return ge::GRAPH_SUCCESS;
        }
        uint64_t T::GetTilingKey() const {
          return GET_TPL_TILING_KEY(0, 1);
        }
        