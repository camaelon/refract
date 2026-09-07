#include "FileDialog.h"

namespace refract {

// No dialog to put on screen here. The start window says so, and offers the decks it
// remembers instead; naming one on the command line always works.
bool canChooseFiles() { return false; }
std::string chooseDeck() { return {}; }
std::string chooseNewDeck() { return {}; }

}  // namespace refract
