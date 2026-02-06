cmake_minimum_required(VERSION 3.10)
project(CppAppDemo)

set(CMAKE_CXX_STANDARD 17)

# External lib integration pattern as per README
add_subdirectory(../../../ fusion_hawking_core)

add_executable(cpp_app main.cpp)
target_link_libraries(cpp_app PRIVATE fusion_hawking_cpp)

if(WIN32)
    target_compile_definitions(cpp_app PRIVATE _WINSOCK_DEPRECATED_NO_WARNINGS)
endif()
