// The decisions behind an export, apart from doing it.
//
// Where a PDF or a movie of a deck goes and what it is called; how long each slide of a
// movie stays up; the ffmpeg command that lays the narration out to that timeline. None of
// it touches the engine or a window, so it is here on its own where it can be checked
// against a command line and a list of durations rather than a two-minute render.
#pragma once

#include "Captions.h"

#include <string>
#include <vector>

namespace refract {

// Where an export of the deck the player was given goes, and what it is named after.
struct ExportTarget {
    std::string dir;    // beside the deck's sources: the folder above out/, or the zip's
    std::string name;   // the deck's own name, without an extension
};
ExportTarget exportTarget(const std::string& deckInput);

// Slides `from`..`to` of a deck of `count`, as typed (1-based, `to` 0 for the last one),
// clamped to the deck. False when the range is empty.
bool videoRange(int count, int from, int to, int* first, int* last);

// A slide's stay, snapped to whole frames at `fps` and never under a second: the soundtrack
// is cut to the same length, and a fraction of a frame between the two would drift.
double snapToFrames(double seconds, double fps);

// One slide of the soundtrack: its narration, or silence for `duration` seconds.
struct SoundtrackPiece {
    std::string wav;         // empty for silence
    double duration = 0.0;   // seconds, already snapped
};

// The ffmpeg command line that concatenates `pieces` into `audio` (a wav): every piece
// resampled alike and cut or padded to its duration, so the sound lines up with the frames.
std::string soundtrackCommand(const std::vector<SoundtrackPiece>& pieces, const std::string& audio);

// One line of caption for the movie: the words spoken from `start` to `end`.
struct CaptionCue {
    double start = 0.0;
    double end = 0.0;
    std::string text;
    std::vector<CaptionWord> words;   // the line's words with their timings, for lighting them
};

// Word timings folded into lines for a one-line caption band. A line breaks when the next
// word would take it past `maxChars`, after a word that ends a sentence, or across a pause
// longer than `maxGap` seconds. Each line stays up until the next begins, so the band is
// never blank mid-speech; the last holds a moment past its final word.
std::vector<CaptionCue> captionCues(const std::vector<CaptionWord>& words, size_t maxChars = 64,
                                    double maxGap = 1.5);

}  // namespace refract
