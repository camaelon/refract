// The deck the player is showing: the playlist rcplayer walks, plus everything a
// presenter needs on top of it — titles, sections, speaker notes.
//
// refract writes out/deck.json next to the slides; when it is there the deck is exactly
// what the author wrote. When it is not (a hand-assembled directory, an older deck, a zip
// without the manifest) the deck degrades to filenames: "07_a_graph.rc" still reads as
// "A graph", and every slide is its own jump target. Nothing here is required for playback.
#pragma once

#include <string>
#include <vector>

namespace refract {

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
