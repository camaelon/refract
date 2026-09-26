#include "FileDialog.h"

#include <filesystem>

namespace refract {

// No dialog to put on screen here. The start window says so, and offers the decks it
// remembers instead; naming one on the command line always works.
bool canChooseFiles() { return false; }
std::string chooseDeck() { return {}; }
std::string chooseNewDeck() { return {}; }
std::string choosePdf(const std::string&, const std::string&) { return {}; }
bool chooseVideo(const std::string&, const std::string&, int, VideoChoice*) { return false; }

bool trashIsAvailable() { return false; }

bool moveToTrash(const std::string& path) {
    std::error_code ec;
    return std::filesystem::remove(path, ec);
}

}  // namespace refract
