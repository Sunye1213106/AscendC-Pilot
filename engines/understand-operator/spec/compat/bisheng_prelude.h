// Minimal Bisheng frontend declarations for vanilla-clang AST recovery.
// Every identifier here is a compiler builtin absent from CANN headers.
// Intrinsics use C varargs (`...`) to match cce_aicore_intrinsics.h aliases —
// call-site arity varies and fixed prototypes produce "no matching function".
#pragma once
#include <cstdint>
#include <cstddef>

// Catlass (template_linear_algebra) writes bisheng postfix attributes
// `__forceinline__[aicore]`. Vanilla clang cannot parse that. Map to the
// same qualifiers erase_qualifiers already empties. Close the include guard
// so operator 3rd copies of macros.hpp do not reintroduce `[aicore]`.
#ifndef CATLASS_DETAIL_MACROS_HPP
#define CATLASS_DETAIL_MACROS_HPP
#ifndef __forceinline__
#define __forceinline__ inline
#endif
#define CATLASS_DEVICE __forceinline__ __aicore__
#define CATLASS_HOST_DEVICE __forceinline__ __host_aicore__
#define CATLASS_GLOBAL __global__ __aicore__
#endif

// ---- scalar builtin types -------------------------------------------------
// Each FP8/FP4 spelling must be a DISTINCT type: CANN specializes templates on
// float8_e4m3_t / float8_e5m2_t / ... separately, and aliasing them all to one
// struct makes those specializations collide as redefinitions.
struct __bs_f16 {
    uint16_t v;
    constexpr __bs_f16() : v(0) {}
    explicit constexpr __bs_f16(int x) : v(static_cast<uint16_t>(x)) {}
    explicit constexpr __bs_f16(unsigned x) : v(static_cast<uint16_t>(x)) {}
    explicit constexpr __bs_f16(double x) : v(static_cast<uint16_t>(x)) {}
    explicit constexpr operator float() const { return float(v); }
};
struct __bs_b16 { uint16_t v; };
struct __bs_f8_e4m3 { uint8_t v; };
struct __bs_f8_e5m2 { uint8_t v; };
struct __bs_f8_e8m0 { uint8_t v; };
struct __bs_hif8 { uint8_t v; };
struct __bs_f4_e2m1x2 { uint8_t v; };
struct __bs_f4_e1m2x2 { uint8_t v; };

using half = __bs_f16;
using float32_t = float;
using bfloat16_t = __bs_b16;
using hifloat8_t = __bs_hif8;
using float8_e4m3_t = __bs_f8_e4m3;
using float8_e5m2_t = __bs_f8_e5m2;
using float8_e8m0_t = __bs_f8_e8m0;
using fp8_e4m3fn_t = __bs_f8_e4m3;
using fp8_e5m2_t = __bs_f8_e5m2;
using fp8_e8m0_t = __bs_f8_e8m0;
using float4_e2m1x2_t = __bs_f4_e2m1x2;
using float4_e1m2x2_t = __bs_f4_e1m2x2;
using fp4x2_e1m2_t = __bs_f4_e1m2x2;
using fp4x2_e2m1_t = __bs_f4_e2m1x2;
struct __bs_i4x2 { uint8_t v; };
using int4x2_t = __bs_i4x2;

#ifndef uint
using uint = unsigned int;
#endif

// ---- pipe / event / memory handles ---------------------------------------
enum pipe_t {
    PIPE_S = 0, PIPE_V = 1, PIPE_M = 2, PIPE_MTE1 = 3,
    PIPE_MTE2 = 4, PIPE_MTE3 = 5, PIPE_ALL = 6, PIPE_FIX = 7,
    PIPE_MTE4 = 8, PIPE_MTE5 = 9, PIPE_V2 = 10,
};
enum event_t {
    EVENT_ID0 = 0, EVENT_ID1 = 1, EVENT_ID2 = 2, EVENT_ID3 = 3,
    EVENT_ID4 = 4, EVENT_ID5 = 5, EVENT_ID6 = 6, EVENT_ID7 = 7,
};
enum mem_t {
    MEM_UB = 0, MEM_L1 = 1, MEM_L0A = 2, MEM_L0B = 3, MEM_L0C = 4, MEM_GM = 5,
};

// Enums from cce_aicore_intrinsics.h. Stubbed here because that header is only
// reachable after several other builtins parse cleanly; without these stubs
// DMA / pad structs fail early with "unknown type name".
enum QuantMode_t { NoQuant = 0 };
enum pad_t { PAD_NONE = 0 };
enum cache_line_t { SINGLE_CACHE_LINE = 0, ENTIRE_DATA_CACHE = 1 };
enum dcci_dst_t { CACHELINE_ALL = 0, CACHELINE_OUT = 2 };
enum mem_dsb_t { MEM_DSB_NONE = 0 };
enum Spr { SPR_NONE = 0 };

