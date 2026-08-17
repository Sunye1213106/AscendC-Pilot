template <typename T> class Worker { public: void Process(); };
template <typename T>
void Worker<T>::Process() {
  if constexpr (sizeof(T) > 1) { return; }
}
