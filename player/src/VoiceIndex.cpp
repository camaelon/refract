#include "VoiceIndex.h"

#include <nlohmann/json.hpp>

#include <fstream>
#include <iostream>

namespace fs = std::filesystem;

namespace refract {

void VoiceIndex::load(const fs::path& voiceDir) {
    mStems.clear();
    if (voiceDir.empty()) return;
    const fs::path path = voiceDir / "index.json";
    std::error_code ec;
    if (!fs::exists(path, ec)) return;

    std::ifstream in(path);
    std::string text((std::istreambuf_iterator<char>(in)), std::istreambuf_iterator<char>());
    auto doc = nlohmann::json::parse(text, nullptr, /*allow_exceptions=*/false);
    if (doc.is_discarded() || !doc.contains("slides") || !doc["slides"].is_object()) {
        std::cerr << "voice/index.json: unreadable, falling back to slide numbers\n";
        return;
    }
    for (auto it = doc["slides"].begin(); it != doc["slides"].end(); ++it) {
        if (it.value().is_string()) mStems[it.key()] = it.value().get<std::string>();
    }
    mPath = path;
}

std::string VoiceIndex::stemFor(const std::string& sourceKey) const {
    if (sourceKey.empty()) return {};
    auto it = mStems.find(sourceKey);
    return it == mStems.end() ? std::string() : it->second;
}

void VoiceIndex::record(const std::string& sourceKey, const std::string& stem) {
    if (sourceKey.empty() || stem.empty()) return;
    // Recorded again, the slide keeps the wav it had: the recorder writes over that file, so
    // a second pass at one slide replaces its narration rather than orphaning it.
    mStems[sourceKey] = stem;
    save();
}

bool VoiceIndex::save() const {
    if (mPath.empty()) return false;
    nlohmann::ordered_json doc;
    doc["version"] = 1;
    doc["slides"] = nlohmann::ordered_json::object();
    for (const auto& [key, stem] : mStems) doc["slides"][key] = stem;

    std::ofstream out(mPath);
    if (!out) return false;
    out << doc.dump(2) << "\n";
    return true;
}

}  // namespace refract