// cce_aicore_intrinsics.h / __clang_cce_vector_intrinsics.h are compiler
// builtins. CANN headers use these names without including those files.
enum atomic_op_t { ATOMIC_SUM = 0 };
enum atomic_type_t {
    ATOMIC_NONE = 0,
    ATOMIC_F32 = 1,
    ATOMIC_F16 = 2,
    ATOMIC_S16 = 3,
    ATOMIC_S32 = 4,
    ATOMIC_S8 = 5,
    ATOMIC_BF16 = 6,
};
enum class Mode {
    UNKNOWN_VALUE,
    MERGING_VALUE,
    ZEROING_VALUE,
    MERGING_SRC0_VALUE
};

// ---- vector / mask register builtins (Bisheng MicroAPI foundation) -------
// CANN: MaskReg=vector_bool, UnalignRegForStore=vector_align, AddrReg=vector_address.
// Do not stub RegTensor / VecReg here: CANN headers already declare them.
struct vector_bool { uint64_t bits[4]; };
struct vector_align { uint8_t data[32]; };
struct vector_address { uint32_t addr; };
struct vector_u8 { uint8_t v[256]; };
struct vector_u16 { uint16_t v[128]; };
struct vector_u32 { uint32_t v[64]; };
struct vector_u64 { uint64_t v[32]; };
struct vector_s8 { int8_t v[256]; };
struct vector_s16 { int16_t v[128]; };
struct vector_s32 { int32_t v[64]; };
struct vector_s64 { int64_t v[32]; };
struct vector_f16 { uint16_t v[128]; };
struct vector_f32 { float v[64]; };
struct vector_f64 { double v[32]; };
struct vector_bf16 { uint16_t v[128]; };
struct vector_hif8 { uint8_t v[256]; };
struct vector_f8e4m3 { uint8_t v[256]; };
struct vector_f8e5m2 { uint8_t v[256]; };
struct vector_f8e8m0 { uint8_t v[256]; };
struct vector_f4e2m1x2 { uint8_t v[256]; };
struct vector_f4e1m2x2 { uint8_t v[256]; };
// Packed 4-bit lanes (s4x2 / u4x2). Absent from CANN headers under vanilla clang;
// operator TUs then fail probe as `unknown type name 'vector_s4x2'`.
struct vector_s4x2 { uint8_t v[128]; };
struct vector_u4x2 { uint8_t v[128]; };
struct vector_s4 { uint8_t v[128]; };
struct vector_u4 { uint8_t v[128]; };

// Rounding mode tag. Bisheng builtin is `enum class ROUND { R, A, F, C, Z, O, H }`
// in `__clang_dpp_types.h`. An enumerator named ROUND is the wrong stub:
// kernel/CANN code writes `ROUND::…` and then reports
// `'ROUND' is not a class, namespace, or enumeration`.
enum class ROUND { R, A, F, C, Z, O, H };

using MaskReg = vector_bool;
using UnalignRegForLoad = vector_align;
using UnalignRegForStore = vector_align;
using UnalignReg = vector_align;
using AddrReg = vector_address;

namespace __cce_scalar {
inline uint64_t get_ctrl(...) { return 0; }
inline void set_ctrl(...) {}
inline uint64_t sbitset0(...) { return 0; }
inline uint64_t sbitset1(...) { return 0; }
inline void copy_ubuf_to_gm_align_v2(...) {}
inline void copy_ubuf_to_ubuf(...) {}
inline void dcci(...) {}
}

// ---- misc builtin intrinsics (varargs, matching bisheng alias headers) ----
extern "C" {
uint64_t get_ctrl(...);
void set_ctrl(...);
int64_t get_block_idx(...);
int64_t get_block_num(...);
int64_t get_subblockid(...);
int64_t get_subblockdim(...);
int64_t get_coreid(...);
uint64_t get_arch_ver(...);
uint64_t get_pc(...);
uint64_t get_imm(...);
uint64_t get_ar(...);
uint64_t get_rsvd_cnt(...);
uint64_t sbitset0(...);
uint64_t sbitset1(...);
void set_vector_mask(...);
void set_vector_mask_dup(...);
void set_mask_norm(...);
void set_mask_count(...);
void set_atomic_none(...);
void set_padding(...);
void set_loop_size_ubtoout(...);
void set_loop_size_outtoub(...);
void set_st_atomic_cfg(...);
void set_aipp_spr_9(...);
void set_aipp_spr_18(...);
void set_aipp_spr_19(...);
void set_aipp_spr_20(...);
void set_aipp_spr_21(...);
void pipe_barrier(...);
void set_flag(...);
void wait_flag(...);
void hset_flag(...);
void hwait_flag(...);
void dcci(...);
void dsb(...);
void get_buf(...);
void rls_buf(...);
void copy_ubuf_to_gm_align_v2(...);
void copy_ubuf_to_ubuf(...);
void sprclr(...);
int64_t sff0(...);
void trap(...);
}
