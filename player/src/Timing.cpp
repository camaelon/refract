#include "Timing.h"

#include "Deck.h"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <ctime>
#include <fstream>
#include <iostream>

namespace refract {

namespace {

std::string isoNow() {
    std::time_t t = std::time(nullptr);
    std::tm utc{};
    gmtime_r(&t, &utc);
    char buf[32];
    std::strftime(buf, sizeof(buf), "%Y-%m-%dT%H:%M:%SZ", &utc);
    return buf;
}

}  // namespace

bool Timing::loadForDeck(const std::string& source) {
    mEntries.clear();
    mFirstVisit.clear();
    mTotal = 0.0;

    std::string text;
    if (!readDeckSidecar(source, "timing.json", &text) || text.empty()) return false;

    auto doc = nlohmann::json::parse(text, nullptr, /*allow_exceptions=*/false);
    if (doc.is_discarded() || !doc.contains("slides")) {
        std::cerr << "timing.json: unreadable, ignoring\n";
        return false;
    }

    for (const auto& rec : doc["slides"]) {
        if (!rec.contains("file")) continue;
        TimingEntry e;
        e.file     = rec["file"].get<std::string>();
        e.start    = rec.value("start", 0.0);
        e.duration = rec.value("duration", 0.0);
        mFirstVisit.emplace(e.file, mEntries.size());   // emplace keeps the first
        mEntries.push_back(std::move(e));
    }
    mTotal = doc.value("total", mEntries.empty() ? 0.0 : mEntries.back().end());
    if (mEntries.empty()) return false;

    std::cerr << "timing: " << mEntries.size() << " slides, "
              << static_cast<long>(mTotal) << "s\n";
    return true;
}

const TimingEntry* Timing::find(const std::string& file) const {
    auto it = mFirstVisit.find(file);
    return it == mFirstVisit.end() ? nullptr : &mEntries[it->second];
}

std::string Timing::positionAt(double elapsed, double* fractionThroughSlide) const {
    if (fractionThroughSlide) *fractionThroughSlide = 0.0;
    for (const auto& e : mEntries) {
        if (elapsed < e.end() || &e == &mEntries.back()) {
            if (elapsed < e.start) break;
            if (fractionThroughSlide && e.duration > 0.0) {
                *fractionThroughSlide =
                    std::min(1.0, std::max(0.0, (elapsed - e.start) / e.duration));
            }
            return e.file;
        }
    }
    return {};
}

void Timing::beginRecording(const std::string& path) {
    mEntries.clear();
    mFirstVisit.clear();
    mTotal = 0.0;
    mRecording = true;
    mPath = path;
    std::cerr << "recording timings to " << path << "\n";
}

void Timing::mark(const std::string& file, double elapsed) {
    if (!mRecording) return;
    if (!mEntries.empty()) {
        TimingEntry& last = mEntries.back();
        last.duration = std::max(0.0, elapsed - last.start);
    }
    TimingEntry e;
    e.file  = file;
    e.start = elapsed;
    mFirstVisit.emplace(file, mEntries.size());
    mEntries.push_back(std::move(e));
    mTotal = elapsed;
    mLastTickSave = elapsed;
    save();
}

void Timing::tick(double elapsed) {
    if (!mRecording || mEntries.empty()) return;
    mEntries.back().duration = std::max(0.0, elapsed - mEntries.back().start);
    mTotal = elapsed;

    constexpr double kSaveInterval = 5.0;
    if (elapsed - mLastTickSave < kSaveInterval) return;
    mLastTickSave = elapsed;
    save();
}

void Timing::finish(double elapsed) {
    if (!mRecording) return;
    if (!mEntries.empty()) {
        TimingEntry& last = mEntries.back();
        last.duration = std::max(0.0, elapsed - last.start);
    }
    mTotal = elapsed;
    if (save()) {
        std::cerr << "recorded " << mEntries.size() << " slides over "
                  << static_cast<long>(mTotal) << "s to " << mPath << "\n";
    }
    mRecording = false;
}

bool Timing::save() const {
    if (mPath.empty()) return false;
    // Rounded to hundredths, and ordered as written rather than alphabetically: this file is
    // meant to be read and diffed between rehearsals, and full double precision ordered by
    // key name serves neither.
    auto round2 = [](double v) { return std::round(v * 100.0) / 100.0; };
    nlohmann::ordered_json doc;
    doc["version"]  = 1;
    doc["deck"]     = mDeck;
    doc["recorded"] = isoNow();
    doc["total"]    = round2(mTotal);
    for (const auto& e : mEntries) {
        doc["slides"].push_back(nlohmann::ordered_json{{"file", e.file},
                                                       {"start", round2(e.start)},
                                                       {"duration", round2(e.duration)}});
    }
    std::ofstream out(mPath, std::ios::binary | std::ios::trunc);
    if (!out) {
        std::cerr << "timing: cannot write " << mPath << "\n";
        return false;
    }
    out << doc.dump(2) << "\n";
    return true;
}

bool paceDelta(const Timing& timing, const std::string& file, double elapsed,
               double timeOnSlide, double* delta) {
    const TimingEntry* e = timing.find(file);
    if (!e) return false;
    // Credit the rehearsal's own time on this slide, but no more than it actually spent:
    // matching its pace holds the delta steady, and overrunning grows it.
    const double expected = e->start + std::min(timeOnSlide, e->duration);
    *delta = elapsed - expected;
    return true;
}

}  // namespace refract
