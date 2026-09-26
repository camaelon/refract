#include "ExportPlan.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <filesystem>

namespace refract {

namespace fs = std::filesystem;

namespace {

std::string lowerExt(const fs::path& p) {
    std::string ext = p.extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(), [](unsigned char c) { return std::tolower(c); });
    return ext;
}

// Single-quoted for /bin/sh, the one quoting that needs no escaping but of the quote itself.
std::string shellQuoted(const std::string& s) {
    std::string out = "'";
    for (char c : s) { if (c == '\'') out += "'\\''"; else out += c; }
    return out + "'";
}

}  // namespace

ExportTarget exportTarget(const std::string& deckInput) {
    // <deck>/<deck>.pdf beside the sources, where somebody will look for it, rather than
    // refract.py's <deck>/out/deck.pdf. Absolute first, or a deck given as "out" from inside
    // its folder has no parent to be named after.
    const fs::path input(deckInput);
    const bool zip = lowerExt(input) == ".zip";
    fs::path deckDir = fs::absolute(input).lexically_normal();
    if (deckDir.filename().empty()) deckDir = deckDir.parent_path();     // a trailing slash
    if (zip) deckDir = deckDir.parent_path();
    else if (deckDir.filename() == "out") deckDir = deckDir.parent_path();
    ExportTarget target;
    target.dir = deckDir.string();
    target.name = zip ? input.stem().string() : deckDir.filename().string();
    if (target.name.empty()) target.name = "deck";
    return target;
}

bool videoRange(int count, int from, int to, int* first, int* last) {
    *first = std::max(1, from);
    *last = to > 0 ? std::min(to, count) : count;
    return count > 0 && *first <= *last;
}

double snapToFrames(double seconds, double fps) {
    return std::max(1.0, std::lround(seconds * fps) / fps);
}

std::string soundtrackCommand(const std::vector<SoundtrackPiece>& pieces, const std::string& audio) {
    std::string cmd = "ffmpeg -y -loglevel error";
    std::string filter;
    for (size_t k = 0; k < pieces.size(); k++) {
        char d[32];
        std::snprintf(d, sizeof(d), "%.3f", pieces[k].duration);
        if (!pieces[k].wav.empty()) cmd += " -i " + shellQuoted(pieces[k].wav);
        else cmd += std::string(" -f lavfi -t ") + d + " -i anullsrc=r=48000:cl=stereo";
        filter += "[" + std::to_string(k) + ":a]aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,atrim=0:"
                  + d + ",apad=whole_dur=" + d + "[a" + std::to_string(k) + "];";
    }
    for (size_t k = 0; k < pieces.size(); k++) filter += "[a" + std::to_string(k) + "]";
    filter += "concat=n=" + std::to_string(pieces.size()) + ":v=0:a=1[out]";
    cmd += " -filter_complex " + shellQuoted(filter) + " -map '[out]' -ar 48000 -ac 2 " + shellQuoted(audio);
    return cmd;
}

std::vector<CaptionCue> captionCues(const std::vector<CaptionWord>& words, size_t maxChars,
                                    double maxGap) {
    std::vector<CaptionCue> cues;
    CaptionCue line;
    auto endsSentence = [](const std::string& w) {
        return !w.empty() && (w.back() == '.' || w.back() == '?' || w.back() == '!');
    };
    auto flush = [&]() {
        if (!line.text.empty()) cues.push_back(line);
        line = CaptionCue();
    };
    for (const CaptionWord& w : words) {
        if (w.text.empty()) continue;
        if (!line.text.empty()) {
            const bool tooLong = line.text.size() + 1 + w.text.size() > maxChars;
            const bool pause = w.start - line.end > maxGap;
            if (tooLong || pause) flush();
        }
        if (line.text.empty()) {
            line.start = w.start;
            line.text = w.text;
        } else {
            line.text += " " + w.text;
        }
        line.words.push_back(w);
        line.end = w.end;
        if (endsSentence(w.text)) flush();
    }
    flush();
    // Each line holds until the next begins; the last a moment past its final word.
    for (size_t i = 0; i < cues.size(); i++) {
        cues[i].end = i + 1 < cues.size() ? cues[i + 1].start : cues[i].end + 1.0;
    }
    return cues;
}

}  // namespace refract
