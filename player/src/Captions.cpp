#include "Captions.h"

#include "rcplayer/Player.h"

#include <nlohmann/json.hpp>

#include <filesystem>
#include <fstream>
#include <iostream>

namespace fs = std::filesystem;

namespace refract {

void Captions::loadFor(const std::string& entry) {
    if (entry == mEntry) return;
    mEntry = entry;
    mText.clear();
    mWords.clear();

    // Captions sit beside the wav they were made from, under the same slide number.
    fs::path wav = rcplayer::voicePathFor(entry);
    if (wav.empty()) return;
    fs::path path = wav;
    path.replace_extension();               // drop ".wav"
    path += ".words.json";
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
