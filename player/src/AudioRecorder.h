// Microphone capture to a .wav file — one file at a time, swapped as the deck advances.
//
// Used to record a talk's narration slide by slide, so the wavs land exactly where
// voice-over playback looks for them (see rcplayer::voicePathFor) and the deck can then play itself
// back. macOS only; the Linux build gets a stub that reports itself unavailable.
//
// Microphone access is a system permission. A command-line tool has no bundle of its own,
// so the prompt is attributed to whatever launched it (usually the terminal) and the answer
// is remembered against that. The first run may therefore miss the opening slide while the
// prompt is up — isRecording() tells you whether anything is actually being captured.
#pragma once

#include <memory>
#include <string>

namespace refract {

class AudioRecorder {
public:
    // Null when audio capture is unavailable — no device, no permission, or not this
    // platform. Reports the reason on stderr.
    static std::unique_ptr<AudioRecorder> Create();
    ~AudioRecorder();

    AudioRecorder(const AudioRecorder&) = delete;
    AudioRecorder& operator=(const AudioRecorder&) = delete;

    // Start capturing to `path`, finalising whatever was being recorded first. Parent
    // directories are created. Returns false if capture could not start.
    bool start(const std::string& path);

    // Finalise the current file. Safe to call when not recording.
    void stop();

    // Suspend or resume capture without closing the file — the take picks up where it left
    // off. Pausing the talk should pause the microphone, or the break gets recorded into the
    // slide that was up when it started.
    void setPaused(bool paused);

    bool isRecording() const;

    // Sample the input level. Call once per frame while recording; the levels below only
    // change when this is called.
    void updateLevels();

    // Input level over the last sample, 0 (silence) to 1 (clipping), or -1 when not
    // recording. `average` is what a level meter shows; `peak` catches the transients that
    // clip. Both are mapped from the decibel scale the hardware reports onto a range that
    // makes speech legible rather than a sliver at the bottom.
    float averageLevel() const;
    float peakLevel() const;

    // The file currently being written, or "" when not recording.
    const std::string& currentPath() const;

private:
    AudioRecorder();
    // Bring the capture engine up on first use, once permission exists. Idempotent.
    bool ensureEngine();

    struct Impl;
    std::unique_ptr<Impl> mImpl;
};

}  // namespace refract
