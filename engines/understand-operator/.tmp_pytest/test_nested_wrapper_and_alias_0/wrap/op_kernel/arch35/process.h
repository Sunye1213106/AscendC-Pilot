
        using MyTensor = AscendC::LocalTensor<float>;

        class Inner {
         public:
          MutexBuffer<BufferType::L1, SyncType::INNER_CORE_SYNC> storage;
          void Lock() { storage.LockProd(); }
        };

        class Outer {
         public:
          Inner inner;
          void Lock() { inner.Lock(); }
        };

        class Process {
         public:
          Outer x;
          MyTensor ub;
          GlobalTensor<float> gm;
          __aicore__ inline void Process() {
            DataCopy(ub, gm);
            x.Lock();
            SetFlag<HardEvent::MTE2_V>(EVENT_ID0);
          }
        };
        