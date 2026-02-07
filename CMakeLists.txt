cmake_minimum_required(VERSION 3.10)
project(FusionHawking)

set(CMAKE_CXX_STANDARD 23)

# 1. C++ Core Library (Headers will be exported to consumers)

# 1. C++ Core Library
add_library(fusion_hawking_cpp STATIC
    src/cpp/src/runtime.cpp
)
target_include_directories(fusion_hawking_cpp PUBLIC 
    src/cpp/include
    ${PROJECT_SOURCE_DIR}/build/generated/cpp
)

# 2. Simple No-SD Demos
add_executable(simple_server_cpp examples/simple_no_sd/cpp/server.cpp)
add_executable(simple_client_cpp examples/simple_no_sd/cpp/client.cpp)
if(WIN32)
    target_link_libraries(simple_server_cpp ws2_32)
    target_link_libraries(simple_client_cpp ws2_32)
endif()

# 3. Integrated App Demo (Required for CI Artifacts)
add_executable(cpp_app examples/integrated_apps/cpp_app/main.cpp)
target_link_libraries(cpp_app fusion_hawking_cpp)
if(WIN32)
    target_compile_definitions(cpp_app PRIVATE _WINSOCK_DEPRECATED_NO_WARNINGS)
endif()

# 3. C++ Unit Test
add_executable(cpp_test tests/cpp_test.cpp)
target_link_libraries(cpp_test fusion_hawking_cpp)

option(FUSION_ENABLE_COVERAGE "Enable code coverage instrumentation" OFF)

if(FUSION_ENABLE_COVERAGE)
    if(NOT WIN32)
        # Linux (GCC/Clang) coverage flags
        add_compile_options(--coverage)
        add_link_options(--coverage)
    endif()
endif()

if(WIN32)
    target_link_libraries(fusion_hawking_cpp ws2_32)
    target_compile_definitions(fusion_hawking_cpp PRIVATE _WINSOCK_DEPRECATED_NO_WARNINGS)
    target_compile_definitions(cpp_test PRIVATE _WINSOCK_DEPRECATED_NO_WARNINGS)

    # Enable PDB generation for Release builds (Required for OpenCppCoverage)
    if(MSVC)
        set(CMAKE_CXX_FLAGS_RELEASE "${CMAKE_CXX_FLAGS_RELEASE} /Zi")
        set(CMAKE_EXE_LINKER_FLAGS_RELEASE "${CMAKE_EXE_LINKER_FLAGS_RELEASE} /DEBUG /OPT:REF /OPT:ICF")
        set(CMAKE_STATIC_LINKER_FLAGS_RELEASE "${CMAKE_STATIC_LINKER_FLAGS_RELEASE}")
    endif()
endif()
