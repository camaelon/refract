#include "SlideEditor.h"

#include "Completion.h"
#include "Scrolling.h"
#include "Thumbs.h"
#include "Utf8.h"

#include "Ui.h"
#include "ViewGeometry.h"

#include "rcplayer/CpuRenderBackend.h"
#include "rcplayer/MediaTypes.h"
#include "rcplayer/Player.h"          // readFileBytes, for the preview beside the menu

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"
#include "include/core/SkData.h"
#include "include/core/SkFontMetrics.h"
#include "include/core/SkImage.h"
#include "include/core/SkPathBuilder.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <fstream>
#include <iostream>
#include <map>
#include <vector>

namespace refract {

namespace {

constexpr float kFontSize = 13.0f;
constexpr float kLineGap  = 4.0f;
constexpr float kGutterW  = 38.0f;    // line numbers
constexpr float kHeaderH  = 62.0f;
// How close together two clicks have to be to count as one gesture.
constexpr double kDoubleClickSec = 0.4;
constexpr float kFooterH  = 44.0f;

// The colours markdown is read by. Not a highlighter — refract's grammar is small enough that
// four rules cover it, and the point is to see the *structure* of a slide at a glance rather
// than to be a code editor.
SkColor lineTone(const std::string& text, bool inFence) {
    if (inFence) return ui::kDim;
    size_t i = 0;
    while (i < text.size() && (text[i] == ' ' || text[i] == '\t')) i++;
    const std::string body = text.substr(i);
    if (body.rfind("::", 0) == 0)  return ui::kInclude;   // the slide's meta line
    if (body.rfind("???", 0) == 0) return ui::kWarn;      // speaker notes
    if (body.rfind("===", 0) == 0 || body.rfind("+++", 0) == 0) return ui::kAccent;
    if (body.rfind("```", 0) == 0) return ui::kDim;
    if (body.rfind("#", 0) == 0)   return ui::kText;
    if (body.rfind("- ", 0) == 0 || body.rfind("<", 0) == 0) return ui::kAhead;
    return ui::kText;
}

// settings.toml is not markdown. Three rules cover it: a section, a key, and a comment.
SkColor tomlTone(const std::string& text) {
    size_t i = 0;
    while (i < text.size() && (text[i] == ' ' || text[i] == '\t')) i++;
    const std::string body = text.substr(i);
    if (body.rfind("#", 0) == 0) return ui::kDim;
    if (body.rfind("[", 0) == 0) return ui::kInclude;
    if (body.find('=') != std::string::npos) return ui::kText;
    return ui::kText;
}

bool togglesFence(const std::string& text) {
    size_t i = 0;
    while (i < text.size() && (text[i] == ' ' || text[i] == '\t')) i++;
    return text.compare(i, 3, "```") == 0;
}

}  // namespace

struct SlideEditor::Impl {
    CpuRenderBackend backend;
    int width = 0, height = 0;
    int fbWidth = 0, fbHeight = 0;

    TextBuffer buffer;
    int slide = -1;
    std::string file;
    int shared = 1;                  // rendered slides this block produces
    std::string status;
    bool statusError = false;
    bool saving = false;
    // Save on its own once typing stops, so the deck follows the editor without anybody
    // pressing anything. Off by default: a rebuild is a real thing to have happen, and it
    // should be asked for the first time.
    bool autoSave = false;
    double lastEditAt = -1.0;
    SkRect autoButton = SkRect::MakeEmpty();

    // ── Include completion ───────────────────────────────────────────
    // Typing `<` and pausing offers what can go in the brackets. The menu is worked out
    // from the text rather than remembered: backspace, an arrow key, a click and an undo
    // all move the caret out of an include, and a flag would have to be cleared by each of
    // them. Reading the line back costs nothing and cannot fall out of step.
    AssetLister assetLister;
    std::vector<Asset> assetList;
    std::string deckDir;                   // where the files are, for the preview
    std::vector<std::string> assetNames;   // as they would be written between < and >
    std::string namesFor;                  // the file assetNames was worked out for
    bool namesReady = false;               // ...and it has been, even if it found nothing
    bool menuOpen = false;
    // Open once the pause has been waited out, and *stay* open: every key goes through
    // handleKey, which restarts the idle clock, so a menu that re-tested the pause every
    // frame would blink out the moment you pressed the down arrow to walk it.
    bool menuLatched = false;
    Caret menuAnchor{-1, -1};              // the `<` the menu belongs to
    bool menuDismissed = false;            // escape was pressed on this one
    std::vector<int> menuMatches;          // indices into assetNames
    int menuPick = 0;
    int menuTop = 0;                       // first row drawn, for a list longer than the box
    SkRect menuRect = SkRect::MakeEmpty();
    float menuRowH = 0;
    float menuListW = 0;                   // the names' half of it, for hit-testing
    // Decoded previews, by path, and the opening lines of the ones that are text. Only the
    // asset under the cursor is ever read, so walking a folder of 4K screenshots costs one
    // decode per row you stop on rather than all of them at once.
    std::map<std::string, sk_sp<SkImage>> previews;
    std::map<std::string, std::string> excerpts;

    Loader loader;
    Saver  saver;
    Splitter splitter;
    FileLoader fileLoader;
    FileSaver  fileSaver;
    EditTarget target = EditTarget::Slide;
    // The tabs, set while drawing and hit-tested on a click.
    SkRect tabs[3];
    std::function<void()> onSaved;

    float scrollY = 0.0f, scrollX = 0.0f;
    double mouseX = 0, mouseY = 0;
    SkRect saveButton = SkRect::MakeEmpty();
    SkRect revertButton = SkRect::MakeEmpty();
    bool dragging = false;          // the pointer is sweeping out a selection
    // Successive clicks in the same place take more each time: a word, then the line, then
    // the paragraph, then back to a plain caret.
    int    clickCount = 0;
    double lastClickAt = -1.0;
    float  lastClickX = 0, lastClickY = 0;
    double caretBlinkFrom = 0.0;
    // Set when the caret is *moved* — typed at, arrowed, clicked — and cleared by the
    // render that scrolls to it. Following it on every frame instead would put the view
    // back on the caret the moment the wheel moved it away, which reads as a window that
    // will not scroll.
    bool followCaret = true;
    double lastScrollAt = -1.0;      // for the full-rate redraw while it is moving

    // Set while drawing, so a click can be turned into a caret position.
    float textLeft = 0, textTop = 0, lineHeight = 0;
    SkFont mono = uiMonoFont(kFontSize);

    void setStatus(const std::string& text, bool error) { status = text; statusError = error; }

    // The include being typed, if one is. Read back from the line rather than remembered:
    // backspace, an arrow key, a click and an undo all move the caret out of one, and a flag
    // would have to be cleared by every one of them.
    Include includeAt() const {
        const Caret c = buffer.caret();
        return refract::includeAt(buffer.line(c.line), c.col);
    }

    // The names, in the shape the file being edited would have to write them. Recomputed
    // when the editor is pointed somewhere else: a sub-deck's slide names its own assets.
    void namesForFile() {
        if (namesReady && namesFor == file) return;
        namesFor = file;
        namesReady = true;
        std::vector<std::string> paths;
        paths.reserve(assetList.size());
        for (const Asset& asset : assetList) paths.push_back(asset.path);
        assetNames = namesUnder(paths, includeBase(file));
    }

