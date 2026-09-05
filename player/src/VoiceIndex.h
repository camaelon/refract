// Which narration belongs to which slide, when the slide has moved.
//
// A recorded talk leaves one wav per slide in the deck's voice dir, named for the slide's
// number — voice/07.wav for the seventh. That name is a *position*, and reordering a deck
// renumbers every slide after the move, so after one drag in the deck view an hour of
// narration lines up with the wrong slides and nothing says so.
//
// So the recorder also writes voice/index.json: the slide's source block (the thing a reorder
// moves rather than renames) against the wav's stem. The wavs keep the names they always had,
// which matters because the transcription and the web export both read them by number and
// expect NN.txt and NN.words.json beside them.
//
// A recording made before any of this has no index, and the positional name is used — which
// is right, because such a deck has not been reordered under it either.
#pragma once

#include <filesystem>
#include <map>
#include <string>

namespace refract {

class VoiceIndex {
public:
    // Read the index in `voiceDir`, if there is one. Safe to call with no such directory.
    void load(const std::filesystem::path& voiceDir);

    bool empty() const { return mStems.empty(); }

    // The wav stem recorded for this slide, or empty when the index has nothing for it.
    std::string stemFor(const std::string& sourceKey) const;

    // Note that `stem` is this slide's narration, and write the index. Called as each slide
    // is recorded, so a run that ends by being killed still leaves a usable index.
    void record(const std::string& sourceKey, const std::string& stem);

    // Where to write. Set before recording; without it record() only remembers.
    void setPath(const std::filesystem::path& path) { mPath = path; }

private:
    bool save() const;

    std::map<std::string, std::string> mStems;   // source key -> wav stem
    std::filesystem::path mPath;
};

}  // namespace refract
