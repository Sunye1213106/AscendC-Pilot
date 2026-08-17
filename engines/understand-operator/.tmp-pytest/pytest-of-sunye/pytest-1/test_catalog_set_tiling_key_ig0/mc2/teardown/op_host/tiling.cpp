void Pack() {
  uint64_t tilingKey = 10000;
  tilingKey += static_cast<uint64_t>(quantMode);
  context_->SetTilingKey(tilingKey);
}
