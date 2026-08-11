
        template <typename T>
        __aicore__ inline void HelperCopy(LocalTensor<T> dst, GlobalTensor<T> src) {
          DataCopy(dst, src);
        }
        