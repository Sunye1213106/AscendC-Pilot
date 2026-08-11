/**
 * SOURCE: TEST/ops-transformer/examples/add_example/op_kernel/add_example.cpp
 */
    if constexpr (schMode == static_cast<uint32_t>(AddExampleTilingKey::TILING_KEY_EXAMPLE_FLOAT)) {
        NsAddExample::AddExample<float> op;
        op.Init(x, y, z, &tilingData);
        op.Process();
    }
    if constexpr (schMode == static_cast<uint32_t>(AddExampleTilingKey::TILING_KEY_EXAMPLE_INT32)) {
        NsAddExample::AddExample<int32_t> op;
        op.Init(x, y, z, &tilingData);
        op.Process();
    }
