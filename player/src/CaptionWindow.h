// A close-caption window: the narration for the current slide, with each word lit as it is
// spoken.
//
// Driven by the audio clock rather than by anything counted on the main thread, so the
// highlight stays on the word actually coming out of the speakers. With no audio playing it
// still shows the slide's transcript, unlit — which makes it a serviceable teleprompter for
// a talk whose narration has been written down but is being delivered live.
#pragma once

#include "App.h"
#include "Captions.h"

#include <memory>

struct GLFWwindow;

namespace refract {

class CaptionWindow {
public:
    // Opens the window. Null when GLFW could not create it. The caller installs the key
    // callback so every window shares one set of bindings.
    static std::unique_ptr<CaptionWindow> Create(int width, int height);
    ~CaptionWindow();

    GLFWwindow* window() const { return mWindow; }
    bool shouldClose() const;

    // `playbackTime` is where the narration has reached; `playing` says whether it is
    // actually running, which is the difference between lighting words and just showing them.
    void render(const App& app, const Captions& captions, double playbackTime, bool playing);

private:
    CaptionWindow() = default;

    struct Impl;
    std::unique_ptr<Impl> mImpl;
    GLFWwindow* mWindow = nullptr;
};

}  // namespace refract
