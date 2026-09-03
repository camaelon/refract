// A rehearsal trace: when each slide came up, measured from the start of the run.
//
// Recorded with --record, and read back on later runs so the presenter window can say
// whether this run is ahead of or behind the one that was timed. Slides are keyed by
// filename, not position, for the same reason deck.json is: a deck gets slides inserted
// and renumbered around a trace, and the entries that still match should still count.
//
// Written to timing.json beside the slides, after every slide change — a rehearsal that
// ends by closing the window should not lose the trace.
#pragma once

#include <map>
#include <string>
#include <vector>

namespace refract {

struct TimingEntry {
    std::string file;      // slide basename
    double start = 0.0;    // seconds from the start of the run
    double duration = 0.0; // seconds spent on it
    double end() const { return start + duration; }
};

class Timing {
public:
    // ── Reading ──────────────────────────────────────────────────────
    // Load the trace beside the deck at `source` (directory, slide file, or zip).
    // False when there is none — which is not an error, just an untimed deck.
    bool loadForDeck(const std::string& source);

    bool empty() const { return mEntries.empty(); }
    double total() const { return mTotal; }
    const std::vector<TimingEntry>& entries() const { return mEntries; }

    // The trace's timing for a slide, or null when it has none. On a revisited slide this
    // is the *first* visit: that is the point in the talk the pace should be measured at.
    const TimingEntry* find(const std::string& file) const;

    // Where the trace says the talk would be at `elapsed` — the slide's file and how far
    // through it, as a fraction. Empty file when `elapsed` is past the end of the trace.
    std::string positionAt(double elapsed, double* fractionThroughSlide) const;

    // ── Recording ────────────────────────────────────────────────────
    void beginRecording(const std::string& path);
    bool recording() const { return mRecording; }
    const std::string& path() const { return mPath; }

    // Note that `file` came up at `elapsed`, closing the entry before it. Writes the file.
    void mark(const std::string& file, double elapsed);

    // Keep the slide currently being timed up to date. Call each frame while recording: a
    // rehearsal that ends by being killed — or by the machine going to sleep — then still
    // leaves a trace that is complete but for a few seconds. Writes at most every few
    // seconds, so this is cheap to call often.
    void tick(double elapsed);

    // Close the open entry at `elapsed` and write. Call when the run ends.
    void finish(double elapsed);

    void setDeckName(const std::string& name) { mDeck = name; }

private:
    bool save() const;

    std::vector<TimingEntry> mEntries;
    std::map<std::string, size_t> mFirstVisit;   // file -> index of its first entry
    double mTotal = 0.0;
    std::string mDeck;

    bool mRecording = false;
    std::string mPath;
    double mLastTickSave = 0.0;
};

// How far ahead (negative) or behind (positive) this run is against `timing`, in seconds.
// False when the trace has nothing for this slide.
//
// The rehearsal's own progress through the current slide is credited, so holding the same
// pace holds the number steady; it only grows once you have been on a slide longer than the
// rehearsal was, and it drops when you move on early.
bool paceDelta(const Timing& timing, const std::string& file, double elapsed,
               double timeOnSlide, double* delta);

}  // namespace refract