    // The asset a menu row stands for. Looked up rather than derived — the tool already
    // decided what kind each file is and how big it is.
    const Asset* assetFor(const std::string& name) const {
        const std::string path = includeBase(file) + name;
        for (const Asset& asset : assetList) {
            if (asset.path == path) return &asset;
        }
        return nullptr;
    }

    sk_sp<SkImage> preview(const std::string& relative) {
        auto it = previews.find(relative);
        if (it != previews.end()) return it->second;
        sk_sp<SkImage> image;
        std::vector<uint8_t> bytes;
        if (!deckDir.empty()
            && rcplayer::readFileBytes(deckDir + "/" + relative, bytes) && !bytes.empty()) {
            image = SkImages::DeferredFromEncodedData(
                SkData::MakeWithCopy(bytes.data(), bytes.size()));
        }
        previews[relative] = image;   // a null is remembered too: it failed once, it will again
        return image;
    }

    // What the still worker can turn into a picture: a RemoteCompose document — the thing
    // this deck is mostly made of — and a clip, which contributes its first frame. Both are
    // rendered rather than described; see the preview pane.
    static bool renderable(const std::string& name) {
        const size_t dot = name.rfind('.');
        if (dot == std::string::npos) return false;
        std::string ext = name.substr(dot);
        for (char& c : ext) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        return ext == ".rc" || ext == ".rcd" || ext == ".json"
               || rcplayer::isCodecVideoExt(ext) || rcplayer::isAvfVideoExt(ext);
    }

    // A clip. Its frame is a real picture of a real size, unlike a document's still, which
    // is square because the pane is.
    static bool clip(const std::string& name) {
        const size_t dot = name.rfind('.');
        if (dot == std::string::npos) return false;
        std::string ext = name.substr(dot);
        for (char& c : ext) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        return rcplayer::isCodecVideoExt(ext) || rcplayer::isAvfVideoExt(ext);
    }

    // The path the still worker knows a document by: an absolute one, since it reads the
    // file itself.
    std::string fullPath(const std::string& relative) const {
        return deckDir.empty() ? std::string() : deckDir + "/" + relative;
    }

    // Whether the pane can show the file's own text. A .rc is a *compiled* document — its
    // bytes say nothing to anybody — so it is not on the list even though it is a document.
    static bool textual(const std::string& name) {
        const size_t dot = name.rfind('.');
        if (dot == std::string::npos) return false;
        std::string ext = name.substr(dot);
        for (char& c : ext) c = static_cast<char>(std::tolower(static_cast<unsigned char>(c)));
        for (const char* known : {".json", ".md", ".toml", ".sksl", ".txt", ".csv", ".xml",
                                  ".kt", ".kts", ".java", ".py", ".ts", ".js"}) {
            if (ext == known) return true;
        }
        return false;
    }

    // The opening of a text asset, enough to fill the pane and no more.
    //
    // Read as a fixed block rather than line by line: a minified .json is one line of
    // several megabytes, and getline would pull all of it into memory to show sixty
    // characters of it. Lines are cut at a code-point boundary — half a character is not
    // valid UTF-8, and Skia's answer to invalid UTF-8 is to abort the process.
    const std::string& excerpt(const std::string& relative) {
        auto it = excerpts.find(relative);
        if (it != excerpts.end()) return it->second;
        std::string text;
        if (!deckDir.empty()) {
            std::ifstream file(deckDir + "/" + relative, std::ios::binary);
            char block[4096];
            file.read(block, sizeof(block));
            const std::string head(block, static_cast<size_t>(file.gcount()));
            size_t at = 0;
            for (int i = 0; i < 8 && at < head.size(); i++) {
                size_t end = head.find('\n', at);
                if (end == std::string::npos) end = head.size();
                const size_t stop = utf8Boundary(head, std::min(end, at + 60));
                std::string line = head.substr(at, stop - at);
                if (!line.empty() && line.back() == '\r') line.pop_back();
                // A tab or a stray control byte would draw as tofu or nothing at all.
                for (char& c : line) {
                    if (static_cast<unsigned char>(c) < 0x20) c = ' ';
                }
                text += displayable(line);
                text += '\n';
                at = end + 1;
            }
        }
        return excerpts.emplace(relative, std::move(text)).first->second;
    }

    // The caret position under a point in the window.
    Lines lineGeometry() const { return {textTop, lineHeight, kLineGap}; }

    Caret caretAt(float x, float y) const {
        // The line mapping is in ViewGeometry, tested without a window: `textTop` is line 0's
        // *baseline*, its box starts a line higher, and measuring from the wrong one put
        // every click a line above where it was aimed.
        const int line = lineAt(lineGeometry(), y, scrollY, buffer.lineCount());
        return {line, columnAt(buffer.line(line), x)};
    }

