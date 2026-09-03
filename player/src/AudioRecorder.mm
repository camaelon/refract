#import <AVFoundation/AVFoundation.h>

#include "AudioRecorder.h"

#include <atomic>
#include <cmath>
#include <filesystem>
#include <iostream>
#include <mutex>

namespace fs = std::filesystem;

namespace refract {

// Capture runs continuously through an AVAudioEngine tap; only the destination file is
// swapped when the deck moves on. The obvious implementation — an AVAudioRecorder stopped
// and restarted per slide — tears the input device down and back up at every boundary, and
// drops the audio either side of it. Recording a talk that way leaves a click and a hole at
// every slide change, which no amount of care at playback can put back.
struct AudioRecorder::Impl {
    AVAudioEngine* engine = nil;
    AVAudioFormat* tapFormat = nil;

    // The tap runs on an audio thread; everything it touches is guarded.
    std::mutex fileMutex;
    AVAudioFile* file = nil;          // guarded by fileMutex
    bool paused = false;              // guarded by fileMutex

    std::atomic<float> average{-1.0f};
    std::atomic<float> peak{-1.0f};

    std::string path;
    bool warnedDenied = false;
};

namespace {

// Level in dBFS mapped onto 0..1 over the bottom 60 dB: that keeps speech in the upper half
// of a meter, where a linear amplitude mapping would leave it a sliver at the bottom.
float normaliseDb(float db) {
    constexpr float kFloorDb = -60.0f;
    if (db <= kFloorDb) return 0.0f;
    if (db >= 0.0f) return 1.0f;
    return (db - kFloorDb) / -kFloorDb;
}

float amplitudeToNormalisedDb(float amplitude) {
    if (amplitude <= 1e-7f) return 0.0f;
    return normaliseDb(20.0f * std::log10(amplitude));
}

}  // namespace

AudioRecorder::AudioRecorder() : mImpl(std::make_unique<Impl>()) {}

AudioRecorder::~AudioRecorder() {
    stop();
    if (mImpl->engine) {
        [mImpl->engine.inputNode removeTapOnBus:0];
        [mImpl->engine stop];
        mImpl->engine = nil;
    }
}

std::unique_ptr<AudioRecorder> AudioRecorder::Create() {
    auto status = [AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio];
    if (status == AVAuthorizationStatusDenied || status == AVAuthorizationStatusRestricted) {
        std::cerr << "audio: microphone access is denied — grant it in System Settings > "
                     "Privacy & Security > Microphone (for the app running this)\n";
        return nullptr;
    }
    if (status == AVAuthorizationStatusNotDetermined) {
        // Asking blocks on the user, and blocking startup on a dialog is worse than a late
        // start: the request runs in the background and the engine comes up once granted.
        std::cerr << "audio: requesting microphone access — recording starts once granted\n";
        [AVCaptureDevice requestAccessForMediaType:AVMediaTypeAudio
                                 completionHandler:^(BOOL granted) {
            if (!granted) std::cerr << "audio: microphone access refused\n";
        }];
    }
    return std::unique_ptr<AudioRecorder>(new AudioRecorder());
}

// Bring the engine up on first use, once permission exists. Idempotent.
bool AudioRecorder::ensureEngine() {
    if (mImpl->engine) return true;
    if ([AVCaptureDevice authorizationStatusForMediaType:AVMediaTypeAudio]
            != AVAuthorizationStatusAuthorized) {
        if (!mImpl->warnedDenied) {
            std::cerr << "audio: no microphone permission yet — not recording\n";
            mImpl->warnedDenied = true;
        }
        return false;
    }

    AVAudioEngine* engine = [[AVAudioEngine alloc] init];
    AVAudioInputNode* input = engine.inputNode;
    AVAudioFormat* format = [input outputFormatForBus:0];
    if (format.sampleRate <= 0 || format.channelCount == 0) {
        std::cerr << "audio: no usable input device\n";
        return false;
    }

    Impl* impl = mImpl.get();
    [input installTapOnBus:0
                bufferSize:1024
                    format:format
                     block:^(AVAudioPCMBuffer* buffer, AVAudioTime*) {
        // Levels first: they should keep moving even while paused, so the meter shows the
        // microphone is alive before the talk starts.
        const AVAudioFrameCount frames = buffer.frameLength;
        float const* const* channels = buffer.floatChannelData;
        if (channels && frames > 0) {
            double sum = 0.0;
            float peak = 0.0f;
            for (AVAudioFrameCount i = 0; i < frames; i++) {
                const float v = std::fabs(channels[0][i]);
                sum += static_cast<double>(v) * v;
                if (v > peak) peak = v;
            }
            impl->average.store(amplitudeToNormalisedDb(
                                    std::sqrt(static_cast<float>(sum / frames))),
                                std::memory_order_relaxed);
            impl->peak.store(amplitudeToNormalisedDb(peak), std::memory_order_relaxed);
        }

        std::lock_guard<std::mutex> lock(impl->fileMutex);
        if (!impl->file || impl->paused) return;
        NSError* error = nil;
        if (![impl->file writeFromBuffer:buffer error:&error]) {
            // The audio thread is no place to be chatty; one line and carry on.
            static bool complained = false;
            if (!complained) {
                complained = true;
                std::cerr << "audio: write failed — "
                          << (error ? error.localizedDescription.UTF8String : "unknown") << "\n";
            }
        }
    }];

    NSError* error = nil;
    if (![engine startAndReturnError:&error]) {
        std::cerr << "audio: engine failed to start — "
                  << (error ? error.localizedDescription.UTF8String : "unknown error") << "\n";
        [input removeTapOnBus:0];
        return false;
    }

    mImpl->engine = engine;
    mImpl->tapFormat = format;
    return true;
}

bool AudioRecorder::start(const std::string& path) {
    if (!ensureEngine()) return false;

    std::error_code ec;
    fs::create_directories(fs::path(path).parent_path(), ec);

    // 16-bit PCM at the input's own sample rate, so a .wav path gives a plain WAV — what
    // the playback side wants, uncompressed and seekable. AVAudioFile converts from the
    // tap's float buffers as it writes.
    NSDictionary* settings = @{
        AVFormatIDKey:             @(kAudioFormatLinearPCM),
        AVSampleRateKey:           @(mImpl->tapFormat.sampleRate),
        AVNumberOfChannelsKey:     @(mImpl->tapFormat.channelCount),
        AVLinearPCMBitDepthKey:    @16,
        AVLinearPCMIsFloatKey:     @NO,
        AVLinearPCMIsBigEndianKey: @NO,
    };

    NSError* error = nil;
    NSURL* url = [NSURL fileURLWithPath:@(path.c_str())];
    AVAudioFile* file = [[AVAudioFile alloc] initForWriting:url
                                                   settings:settings
                                               commonFormat:AVAudioPCMFormatFloat32
                                                interleaved:NO
                                                      error:&error];
    if (!file) {
        std::cerr << "audio: cannot record to " << path << " — "
                  << (error ? error.localizedDescription.UTF8String : "unknown error") << "\n";
        return false;
    }

    // The swap is the whole point: the tap never stops, so no samples are dropped — a
    // buffer that straddles the change lands wholly in one file or the other, and the two
    // wavs still join back up. A small tap buffer keeps that boundary tight (~20 ms).
    {
        std::lock_guard<std::mutex> lock(mImpl->fileMutex);
        mImpl->file = file;
        mImpl->paused = false;
    }
    mImpl->path = path;
    return true;
}

void AudioRecorder::stop() {
    std::lock_guard<std::mutex> lock(mImpl->fileMutex);
    mImpl->file = nil;          // closes and finalises the wav
    mImpl->path.clear();
}

void AudioRecorder::setPaused(bool paused) {
    std::lock_guard<std::mutex> lock(mImpl->fileMutex);
    mImpl->paused = paused;
}

bool AudioRecorder::isRecording() const {
    std::lock_guard<std::mutex> lock(mImpl->fileMutex);
    return mImpl->file != nil && !mImpl->paused;
}

void AudioRecorder::updateLevels() {
    // The tap keeps these current; nothing to do but let the caller read them.
}

float AudioRecorder::averageLevel() const {
    return mImpl->average.load(std::memory_order_relaxed);
}

float AudioRecorder::peakLevel() const {
    return mImpl->peak.load(std::memory_order_relaxed);
}

const std::string& AudioRecorder::currentPath() const { return mImpl->path; }

}  // namespace refract
