uint64_t GetTilingKey() const {
  return GET_TILINGKEY(layout, sparse, mask);
}
void PackBits() {
  uint64_t tilingKey = static_cast<uint64_t>(inDtype == ge::DT_BF16);
  tilingKey = (tilingKey << 2) + static_cast<uint64_t>(param.cacheMode);
}
