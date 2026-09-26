#include "VoiceDir.h"

namespace refract {

namespace fs = std::filesystem;

fs::path deckVoiceDir(const fs::path& input) {
    std::error_code ec;
    if (!fs::is_directory(input, ec)) return {};
    fs::path deckDir = fs::absolute(input).lexically_normal();
    if (deckDir.filename().empty()) deckDir = deckDir.parent_path();     // a trailing slash
    deckDir = deckDir.parent_path();
    if (fs::exists(deckDir / "slides.md", ec) || fs::is_directory(deckDir / "voice", ec)) return deckDir / "voice";
    return {};
}

Adoption adoptVoiceDir(const fs::path& input, const fs::path& target) {
    Adoption result;
    if (target.empty()) return result;
    std::error_code ec;
    const fs::path old = fs::path(input) / "voice";
    if (!fs::is_directory(old, ec) || fs::exists(target, ec)) return result;
    bool anyWav = false;
    for (const auto& entry : fs::directory_iterator(old, ec)) {
        if (entry.path().extension() == ".wav") { anyWav = true; break; }
    }
    if (!anyWav) return result;
    result.from = old;
    result.to = target;
    fs::rename(old, target, ec);
    if (ec) {
        result.outcome = Adoption::Outcome::Failed;
        result.error = ec.message();
    } else {
        result.outcome = Adoption::Outcome::Moved;
    }
    return result;
}

std::vector<fs::path> narrationFiles(const fs::path& wav) {
    std::vector<fs::path> files;
    if (wav.empty()) return files;
    for (const char* ext : {".wav", ".txt", ".words.json"}) {
        fs::path path = wav;
        path.replace_extension();
        path += ext;
        files.push_back(path);
    }
    return files;
}

}  // namespace refract
