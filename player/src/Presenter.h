// The presenter window: a second window, for the laptop screen, while the deck plays
// fullscreen on the projector.
//
// It shows the wall clock, the talk timer, the slide you are on and the one coming, and
// the speaker notes. It renders on the CPU — it is text and two stills, it never needs the
// GPU, and keeping it off the GPU keeps it out of the way of the slide's shaders.
#pragma once

#include "App.h"
#include "CaptionView.h"
#include "Captions.h"

#include "include/core/SkImage.h"
#include "include/core/SkRefCnt.h"

#include <functional>
#include <memory>
#include <string>
#include <vector>

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

    // What the play/pause button does. Set once, after Create.
    void setOnToggleClock(std::function<void()> action);

    // The record button: start a take over this slide's narration, then keep it. `discard`
    // drops the take in progress and leaves the old one alone. Both are the app's, which
    // owns the microphone and the file.
    void setOnRecordSlide(std::function<void()> record, std::function<void()> discard);

    // The "stop recording" button shown while a whole run is being recorded (--record-audio):
    // closes the slide's wav and the timing trace, so the run ends where you say and not at
    // the next slide or on quit.
    void setOnStopRun(std::function<void()> stop);

    // The "delete recording" button, shown when the slide has a wav: the recording and the
    // transcript made from it go together. The window asks first — the row turns into a
    // question with keep and delete — and only then calls this with the slide it asked
    // about. `setDeleteGoesToTrash` says how the question is worded: to the Trash, or gone.
    void setOnDeleteRecording(std::function<void(int slide)> remove);
    void setDeleteGoesToTrash(bool trash);

    // The "autoplay narration" checkbox, when the deck has any narration to play. The
    // window only draws the state (app.autoplayVoice) and reports the click.
    void setOnToggleAutoplay(std::function<void()> toggle);

    // The "transcribe slide N" button, shown when the slide has a recording. `busy` says a
    // transcription is already running, so the button reads as such and does nothing.
    void setOnTranscribeSlide(std::function<void()> transcribe);
    // `status` says where it has got to ("3 of 23 · aligning 07") and `fraction` how far,
    // 0..1, or negative when unknown; both are shown while `busy`.
    void setTranscribing(bool busy, const std::string& status = std::string(), float fraction = -1.0f);

    // The slide's narration, for the strip above the buttons: its name, its envelope (peak
    // per bin, 0..1, left to right), its length, and where playback is. Null envelope: no
    // recording, no strip. The envelope is the caller's and must outlive the frame.
    struct Narration {
        std::string label;
        const std::vector<float>* envelope = nullptr;
        double duration = 0.0;
        double position = -1.0;    // seconds into it, or negative when not playing
    };
    void setNarration(const Narration& narration);

    // ── The notes pane's tabs ────────────────────────────────────────
    // Under the slides, one pane with two tabs: the speaker notes, and the captions — the
    // same widget as the caption window, editing included, so a transcription asked for
    // from here can be read and corrected here. `setCaptions` is called each frame with
    // the slide's captions and where the narration has got to, as the caption window is.
    enum class Tab { Notes, Captions };
    void setCaptions(Captions* captions, double playbackTime, bool playing);
    void showTab(Tab tab);
    Tab tab() const;
    // The widget, for keys and its editing state; the presenter's key callback hands it
    // keys first, as the caption window's does.
    CaptionView& captionView();

    // Feed the current microphone level (0..1) for the recording meter, or -1 when not
    // recording. Sampled by the caller because the recorder is the app's, not the window's.
    void pushAudioLevel(float average, float peak);

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
