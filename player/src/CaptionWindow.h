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

#include <functional>
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
    void render(const App& app, Captions& captions, double playbackTime, bool playing);

    // ── Correcting the transcript ────────────────────────────────────
    // A transcriber mishears words, and the place you notice is here, watching them go by.
    // So they can be fixed here: click Edit, click a word, type the right one.

    bool isEditing() const;

    // Leave edit mode, keeping the word in progress. Used on the way out, so quitting
    // mid-correction is not the one way to lose one.
    void finishEditing();

    // Called when edit mode is entered or left. The narration should stop while the words
    // are being changed — the highlight would be moving under the cursor — and start again
    // from the beginning of the slide afterwards, so the correction can be heard in place.
    void setOnEditingChanged(std::function<void(bool editing)> action);

    // Keyboard while editing. Returns true when the key was consumed, in which case the
    // player's own bindings must not also see it: typing "b" into a word should not blank
    // the projector.
    bool handleKey(int key, int action, int mods);
    void handleChar(unsigned int codepoint);

private:
    CaptionWindow() = default;

    struct Impl;
    std::unique_ptr<Impl> mImpl;
    GLFWwindow* mWindow = nullptr;
};

}  // namespace refract
