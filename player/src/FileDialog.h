// Asking the person which deck, when nothing on the command line said.
//
// GLFW has no file dialogs — it is a window and an event loop and nothing else — so this is
// the platform's own. Elsewhere it answers "cannot ask", and the caller falls back to the
// decks it already knows about.
#pragma once

#include <string>

namespace refract {

// True when this platform can actually put a dialog on screen.
bool canChooseFiles();

// An existing deck directory — the one with slides.md in it. Empty when cancelled.
std::string chooseDeck();

// Where to make a new deck. Empty when cancelled. The directory need not exist yet.
std::string chooseNewDeck();

// Where to write a PDF of the deck, starting from `dir` with `name` filled in. Empty when
// cancelled. The panel adds .pdf when the person leaves it off.
std::string choosePdf(const std::string& dir, const std::string& name);

// Where to write a movie of the deck, and which slides go in it. The panel carries the
// range and the frame rate as fields under the file name; `from`/`to` are 1-based and
// inclusive, and arrive prefilled with the whole deck. False when cancelled.
struct VideoChoice {
    std::string path;
    int from = 1, to = 0;
    double fps = 30.0;
};
bool chooseVideo(const std::string& dir, const std::string& name, int slideCount, VideoChoice* out);

}  // namespace refract
