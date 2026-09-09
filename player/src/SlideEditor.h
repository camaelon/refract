// The slide editor: the markdown behind the slide on screen, editable, in a window.
//
// A slide is one `---`-separated block of a slides.md, and deck.json records which. So this
// asks for that block, lets it be edited, hands it back, and the deck is rebuilt around it —
// the same loop the deck view uses for reordering, with text instead of position.
//
// It edits a *block*, not a slide: refract expands one block into several rendered slides (a
// stepped bullet list is one block and four slides), so editing any of them edits the source
// they share. The header says so when that is the case.
#pragma once

#include "App.h"
#include "Asset.h"
#include "TextBuffer.h"

#include <functional>
#include <memory>
#include <string>

struct GLFWwindow;

namespace refract {

// What the editor is pointed at. A slide is one `---`-separated block and follows the deck;
// the other two are whole files and stay where they are put.
enum class EditTarget { Slide, Deck, Settings };

class SlideEditor {
public:
    static std::unique_ptr<SlideEditor> Create(int width, int height);
    ~SlideEditor();

    GLFWwindow* window() const { return mWindow; }
    bool shouldClose() const;

    // Being scrolled right now. Drawing a panel at twenty frames a second is fine for a
    // clock and wrong for a moving list — the distance is right and the picture arrives in
    // steps, which is what "slow scrolling" usually turns out to mean. The loop draws it
    // every frame while this is true.
    bool scrolling() const;

    // Fetch the markdown for a slide. Returns false and sets `error` when it cannot be read.
    using Loader = std::function<bool(int slide, std::string* text, std::string* file,
                                      int* sharedSlides, std::string* error)>;
    // The same for a whole file under the deck, by its path relative to it.
    using FileLoader = std::function<bool(const std::string& path, std::string* text,
                                          std::string* error)>;
    using FileSaver = std::function<bool(const std::string& path, const std::string& text,
                                         std::string* error)>;
    // Write it back and rebuild. True when the work was *started* — it runs off the main
    // thread, and saveFinished() says how it went. False means it never began.
    using Saver = std::function<bool(int slide, const std::string& text, std::string* error)>;

    void setLoader(Loader loader);
    void setSaver(Saver saver);

    // Break this slide in two at `line`, applying `text` first — so a slide can be split
    // while it still has unsaved changes, as one edit rather than a save and then a split.
    using Splitter = std::function<bool(int slide, const std::string& text, int line,
                                        std::string* error)>;
    void setSplitter(Splitter splitter);
    void setFileAccess(FileLoader loader, FileSaver saver);

    // What can go between `<` and `>`. Typing an include and pausing offers the deck's
    // assets — the names are the thing nobody remembers, and getting one wrong is a slide
    // that builds and renders nothing.
    using AssetLister = std::function<bool(std::vector<Asset>* out, std::string* deckDir,
                                           std::string* error)>;
    void setAssetLister(AssetLister lister);
    // Ask for the list again. Done when the editor opens and after a rebuild rather than
    // when the menu is wanted: the scan runs a script, and a pause between the keystroke
    // and the menu is exactly where that would be felt.
    void refreshAssets();

    // Point the editor at a slide, the whole of slides.md, or settings.toml. Refused while
    // there are unsaved changes: the buffer belongs to what it was opened on.
    void setTarget(EditTarget target);
    EditTarget target() const;

    // Show this slide's source. Does nothing while there are unsaved changes — the editor
    // holds its ground rather than throwing away an edit because the deck moved on.
    void showSlide(int slide);
    int  slide() const;
    bool dirty() const;

    // Whether saving happens on its own once typing stops. Remembered between runs.
    bool autoSave() const;
    void setAutoSave(bool on);

    // The save this editor asked for has finished and the deck has been rebuilt.
    void saveFinished(bool ok, const std::string& status);

    // Called after a successful save, once the deck has been rebuilt.
    void setOnSaved(std::function<void()> action);

    bool handleKey(int key, int action, int mods);
    void handleChar(unsigned int codepoint);
    void render(App& app);

private:
    SlideEditor() = default;

    void save();
    void revert();
    // Put the chosen asset in the brackets: the name replaces whatever has been typed since
    // the `<`, and the `>` is added, because an unclosed include is not one.
    void acceptCompletion(int match);

    struct Impl;
    std::unique_ptr<Impl> mImpl;
    GLFWwindow* mWindow = nullptr;
};

}  // namespace refract
