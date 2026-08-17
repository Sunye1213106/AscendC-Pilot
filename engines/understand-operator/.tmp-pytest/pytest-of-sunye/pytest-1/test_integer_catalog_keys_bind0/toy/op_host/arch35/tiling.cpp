void GenTilingKey() {
  tilingKey_ = static_cast<uint64_t>(templateType_) * 100 + isFullyLoad_;
}
uint64_t GetTilingKey() const { return tilingKey_; }
