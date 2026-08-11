
        template <typename T>
        class Process {
         public:
          __aicore__ inline void Process() {
            MutexBuffer<BufferType::L1, SyncType::INNER_CORE_SYNC> anyName;
            MutexBuffer<bufferType, syncType> otherName;
            LocalTensor<T> ub;
            DataCopy(ub, anyName);
          }
        };
        