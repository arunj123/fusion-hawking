cmake_minimum_required(VERSION 3.10)
project(RadarDemo)

set(CMAKE_CXX_STANDARD 23)

# Include the FusionCodegen helper
include(${CMAKE_CURRENT_SOURCE_DIR}/../../../cmake/FusionCodegen.cmake)

if(NOT TARGET fusion_hawking_cpp)
    add_subdirectory(../../../ fusion_hawking_core)
endif()

# Generate C++ bindings for automotive_pubsub at configure time
fusion_generate_bindings_static(
    automotive_pubsub
    examples.automotive_pubsub.idl
    ${CMAKE_SOURCE_DIR}/build/generated/automotive_pubsub
)

# Only add the executable if it hasn't been added by the root project
if(NOT TARGET radar_demo)
    add_executable(radar_demo main.cpp)
    target_link_libraries(radar_demo PRIVATE fusion_hawking_cpp)
    # Include per-project generated headers
    target_include_directories(radar_demo PRIVATE
        ${CMAKE_SOURCE_DIR}/build/generated/automotive_pubsub/cpp
    )
endif()

if(WIN32)
    target_compile_definitions(radar_demo PRIVATE _WINSOCK_DEPRECATED_NO_WARNINGS)
endif()
