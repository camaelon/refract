// The deck the player is showing: the playlist rcplayer walks, plus everything a
// presenter needs on top of it — titles, sections, speaker notes.
//
// refract writes out/deck.json next to the slides; when it is there the deck is exactly
// what the author wrote. When it is not (a hand-assembled directory, an older deck, a zip
// without the manifest) the deck degrades to filenames: "07_a_graph.rc" still reads as
// "A graph", and every slide is its own jump target. Nothing here is required for playback.
#pragma once

#include "DeckOrder.h"

#include <filesystem>
#include <string>
#include <vector>

namespace refract {

// Read a file that sits beside the slides — "deck.json", "timing.json". Handles all three
// things a deck can be: a directory, a single slide file, or a zip bundle. False when it is
// not there.
bool readDeckSidecar(const std::string& source, const std::string& name, std::string* out);

// Where such a file would be *written*. Empty for a zip bundle, which cannot be written into.
std::filesystem::path deckSidecarPath(const std::string& source, const std::string& name);

struct Slide {
    int index = 0;             // position in the deck, 0-based
    std::string entry;         // playlist entry — a path, or a zip entry name
    std::string file;          // basename, for display
    std::string title;         // manifest title, else the filename slug prettified
    std::string type;          // "title" | "section" | "content" | "split" | …
    std::string author;        // @author attribution, when the deck has one
    int sectionNumber = 0;     // set when this slide *is* a section heading
    int inSection = 0;         // the section this slide falls under (0 = front matter)
    bool hasNotes = false;
    std::string notes;         // loaded on demand by notesFor()
    bool notesLoaded = false;

    // Where the slide was written. `srcFile` is a markdown path relative to the deck
    // directory and `srcIndex` the `---`-separated block within it. One block can produce
    // several slides (bullet fragments, scroll pages, staggered embeds), so these are what
    // the deck view groups and reorders by. srcIndex is -1 when the manifest predates them
    // or the deck was not built by refract, and the deck view is then read-only.
    std::string srcFile;
    int srcIndex = -1;
    // The chain of `:: include` lines that pulled this slide in, outermost first — empty for
    // a slide of the deck's own markdown. `srcFile`/`srcIndex` say where the slide is written
    // and move it inside its own deck; the front of this chain is the block that moves the
    // whole sub-deck inside the deck being looked at.
    std::vector<SourceRef> srcVia;

    // Which of the slides that share this block this one is: 0 unless refract expanded the
    // block into several (bullet fragments, scroll pages, staggered embeds).
    int srcStep = 0;

    // A name for the slide that survives the deck being reordered.
    //
    // Filenames cannot: they carry the slide's position, so moving one slide renames every
    // slide after it. A rehearsal trace and a recording of the narration are both keyed by
    // slide, and both used to be silently wrong the moment anything moved. This is the block
    // the slide was written in, which is what a reorder moves rather than renames. Empty when
    // the deck has no provenance, and callers fall back to the filename.
    std::string sourceKey() const {
        if (srcFile.empty() || srcIndex < 0) return {};
        return srcFile + "#" + std::to_string(srcIndex) + "." + std::to_string(srcStep);
    }

    // Full provenance, root-first, ending with the slide's own block.
    std::vector<SourceRef> sourcePath() const {
        std::vector<SourceRef> path = srcVia;
        if (srcIndex >= 0) path.push_back({srcFile, srcIndex});
        return path;
    }
};

struct Section {
    int number = 0;
    std::string title;
    int firstSlide = 0;        // index of the section heading slide
};

class Deck {
public:
    // Build from the playlist rcplayer collected. `source` is the directory, zip path, or
    // file the user named — it is where the manifest is looked for.
    void build(const std::vector<std::string>& entries, const std::string& source);

    bool empty() const { return mSlides.empty(); }
    int  size()  const { return static_cast<int>(mSlides.size()); }
    const std::vector<Slide>&   slides()   const { return mSlides; }
    const std::vector<Section>& sections() const { return mSections; }
    bool hasManifest() const { return mHasManifest; }
    const std::string& name() const { return mName; }

    const Slide& at(int i) const { return mSlides[clamp(i)]; }
    int clamp(int i) const;

    // True when every slide records where it came from, i.e. the deck can be reordered by
    // rewriting its markdown.
    bool reorderable() const;

    // The slide with this source key, or -1. How a trace or a recording finds its slide
    // again after the deck has been reordered.
    int indexOfSourceKey(const std::string& key) const;

    // Position of the slide with this basename, or -1. Traces key by name for the same
    // reason the manifest does: it survives a deck being renumbered around it.
    int indexOfFile(const std::string& file) const;

    // The speaker notes for a slide, read from its "<entry>.notes" sidecar the first time
    // it is asked for. Empty when the slide has none.
    const std::string& notesFor(int i);

    // Index of the section heading at or before `slide`, or -1 when the slide sits ahead
    // of the first section.
    int sectionIndexOf(int slide) const;

    // First slide of the previous / next section relative to `slide`, or -1 when there is
    // none in that direction. Used by the section-step keys.
    int prevSectionSlide(int slide) const;
    int nextSectionSlide(int slide) const;

private:
    std::vector<Slide>   mSlides;
    std::vector<Section> mSections;
    bool mHasManifest = false;
    std::string mName;
};

}  // namespace refract
