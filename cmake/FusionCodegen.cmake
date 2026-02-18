# CMake function for Fusion Hawking Codegen
# Usage:
#   include(cmake/FusionCodegen.cmake)
#   fusion_generate_bindings(my_target integrated_apps examples.integrated_apps.idl)
#   fusion_generate_bindings_static(integrated_apps examples.integrated_apps.idl /path/to/output)

find_package(Python3 COMPONENTS Interpreter REQUIRED)

# Build-time codegen (via add_custom_command — runs during cmake --build)
function(fusion_generate_bindings TARGET PROJECT_NAME IDL_MODULE)
    set(GEN_DIR "${CMAKE_BINARY_DIR}/generated/${PROJECT_NAME}/cpp")

    # Get all IDL source files for dependency tracking
    execute_process(
        COMMAND ${Python3_EXECUTABLE} -c "
import importlib, os, sys
sys.path.insert(0, '${CMAKE_SOURCE_DIR}/src/python')
sys.path.insert(0, '${CMAKE_SOURCE_DIR}')
mod = importlib.import_module('${IDL_MODULE}')
if hasattr(mod, '__path__'):
    for root, dirs, files in os.walk(mod.__path__[0]):
        for f in files:
            if f.endswith('.py'):
                print(os.path.join(root, f))
else:
    print(mod.__file__)
"
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
        OUTPUT_VARIABLE IDL_FILES
        OUTPUT_STRIP_TRAILING_WHITESPACE
    )
    string(REPLACE "\n" ";" IDL_FILES "${IDL_FILES}")

    # Custom command to generate bindings
    add_custom_command(
        OUTPUT ${GEN_DIR}/bindings.h
        COMMAND ${Python3_EXECUTABLE} -m tools.codegen.main
            --project ${PROJECT_NAME}
            --lang cpp
            --module ${IDL_MODULE}
            --output-dir ${CMAKE_BINARY_DIR}/generated/${PROJECT_NAME}
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
        DEPENDS ${IDL_FILES}
        COMMENT "Generating C++ bindings for ${PROJECT_NAME}"
    )

    # Create a custom target for the generation
    add_custom_target(${PROJECT_NAME}_codegen
        DEPENDS ${GEN_DIR}/bindings.h
    )

    # Add dependency and include path to the target
    add_dependencies(${TARGET} ${PROJECT_NAME}_codegen)
    target_include_directories(${TARGET} PRIVATE ${GEN_DIR})
endfunction()

# Configure-time codegen (via execute_process — runs during cmake configure)
# Simpler and ensures headers exist before compilation.
# Usage: fusion_generate_bindings_static(PROJECT_NAME IDL_MODULE OUTPUT_BASE_DIR)
function(fusion_generate_bindings_static PROJECT_NAME IDL_MODULE OUTPUT_BASE_DIR)
    set(GEN_DIR "${OUTPUT_BASE_DIR}/cpp")

    message(STATUS "[FusionCodegen] Generating C++ bindings for ${PROJECT_NAME} -> ${GEN_DIR}")

    execute_process(
        COMMAND ${Python3_EXECUTABLE} -m tools.codegen.main
            --project ${PROJECT_NAME}
            --lang cpp
            --module ${IDL_MODULE}
            --output-dir ${OUTPUT_BASE_DIR}
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
        RESULT_VARIABLE codegen_result
        OUTPUT_VARIABLE codegen_output
        ERROR_VARIABLE codegen_error
    )

    if(NOT codegen_result EQUAL 0)
        message(WARNING "[FusionCodegen] Codegen for ${PROJECT_NAME} failed (exit ${codegen_result}). "
                        "Build may fail if headers are missing.\n${codegen_error}")
    else()
        message(STATUS "[FusionCodegen] Done: ${PROJECT_NAME}")
    endif()
endfunction()

# Validate a config.json file using the Fusion Hawking config validator
function(fusion_validate_config CONFIG_PATH)
    execute_process(
        COMMAND ${Python3_EXECUTABLE} -m tools.fusion.config_validator ${CONFIG_PATH}
        WORKING_DIRECTORY ${CMAKE_SOURCE_DIR}
        RESULT_VARIABLE rc
    )
    if(NOT rc EQUAL 0)
        message(FATAL_ERROR "Config validation failed for ${CONFIG_PATH}")
    endif()
endfunction()
