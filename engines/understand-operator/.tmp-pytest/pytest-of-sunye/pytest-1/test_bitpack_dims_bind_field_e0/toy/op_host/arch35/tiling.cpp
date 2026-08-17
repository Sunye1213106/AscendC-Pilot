void SetKey() {
  uint64_t tilingKey = static_cast<uint64_t>(inDtype == ge::DT_BF16);
  tilingKey = (tilingKey << 2) + static_cast<uint64_t>(param.cacheMode);
  context->SetTilingKey(tilingKey);
}
