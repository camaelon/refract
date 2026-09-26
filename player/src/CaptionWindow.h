// A close-caption window: the narration for the current slide, with each word lit as it is
// spoken.
//
// A window around a CaptionView — the same widget the presenter shows on its Captions tab.
// This owns the GLFW window and forwards it the mouse; the caller installs the key callback
// so every window shares one set of bindings, and hands keys here first.
#pragma once

#include "App.h"
#include "Captions.h"
#include "CaptionView.h"

#include "rcplayer/CpuRenderBackend.h"

#include <functional>
#include <memory>

struct GLFWwindow;

namespace refract {

class CaptionWindow {
public:
    // Opens the window. Null when GLFW could not create it.
    static std::unique_ptr<CaptionWindow> Create(int width, int height);
    ~CaptionWindow();

    GLFWwindow* window() const { return mWindow; }
    bool shouldClose() const;

    // `playbackTime` is where the narration has reached; `playing` says whether it is
    // actually running, which is the difference between lighting words and just showing them.
    void render(const App& app, Captions& captions, double playbackTime, bool playing);

    // The widget, for keys, edit state and the editing-changed hook. See CaptionView.
    CaptionView& view() { return mImpl->view; }
    bool isEditing() const;
    void finishEditing();
    void setOnEditingChanged(std::function<void(bool editing)> action);
    bool handleKey(int key, int action, int mods);
    void handleChar(unsigned int codepoint);

private:
    CaptionWindow() = default;

    struct Impl {
        CpuRenderBackend backend;
        int width = 0, height = 0;
        int fbWidth = 0, fbHeight = 0;
        double mouseX = 0, mouseY = 0;
        CaptionView view;
    };
    std::unique_ptr<Impl> mImpl;
    GLFWwindow* mWindow = nullptr;
};

}  // namespace refract
