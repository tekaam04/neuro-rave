cmake_minimum_required(VERSION 3.16)
project(neuro_rave_native C CXX)

set(CMAKE_C_STANDARD   11)
set(CMAKE_CXX_STANDARD 20)

# ── liblsl ────────────────────────────────────────────────────────────────────
# Try the CMake package first (works when liblsl was installed via CMake or Homebrew).
# Fall back to find_library for manual installations.

find_package(LSL QUIET
    HINTS
        /opt/homebrew/lib/cmake/LSL
        /usr/local/lib/cmake/LSL
        $ENV{LSL_DIR})

if(TARGET LSL::lsl AND NOT DEFINED ENV{LSL_FORCE_FIND_LIBRARY})
    message(STATUS "Found liblsl via CMake package")
    # Some liblsl versions don't propagate include dirs via the imported target.
    find_path(LSL_INCLUDE_DIR lsl/lsl_c.h
        HINTS /opt/homebrew/include /usr/local/include /usr/include)
    if(LSL_INCLUDE_DIR)
        set_target_properties(LSL::lsl PROPERTIES
            INTERFACE_INCLUDE_DIRECTORIES "${LSL_INCLUDE_DIR}")
    endif()
    set(LSL_TARGET LSL::lsl)
else()
    # macOS Homebrew installs liblsl as LSL.framework
    find_library(LSL_FRAMEWORK NAMES LSL
        HINTS /usr/local/Frameworks /opt/homebrew/Frameworks /Library/Frameworks
              /usr/local/Cellar/lsl/1.17.4/Frameworks)
    if(LSL_FRAMEWORK)
        message(STATUS "Found liblsl framework: ${LSL_FRAMEWORK}")
        add_library(_lsl INTERFACE IMPORTED)
        set_target_properties(_lsl PROPERTIES
            INTERFACE_LINK_LIBRARIES      "${LSL_FRAMEWORK}"
            INTERFACE_INCLUDE_DIRECTORIES "${LSL_FRAMEWORK}/Headers")
        set(LSL_TARGET _lsl)
    else()
        find_library(LSL_LIBRARY NAMES lsl
            HINTS /opt/homebrew/lib /usr/local/lib /usr/lib
            REQUIRED)
        find_path(LSL_INCLUDE_DIR lsl/lsl_c.h
            HINTS /opt/homebrew/include /usr/local/include /usr/include
            REQUIRED)
        message(STATUS "Found liblsl via find_library: ${LSL_LIBRARY}")
        add_library(_lsl UNKNOWN IMPORTED)
        set_target_properties(_lsl PROPERTIES
            IMPORTED_LOCATION             "${LSL_LIBRARY}"
            INTERFACE_INCLUDE_DIRECTORIES "${LSL_INCLUDE_DIR}")
        set(LSL_TARGET _lsl)
    endif()
endif()

# ── libwebsockets ─────────────────────────────────────────────────────────────

find_package(libwebsockets QUIET
    HINTS
        /opt/homebrew/lib/cmake/libwebsockets
        /usr/local/lib/cmake/libwebsockets
        $ENV{LWS_DIR})

if(TARGET websockets)
    message(STATUS "Found libwebsockets via CMake package")
    set(LWS_TARGET websockets)
else()
    find_library(LWS_LIBRARY NAMES websockets
        HINTS /opt/homebrew/lib /usr/local/lib /usr/lib
        REQUIRED)
    find_path(LWS_INCLUDE_DIR libwebsockets.h
        HINTS /opt/homebrew/include /usr/local/include /usr/include
        REQUIRED)
    message(STATUS "Found libwebsockets via find_library: ${LWS_LIBRARY}")
    add_library(_lws UNKNOWN IMPORTED)
    set_target_properties(_lws PROPERTIES
        IMPORTED_LOCATION             "${LWS_LIBRARY}"
        INTERFACE_INCLUDE_DIRECTORIES "${LWS_INCLUDE_DIR}")
    set(LWS_TARGET _lws)
endif()

# ── dsp-lib (submodule) ───────────────────────────────────────────────────────

add_subdirectory(dsp-lib)

# ── Shared config source ──────────────────────────────────────────────────────

set(CONFIG_SRC src/streaming/config.c)

# ── neuro_lsl_bridge ──────────────────────────────────────────────────────────
# Standalone binary: reads BioSemi TCP stream → publishes to LSL outlet

add_executable(neuro_lsl_bridge
    ${CONFIG_SRC}
    src/streaming/lsl_bridge.cpp)

target_include_directories(neuro_lsl_bridge PRIVATE include include/streaming include/processing include/audio)
target_link_libraries(neuro_lsl_bridge PRIVATE ${LSL_TARGET})

# ── neuro_ws_server ───────────────────────────────────────────────────────────
# Standalone binary: reads LSL inlet → broadcasts raw EEG over WebSocket

add_executable(neuro_ws_server
    ${CONFIG_SRC}
    src/streaming/ws_server.cpp)

target_include_directories(neuro_ws_server PRIVATE include include/streaming include/processing include/audio)
target_link_libraries(neuro_ws_server PRIVATE ${LSL_TARGET} ${LWS_TARGET})

# ── neuro_lsl_bridge_c (C version) ────────────────────────────────────────────

add_executable(neuro_lsl_bridge_c
    ${CONFIG_SRC}
    src/streaming/lsl_bridge_c.c)

target_include_directories(neuro_lsl_bridge_c PRIVATE include include/streaming include/processing include/audio)
target_link_libraries(neuro_lsl_bridge_c PRIVATE ${LSL_TARGET})

# ── neuro_ws_server_c (C version) ─────────────────────────────────────────────

add_executable(neuro_ws_server_c
    ${CONFIG_SRC}
    src/streaming/ws_server_c.c)

target_include_directories(neuro_ws_server_c PRIVATE include include/streaming include/processing include/audio)
target_link_libraries(neuro_ws_server_c PRIVATE ${LSL_TARGET} ${LWS_TARGET})

# ── neuro_rave (full pipeline with audio synth) ───────────────────────────────
# Combined binary: simulate or live LSL → FIFO → audio output + WebSocket

add_executable(neuro_rave
    ${CONFIG_SRC}
    main.cpp
    src/streaming/lsl_bridge.cpp
    src/streaming/ws_server.cpp)

target_include_directories(neuro_rave PRIVATE include include/streaming)
target_compile_definitions(neuro_rave PRIVATE NEURO_RAVE_LIB)
target_link_libraries(neuro_rave PRIVATE dsp_lib ${LSL_TARGET} ${LWS_TARGET})

# ── Installation ──────────────────────────────────────────────────────────────

install(TARGETS neuro_lsl_bridge neuro_ws_server neuro_lsl_bridge_c neuro_ws_server_c neuro_rave
    RUNTIME DESTINATION bin)
