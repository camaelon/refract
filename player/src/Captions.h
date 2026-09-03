// Per-word caption timings for a slide's narration.
//
// Written by `refract.py <deck> --captions`, which transcribes each recorded wav and then
// force-aligns the transcript against it to get a start and end per word. Here they are read
// back so the words can be lit as they are spoken.
//
// A slide with no narration, or narration that has not been processed, simply has none —
// captions are an addition to a deck, never a requirement of one.
#pragma once

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
    // repeatedly with the same entry; results are cached, misses included.
    void loadFor(const std::string& entry);

    bool empty() const { return mWords.empty(); }
    const std::vector<CaptionWord>& words() const { return mWords; }
    const std::string& text() const { return mText; }

    // The word being spoken at `t`, or -1 before the first one. A word stays current through
    // the pause after it until the next begins, so the highlight moves once per word instead
    // of blinking off in every gap between them.
    int wordAt(double t) const;

private:
    std::string mEntry;                 // the slide these belong to
    std::string mText;
    std::vector<CaptionWord> mWords;
};

}  // namespace refract
