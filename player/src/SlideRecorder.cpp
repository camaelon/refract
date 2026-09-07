#include "SlideRecorder.h"

#include <iostream>

namespace fs = std::filesystem;

namespace refract {

void SlideRecorder::configure(std::function<fs::path(int)> wavFor,
                              std::function<void(const std::string&)> capture,
                              std::function<void()> stopCapture,
                              std::function<void(int, const std::string&)> onKept) {
    mWavFor = std::move(wavFor);
    mCapture = std::move(capture);
    mStopCapture = std::move(stopCapture);
    mOnKept = std::move(onKept);
}

bool SlideRecorder::toggle(int slide, std::string* why) {
    if (mRunning) {
        stop(/*keep=*/true);
        return true;
    }
    if (!mWavFor || !mCapture) {
        *why = "there is no microphone to record with";
        return false;
    }
    const fs::path wav = mWavFor(slide);
    if (wav.empty()) {
        *why = "this deck has nowhere to keep narration";
        return false;
    }

    std::error_code ec;
    fs::create_directories(wav.parent_path(), ec);
    mTarget = wav;
    mTemp = wav;
    mTemp.replace_extension(".take.wav");
    mSlide = slide;
    mRunning = true;
    mCapture(mTemp.string());
    return true;
}

void SlideRecorder::stop(bool keep) {
    if (!mRunning) return;
    mRunning = false;
    if (mStopCapture) mStopCapture();

    std::error_code ec;
    // Kept only if there is something to keep. A take that recorded nothing — the microphone
    // never opened, the permission was refused — must not replace one that has something in
    // it, which is exactly the case where somebody would not notice until the talk.
    const bool something = fs::exists(mTemp, ec) && fs::file_size(mTemp, ec) > 0;
    if (keep && something) {
        fs::rename(mTemp, mTarget, ec);
        if (ec) {
            fs::copy_file(mTemp, mTarget, fs::copy_options::overwrite_existing, ec);
            fs::remove(mTemp, ec);
        }
        // The transcript and the word timings were made from the take that has just been
        // replaced; leaving them would light the wrong words under the new one.
        for (const char* ext : {".txt", ".words.json"}) {
            fs::path stale = mTarget;
            stale.replace_extension();
            stale += ext;
            if (fs::exists(stale, ec)) {
                fs::remove(stale, ec);
                std::cerr << "audio: removed " << stale.filename().string()
                          << " — re-run --transcribe for this slide\n";
            }
        }
        if (mOnKept) mOnKept(mSlide, mTarget.stem().string());
        std::cerr << "audio: re-recorded " << mTarget.filename().string() << "\n";
    } else {
        fs::remove(mTemp, ec);
        std::cerr << "audio: re-record " << (keep ? "captured nothing" : "cancelled")
                  << "; the old take is untouched\n";
    }
    mSlide = -1;
}

}  // namespace refract
