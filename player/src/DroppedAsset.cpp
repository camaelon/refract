#include "DroppedAsset.h"

#include <algorithm>
#include <cctype>
#include <cstring>
#include <fstream>
#include <system_error>

namespace fs = std::filesystem;

namespace refract {

namespace {

// The same list refract resolves an `<include>` against (refractkit/deck.py).
const char* kIncludable[] = {".png", ".jpg", ".jpeg", ".gif", ".webp",
                             ".mp4", ".mov", ".m4v", ".webm",
                             ".rc", ".json",
                             ".kt", ".kts", ".java", ".py", ".ts", ".js"};

}  // namespace

bool includable(const fs::path& path) {
    std::string ext = path.extension().string();
    std::transform(ext.begin(), ext.end(), ext.begin(),
                   [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    for (const char* known : kIncludable) {
        if (ext == known) return true;
    }
    return false;
}

bool sameFile(const fs::path& a, const fs::path& b) {
    std::error_code ec;
    if (!fs::exists(a, ec) || !fs::exists(b, ec)) return false;
    if (fs::file_size(a, ec) != fs::file_size(b, ec) || ec) return false;
    std::ifstream fa(a, std::ios::binary), fb(b, std::ios::binary);
    if (!fa || !fb) return false;
    constexpr size_t kChunk = 64 * 1024;
    std::string bufA(kChunk, '\0'), bufB(kChunk, '\0');
    while (fa && fb) {
        fa.read(&bufA[0], kChunk);
        fb.read(&bufB[0], kChunk);
        const std::streamsize got = fa.gcount();
        if (got != fb.gcount()) return false;
        if (std::memcmp(bufA.data(), bufB.data(), static_cast<size_t>(got)) != 0) return false;
        if (got == 0) break;
    }
    return true;
}

fs::path placeFor(const fs::path& source, const fs::path& includes) {
    const fs::path bare = source.filename();
    fs::path candidate = includes / bare;
    std::error_code ec;
    if (!fs::exists(candidate, ec)) return candidate;
    if (sameFile(source, candidate)) return candidate;   // already here, under this name

    const std::string stem = bare.stem().string();
    const std::string ext = bare.extension().string();
    for (int n = 2; n < 1000; n++) {
        candidate = includes / (stem + "-" + std::to_string(n) + ext);
        if (!fs::exists(candidate, ec)) return candidate;
        if (sameFile(source, candidate)) return candidate;
    }
    return includes / bare;    // a thousand of them: the caller will fail to copy, and say so
}

std::string includeLine(const fs::path& placed) {
    return "<" + placed.filename().string() + ">";
}

}  // namespace refract