    // The byte column in `line` nearest to an x in window coordinates. Measured prefix by
    // prefix rather than divided by a character width: the fallback face may not be mono.
    int columnAt(const std::string& text, float x) const {
        const float from = textLeft - scrollX;
        int best = 0;
        float bestDist = std::fabs(x - from);
        for (size_t i = 1; i <= text.size(); i++) {
            if (i < text.size() && (static_cast<unsigned char>(text[i]) & 0xC0) == 0x80) continue;
            const float at = from + textWidth(mono, text.substr(0, i));
            const float dist = std::fabs(x - at);
            if (dist < bestDist) { bestDist = dist; best = static_cast<int>(i); }
        }
        return best;
    }
};

std::unique_ptr<SlideEditor> SlideEditor::Create(int width, int height) {
    GLFWwindow* previous = glfwGetCurrentContext();

    glfwWindowHint(GLFW_DECORATED, GLFW_TRUE);
    glfwWindowHint(GLFW_TRANSPARENT_FRAMEBUFFER, GLFW_FALSE);
    glfwWindowHint(GLFW_FLOATING, GLFW_FALSE);
    glfwWindowHint(GLFW_FOCUSED, GLFW_TRUE);
    glfwWindowHint(GLFW_FOCUS_ON_SHOW, GLFW_TRUE);
    GLFWwindow* window = glfwCreateWindow(width, height, "refract — slide", nullptr, nullptr);
    if (!window) {
        std::cerr << "slide editor: window creation failed\n";
        if (previous) glfwMakeContextCurrent(previous);
        return nullptr;
    }

    auto editor = std::unique_ptr<SlideEditor>(new SlideEditor());
    editor->mWindow = window;
    editor->mImpl = std::make_unique<Impl>();

    glfwSetWindowUserPointer(window, editor.get());
    glfwSetCursorPosCallback(window, [](GLFWwindow* w, double x, double y) {
        auto* self = static_cast<SlideEditor*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        Impl& impl = *self->mImpl;
        impl.mouseX = x;
        impl.mouseY = y;
        // Sweeping out a selection. The mode was decided at the press, so an option-drag
        // stays a rectangle even if the key is released half way.
        if (impl.dragging && impl.lineHeight > 0) {
            impl.buffer.setCaret(impl.caretAt(static_cast<float>(x), static_cast<float>(y)),
                                 /*select=*/true);
            impl.followCaret = true;
            impl.caretBlinkFrom = glfwGetTime();
        }
    });
    glfwSetScrollCallback(window, [](GLFWwindow* w, double dx, double dy) {
        auto* self = static_cast<SlideEditor*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        self->mImpl->scrollY =
            std::max(0.0f, self->mImpl->scrollY - scrollPixels(dy, self->mImpl->lineHeight));
        self->mImpl->scrollX =
            std::max(0.0f, self->mImpl->scrollX - scrollPixels(dx, 0.5f * self->mImpl->lineHeight));
        self->mImpl->lastScrollAt = glfwGetTime();
    });
    glfwSetMouseButtonCallback(window, [](GLFWwindow* w, int button, int action, int mods) {
        auto* self = static_cast<SlideEditor*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl || button != GLFW_MOUSE_BUTTON_LEFT) return;
        Impl& impl = *self->mImpl;
        if (action == GLFW_RELEASE) {
            impl.dragging = false;
            return;
        }
        if (action != GLFW_PRESS) return;
        const float x = static_cast<float>(impl.mouseX), y = static_cast<float>(impl.mouseY);
        for (int i = 0; i < 3; i++) {
            if (!impl.tabs[i].contains(x, y)) continue;
            self->setTarget(i == 0 ? EditTarget::Slide
                                   : i == 1 ? EditTarget::Deck : EditTarget::Settings);
            return;
        }
        // The menu is over the text, so it is asked first: a click in it is a choice, not
        // somewhere to put the caret.
        if (impl.menuOpen && impl.menuRect.contains(x, y) && impl.menuRowH > 0) {
            // Only the names are clickable. The preview beside them is something to look
            // at, and a click on it should not take whatever row it happens to be level
            // with — but it should not put the caret behind the menu either.
            if (x <= impl.menuRect.left() + impl.menuListW) {
                const int row = static_cast<int>((y - impl.menuRect.top() - 4) / impl.menuRowH);
                self->acceptCompletion(impl.menuTop + row);
            }
            return;
        }
        if (impl.autoButton.contains(x, y)) { impl.autoSave = !impl.autoSave; return; }
        if (impl.saveButton.contains(x, y)) { self->save(); return; }
        if (impl.revertButton.contains(x, y)) { self->revert(); return; }
        if (y < impl.textTop - impl.lineHeight || impl.lineHeight <= 0) return;

        // Option held makes whatever is swept out a rectangle rather than a run.
        impl.buffer.setBlockMode((mods & GLFW_MOD_ALT) != 0);
        // Shift-click extends, the way a shifted arrow does.
        const bool extending = (mods & GLFW_MOD_SHIFT) != 0;
        impl.buffer.setCaret(impl.caretAt(x, y), extending);
        impl.followCaret = true;
        impl.caretBlinkFrom = glfwGetTime();
        impl.lastEditAt = glfwGetTime();

        // A repeat click has to be in the same place as well as soon after: moving the
        // pointer to another word and clicking is two first clicks, not a double.
        const double now = glfwGetTime();
        const bool repeat = !extending && now - impl.lastClickAt < kDoubleClickSec
                            && std::fabs(x - impl.lastClickX) < 4
                            && std::fabs(y - impl.lastClickY) < 4;
        impl.clickCount = repeat ? impl.clickCount + 1 : 1;
        impl.lastClickAt = now;
        impl.lastClickX = x;
        impl.lastClickY = y;

        switch (impl.clickCount % 4) {
            case 2: impl.buffer.selectWord(); break;
            case 3: impl.buffer.selectLine(); break;
            case 0: impl.buffer.selectParagraph(); break;
            default: break;      // a single click is the caret, and starts a drag
        }
        // Only a plain click sweeps: a double-click followed by a twitch should keep the
        // word it just took rather than collapse it to a caret.
        impl.dragging = impl.clickCount % 4 == 1;
    });

    glfwMakeContextCurrent(window);
    glfwSwapInterval(0);
    editor->mImpl->backend.resize(width, height);
    editor->mImpl->width = width;
    editor->mImpl->height = height;

    if (previous) glfwMakeContextCurrent(previous);
    return editor;
}

SlideEditor::~SlideEditor() {
    if (mWindow) {
        GLFWwindow* previous = glfwGetCurrentContext();
        glfwMakeContextCurrent(mWindow);
        mImpl.reset();
        if (previous && previous != mWindow) glfwMakeContextCurrent(previous);
        glfwDestroyWindow(mWindow);
    }
}

bool SlideEditor::shouldClose() const {
    return mWindow && glfwWindowShouldClose(mWindow);
}

bool SlideEditor::scrolling() const {
    return mImpl && mImpl->lastScrollAt > 0
           && glfwGetTime() - mImpl->lastScrollAt < kScrollingFor;
}

void SlideEditor::setLoader(Loader loader) { mImpl->loader = std::move(loader); }
void SlideEditor::setSaver(Saver saver) { mImpl->saver = std::move(saver); }
void SlideEditor::setSplitter(Splitter splitter) { mImpl->splitter = std::move(splitter); }

void SlideEditor::setAssetLister(AssetLister lister) {
    mImpl->assetLister = std::move(lister);
}

void SlideEditor::refreshAssets() {
    Impl& impl = *mImpl;
    if (!impl.assetLister) return;
    std::vector<Asset> found;
    std::string dir, error;
    if (!impl.assetLister(&found, &dir, &error)) return;   // a zip bundle, or no deck
    impl.assetList = std::move(found);
    impl.deckDir = dir;
    // A rebuild may have replaced the file behind a name, so nothing about it is kept —
    // including the still the worker rendered from it.
    std::vector<std::string> stale;
    for (const Asset& asset : impl.assetList) stale.push_back(impl.fullPath(asset.path));
    dropThumbs(stale);
    impl.previews.clear();
    impl.excerpts.clear();
    impl.namesReady = false;     // the names are worked out again for whatever is open
    impl.assetNames.clear();
}

void SlideEditor::setFileAccess(FileLoader loader, FileSaver saver) {
    mImpl->fileLoader = std::move(loader);
    mImpl->fileSaver = std::move(saver);
}

EditTarget SlideEditor::target() const { return mImpl->target; }

namespace {
// What each target is called, and which file it is.
const char* targetLabel(EditTarget t) {
    switch (t) {
        case EditTarget::Deck: return "slides.md";
        case EditTarget::Settings: return "settings.toml";
        default: return "slide";
    }
}
const char* targetPath(EditTarget t) {
    return t == EditTarget::Settings ? "settings.toml" : "slides.md";
}
}  // namespace

void SlideEditor::setTarget(EditTarget target) {
    Impl& impl = *mImpl;
    if (target == impl.target) return;
    if (impl.buffer.dirty()) {
        impl.setStatus("save or revert before moving to " + std::string(targetLabel(target)),
                       true);
        return;
    }
    impl.target = target;
    impl.slide = -1;          // so a later showSlide reloads rather than seeing no change
    if (target == EditTarget::Slide) {
        impl.buffer.setText("");
        impl.file.clear();
        return;
    }
    std::string text, error;
    if (impl.fileLoader && impl.fileLoader(targetPath(target), &text, &error)) {
        impl.file = targetPath(target);
        impl.shared = 1;
        impl.buffer.setText(text);
        impl.scrollX = impl.scrollY = 0;
        impl.setStatus("", false);
    } else {
        impl.buffer.setText("");
        impl.setStatus(error.empty() ? "cannot read that file" : error, true);
    }
}
void SlideEditor::setOnSaved(std::function<void()> action) { mImpl->onSaved = std::move(action); }

