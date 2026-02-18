cmake_minimum_required(VERSION 3.10)
project(CppAppDemo)

set(CMAKE_CXX_STANDARD 23)

# Include the FusionCodegen helper
include(${CMAKE_CURRENT_SOURCE_DIR}/../../../cmake/FusionCodegen.cmake)

if(NOT TARGET fusion_hawking_cpp)
    # External lib integration pattern as per README
    add_subdirectory(../../../ fusion_hawking_core)
endif()

# Generate C++ bindings for integrated_apps at configure time
fusion_generate_bindings_static(
    integrated_apps
    examples.integrated_apps.idl
    ${CMAKE_SOURCE_DIR}/build/generated/integrated_apps
)

# Only add the executable if it hasn't been added by the root project
if(NOT TARGET cpp_app)
    add_executable(cpp_app main.cpp)
    target_link_libraries(cpp_app PRIVATE fusion_hawking_cpp)
    # Include per-project generated headers
    target_include_directories(cpp_app PRIVATE
        ${CMAKE_SOURCE_DIR}/build/generated/integrated_apps/cpp
    )
endif()

if(WIN32)
    target_compile_definitions(cpp_app PRIVATE _WINSOCK_DEPRECATED_NO_WARNINGS)
endif()
