// The deck view: every slide at once, in a window of its own, and the one place the deck's
// *order* can be changed.
//
// Reordering here is not a player setting — it rewrites the markdown the deck was built
// from, moves the `---`-separated block behind the slide, and rebuilds. That is what makes
// the change stick: the next build, the PDF, the web export and anyone else's checkout all
// see the new order.
//
// What moves is a source block, not a slide. refract expands one block into several slides
// (bullet fragments, scroll pages, staggered embeds), and those only make sense in sequence,
// so they are shown as a group and travel together. A deck built without that provenance —
// an older deck.json, a zip bundle, a hand-assembled directory — is still browsable here,
// just not reorderable.
#pragma once

#include "App.h"

#include "include/core/SkRefCnt.h"

#include <functional>
#include <memory>
#include <string>

struct GLFWwindow;

namespace refract {

class DeckViewWindow {
public:
    static std::unique_ptr<DeckViewWindow> Create(int width, int height);
    ~DeckViewWindow();

    GLFWwindow* window() const { return mWindow; }
    bool shouldClose() const;

    // Jump the deck to a slide — a double-click, or Enter on the cursor.
    void setOnOpenSlide(std::function<void(int)> action);

    // Move the slide at `from` so it ends up at `to`, in deck order, by rewriting the
    // markdown and rebuilding. True when the work was *started* — it runs off the main
    // thread, and editFinished() says how it went. False means it never began, and `status`
    // says why.
    void setOnMoveSlide(std::function<bool(int from, int to, std::string* status)> action);

    // Add an empty slide after `slide` (or before it), or remove the block `slide` came
    // from. Same contract as the moves: true when the work was started.
    void setOnAddSlide(std::function<bool(int slide, bool before, std::string* status)> action);
    void setOnDeleteSlide(std::function<bool(int slide, std::string* status)> action);

    // The rewrite this view asked for has finished and the deck has been reloaded.
    void editFinished(bool ok, const std::string& status);

    // Move a whole run — an included sub-deck, or a section — by lifting the block range
    // `first..last` out of `file` and putting it back starting at `dst`. Same contract as
    // setOnMoveSlide: true when the deck was rebuilt and reloaded.
    void setOnMoveRun(std::function<bool(const std::string& file, int first, int last, int dst,
                                         std::string* status)> action);

    // Keys the view claims. False for anything it does not want, so the caller can fall
    // through to the player's bindings and drive the talk from this window too.
    bool handleKey(int key, int action, int mods);

    void render(App& app);

private:
    DeckViewWindow() = default;

    // Apply a drag: move the group holding `slide` so that it lands before group `drop`.
    void commitDrag(int slide, int drop);
    // Apply a drag of a run's grip bar.
    void commitRunDrag(int bar, int atChunk, bool after);
    // Step the cursor's group one place earlier (-1) or later (+1).
    void nudge(int delta);
    // The same, for the whole run the cursor is in — the keyboard's grip bar.
    void nudgeRun(int delta);
    // Fold or unfold the run the cursor is in; and everything, in either direction.
    void foldAtCursor();
    void foldAll(bool shut);
    bool allFolded() const;

    struct Impl;
    std::unique_ptr<Impl> mImpl;
    GLFWwindow* mWindow = nullptr;
};

}  // namespace refract
