#include "Captions.h"

#include "rcplayer/Player.h"

#include <nlohmann/json.hpp>

#include <cctype>
#include <cstddef>
#include <filesystem>
#include <fstream>
#include <iostream>

namespace fs = std::filesystem;

namespace refract {

void Captions::loadFor(const std::string& entry) {
    if (entry == mEntry) return;
    if (mDirty) save();          // never lose a correction to a slide change
    mEntry = entry;
    mPath.clear();
    mText.clear();
    mWords.clear();
    mDirty = false;
    mEarliestEdit = -1.0;

    // Captions sit beside the wav they were made from, under the same slide number.
    fs::path wav = rcplayer::voicePathFor(entry);
    if (wav.empty()) return;
    fs::path path = wav;
    path.replace_extension();               // drop ".wav"
    path += ".words.json";
    mPath = path.string();
    if (!fs::exists(path)) return;

    std::ifstream in(path, std::ios::binary);
    std::string raw((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    auto doc = nlohmann::json::parse(raw, nullptr, /*allow_exceptions=*/false);
    if (doc.is_discarded() || !doc.contains("words")) {
        std::cerr << "captions: unreadable " << path.string() << "\n";
        return;
    }

    mText = doc.value("text", std::string());
    for (const auto& rec : doc["words"]) {
        if (!rec.contains("w")) continue;
        CaptionWord word;
        word.text  = rec["w"].get<std::string>();
        word.start = rec.value("start", 0.0);
        word.end   = rec.value("end", 0.0);
        if (!word.text.empty()) mWords.push_back(std::move(word));
    }
}

void Captions::replaceRange(int first, int last, const std::string& text) {
    const int count = static_cast<int>(mWords.size());
    if (first < 0 || last < first || last >= count) return;

    std::vector<std::string> tokens;
    for (std::size_t i = 0; i < text.size(); ) {
        while (i < text.size() && std::isspace(static_cast<unsigned char>(text[i]))) i++;
        std::size_t begin = i;
        while (i < text.size() && !std::isspace(static_cast<unsigned char>(text[i]))) i++;
        if (i > begin) tokens.push_back(text.substr(begin, i - begin));
    }

    // Nothing to do when the words are already exactly that.
    if (static_cast<int>(tokens.size()) == last - first + 1) {
        bool same = true;
        for (std::size_t i = 0; i < tokens.size(); i++) {
            if (mWords[first + i].text != tokens[i]) { same = false; break; }
        }
        if (same) return;
    }

    const double spanStart = mWords[first].start;
    const double spanEnd = mWords[last].end;

    // Remember the earliest point touched, so playback can resume near it.
    if (mEarliestEdit < 0.0 || spanStart < mEarliestEdit) mEarliestEdit = spanStart;

    std::vector<CaptionWord> replacement;
    if (!tokens.empty()) {
        // Longer words take longer to say, so the span is shared out by length rather than
        // evenly. Close enough to keep a highlight on the right word until a real alignment
        // is run over the corrected text.
        double total = 0;
        for (const auto& token : tokens) total += static_cast<double>(token.size());
        double at = spanStart;
        for (std::size_t i = 0; i < tokens.size(); i++) {
            const double share = (spanEnd - spanStart) * (tokens[i].size() / total);
            CaptionWord word;
            word.text = tokens[i];
            word.start = at;
            word.end = (i + 1 == tokens.size()) ? spanEnd : at + share;
            at = word.end;
            replacement.push_back(std::move(word));
        }
    }

    mWords.erase(mWords.begin() + first, mWords.begin() + last + 1);
    mWords.insert(mWords.begin() + first, replacement.begin(), replacement.end());
    mDirty = true;
}

bool Captions::save() {
    if (mPath.empty()) return false;

    // The transcript is rebuilt from the words rather than kept alongside them: they are what
    // was corrected, and two copies that can disagree is one too many.
    std::string text;
    for (const auto& word : mWords) {
        if (!text.empty()) text += ' ';
        text += word.text;
    }
    mText = text;

    nlohmann::ordered_json doc;
    doc["version"] = 1;
    doc["wav"] = fs::path(mPath).filename().replace_extension().replace_extension(".wav")
                     .string();
    doc["text"] = mText;
    for (const auto& word : mWords) {
        doc["words"].push_back(nlohmann::ordered_json{
            {"w", word.text}, {"start", word.start}, {"end", word.end}});
    }

    std::ofstream out(mPath, std::ios::binary | std::ios::trunc);
    if (!out) {
        std::cerr << "captions: cannot write " << mPath << "\n";
        return false;
    }
    out << doc.dump(2) << "\n";

    // Keep the plain transcript in step, so re-running --transcribe re-aligns against the
    // corrected words instead of transcribing the same mistake again.
    fs::path txt = fs::path(mPath);
    txt.replace_extension();            // drop ".json"
    txt.replace_extension(".txt");      // ".words" -> ".txt"
    std::ofstream textOut(txt, std::ios::binary | std::ios::trunc);
    if (textOut) textOut << mText << "\n";

    mDirty = false;
    std::cerr << "captions: saved " << mPath << "\n";
    return true;
}

int Captions::wordAt(double t) const {
    if (mWords.empty()) return -1;
    if (t < mWords.front().start) return -1;
    // Linear scan: a slide's narration is tens of words, and the answer is nearly always the
    // one after last time's.
    int found = -1;
    for (size_t i = 0; i < mWords.size(); i++) {
        if (t >= mWords[i].start) found = static_cast<int>(i);
        else break;
    }
    return found;
}

}  // namespace refract
