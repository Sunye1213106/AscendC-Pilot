
        #include "helper.h"
        template <typename T>
        class Process {
         public:
          __aicore__ inline void Process() {
            LocalTensor<T> qUb;
            GlobalTensor<T> qGm;
            LocalTensor<T> tmpUb;
            SetFlag(HARD_EVENT, PIPE_MTE2, EVENT_ID0);
            HelperCopy(qUb, qGm);
            WaitFlag(HARD_EVENT, PIPE_MTE2, EVENT_ID0);
            Exp(tmpUb, qUb);
          }
        };
        