int  SlideEditor::slide() const { return mImpl->slide; }
bool SlideEditor::autoSave() const { return mImpl->autoSave; }
void SlideEditor::setAutoSave(bool on) { mImpl->autoSave = on; }
bool SlideEditor::dirty() const { return mImpl->buffer.dirty(); }

void SlideEditor::showSlide(int slide) {
    Impl& impl = *mImpl;
    if (impl.target != EditTarget::Slide) return;   // a whole file does not follow the deck
    if (slide == impl.slide) return;
    // An unsaved edit is not thrown away because the deck moved on. The editor stays on the
    // slide being edited and says so; the player's own guard stops the deck moving at all
    // while that is true, so this is the second line of defence rather than the first.
    if (impl.buffer.dirty()) return;
    if (!impl.loader) return;

    std::string text, file, error;
    int shared = 1;
    if (!impl.loader(slide, &text, &file, &shared, &error)) {
        impl.slide = slide;
        impl.file.clear();
        impl.buffer.setText("");
        impl.setStatus(error.empty() ? "this slide has no editable source" : error, true);
        return;
    }
    impl.slide = slide;
    impl.file = file;
    impl.shared = std::max(1, shared);
    impl.buffer.setText(text);
    impl.scrollX = impl.scrollY = 0;
    impl.setStatus("", false);
}

void SlideEditor::revert() {
    Impl& impl = *mImpl;
    if (impl.target != EditTarget::Slide) {
        const EditTarget target = impl.target;
        impl.target = EditTarget::Slide;    // force setTarget to reload it
        impl.buffer.markClean();
        setTarget(target);
        impl.setStatus("reverted", false);
        return;
    }
    const int slide = impl.slide;
    impl.slide = -1;               // force showSlide to reload it
    impl.buffer.markClean();
    showSlide(slide);
    impl.setStatus("reverted", false);
}

void SlideEditor::save() {
    Impl& impl = *mImpl;
    if (impl.saving) return;
    if (impl.target == EditTarget::Slide && (!impl.saver || impl.slide < 0)) return;
    if (!impl.buffer.dirty()) {
        impl.setStatus("no changes", false);
        return;
    }
    std::string error;
    const bool ok = impl.target == EditTarget::Slide
        ? (impl.saver && impl.saver(impl.slide, impl.buffer.text(), &error))
        : (impl.fileSaver && impl.fileSaver(targetPath(impl.target), impl.buffer.text(),
                                            &error));
    if (!ok) {
        impl.setStatus(error.empty() ? "the save could not be started" : error, true);
        return;
    }
    // The rebuild takes seconds on a big deck and runs on another thread. The buffer is
    // marked clean now rather than on the way back: what was sent *is* what is being written,
    // and leaving it dirty would let the slide-change guard hold the deck for the whole
    // rebuild — for an edit that has already been handed over.
    impl.saving = true;
    impl.buffer.markClean();
    impl.setStatus("saving…", false);
}

void SlideEditor::acceptCompletion(int match) {
    Impl& impl = *mImpl;
    if (match < 0 || match >= static_cast<int>(impl.menuMatches.size())) return;
    const Include include = impl.includeAt();
    if (!include.found) return;
    const std::string name = impl.assetNames[impl.menuMatches[match]];

    // Select what has been typed since the `<` and type over it — one edit, one undo step,
    // and the same code path as any other insertion.
    const Caret caret = impl.buffer.caret();
    impl.buffer.setBlockMode(false);
    impl.buffer.setCaret({caret.line, include.start + 1}, /*select=*/false);
    impl.buffer.setCaret(caret, /*select=*/true);
    impl.buffer.insert(name + ">");
    impl.menuOpen = false;
    impl.caretBlinkFrom = glfwGetTime();
    impl.lastEditAt = glfwGetTime();
}

void SlideEditor::saveFinished(bool ok, const std::string& status) {
    Impl& impl = *mImpl;
    impl.saving = false;
    impl.setStatus(status, !ok);
    if (ok && impl.onSaved) impl.onSaved();
}

bool SlideEditor::handleKey(int key, int action, int mods) {
    if (action != GLFW_PRESS && action != GLFW_REPEAT) return false;
    Impl& impl = *mImpl;
    impl.caretBlinkFrom = glfwGetTime();
    impl.followCaret = true;      // a key either moves the caret or types at it
    impl.lastEditAt = glfwGetTime();

    // Command on macOS, Control elsewhere — whichever this platform's shortcuts use.
#if defined(__APPLE__)
    const bool cmd = (mods & GLFW_MOD_SUPER) != 0;
#else
    const bool cmd = (mods & GLFW_MOD_CONTROL) != 0;
#endif
    const bool shift = (mods & GLFW_MOD_SHIFT) != 0;
    // Option turns an extend into a frame — a rectangle down the lines, cut at the caret's
    // column, rather than a run through them. Live: it applies for as long as the key is
    // held, and letting go and extending again gives an ordinary selection back.
    impl.buffer.setBlockMode((mods & GLFW_MOD_ALT) != 0);

    // The completion menu, while it is up, takes the four keys that mean something to a
    // list and leaves the rest to the editor — typing goes on filtering it.
    if (impl.menuOpen && !cmd) {
        switch (key) {
            case GLFW_KEY_DOWN:
                impl.menuPick = std::min(impl.menuPick + 1,
                                         static_cast<int>(impl.menuMatches.size()) - 1);
                return true;
            case GLFW_KEY_UP:
                impl.menuPick = std::max(0, impl.menuPick - 1);
                return true;
            case GLFW_KEY_ENTER:
            case GLFW_KEY_KP_ENTER:
            case GLFW_KEY_TAB:
                acceptCompletion(impl.menuPick);
                return true;
            case GLFW_KEY_ESCAPE:
                // Dismissed for this `<` only: moving to another one offers again.
                impl.menuDismissed = true;
                impl.menuOpen = false;
                return true;
            default:
                break;      // everything else is still editing, and re-filters as it goes
        }
    }

    if (cmd) {
        switch (key) {
            case GLFW_KEY_S: save(); return true;
            case GLFW_KEY_ENTER:
            case GLFW_KEY_KP_ENTER: {
                // Break the slide here. The buffer goes with it, so a slide can be split
                // while it is still being edited — which is when you want to.
                if (!impl.splitter || impl.slide < 0 || impl.saving) return true;
                std::string error;
                if (!impl.splitter(impl.slide, impl.buffer.text(), impl.buffer.caret().line,
                                   &error)) {
                    impl.setStatus(error.empty() ? "cannot split here" : error, true);
                    return true;
                }
                impl.saving = true;
                impl.buffer.markClean();
                impl.setStatus("splitting…", false);
                return true;
            }
            case GLFW_KEY_A: impl.buffer.selectAll(); return true;
            case GLFW_KEY_Z:
                if (shift) impl.buffer.redo(); else impl.buffer.undo();
                return true;
            case GLFW_KEY_C:
            case GLFW_KEY_X: {
                const std::string picked = impl.buffer.selectedText();
                if (!picked.empty()) glfwSetClipboardString(mWindow, picked.c_str());
                if (key == GLFW_KEY_X && !picked.empty()) impl.buffer.deleteSelection();
                return true;
            }
            case GLFW_KEY_V: {
                if (const char* text = glfwGetClipboardString(mWindow)) impl.buffer.insert(text);
                return true;
            }
            // The Mac's own bindings: command for the ends of the line and the document.
            case GLFW_KEY_UP:   impl.buffer.moveDocStart(shift); return true;
            case GLFW_KEY_DOWN: impl.buffer.moveDocEnd(shift); return true;
            case GLFW_KEY_LEFT: impl.buffer.moveHome(shift); return true;
            case GLFW_KEY_RIGHT: impl.buffer.moveEnd(shift); return true;
            default: return true;   // no other command key belongs to the player either
        }
    }

    // Option and a plain arrow steps a word, as it does everywhere else on the platform.
    // With shift it is the frame extend instead — option means "by column" there, and the
    // two never overlap because one of them needs shift and the other must not have it.
    const bool word = (mods & GLFW_MOD_ALT) != 0 && !shift;

    switch (key) {
        case GLFW_KEY_LEFT:
            if (word) impl.buffer.moveWordLeft(false); else impl.buffer.moveLeft(shift);
            return true;
        case GLFW_KEY_RIGHT:
            if (word) impl.buffer.moveWordRight(false); else impl.buffer.moveRight(shift);
            return true;
        case GLFW_KEY_UP:        impl.buffer.moveUp(shift); return true;
        case GLFW_KEY_DOWN:      impl.buffer.moveDown(shift); return true;
        case GLFW_KEY_HOME:      impl.buffer.moveHome(shift); return true;
        case GLFW_KEY_END:       impl.buffer.moveEnd(shift); return true;
        case GLFW_KEY_PAGE_UP:
        case GLFW_KEY_PAGE_DOWN: {
            const int step = std::max(1, static_cast<int>((impl.height - kHeaderH - kFooterH)
                                                          / std::max(1.0f, impl.lineHeight)));
            for (int i = 0; i < step; i++) {
                if (key == GLFW_KEY_PAGE_UP) impl.buffer.moveUp(shift);
                else impl.buffer.moveDown(shift);
            }
            return true;
        }
        case GLFW_KEY_BACKSPACE: impl.buffer.backspace(); return true;
        case GLFW_KEY_DELETE:    impl.buffer.del(); return true;
        case GLFW_KEY_ENTER:
        case GLFW_KEY_KP_ENTER:  impl.buffer.newline(); return true;
        case GLFW_KEY_TAB:       impl.buffer.indent(); return true;
        case GLFW_KEY_ESCAPE:
            // Esc closes a clean editor and clears the status of a dirty one. Losing an edit
            // to a stray Esc is the one thing an editor must never do.
            if (impl.buffer.dirty()) impl.setStatus("unsaved changes — save, or revert", true);
            else glfwSetWindowShouldClose(mWindow, GLFW_TRUE);
            return true;
        default:
            // Every other key belongs to the editor too while it has focus: "b" is a letter
            // here, not the blank-the-projector binding.
            return true;
    }
}

