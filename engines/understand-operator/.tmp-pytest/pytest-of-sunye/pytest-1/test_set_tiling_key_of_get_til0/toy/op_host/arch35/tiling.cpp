#define KEY_BASE 100000
#define KEY_SCENE 100
uint64_t T::GetTilingKey() const {
  return KEY_BASE + scene * KEY_SCENE + dtypeKey(dtype);
}
void T::PostTiling() { context_->SetTilingKey(GetTilingKey()); }
