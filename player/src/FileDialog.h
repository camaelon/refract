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
// Every export panel has a "slides" field — "3-12, 20", 1-based, empty for all — opened
// with `slidesDefault`, which is what the deck view has selected when it has a selection.
struct PdfChoice {
    std::string path;
    std::string slides;
};
bool choosePdf(const std::string& dir, const std::string& name, const std::string& slidesDefault,
               PdfChoice* out);

// Where to write a movie of the deck, and which slides go in it. The panel carries the
// range and the frame rate as fields under the file name; `from`/`to` are 1-based and
// inclusive, and arrive prefilled with the whole deck. False when cancelled.
struct VideoChoice {
    std::string path;
    std::string slides;
    double fps = 30.0;
    bool captions = false;     // a caption line under the slides, from the transcripts
};
bool chooseVideo(const std::string& dir, const std::string& name, const std::string& slidesDefault,
                 VideoChoice* out);

// A folder for the web export, offered as `name` inside `dir`; created by the caller.
struct WebChoice {
    std::string dir;
    std::string slides;
};
bool chooseWebDir(const std::string& dir, const std::string& name, const std::string& slidesDefault,
                  WebChoice* out);

// Move a file to the Trash rather than deleting it, so a wrong click can be undone from the
// Finder. False when it could not be moved (the file stays). Elsewhere than macOS the file is
// removed outright, and the caller's wording should say so.
bool moveToTrash(const std::string& path);
bool trashIsAvailable();

}  // namespace refract
