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
#include "TextBuffer.h"

#include <functional>
#include <memory>
#include <string>

struct GLFWwindow;

namespace refract {

class SlideEditor {
public:
    static std::unique_ptr<SlideEditor> Create(int width, int height);
    ~SlideEditor();

    GLFWwindow* window() const { return mWindow; }
    bool shouldClose() const;

    // Fetch the markdown for a slide. Returns false and sets `error` when it cannot be read.
    using Loader = std::function<bool(int slide, std::string* text, std::string* file,
                                      int* sharedSlides, std::string* error)>;
    // Write it back and rebuild. True when the work was *started* — it runs off the main
    // thread, and saveFinished() says how it went. False means it never began.
    using Saver = std::function<bool(int slide, const std::string& text, std::string* error)>;

    void setLoader(Loader loader);
    void setSaver(Saver saver);

    // Show this slide's source. Does nothing while there are unsaved changes — the editor
    // holds its ground rather than throwing away an edit because the deck moved on.
    void showSlide(int slide);
    int  slide() const;
    bool dirty() const;

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

    struct Impl;
    std::unique_ptr<Impl> mImpl;
    GLFWwindow* mWindow = nullptr;
};

}  // namespace refract
