// Voice-over playback is macOS-only for now; this keeps the Linux build linking. A player
// built without it falls back to rcplayer's afplay path.
#include "AudioPlayer.h"

namespace refract {

struct AudioPlayer::Impl {};

AudioPlayer::AudioPlayer() : mImpl(std::make_unique<Impl>()) {}
AudioPlayer::~AudioPlayer() = default;

std::unique_ptr<AudioPlayer> AudioPlayer::Create() { return nullptr; }

void AudioPlayer::preload(const std::string&) {}
bool AudioPlayer::play(const std::string&, bool, double) { return false; }
double AudioPlayer::currentTime() const { return 0.0; }
double AudioPlayer::remaining() const { return 0.0; }
void AudioPlayer::stop() {}
void AudioPlayer::setPaused(bool) {}
bool AudioPlayer::isPlaying() const { return false; }

}  // namespace refract
