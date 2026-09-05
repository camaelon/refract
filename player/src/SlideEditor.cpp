#include "SlideEditor.h"

#include "Ui.h"

#include "rcplayer/CpuRenderBackend.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"
#include "include/core/SkFontMetrics.h"

#include <algorithm>
#include <cmath>
#include <iostream>
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

    Loader loader;
    Saver  saver;
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

    // Set while drawing, so a click can be turned into a caret position.
    float textLeft = 0, textTop = 0, lineHeight = 0;
    SkFont mono = uiMonoFont(kFontSize);

    void setStatus(const std::string& text, bool error) { status = text; statusError = error; }

    // The caret position under a point in the window.
    Caret caretAt(float x, float y) const {
        // `textTop + i * lineHeight` is line i's *baseline*; its box runs from one line
        // higher. Measuring from the baseline put every click a line above where it was
        // aimed, which is the sort of thing you feel long before you can name it.
        const float top = textTop - lineHeight + kLineGap;
        const float row = (y - top + scrollY) / std::max(1.0f, lineHeight);
        const int line = std::max(0, std::min(buffer.lineCount() - 1,
                                              static_cast<int>(std::floor(row))));
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
            impl.caretBlinkFrom = glfwGetTime();
        }
    });
    glfwSetScrollCallback(window, [](GLFWwindow* w, double dx, double dy) {
        auto* self = static_cast<SlideEditor*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        self->mImpl->scrollY = std::max(0.0f, self->mImpl->scrollY - float(dy) * 40.0f);
        self->mImpl->scrollX = std::max(0.0f, self->mImpl->scrollX - float(dx) * 20.0f);
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
        if (impl.saveButton.contains(x, y)) { self->save(); return; }
        if (impl.revertButton.contains(x, y)) { self->revert(); return; }
        if (y < impl.textTop - impl.lineHeight || impl.lineHeight <= 0) return;

        // Option held makes whatever is swept out a rectangle rather than a run.
        impl.buffer.setBlockMode((mods & GLFW_MOD_ALT) != 0);
        // Shift-click extends, the way a shifted arrow does.
        const bool extending = (mods & GLFW_MOD_SHIFT) != 0;
        impl.buffer.setCaret(impl.caretAt(x, y), extending);
        impl.caretBlinkFrom = glfwGetTime();

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

void SlideEditor::setLoader(Loader loader) { mImpl->loader = std::move(loader); }
void SlideEditor::setSaver(Saver saver) { mImpl->saver = std::move(saver); }
void SlideEditor::setOnSaved(std::function<void()> action) { mImpl->onSaved = std::move(action); }

int  SlideEditor::slide() const { return mImpl->slide; }
bool SlideEditor::dirty() const { return mImpl->buffer.dirty(); }

void SlideEditor::showSlide(int slide) {
    Impl& impl = *mImpl;
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
    const int slide = impl.slide;
    impl.slide = -1;               // force showSlide to reload it
    impl.buffer.markClean();
    showSlide(slide);
    impl.setStatus("reverted", false);
}

void SlideEditor::save() {
    Impl& impl = *mImpl;
    if (!impl.saver || impl.slide < 0 || impl.saving) return;
    if (!impl.buffer.dirty()) {
        impl.setStatus("no changes", false);
        return;
    }
    impl.saving = true;
    std::string error;
    const bool ok = impl.saver(impl.slide, impl.buffer.text(), &error);
    impl.saving = false;
    if (ok) {
        impl.buffer.markClean();
        impl.setStatus("saved", false);
        if (impl.onSaved) impl.onSaved();
    } else {
        impl.setStatus(error.empty() ? "save failed — see the terminal" : error, true);
    }
}

bool SlideEditor::handleKey(int key, int action, int mods) {
    if (action != GLFW_PRESS && action != GLFW_REPEAT) return false;
    Impl& impl = *mImpl;
    impl.caretBlinkFrom = glfwGetTime();

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

    if (cmd) {
        switch (key) {
            case GLFW_KEY_S: save(); return true;
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
    mImpl->caretBlinkFrom = glfwGetTime();
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
    const std::string title = impl.slide >= 0
        ? "Slide " + std::to_string(impl.slide + 1) + " of " + std::to_string(app.deck.size())
        : "No slide";
    drawText(canvas, title, pad, 26, uiFont(15, true), ui::kText);
    if (impl.buffer.dirty()) {
        drawText(canvas, "  edited", pad + textWidth(uiFont(15, true), title), 26, uiFont(12),
                 ui::kWarn);
    }
    std::string where = impl.file;
    if (impl.shared > 1) {
        // Said out loud: editing any step of an expanded slide edits the source all of them
        // come from, and the surprise otherwise is finding four slides changed.
        where += "  —  one block, " + std::to_string(impl.shared) + " slides";
    }
    drawText(canvas, ellipsize(where, uiFont(11), w - pad * 2), pad, 44, uiFont(11), ui::kDim);
    fillRect(canvas, SkRect::MakeXYWH(0, kHeaderH - 1, w, 1), ui::kLine);

    // ── Text ─────────────────────────────────────────────────────────
    const float viewTop = kHeaderH, viewBottom = h - kFooterH;
    const float viewH = viewBottom - viewTop;

    // Keep the caret on screen — following it is the whole job of the scroll here.
    const Caret caret = impl.buffer.caret();
    const float caretTop = caret.line * lineHeight;
    if (caretTop < impl.scrollY) impl.scrollY = caretTop;
    else if (caretTop + lineHeight > impl.scrollY + viewH - lineHeight)
        impl.scrollY = caretTop + lineHeight * 2 - viewH;
    const float caretX = textWidth(mono, impl.buffer.line(caret.line).substr(0, caret.col));
    const float textW = w - impl.textLeft - pad;
    if (caretX < impl.scrollX) impl.scrollX = std::max(0.0f, caretX - 40);
    else if (caretX > impl.scrollX + textW - 20) impl.scrollX = caretX - textW + 40;
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
        const SkColor tone = lineTone(text, inFence && !fenceLine);
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

    if (!impl.status.empty()) {
        drawText(canvas, ellipsize(impl.status, uiFont(12), w - pad * 2 - 190),
                 pad + 180, viewBottom + 26, uiFont(12),
                 impl.statusError ? ui::kOver : ui::kAhead);
    }
    drawTextRight(canvas, "cmd+S saves", w - pad, viewBottom + 26, uiFont(11), ui::kDim);

    impl.backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
