
        #include "kernel_operator.h"
        namespace AscendC {
        using namespace MicroAPI;
        __aicore__ inline void Process() {
          RegTensor<float> vregSrc;
          MaskReg preg;
          LocalTensor<float> ub;
          GlobalTensor<float> gm;
          LoadAlign(vregSrc, ((__ubuf__ float *&)ub), 64);
          DataCopy(ub, gm);
        }
        }
        