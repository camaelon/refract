// Audio capture is macOS-only for now; this keeps the Linux build linking.
#include "AudioRecorder.h"

#include <iostream>

namespace refract {

struct AudioRecorder::Impl {
    std::string path;
};

AudioRecorder::AudioRecorder() : mImpl(std::make_unique<Impl>()) {}
AudioRecorder::~AudioRecorder() = default;

std::unique_ptr<AudioRecorder> AudioRecorder::Create() {
    std::cerr << "audio: recording is not implemented on this platform\n";
    return nullptr;
}

bool AudioRecorder::ensureEngine() { return false; }
bool AudioRecorder::start(const std::string&) { return false; }
void AudioRecorder::stop() {}
bool AudioRecorder::isRecording() const { return false; }
void AudioRecorder::setPaused(bool) {}
void AudioRecorder::updateLevels() {}
float AudioRecorder::averageLevel() const { return -1.0f; }
float AudioRecorder::peakLevel() const { return -1.0f; }
const std::string& AudioRecorder::currentPath() const { return mImpl->path; }

}  // namespace refract
