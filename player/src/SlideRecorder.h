// Recording over one slide's narration.
//
// A rehearsal is recorded in one pass, and a slide that came out badly used to cost the whole
// take. This does the one slide — and the reason it can is that the narration is identified by
// the markdown block a slide was written in rather than by the slide's number, so recording
// over one wav means something definite even after the deck has been rearranged.
//
// The take goes to a temporary file and only replaces the old one when it is kept. Starting a
// re-record and thinking better of it costs nothing, which is the point: this is the only
// thing in the player that writes over a recording.
//
// The microphone and the file naming are the caller's — passed in — so what is left here is
// the part worth being sure about: when the old take is replaced, and when it is not.
#pragma once

#include <filesystem>
#include <functional>
#include <string>

namespace refract {

class SlideRecorder {
public:
    // `wavFor` says where a slide's narration lives — empty when it has nowhere to live.
    // `capture` opens the microphone onto a path; `stopCapture` closes it.
    // `onKept` is told which slide got a new take, and under which stem, once one lands.
    void configure(std::function<std::filesystem::path(int)> wavFor,
                   std::function<void(const std::string&)> capture,
                   std::function<void()> stopCapture,
                   std::function<void(int, const std::string&)> onKept);

    bool running() const { return mRunning; }
    int  slide() const { return mSlide; }

    // Start a take over `slide`, or — when one is already running — keep it. False when it
    // could not be started, with `why` saying so.
    bool toggle(int slide, std::string* why);

    // Finish. `keep` replaces the old take with the new one; otherwise the new one is thrown
    // away and the old is untouched. Does nothing when nothing is running.
    void stop(bool keep);

private:
    std::function<std::filesystem::path(int)> mWavFor;
    std::function<void(const std::string&)> mCapture;
    std::function<void()> mStopCapture;
    std::function<void(int, const std::string&)> mOnKept;

    bool mRunning = false;
    int  mSlide = -1;
    std::filesystem::path mTemp, mTarget;
};

}  // namespace refract
