// The presenter window: a second window, for the laptop screen, while the deck plays
// fullscreen on the projector.
//
// It shows the wall clock, the talk timer, the slide you are on and the one coming, and
// the speaker notes. It renders on the CPU — it is text and two stills, it never needs the
// GPU, and keeping it off the GPU keeps it out of the way of the slide's shaders.
#pragma once

#include "App.h"

#include "include/core/SkImage.h"
#include "include/core/SkRefCnt.h"

#include <memory>

struct GLFWwindow;

namespace refract {

class PresenterWindow {
public:
    // Opens the window. Null when GLFW could not create it. The caller installs the key
    // callback so both windows share one set of bindings.
    static std::unique_ptr<PresenterWindow> Create(int width, int height);
    ~PresenterWindow();

    GLFWwindow* window() const { return mWindow; }
    bool shouldClose() const;

    // Draw one frame and swap. `live` is the last frame the slide window painted (null
    // until there is one); it is what the "current" pane shows, so the presenter sees the
    // real slide mid-animation rather than a still that disagrees with the projector.
    void render(App& app, const sk_sp<SkImage>& live);

private:
    PresenterWindow() = default;

    struct Impl;
    std::unique_ptr<Impl> mImpl;
    GLFWwindow* mWindow = nullptr;
};

}  // namespace refract
