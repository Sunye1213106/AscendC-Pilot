cmake_minimum_required(VERSION 3.16)
project(uo_walk LANGUAGES CXX)

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
  message(STATUS "uo_walk: libclang not found (optional); skipping build")
  return()
endif()

add_executable(uo_walk uo_walk.cpp)
target_include_directories(uo_walk PRIVATE ${LIBCLANG_INCLUDE_DIR})
target_link_libraries(uo_walk PRIVATE ${LIBCLANG_LIBRARY})

if(WIN32)
  target_compile_definitions(uo_walk PRIVATE _CRT_SECURE_NO_WARNINGS)
endif()
