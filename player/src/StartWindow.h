// What the player shows when nobody said which deck.
//
// Launched from a terminal that is one thing — the usage text is right there. Launched by
// double-clicking, it was a window that never opened and a process that exited, which is not
// an answer. And the player can now write a deck as well as play one, so "start a new deck"
// is a thing it can actually offer.
//
// A small window: the decks it has played before, a button to open another, and a button to
// make one. It runs its own loop and hands back a deck path, which the player then opens
// exactly as if it had been named on the command line.
#pragma once

#include <string>

namespace refract {

// Show the start window and wait. Returns the deck to open, or empty when the window was
// closed without choosing one — in which case the player has nothing to do and stops.
std::string runStartWindow();

}  // namespace refract
