/**
 * SOURCE: TEST/ops-transformer/examples/flash_attn_example/ascend_ops/csrc/flash_attn_example/torch_interface.cpp
 */
    // 空 Tensor 检查
    if (q.numel() == 0) {
        printf("Error: query empty tensor is not supported.\n");
        return false;
    }
    if (k.numel() == 0) {
        printf("Error: key empty tensor is not supported.\n");
        return false;
    }
    if (v.numel() == 0) {
        printf("Error: value empty tensor is not supported.\n");
        return false;
    }
