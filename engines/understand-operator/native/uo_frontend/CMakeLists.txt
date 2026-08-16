cmake_minimum_required(VERSION 3.16)
project(uo_frontend LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_path(
  LIBCLANG_INCLUDE_DIR
  NAMES clang-c/Index.h
  HINTS ENV LLVM_DIR ENV CLANG_DIR
  PATH_SUFFIXES include
)
find_library(
  LIBCLANG_LIBRARY
  NAMES clang libclang
  HINTS ENV LLVM_DIR ENV CLANG_DIR
  PATH_SUFFIXES lib lib64
)

if(NOT LIBCLANG_INCLUDE_DIR OR NOT LIBCLANG_LIBRARY)
  message(STATUS "uo_frontend: libclang not found (optional); skipping build")
  return()
endif()

add_executable(uo_frontend uo_frontend.cpp)
target_include_directories(uo_frontend PRIVATE ${LIBCLANG_INCLUDE_DIR})
target_link_libraries(uo_frontend PRIVATE ${LIBCLANG_LIBRARY})

if(WIN32)
  target_compile_definitions(uo_frontend PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()

option(UO_FRONTEND_SANITIZE "Build uo_frontend with ASAN/UBSAN" OFF)
if(UO_FRONTEND_SANITIZE AND NOT WIN32)
  target_compile_options(uo_frontend PRIVATE -fsanitize=address,undefined)
  target_link_options(uo_frontend PRIVATE -fsanitize=address,undefined)
endif()
