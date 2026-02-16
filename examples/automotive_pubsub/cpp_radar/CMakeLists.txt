cmake_minimum_required(VERSION 3.10)
project(RadarDemo)

set(CMAKE_CXX_STANDARD 23)

if(NOT TARGET fusion_hawking_cpp)
    add_subdirectory(../../../ fusion_hawking_core)
endif()

# Only add the executable if it hasn't been added by the root project
if(NOT TARGET radar_demo)
    add_executable(radar_demo main.cpp)
    target_link_libraries(radar_demo PRIVATE fusion_hawking_cpp)
endif()

if(WIN32)
    target_compile_definitions(radar_demo PRIVATE _WINSOCK_DEPRECATED_NO_WARNINGS)
endif()
