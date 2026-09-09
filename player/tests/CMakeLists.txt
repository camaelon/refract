# The player's logic tests: the deck's ordering, the editor's text model, and the geometry
# behind clicking and scrolling. None of them opens a window, touches a GPU or links the
# RemoteCompose engine — they are plain objects with plain assertions.
#
# Configurable on its own, which is the point: configuring the player pulls in the engine and
# fetches Skia, and none of that is needed to check that a click lands on the line it is over.
#
#   cmake -B build -S player/tests && cmake --build build && ctest --test-dir build
cmake_minimum_required(VERSION 3.20)

if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(RefractPlayerTests LANGUAGES CXX)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
    enable_testing()
endif()

set(PLAYER_SRC ${CMAKE_CURRENT_SOURCE_DIR}/../src)

foreach(suite deck_order:DeckOrder text_buffer:TextBuffer view_geometry:ViewGeometry
              options:Options completion:Completion utf8:Utf8 scrolling:Scrolling
              plan:Plan
              slide_recorder:SlideRecorder deck_library:DeckLibrary)
    string(REPLACE ":" ";" parts ${suite})
    list(GET parts 0 name)
    list(GET parts 1 unit)
    add_executable(${name}_test ${CMAKE_CURRENT_SOURCE_DIR}/${name}_test.cpp
                                ${PLAYER_SRC}/${unit}.cpp)
    target_include_directories(${name}_test PRIVATE ${PLAYER_SRC})
    add_test(NAME ${name} COMMAND ${name}_test)
endforeach()