void SlideEditor::handleChar(unsigned int codepoint) {
    // GLFW hands over a codepoint; the buffer stores UTF-8.
    std::string utf8;
    if (codepoint < 0x80) {
        utf8 += static_cast<char>(codepoint);
    } else if (codepoint < 0x800) {
        utf8 += static_cast<char>(0xC0 | (codepoint >> 6));
        utf8 += static_cast<char>(0x80 | (codepoint & 0x3F));
    } else if (codepoint < 0x10000) {
        utf8 += static_cast<char>(0xE0 | (codepoint >> 12));
        utf8 += static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F));
        utf8 += static_cast<char>(0x80 | (codepoint & 0x3F));
    } else {
        utf8 += static_cast<char>(0xF0 | (codepoint >> 18));
        utf8 += static_cast<char>(0x80 | ((codepoint >> 12) & 0x3F));
        utf8 += static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F));
        utf8 += static_cast<char>(0x80 | (codepoint & 0x3F));
    }
    mImpl->buffer.insert(utf8);
    mImpl->followCaret = true;
    mImpl->caretBlinkFrom = glfwGetTime();
    mImpl->lastEditAt = glfwGetTime();
}

void SlideEditor::render(App& app) {
    if (!mWindow || !mImpl) return;
    Impl& impl = *mImpl;
    glfwMakeContextCurrent(mWindow);

    int w = 0, h = 0;
    glfwGetWindowSize(mWindow, &w, &h);
    if (w <= 0 || h <= 0) return;
    if (w != impl.width || h != impl.height) {
        impl.backend.resize(w, h);
        impl.width = w;
        impl.height = h;
    }
    int fbW = 0, fbH = 0;
    glfwGetFramebufferSize(mWindow, &fbW, &fbH);
    if (fbW != impl.fbWidth || fbH != impl.fbHeight) {
        impl.backend.onFramebufferResize(fbW, fbH);
        impl.fbWidth = fbW;
        impl.fbHeight = fbH;
    }

    // The include menu. Half a second after the last keystroke, so it follows a pause
    // rather than interrupting a word — and short enough that pausing on purpose to ask
    // "what have I got?" is answered straight away.
    constexpr double kIncludeIdleSec = 0.5;
    {
        // `<>` is markdown's include; settings.toml has no such thing, so nothing is offered
        // there rather than something of the wrong shape.
        const bool markdown = impl.target != EditTarget::Settings;
        const Include include = impl.includeAt();
        if (markdown && !impl.assetList.empty() && include.found) {
            impl.namesForFile();
            const Caret anchor{impl.buffer.caret().line, include.start};
            if (anchor != impl.menuAnchor) {
                // A different `<`: whatever was decided about the last one does not apply.
                impl.menuAnchor = anchor;
                impl.menuDismissed = false;
                impl.menuLatched = false;
                impl.menuPick = 0;
                impl.menuTop = 0;
            }
            impl.menuMatches = matchNames(impl.assetNames, include.prefix);
            impl.menuPick = std::max(0, std::min(impl.menuPick,
                                                 static_cast<int>(impl.menuMatches.size()) - 1));
            if (!impl.menuLatched && glfwGetTime() - impl.lastEditAt >= kIncludeIdleSec) {
                impl.menuLatched = true;
            }
            // A prefix nothing matches hides the list without unlatching it: deleting back
            // to something that does match brings it straight back, with no second pause.
            impl.menuOpen = impl.menuLatched && !impl.menuDismissed
                            && !impl.menuMatches.empty();
        } else {
            impl.menuOpen = false;
            impl.menuLatched = false;
            impl.menuAnchor = {-1, -1};
            impl.menuDismissed = false;
            impl.menuMatches.clear();
        }
        if (!impl.menuOpen) impl.menuRect = SkRect::MakeEmpty();
    }

    // Saved once typing has stopped for a moment. The pause is what makes it feel like the
    // deck is keeping up rather than like something is running while you type.
    constexpr double kAutoSaveIdleSec = 1.2;
    if (impl.autoSave && impl.buffer.dirty() && !impl.saving && impl.lastEditAt > 0
        && glfwGetTime() - impl.lastEditAt >= kAutoSaveIdleSec) {
        save();
    }

    SkCanvas* canvas = impl.backend.canvas();
    if (!canvas) return;
    canvas->clear(ui::kBg);

    const float pad = 16;
    SkFont mono = uiMonoFont(kFontSize);
    impl.mono = mono;
    SkFontMetrics metrics;
    mono.getMetrics(&metrics);
    const float lineHeight = std::round(-metrics.fAscent + metrics.fDescent + kLineGap);
    impl.lineHeight = lineHeight;
    impl.textLeft = pad + kGutterW;
    impl.textTop = kHeaderH + lineHeight;

    // ── Header ───────────────────────────────────────────────────────
    // Three things the editor can be pointed at, as tabs: this slide, the whole deck, and
    // the deck's settings. The theme was the last thing that still needed a terminal.
    static const struct { EditTarget target; const char* label; } kTabs[] = {
        {EditTarget::Slide, "slide"},
        {EditTarget::Deck, "slides.md"},
        {EditTarget::Settings, "settings.toml"},
    };
    SkFont tabFont = uiFont(12, true);
    float tabX = pad;
    for (int i = 0; i < 3; i++) {
        const bool on = impl.target == kTabs[i].target;
        const float tw = textWidth(tabFont, kTabs[i].label) + 20;
        impl.tabs[i] = SkRect::MakeXYWH(tabX, 12, tw, 24);
        const bool hot = impl.tabs[i].contains(static_cast<float>(impl.mouseX),
                                               static_cast<float>(impl.mouseY));
        fillRoundRect(canvas, impl.tabs[i], 12, on ? ui::kPanel : ui::kBg);
        strokeRoundRect(canvas, impl.tabs[i], 12,
                        on ? ui::kAccent : (hot ? ui::kDim : ui::kLine), 1.0f);
        drawTextCentred(canvas, kTabs[i].label, impl.tabs[i], tabFont,
                        on ? ui::kText : ui::kDim);
        tabX += tw + 6;
    }
    const std::string title = impl.target != EditTarget::Slide
        ? std::string()
        : (impl.slide >= 0
               ? "Slide " + std::to_string(impl.slide + 1) + " of "
                     + std::to_string(app.deck.size())
               : std::string("No slide"));
    float titleEnd = tabX + 10;
    if (!title.empty()) titleEnd += drawText(canvas, title, tabX + 10, 29, uiFont(13), ui::kDim);
    if (impl.buffer.dirty()) {
        drawText(canvas, "  edited", titleEnd, 29, uiFont(12), ui::kWarn);
    }
    std::string where = impl.file;
    if (impl.target == EditTarget::Slide && impl.shared > 1) {
        // Said out loud: editing any step of an expanded slide edits the source all of them
        // come from, and the surprise otherwise is finding four slides changed.
        where += "  —  one block, " + std::to_string(impl.shared) + " slides";
    }
    drawText(canvas, ellipsize(where, uiFont(11), w - pad * 2), pad, 44, uiFont(11), ui::kDim);
    fillRect(canvas, SkRect::MakeXYWH(0, kHeaderH - 1, w, 1), ui::kLine);

    // ── Text ─────────────────────────────────────────────────────────
    const float viewTop = kHeaderH, viewBottom = h - kFooterH;
    const float viewH = viewBottom - viewTop;

    // Bring the caret back into view whenever it has moved — typing must never run off the
    // bottom of the window. Only when it has moved, though: doing it every frame would undo
    // the wheel, and reading further down a slide than you are editing is a thing people do.
    const Caret caret = impl.buffer.caret();
    const float caretX = textWidth(mono, impl.buffer.line(caret.line).substr(0, caret.col));
    const float textW = w - impl.textLeft - pad;
    if (impl.followCaret) {
        impl.followCaret = false;
        impl.scrollY = scrollToShowLine(impl.lineGeometry(), caret.line, impl.scrollY, viewH);
        if (caretX < impl.scrollX) impl.scrollX = std::max(0.0f, caretX - 40);
        else if (caretX > impl.scrollX + textW - 20) impl.scrollX = caretX - textW + 40;
    }
    const float maxScroll = std::max(0.0f, impl.buffer.lineCount() * lineHeight - viewH
                                               + lineHeight * 2);
    impl.scrollY = std::max(0.0f, std::min(maxScroll, impl.scrollY));
    impl.scrollX = std::max(0.0f, impl.scrollX);

    canvas->save();
    canvas->clipRect(SkRect::MakeLTRB(0, viewTop, w, viewBottom));

    const auto [selFrom, selTo] = impl.buffer.selection();
    const bool selecting = impl.buffer.hasSelection();
    const bool framed = impl.buffer.blockSelection();
    // The frame's two edges, measured once: every line it crosses is cut at the same x, and
    // measuring per line would let a line with an accent in it bend the rectangle.
    //
    // Measured against the longest line the frame crosses, because a shorter one does not
    // reach the right-hand column and would draw the rectangle too narrow. (With a truly
    // monospaced face any line would do; the fallback face on a machine with no mono font
    // is not one, and this is what keeps the frame square there too.)
    float frameLeftX = 0, frameRightX = 0;
    if (framed) {
        const auto [left, right] = impl.buffer.blockColumns();
        int ruler = selFrom.line, longest = -1;
        for (int i = selFrom.line; i <= selTo.line; i++) {
            const int chars = impl.buffer.displayColumn(
                i, static_cast<int>(impl.buffer.line(i).size()));
            if (chars > longest) { longest = chars; ruler = i; }
        }
        const std::string& text = impl.buffer.line(ruler);
        frameLeftX = textWidth(mono, text.substr(0, impl.buffer.byteColumn(ruler, left)));
        frameRightX = textWidth(mono, text.substr(0, impl.buffer.byteColumn(ruler, right)));
    }
    SkFont gutterFont = uiMonoFont(kFontSize - 2);
    bool inFence = false;

    for (int i = 0; i < impl.buffer.lineCount(); i++) {
        const std::string& text = impl.buffer.line(i);
        const bool fenceLine = togglesFence(text);
        const SkColor tone = impl.target == EditTarget::Settings
                                 ? tomlTone(text)
                                 : lineTone(text, inFence && !fenceLine);
        if (fenceLine) inFence = !inFence;

        const float y = impl.textTop + i * lineHeight - impl.scrollY;
        if (y < viewTop - lineHeight || y > viewBottom + lineHeight) continue;

        if (i == caret.line && !selecting) {
            fillRect(canvas, SkRect::MakeLTRB(0, y - lineHeight + kLineGap, w, y + kLineGap),
                     ui::kPanel);
        }
        drawTextRight(canvas, std::to_string(i + 1), pad + kGutterW - 10, y, gutterFont,
                      i == caret.line ? ui::kDim : ui::kLine);

        // Selection, clipped to this line.
        if (selecting && i >= selFrom.line && i <= selTo.line) {
            const float top = y - lineHeight + kLineGap, bottom = y + kLineGap;
            if (framed) {
                // The frame is drawn over the whole column span, on every line it crosses —
                // that is what makes it read as a rectangle rather than as a run that
                // happens to be ragged. Where a line stops short there is nothing to take,
                // so that part is a wash rather than a selection.
                const auto [from, to] = impl.buffer.blockRangeOn(i);
                const float x0 = impl.textLeft - impl.scrollX + frameLeftX;
                const float x1 = impl.textLeft - impl.scrollX + frameRightX;
                fillRect(canvas, SkRect::MakeLTRB(x0, top, x1, bottom),
                         withAlpha(ui::kAccent, 0x1E));
                if (to > from) {
                    const float t0 = impl.textLeft - impl.scrollX
                                     + textWidth(mono, text.substr(0, from));
                    const float t1 = impl.textLeft - impl.scrollX
                                     + textWidth(mono, text.substr(0, to));
                    fillRect(canvas, SkRect::MakeLTRB(t0, top, t1, bottom),
                             withAlpha(ui::kAccent, 0x44));
                }
            } else {
                const int from = i == selFrom.line ? selFrom.col : 0;
                const int to = i == selTo.line ? selTo.col : static_cast<int>(text.size());
                const float x0 = impl.textLeft - impl.scrollX
                                 + textWidth(mono, text.substr(0, from));
                float x1 = impl.textLeft - impl.scrollX + textWidth(mono, text.substr(0, to));
                // A selected line break shows as a sliver past the end, so a multi-line
                // selection does not look like it stops at the last character.
                if (i < selTo.line) x1 += textWidth(mono, " ");
                fillRect(canvas, SkRect::MakeLTRB(x0, top, x1, bottom),
                         withAlpha(ui::kAccent, 0x44));
            }
        }

        drawText(canvas, text, impl.textLeft - impl.scrollX, y, mono, tone);
    }

    // The caret blinks from the last keystroke, so it is solid while you are typing.
    const double since = glfwGetTime() - impl.caretBlinkFrom;
    if (std::fmod(since, 1.06) < 0.6) {
        const float y = impl.textTop + caret.line * lineHeight - impl.scrollY;
        fillRect(canvas, SkRect::MakeLTRB(impl.textLeft - impl.scrollX + caretX,
                                          y - lineHeight + kLineGap,
                                          impl.textLeft - impl.scrollX + caretX + 1.5f,
                                          y + kLineGap),
                 ui::kAccent);
    }
    canvas->restore();

    // ── Footer ───────────────────────────────────────────────────────
    fillRect(canvas, SkRect::MakeXYWH(0, viewBottom, w, 1), ui::kLine);
    SkFont buttonFont = uiFont(12, true);

    impl.saveButton = SkRect::MakeXYWH(pad, viewBottom + 10, 82, 24);
    const bool canSave = impl.buffer.dirty() && !impl.saving;
    const bool saveHot = impl.saveButton.contains(static_cast<float>(impl.mouseX),
                                                  static_cast<float>(impl.mouseY));
    fillRoundRect(canvas, impl.saveButton, 12, canSave && saveHot ? ui::kAccent : ui::kPanel);
    strokeRoundRect(canvas, impl.saveButton, 12, canSave ? ui::kAccent : ui::kLine, 1.0f);
    drawTextCentred(canvas, impl.saving ? "saving…" : "Save", impl.saveButton, buttonFont,
                    canSave ? (saveHot ? ui::kBg : ui::kText) : ui::kDim);

    impl.revertButton = SkRect::MakeXYWH(pad + 92, viewBottom + 10, 76, 24);
    const bool revertHot = impl.revertButton.contains(static_cast<float>(impl.mouseX),
                                                      static_cast<float>(impl.mouseY));
    fillRoundRect(canvas, impl.revertButton, 12, ui::kPanel);
    strokeRoundRect(canvas, impl.revertButton, 12,
                    impl.buffer.dirty() && revertHot ? ui::kOver : ui::kLine, 1.0f);
    drawTextCentred(canvas, "Revert", impl.revertButton, buttonFont,
                    impl.buffer.dirty() ? ui::kText : ui::kDim);

    // Auto-save, as a toggle rather than a checkbox: it sits with the two buttons it acts
    // for, and its state is the whole label.
    SkFont autoFont = uiFont(11, true);
    const std::string autoLabel = impl.autoSave ? "auto-save on" : "auto-save";
    impl.autoButton = SkRect::MakeXYWH(pad + 176, viewBottom + 10,
                                       textWidth(autoFont, "auto-save on") + 20, 24);
    const bool autoHot = impl.autoButton.contains(static_cast<float>(impl.mouseX),
                                                  static_cast<float>(impl.mouseY));
    fillRoundRect(canvas, impl.autoButton, 12, impl.autoSave ? ui::kPanel : ui::kBg);
    strokeRoundRect(canvas, impl.autoButton, 12,
                    impl.autoSave ? ui::kAhead : (autoHot ? ui::kDim : ui::kLine), 1.0f);
    drawTextCentred(canvas, autoLabel, impl.autoButton, autoFont,
                    impl.autoSave ? ui::kAhead : ui::kDim);

    if (!impl.status.empty()) {
        const float from = impl.autoButton.right() + 14;
        drawText(canvas, ellipsize(impl.status, uiFont(12), w - pad - from - 90),
                 from, viewBottom + 26, uiFont(12),
                 impl.statusError ? ui::kOver : ui::kAhead);
    }
    drawTextRight(canvas, "cmd+S saves", w - pad, viewBottom + 26, uiFont(11), ui::kDim);

    // ── The include menu ─────────────────────────────────────────────
    // Drawn last so nothing is over it, and anchored to the `<` rather than to the caret:
    // it is a list of what could follow that bracket, and it should not slide sideways as
    // the name is typed.
    if (impl.menuOpen) {
        constexpr int kMaxRows = 8;
        const int rows = std::min<int>(kMaxRows, static_cast<int>(impl.menuMatches.size()));
        // Keep the pick in view when the list is longer than the box.
        impl.menuTop = std::min(impl.menuTop, impl.menuPick);
        impl.menuTop = std::max(impl.menuTop, impl.menuPick - rows + 1);
        impl.menuTop = std::max(0, std::min(impl.menuTop,
                                            static_cast<int>(impl.menuMatches.size()) - rows));

        SkFont rowFont = uiMonoFont(kFontSize - 1);
        SkFont kindFont = uiFont(10);
        const float rowH = std::round(kFontSize + 10);
        impl.menuRowH = rowH;

        float listW = 130;
        for (int i = 0; i < rows; i++) {
            const std::string& name = impl.assetNames[impl.menuMatches[impl.menuTop + i]];
            listW = std::max(listW, textWidth(rowFont, name)
                                        + textWidth(kindFont, "document") + 46);
        }
        // The menu is at least tall enough for the preview to be worth looking at. One
        // match is exactly when you most want to see the file before taking it, and a
        // 20-pixel square would be no answer at all.
        constexpr float kMinPane = 116;
        const float boxH = std::max(rows * rowH + 8, kMinPane + 8);
        // The preview is a square down the full height of the menu, beside the names — so it
        // grows with the list rather than sitting in a fixed well, and an image is shown as
        // large as the menu is tall. In an editor too narrow for both, the names win.
        const float paneSide = boxH - 8;
        const float room = w - pad * 2;
        const bool withPane = listW + paneSide + 10 <= room;
        const float boxW = std::min(withPane ? listW + paneSide + 10 : listW, room);

        const std::string& anchorLine = impl.buffer.line(impl.menuAnchor.line);
        const float anchorX = impl.textLeft - impl.scrollX
                              + textWidth(mono, anchorLine.substr(0, impl.menuAnchor.col));
        const float x = std::max(pad, std::min(anchorX, w - pad - boxW));
        const float lineBottom = impl.textTop + impl.menuAnchor.line * lineHeight
                                 - impl.scrollY + kLineGap;
        // Below the line it belongs to, unless there is no room — then above it, which is
        // what every other menu in the world does at the bottom of a screen.
        float y = lineBottom + 4;
        if (y + boxH > viewBottom) y = lineBottom - lineHeight - boxH - 2;
        y = std::max(viewTop + 2, y);

        impl.menuRect = SkRect::MakeXYWH(x, y, boxW, boxH);
        fillRoundRect(canvas, impl.menuRect, 8, ui::kPanel);
        strokeRoundRect(canvas, impl.menuRect, 8, ui::kAccent, 1.0f);

        const float rowsW = withPane ? boxW - paneSide - 10 : boxW;
        impl.menuListW = rowsW;
        for (int i = 0; i < rows; i++) {
            const int index = impl.menuMatches[impl.menuTop + i];
            const std::string& name = impl.assetNames[index];
            const SkRect row = SkRect::MakeXYWH(x + 4, y + 4 + i * rowH, rowsW - 8, rowH);
            const bool picked = impl.menuTop + i == impl.menuPick;
            const bool hot = row.contains(static_cast<float>(impl.mouseX),
                                          static_cast<float>(impl.mouseY));
            if (picked || hot) {
                fillRoundRect(canvas, row, 5,
                              picked ? withAlpha(ui::kAccent, 0x44) : withAlpha(ui::kBg, 0x60));
            }
            const float baseline = row.centerY() + kFontSize * 0.35f;
            const Asset* asset = impl.assetFor(name);
            const float kindW = asset ? textWidth(kindFont, asset->kind) + 14 : 8;
            drawText(canvas, ellipsize(name, rowFont, row.width() - kindW - 12),
                     row.left() + 8, baseline, rowFont, picked ? ui::kText : ui::kDim);
            if (asset && !asset->kind.empty()) {
                drawTextRight(canvas, asset->kind, row.right() - 8, baseline, kindFont,
                              ui::kLine);
            }
        }

        // ── The preview ──────────────────────────────────────────────
        // What the name under the cursor actually is: the picture for a picture, the opening
        // lines for anything that is text. The names alone are not enough to tell two
        // screenshots apart, which is most of what the folder is.
        if (withPane && impl.menuPick < static_cast<int>(impl.menuMatches.size())) {
            const std::string& name = impl.assetNames[impl.menuMatches[impl.menuPick]];
            const Asset* asset = impl.assetFor(name);
            const SkRect pane = SkRect::MakeXYWH(x + boxW - paneSide - 4, y + 4,
                                                 paneSide, paneSide);
            fillRoundRect(canvas, pane, 6, ui::kBg);
            strokeRoundRect(canvas, pane, 6, ui::kLine, 1.0f);

            // A strip along the bottom for what the picture cannot say: how big the file is,
            // and — once it has been decoded — how big the image is.
            const float stripH = 16;
            const SkRect art = SkRect::MakeLTRB(pane.left() + 4, pane.top() + 4,
                                                pane.right() - 4, pane.bottom() - stripH);
            std::string caption;
            // A document is rendered by the same engine that plays the deck, on the still
            // worker, and cached — so the pane shows the slide rather than its source. It
            // arrives a frame or two later; until then the pane says so.
            bool rendering = false;
            bool isPicture = false;          // a real image, whose own size is worth saying
            sk_sp<SkImage> image;
            if (asset && Impl::renderable(name)) {
                const int side = static_cast<int>(art.width());
                image = thumbIfReady(impl.fullPath(asset->path), side, side);
                rendering = !image;
                // A clip's frame is the clip's own size; a document's still is square
                // because the pane is, and saying so would be saying nothing.
                isPicture = image && Impl::clip(name);
                // The neighbours, unhurried, so arrowing through the list is instant.
                for (int step : {-1, 1}) {
                    const int at = impl.menuPick + step;
                    if (at < 0 || at >= static_cast<int>(impl.menuMatches.size())) continue;
                    const std::string& near = impl.assetNames[impl.menuMatches[at]];
                    if (!Impl::renderable(near)) continue;
                    if (const Asset* other = impl.assetFor(near)) {
                        requestThumb(impl.fullPath(other->path), side, side);
                    }
                }
            } else if (asset && asset->kind == "image") {
                image = impl.preview(asset->path);
                isPicture = image != nullptr;
            }
            if (image) {
                canvas->save();
                canvas->clipRect(art, true);
                const SkRect drawn = drawImageFit(canvas, image, art);
                // A frame out of a clip and a photograph are the same picture on the page,
                // so a clip is marked as one. Small, in the corner, over its own shade.
                if (Impl::clip(name)) {
                    const float r = 9;
                    const float cx = drawn.right() - r - 5, cy = drawn.bottom() - r - 5;
                    SkPaint disc;
                    disc.setAntiAlias(true);
                    disc.setColor(withAlpha(SK_ColorBLACK, 0xA0));
                    canvas->drawCircle(cx, cy, r, disc);
                    SkPathBuilder play;
                    play.moveTo(cx - 2.5f, cy - 4.5f);
                    play.lineTo(cx + 4.5f, cy);
                    play.lineTo(cx - 2.5f, cy + 4.5f);
                    play.close();
                    disc.setColor(SK_ColorWHITE);
                    canvas->drawPath(play.detach(), disc);
                }
                canvas->restore();
                if (isPicture) {
                    caption = std::to_string(image->width()) + " × "
                              + std::to_string(image->height());
                }
            } else if (rendering) {
                drawTextCentred(canvas, "rendering…", art, uiFont(11), ui::kLine);
            } else if (Impl::textual(name)) {
                const std::string& text = impl.excerpt(asset ? asset->path : name);
                SkFont small = uiMonoFont(9);
                float ty = art.top() + 10;
                size_t at = 0;
                canvas->save();
                canvas->clipRect(art, true);
                while (at < text.size() && ty < art.bottom()) {
                    const size_t end = text.find('\n', at);
                    const std::string line = text.substr(at, end - at);
                    drawText(canvas, ellipsize(line, small, art.width() - 8), art.left() + 4,
                             ty, small, ui::kDim);
                    if (end == std::string::npos) break;
                    at = end + 1;
                    ty += 11;
                }
                canvas->restore();
            } else {
                // A video, or a compiled .rc: nothing to draw, so it says what it is.
                drawTextCentred(canvas, asset ? asset->kind : "no preview", art,
                                uiFont(11, true), ui::kLine);
            }
            if (asset) {
                if (!caption.empty()) caption += "  ·  ";
                caption += humanBytes(asset->size);
            }
            if (!caption.empty()) {
                drawTextCentred(canvas, caption,
                                SkRect::MakeLTRB(pane.left(), pane.bottom() - stripH,
                                                 pane.right(), pane.bottom()),
                                uiFont(9), ui::kLine);
            }
        }

        // Said once, at the foot of the list: the two keys that finish the job.
        if (static_cast<int>(impl.menuMatches.size()) > rows) {
            if (impl.menuRect.bottom() + 16 < viewBottom) {
                drawTextRight(canvas,
                              std::to_string(impl.menuMatches.size() - rows) + " more",
                              impl.menuRect.right() - 8, impl.menuRect.bottom() + 13,
                              uiFont(10), ui::kLine);
            }
        }
        if (impl.menuRect.bottom() + 16 < viewBottom) {
            drawText(canvas, "↩ inserts  ·  esc dismisses", impl.menuRect.left(),
                     impl.menuRect.bottom() + 13, uiFont(10), ui::kLine);
        }
    }

    impl.backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
