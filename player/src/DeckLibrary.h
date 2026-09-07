// The decks this player knows about, and making a new one.
//
// Kept per user rather than per deck — it is the only thing the player remembers that is not
// about a particular deck, so it is the only thing it writes outside one.
#pragma once

#include <string>
#include <vector>

namespace refract {

// Where the list lives. Empty when there is no home directory to put it in.
std::string recentPath();

// Decks opened before, most recent first. A deck that has been moved or deleted since is left
// out: a list of things that do not open is worse than a shorter list.
std::vector<std::string> recentDecks();

// Note that a deck was opened. It goes to the front, and the list stays short.
void rememberDeck(const std::string& deckDir);

// Make a deck at `path`: the directory, and a slides.md with enough in it to show what the
// grammar looks like. False when it could not be written, or when a deck is already there.
bool createDeck(const std::string& path, std::string* error);

// What a new deck starts as.
const char* starterDeck();

}  // namespace refract
