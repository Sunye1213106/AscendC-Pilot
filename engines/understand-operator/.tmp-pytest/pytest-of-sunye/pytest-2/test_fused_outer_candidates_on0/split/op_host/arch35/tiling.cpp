
void SetSplitCore() {
  int64_t fusedOuter = b * n2 * g;
  int64_t fusedOuterBn2 = b * n2;
  td->blockOuter = fusedOuter;
}
