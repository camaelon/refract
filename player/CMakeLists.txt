# refractplayer — a presenter's player for refract decks.
#
# Playback comes from `rcplayer`, the library in the RemoteCompose players/cpp tree
# ("rcX"); this project builds only the presenter's shell around it. That tree is NOT
# vendored — point RCX_DIR at your checkout and updates to the engine arrive by pulling it.
#
#   cmake -B build -DRCX_DIR=../../remotecompose-experiments/players/cpp
#   cmake --build build -j
#
# ./build.sh does the same with the sibling checkout auto-detected.
cmake_minimum_required(VERSION 3.20)
project(RefractPlayer VERSION 0.1.0 LANGUAGES C CXX)

if(APPLE)
    enable_language(OBJCXX)   # the audio recorder is AVFoundation
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

# ── The rcX tree ──────────────────────────────────────────────────────
set(RCX_DIR "" CACHE PATH "Path to the RemoteCompose players/cpp tree (provides rcplayer)")

if(NOT RCX_DIR)
    if(DEFINED ENV{RCX_DIR})
        set(RCX_DIR "$ENV{RCX_DIR}")
    else()
        # The usual layout: refract and remotecompose-experiments checked out side by side.
        foreach(candidate
                "${CMAKE_CURRENT_SOURCE_DIR}/../../remotecompose-experiments/players/cpp"
                "${CMAKE_CURRENT_SOURCE_DIR}/../../rcX"
                "${CMAKE_CURRENT_SOURCE_DIR}/../rcX")
            if(EXISTS "${candidate}/lib/rcplayer/CMakeLists.txt")
                set(RCX_DIR "${candidate}")
                break()
            endif()
        endforeach()
    endif()
endif()

if(NOT RCX_DIR OR NOT EXISTS "${RCX_DIR}/lib/rcplayer/CMakeLists.txt")
    message(FATAL_ERROR
        "rcplayer not found.\n"
        "Clone https://github.com/camaelon/remotecompose-experiments next to this repo, or "
        "configure with -DRCX_DIR=/path/to/players/cpp (or set RCX_DIR in the environment).\n"
        "Tried: ${RCX_DIR}")
endif()
get_filename_component(RCX_DIR "${RCX_DIR}" ABSOLUTE)
message(STATUS "rcX tree: ${RCX_DIR}")

# We want the libraries, not upstream's own viewer and tools.
set(RCX_BUILD_APPS  OFF CACHE BOOL "" FORCE)
set(RCX_BUILD_TOOLS OFF CACHE BOOL "" FORCE)
set(RCX_BUILD_TESTS OFF CACHE BOOL "" FORCE)
add_subdirectory("${RCX_DIR}" "${CMAKE_BINARY_DIR}/rcx")

# ── nlohmann/json — reads the deck manifest ───────────────────────────
include(FetchContent)
set(JSON_BuildTests OFF CACHE INTERNAL "")
FetchContent_Declare(nlohmann_json
    URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz
    URL_HASH SHA256=d6c65aca6b1ed68e7a182f4757257b107ae403032760ed6ef121c9d55e81757d
    DOWNLOAD_EXTRACT_TIMESTAMP TRUE
)
FetchContent_MakeAvailable(nlohmann_json)

# ── The player ────────────────────────────────────────────────────────
set(REFRACTPLAYER_SOURCES
    src/App.cpp
    src/BuildPanel.cpp
    src/CaptionWindow.cpp
    src/Captions.cpp
    src/Deck.cpp
    src/DeckOrder.cpp
    src/DeckView.cpp
    src/Navigator.cpp
    src/Presenter.cpp
    src/Thumbs.cpp
    src/Timing.cpp
    src/Ui.cpp
    src/main.cpp
)

if(APPLE)
    list(APPEND REFRACTPLAYER_SOURCES src/AudioPlayer.mm src/AudioRecorder.mm)
else()
    list(APPEND REFRACTPLAYER_SOURCES src/AudioPlayerStub.cpp src/AudioRecorderStub.cpp)
endif()

add_executable(refractplayer ${REFRACTPLAYER_SOURCES})

if(APPLE)
    set_source_files_properties(src/AudioPlayer.mm src/AudioRecorder.mm
                                PROPERTIES COMPILE_FLAGS "-fobjc-arc")
endif()

target_link_libraries(refractplayer PRIVATE rcplayer nlohmann_json::nlohmann_json)
target_include_directories(refractplayer PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)

# ── Tests ─────────────────────────────────────────────────────────────
# The reorder arithmetic only. It has no window, no GPU and no engine behind it, so it
# builds and runs in a second — which is the point of having pulled it out of the view.
enable_testing()
add_executable(deck_order_test tests/deck_order_test.cpp src/DeckOrder.cpp)
target_include_directories(deck_order_test PRIVATE ${CMAKE_CURRENT_SOURCE_DIR}/src)
add_test(NAME deck_order COMMAND deck_order_test)
