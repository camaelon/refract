#include "FileDialog.h"

#include <filesystem>

namespace refract {

// No dialog to put on screen here. The start window says so, and offers the decks it
// remembers instead; naming one on the command line always works.
bool canChooseFiles() { return false; }
std::string chooseDeck() { return {}; }
std::string chooseNewDeck() { return {}; }
bool choosePdf(const std::string& dir, const std::string& name, const std::string& slidesDefault,
               PdfChoice* out) {
    out->path = (std::filesystem::path(dir) / name).string();
    out->slides = slidesDefault;
    return true;
}
bool chooseVideo(const std::string&, const std::string&, const std::string& slidesDefault, VideoChoice* out) {
    out->slides = slidesDefault;
    return false;
}

bool chooseWebDir(const std::string& dir, const std::string& name, const std::string& slidesDefault,
                  WebChoice* out) {
    out->dir = (std::filesystem::path(dir) / name).string();
    out->slides = slidesDefault;
    return true;
}

bool trashIsAvailable() { return false; }

bool moveToTrash(const std::string& path) {
    std::error_code ec;
    return std::filesystem::remove(path, ec);
}

}  // namespace refract
