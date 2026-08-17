void ComputeTilingKey() {
  tilingKey_ += normType * NORM_TYPE_TILING_KEY;
  tilingKey_ += normAddedType * NORM_ADDED_TYPE_TILING_KEY;
  tilingKey_ += ropeType * ROPE_TYPE_TILING_KEY;
  tilingKey_ += concatOrder * CONCAT_ORDER_TILING_KEY;
}
void PostTiling() { context_->SetTilingKey(tilingKey_); }
