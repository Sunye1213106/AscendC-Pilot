# Query → ANSWERED — empty tensor supported? (real TEST)

## Source

`TEST/.../flash_attn_example/.../torch_interface.cpp`

## Question

Does flash_attn_example support empty query/key/value tensors?

## Correct answer

`ANSWERED`: No — host returns false when `q/k/v.numel()==0`, with printf errors.
