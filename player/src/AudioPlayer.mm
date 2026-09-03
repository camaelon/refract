#import <AVFoundation/AVFoundation.h>

#include "AudioPlayer.h"

#include <algorithm>
#include <filesystem>
#include <iostream>

namespace fs = std::filesystem;

namespace refract {

struct AudioPlayer::Impl {
    AVAudioPlayer* current = nil;
    AVAudioPlayer* prepared = nil;      // the next slide's audio, already opened
    AVAudioPlayer* outgoing = nil;      // the one before, running out under the current one
    std::string preparedPath;
};

AudioPlayer::AudioPlayer() : mImpl(std::make_unique<Impl>()) {}

AudioPlayer::~AudioPlayer() {
    stop();
    mImpl->prepared = nil;
}

std::unique_ptr<AudioPlayer> AudioPlayer::Create() {
    return std::unique_ptr<AudioPlayer>(new AudioPlayer());
}

namespace {

AVAudioPlayer* open(const std::string& path) {
    std::error_code ec;
    if (path.empty() || !fs::exists(path, ec)) return nil;
    NSError* error = nil;
    NSURL* url = [NSURL fileURLWithPath:@(path.c_str())];
    AVAudioPlayer* player = [[AVAudioPlayer alloc] initWithContentsOfURL:url error:&error];
    if (!player) {
        std::cerr << "voice: cannot open " << path << " — "
                  << (error ? error.localizedDescription.UTF8String : "unknown error") << "\n";
        return nil;
    }
    // Opens the output device and fills the first buffers. This is the part that costs
    // milliseconds, and doing it now is the whole point of preloading.
    [player prepareToPlay];
    return player;
}

}  // namespace

void AudioPlayer::preload(const std::string& path) {
    if (path.empty() || mImpl->preparedPath == path) return;
    mImpl->prepared = open(path);
    mImpl->preparedPath = mImpl->prepared ? path : std::string();
}

bool AudioPlayer::play(const std::string& path, bool letPreviousFinish,
                       double startAt) {
    AVAudioPlayer* player = nil;
    if (mImpl->prepared && mImpl->preparedPath == path) {
        player = mImpl->prepared;
        mImpl->prepared = nil;
        mImpl->preparedPath.clear();
    } else {
        player = open(path);   // not the slide we expected next — open it now
    }
    if (!player) {
        stop();
        return false;
    }

    // Whatever is playing either stops now or is left to run out under the new audio. The
    // outgoing one is held only until the next handover, by which time it is long done.
    mImpl->outgoing = nil;
    if (mImpl->current) {
        if (letPreviousFinish) mImpl->outgoing = mImpl->current;
        else                   [mImpl->current stop];
    }
    mImpl->current = player;
    mImpl->current.currentTime = std::max(0.0, std::min(startAt, mImpl->current.duration));
    return [mImpl->current play];
}

void AudioPlayer::stop() {
    if (mImpl->outgoing) {
        [mImpl->outgoing stop];
        mImpl->outgoing = nil;
    }
    if (!mImpl->current) return;
    [mImpl->current stop];
    mImpl->current = nil;
}

double AudioPlayer::currentTime() const {
    if (!mImpl->current) return 0.0;
    return mImpl->current.currentTime;
}

double AudioPlayer::remaining() const {
    if (!mImpl->current || ![mImpl->current isPlaying]) return 0.0;
    return std::max(0.0, mImpl->current.duration - mImpl->current.currentTime);
}

void AudioPlayer::setPaused(bool paused) {
    if (!mImpl->current) return;
    if (paused) [mImpl->current pause];
    else        [mImpl->current play];
}

bool AudioPlayer::isPlaying() const {
    return mImpl->current != nil && [mImpl->current isPlaying];
}

}  // namespace refract
