
void SetSplitCore() {
  int64_t fusedOuter = b * n2 * g;
  int64_t blockFactor = (fusedOuter + aicNum - 1) / aicNum;
  int64_t blockOuter = (fusedOuter + blockFactor - 1) / blockFactor;
  td->blockOuter = blockOuter;
}
