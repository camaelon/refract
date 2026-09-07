// The deck's markdown, as the player sees it: everything that reads or rewrites a deck's
// own source files.
//
// None of this work is done here. The markdown grammar belongs to refract, so the code that
// owns the parser owns the surgery — every call below runs one of the scripts in
// player/tools/ and reports what it said. What this class is for is the wiring that used to
// sit in main: which tool, which arguments, where the deck is, and who to tell when it
// lands.
//
// Reads (a slide's text, the asset list) are synchronous: they are one short Python run and
// the answer is wanted now. Writes are not — refract takes seconds on a big deck, and a
// frozen window during a save would be the wrong trade — so they go through the EditRunner
// on a worker, and report back on the main thread once the deck has been reloaded.
#pragma once

#include "Asset.h"
#include "EditRunner.h"

#include <functional>
#include <string>
#include <vector>

namespace refract {

class DeckSource {
public:
    // What a finished write says: whether it worked, and a line to put in front of somebody.
    using Report = std::function<void(bool ok, const std::string& status)>;

    // Where the deck's generated files are — the directory holding deck.json. Empty until
    // this is called, and left empty for a zip bundle, which has no markdown behind it.
    void setOutDir(const std::string& outDir);
    bool available() const { return !mOutDir.empty(); }
    const std::string& outDir() const { return mOutDir; }
    // The deck itself: the directory the out/ one sits in.
    std::string deckDir() const;

    // A write is in flight. The deck must not be edited from two places at once, and the
    // build panel holds off its watch while one is running.
    bool running() const { return mEdits.running(); }
    void collect() { mEdits.collect(); }          // pumped from the main loop
    void join() { mEdits.join(); }

    // Called on the main thread when a write changed the deck on disk, with the outputs the
    // rebuild actually rewrote. This is what makes the player reload.
    void setOnChanged(std::function<void(std::vector<std::string>)> onChanged);
    // Where a finished block edit and a finished save are reported. One each, because there
    // is one deck view and one editor.
    void setOnEditFinished(Report report) { mOnEdit = std::move(report); }
    void setOnSaveFinished(Report report) { mOnSave = std::move(report); }

    // ── Block edits ──────────────────────────────────────────────────
    // Signatures match the deck view's callbacks exactly: the view decides which slide goes
    // where, this carries it to the tool that can do it.
    bool moveSlide(int from, int to, std::string* status);
    bool moveRun(const std::string& file, int first, int last, int dst, std::string* status);
    bool addSlide(int slide, bool before, std::string* status);
    bool duplicateSlide(int slide, std::string* status);
    bool mergeSlide(int slide, std::string* status);
    bool deleteSlide(int slide, std::string* status);
    bool undo(bool redo, std::string* status);

    // ── The editor's files ───────────────────────────────────────────
    // One slide's markdown. `shared` comes back as the number of slides that block produces,
    // which is what the editor warns about before rewriting it.
    bool readSlide(int slide, std::string* text, std::string* file, int* shared,
                   std::string* error);
    bool writeSlide(int slide, const std::string& text, std::string* error);
    // The same write, breaking the block in two at `line` — one rewrite, one history entry.
    bool splitSlide(int slide, const std::string& text, int line, std::string* error);
    // A whole file under the deck: slides.md end to end, or settings.toml.
    bool readFile(const std::string& path, std::string* text, std::string* error);
    bool writeFile(const std::string& path, const std::string& text, std::string* error);

    // ── Assets ───────────────────────────────────────────────────────
    // What is in includes/ and which slides use it. `deckDir` comes back with them: the
    // window reads the image files themselves to draw a thumbnail.
    bool scanAssets(std::vector<Asset>* out, std::string* deckDir, std::string* error);
    // Move one to out/.trash/. Refused by the tool while something uses it, unless forced —
    // the window asks first, and says what uses it.
    bool removeAsset(const std::string& path, bool force, std::string* status);

private:
    // Start a write, reload the deck when it lands, then call `report`.
    bool start(const std::string& tool, std::vector<std::string> args,
               std::string doneMessage, Report report, std::string* status);
    // The three saves all write the editor's text to a temp file first: a slide's markdown
    // has newlines and quotes in it and does not belong in an argument. The file outlives
    // the call — the worker is still reading it — and is removed when the job reports back.
    bool writeThroughTemp(const char* what, std::vector<std::string> args,
                          const std::string& text, const std::string& doneMessage,
                          std::string* error);

    EditRunner mEdits;
    std::string mOutDir;
    std::function<void(std::vector<std::string>)> mOnChanged;
    Report mOnEdit, mOnSave;
};

}  // namespace refract
