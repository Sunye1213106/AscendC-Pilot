uint64_t BuildKey() {
  bool isTnd = true;
  return GET_TPL_TILING_KEY(0, static_cast<uint8_t>(splitAxis), isTnd);
}
