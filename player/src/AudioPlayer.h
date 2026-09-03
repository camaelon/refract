// Voice-over playback with the next slide's audio prepared in advance.
//
// The player's own voice-over path forks `afplay` per slide, and process spawn plus audio
// device setup is long enough to hear as a gap at every slide change — which is precisely
// where a recorded narration is continuous and must not be broken. Holding the file open and
// prepared means starting it costs nothing at the moment it matters.
#pragma once

#include <memory>
#include <string>

namespace refract {

class AudioPlayer {
public:
    // Null when playback is unavailable on this platform.
    static std::unique_ptr<AudioPlayer> Create();
    ~AudioPlayer();

    AudioPlayer(const AudioPlayer&) = delete;
    AudioPlayer& operator=(const AudioPlayer&) = delete;

    // Open and prepare `path` so a later play() of it starts immediately. Does nothing if
    // that path is already prepared, or if the file does not exist.
    void preload(const std::string& path);

    // Start `path`, using the prepared player when it is the one that was preloaded.
    // False when the file is missing or cannot be opened.
    //
    // `letPreviousFinish` starts the new audio *over* the outgoing one instead of cutting
    // it. Used when handing over between consecutive slides of a recorded narration: the
    // handover happens a moment before the outgoing file ends, and letting its last few
    // milliseconds play out underneath leaves no silence at the join at all. A slide change
    // the presenter asked for wants the opposite — the narration should stop at once.
    // `startAt` begins playback that many seconds in, for picking up near a correction
    // rather than at the top of the file.
    bool play(const std::string& path, bool letPreviousFinish = false, double startAt = 0.0);

    // How far into the current file playback has reached, or 0 when nothing is playing.
    // This is what drives caption highlighting, so it has to be the audio clock rather than
    // anything counted on the main thread.
    double currentTime() const;

    // Seconds left of what is playing, or 0 when nothing is.
    double remaining() const;

    void stop();
    void setPaused(bool paused);

    // True while audio is actually playing — the signal --auto-voice advances on.
    bool isPlaying() const;

private:
    AudioPlayer();
    struct Impl;
    std::unique_ptr<Impl> mImpl;
};

}  // namespace refract
