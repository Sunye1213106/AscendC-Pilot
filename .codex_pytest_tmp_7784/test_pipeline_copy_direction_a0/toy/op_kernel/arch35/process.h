
        template <typename T>
        class Process {
         public:
          __aicore__ inline void Process() {
            LocalTensor<T> qUb;
            GlobalTensor<T> qGm;
            LocalTensor<T> tmpUb;
            GlobalTensor<T> outGm;
            pipe.InitBuffer(qQueue, 2, size);
            qUb = qQueue.AllocTensor<T>();
            DataCopy(qUb, qGm);
            SetFlag(HARD_EVENT, PIPE_MTE2, EVENT_ID0);
            WaitFlag(HARD_EVENT, PIPE_MTE2, EVENT_ID0);
            Exp(tmpUb, qUb);
            DataCopy(outGm, tmpUb);
            qQueue.FreeTensor(qUb);
          }
        };
        