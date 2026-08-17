uint64_t GetTilingKey() const {
  return GET_TILINGKEY(tilingKeyLayout, hasAttenMask, hasTopkMask);
}
