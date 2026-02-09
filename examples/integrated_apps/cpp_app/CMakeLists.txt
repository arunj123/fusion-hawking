cmake_minimum_required(VERSION 3.10)
project(CppAppDemo)

set(CMAKE_CXX_STANDARD 23)

if(NOT TARGET fusion_hawking_cpp)
    # External lib integration pattern as per README
    add_subdirectory(../../../ fusion_hawking_core)
endif()

# Only add the executable if it hasn't been added by the root project
if(NOT TARGET cpp_app)
    add_executable(cpp_app main.cpp)
    target_link_libraries(cpp_app PRIVATE fusion_hawking_cpp)
endif()

if(WIN32)
    target_compile_definitions(cpp_app PRIVATE _WINSOCK_DEPRECATED_NO_WARNINGS)
endif()
