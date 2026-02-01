cmake_minimum_required(VERSION 3.10)
project(FusionHawking_Cpp)

set(CMAKE_CXX_STANDARD 17)

# Bindings Header location
include_directories(${CMAKE_BINARY_DIR}/generated/cpp)

# 1. C++ App (Demo)
add_executable(cpp_app examples/cpp_app/main.cpp)
if(WIN32)
    target_link_libraries(cpp_app ws2_32)
endif()

# 2. C++ Unit Test
add_executable(cpp_test tests/cpp_test.cpp)
if(WIN32)
    target_link_libraries(cpp_test ws2_32)
endif()
