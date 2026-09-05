// Per-word caption timings for a slide's narration.
//
// Written by `refract.py <deck> --captions`, which transcribes each recorded wav and then
// force-aligns the transcript against it to get a start and end per word. Here they are read
// back so the words can be lit as they are spoken.
//
// A slide with no narration, or narration that has not been processed, simply has none —
// captions are an addition to a deck, never a requirement of one.
#pragma once

#include <filesystem>
#include <string>
#include <vector>

namespace refract {

struct CaptionWord {
    std::string text;
    double start = 0.0;
    double end = 0.0;
};

class Captions {
public:
    // Load the timings beside a slide's wav ("<voice>/NN.words.json"). Cheap to call
    // repeatedly with the same wav; results are cached, misses included.
    //
    // Given the wav rather than the slide, because which wav a slide's narration is in is a
    // question the deck has to answer once the deck has been reordered — see VoiceIndex.
    void loadForVoice(const std::filesystem::path& wav);

    bool empty() const { return mWords.empty(); }
    const std::vector<CaptionWord>& words() const { return mWords; }
    const std::string& text() const { return mText; }

    // The word being spoken at `t`, or -1 before the first one. A word stays current through
    // the pause after it until the next begins, so the highlight moves once per word instead
    // of blinking off in every gap between them.
    int wordAt(double t) const;

    // ── Correcting a transcript ──────────────────────────────────────
    // A transcriber mishears words, and the fix is a relabelling: the audio has not changed,
    // so the word still occupies exactly the time it did. That is why a correction needs no
    // re-alignment — only the text is rewritten, and the timings are kept.
    //
    // A range can be replaced by any number of words, which is what a word heard as two — or
    // two heard as one — needs. The span the old words covered is divided among the new ones
    // in proportion to their length: a guess, but the only one available without re-running
    // forced alignment, and re-running `--transcribe` afterwards replaces the guess with a
    // real alignment against the corrected text.
    //
    // An empty `text` deletes the range, for the case where words were heard that were never
    // said.
    void replaceRange(int first, int last, const std::string& text);

    // True when something has been changed and not yet written.
    bool dirty() const { return mDirty; }

    // Where in the narration the earliest correction of this editing session was, or -1 when
    // nothing has been changed. Playback picks up from near here afterwards rather than from
    // the top of the slide: the point of replaying is to hear the correction in place, and
    // everything before it was already right.
    double earliestEdit() const { return mEarliestEdit; }
    void clearEditMarker() { mEarliestEdit = -1.0; }

    // Write the timings back, and the transcript alongside them so a later --transcribe run
    // aligns against the corrected text rather than re-hearing the same mistake.
    bool save();

private:
    std::string mEntry;                 // the slide these belong to
    std::string mPath;                  // the .words.json these came from
    std::string mText;
    std::vector<CaptionWord> mWords;
    bool mDirty = false;
    double mEarliestEdit = -1.0;
};

}  // namespace refract
