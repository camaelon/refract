#include "Deck.h"

#include "rcplayer/MediaTypes.h"
#include "rcplayer/PdfExport.h"
#include "rcplayer/Player.h"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cctype>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>

namespace fs = std::filesystem;

namespace refract {

namespace {

// "07_a_graph.rc" -> "A graph". The generator slugs the title into the filename, so the
// filename is a lossy but serviceable stand-in when there is no manifest.
std::string titleFromFilename(const std::string& file) {
    std::string stem = file;
    auto dot = stem.rfind('.');
    if (dot != std::string::npos) stem = stem.substr(0, dot);
    // Drop the "NN_" ordering prefix.
    size_t i = 0;
    while (i < stem.size() && std::isdigit(static_cast<unsigned char>(stem[i]))) i++;
    if (i > 0 && i < stem.size() && stem[i] == '_') stem = stem.substr(i + 1);
    std::replace(stem.begin(), stem.end(), '_', ' ');
    if (!stem.empty()) stem[0] = static_cast<char>(std::toupper(static_cast<unsigned char>(stem[0])));
    return stem;
}

}  // namespace

fs::path deckSidecarPath(const std::string& source, const std::string& name) {
    if (rcplayer::g.zip) return {};
    fs::path p(source);
    if (fs::is_directory(p)) return p / name;
    if (fs::is_regular_file(p)) return p.parent_path() / name;
    return {};
}

bool readDeckSidecar(const std::string& source, const std::string& name, std::string* out) {
    out->clear();
    if (rcplayer::g.zip) {
        // A bundle may have been zipped from the deck root or from out/, so try both.
        for (const std::string candidate : {name, "out/" + name}) {
            std::vector<uint8_t> bytes;
            if (rcplayer::g.zip->read(candidate, bytes)) {
                out->assign(bytes.begin(), bytes.end());
                return true;
            }
        }
        return false;
    }
    fs::path path = deckSidecarPath(source, name);
    if (path.empty() || !fs::exists(path)) return false;
    std::ifstream in(path, std::ios::binary);
    out->assign((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    return true;
}

int Deck::clamp(int i) const {
    if (mSlides.empty()) return 0;
    int n = static_cast<int>(mSlides.size());
    return std::max(0, std::min(i, n - 1));
}

void Deck::build(const std::vector<std::string>& entries, const std::string& source) {
    mSlides.clear();
    mSections.clear();
    mHasManifest = false;
    mName = fs::path(source).filename().string();

    // Every playlist entry becomes a slide; the manifest only ever *decorates* them. That
    // ordering matters: playback follows rcplayer's playlist, so a manifest that has drifted
    // from the directory (a stale deck.json, an extra file dropped in) cannot desync the
    // player from what it is actually showing.
    for (size_t i = 0; i < entries.size(); i++) {
        Slide s;
        s.index = static_cast<int>(i);
        s.entry = entries[i];
        s.file  = rcplayer::baseName(entries[i]);
        s.title = titleFromFilename(s.file);
        s.type  = "content";
        mSlides.push_back(std::move(s));
    }
    if (mSlides.empty()) return;

    // ── Manifest ─────────────────────────────────────────────────────
    std::string text;
    readDeckSidecar(source, "deck.json", &text);

    if (!text.empty()) {
        auto doc = nlohmann::json::parse(text, nullptr, /*allow_exceptions=*/false);
        if (doc.is_discarded() || !doc.contains("slides")) {
            std::cerr << "deck.json: unreadable, falling back to filenames\n";
        } else {
            // Match on filename, not position: a deck.json listing a slide the directory no
            // longer has (or vice versa) then costs only that slide's metadata.
            std::map<std::string, const nlohmann::json*> byFile;
            for (const auto& rec : doc["slides"]) {
                if (rec.contains("file")) byFile[rec["file"].get<std::string>()] = &rec;
            }
            int matched = 0;
            for (auto& slide : mSlides) {
                auto it = byFile.find(slide.file);
                if (it == byFile.end()) continue;
                const auto& rec = *it->second;
                matched++;
                if (rec.value("title", std::string()).size())
                    slide.title = rec["title"].get<std::string>();
                slide.type          = rec.value("type", slide.type);
                slide.author        = rec.value("author", std::string());
                slide.sectionNumber = rec.value("section", 0);
                slide.hasNotes      = rec.value("notes", false);
                slide.srcFile       = rec.value("src", std::string());
                slide.srcIndex      = rec.value("src_index", -1);
                slide.srcVia.clear();
                if (rec.contains("src_via") && rec["src_via"].is_array()) {
                    for (const auto& via : rec["src_via"]) {
                        slide.srcVia.push_back({via.value("src", std::string()),
                                                via.value("src_index", -1)});
                    }
                }
            }
            mHasManifest = matched > 0;
            if (doc.contains("deck")) mName = doc["deck"].get<std::string>();
        }
    }

    // Number the slides that came out of one markdown block, so each still has a name of
    // its own: four steps of a stepped bullet list are one block and four slides.
    for (size_t i = 0; i < mSlides.size(); i++) {
        if (mSlides[i].srcIndex < 0) continue;
        mSlides[i].srcStep = (i > 0 && mSlides[i - 1].srcIndex == mSlides[i].srcIndex
                              && mSlides[i - 1].srcFile == mSlides[i].srcFile)
                                 ? mSlides[i - 1].srcStep + 1 : 0;
    }

    // ── Sections ─────────────────────────────────────────────────────
    for (const auto& slide : mSlides) {
        if (slide.type == "section" || slide.sectionNumber > 0) {
            Section sec;
            sec.number     = slide.sectionNumber > 0 ? slide.sectionNumber
                                                     : static_cast<int>(mSections.size()) + 1;
            sec.title      = slide.title;
            sec.firstSlide = slide.index;
            mSections.push_back(sec);
        }
    }
    // Tag each slide with the section it falls under, so the presenter can name where we are.
    int current = 0;
    for (auto& slide : mSlides) {
        for (const auto& sec : mSections) {
            if (sec.firstSlide == slide.index) current = sec.number;
        }
        slide.inSection = current;
    }
}

const std::string& Deck::notesFor(int i) {
    static const std::string kNone;
    if (mSlides.empty()) return kNone;
    Slide& slide = mSlides[clamp(i)];
    if (slide.notesLoaded) return slide.notes;
    slide.notesLoaded = true;

    if (rcplayer::g.zip) {
        std::vector<uint8_t> bytes;
        if (rcplayer::g.zip->read(slide.entry + ".notes", bytes))
            slide.notes.assign(bytes.begin(), bytes.end());
    } else {
        slide.notes = rcplayer::readSlideNotes(slide.entry);
    }
    while (!slide.notes.empty() && std::isspace(static_cast<unsigned char>(slide.notes.back())))
        slide.notes.pop_back();
    return slide.notes;
}

bool Deck::reorderable() const {
    if (mSlides.empty() || rcplayer::g.zip) return false;
    for (const auto& slide : mSlides) {
        if (slide.srcIndex < 0 || slide.srcFile.empty()) return false;
    }
    return true;
}

int Deck::indexOfSourceKey(const std::string& key) const {
    if (key.empty()) return -1;
    for (const auto& slide : mSlides) {
        if (slide.sourceKey() == key) return slide.index;
    }
    return -1;
}

int Deck::indexOfFile(const std::string& file) const {
    for (const auto& slide : mSlides) {
        if (slide.file == file) return slide.index;
    }
    return -1;
}

int Deck::sectionIndexOf(int slide) const {
    int found = -1;
    for (size_t i = 0; i < mSections.size(); i++) {
        if (mSections[i].firstSlide <= slide) found = static_cast<int>(i);
    }
    return found;
}

int Deck::prevSectionSlide(int slide) const {
    // Stepping back from inside a section goes to that section's own heading first, the way
    // a "previous chapter" control does — a second press then leaves for the one before.
    int here = sectionIndexOf(slide);
    if (here < 0) return -1;
    if (mSections[here].firstSlide < slide) return mSections[here].firstSlide;
    return here > 0 ? mSections[here - 1].firstSlide : -1;
}

int Deck::nextSectionSlide(int slide) const {
    for (const auto& sec : mSections) {
        if (sec.firstSlide > slide) return sec.firstSlide;
    }
    return -1;
}

}  // namespace refract
