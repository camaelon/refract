#include "CaptionWindow.h"

#include "Ui.h"

#include "rcplayer/CpuRenderBackend.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <functional>
#include <cmath>
#include <iostream>
#include <vector>

namespace refract {

// One word as it was laid out, kept from the last frame so a click can be turned back into
// the word under it.
struct PlacedWord {
    int index = 0;
    float x = 0, y = 0, width = 0;   // y is the baseline
};

struct CaptionWindow::Impl {
    CpuRenderBackend backend;
    int width = 0, height = 0;
    int fbWidth = 0, fbHeight = 0;
    float scroll = 0.0f;       // eased toward keeping the spoken line in view

    std::vector<PlacedWord> placed;   // last frame's layout, for hit-testing
    float lineHeight = 0;
    float textSize = 0;
    float originX = 0, originY = 0;   // where the layout was translated to

    bool editing = false;
    // The words being retyped, inclusive. A range rather than one word because a
    // mis-transcription is often a join or a split — one word heard as two, or two as one —
    // and fixing that means replacing a span with a different number of words.
    int selFirst = -1, selLast = -1;
    int anchor = -1;                  // where a shift-extended selection started
    std::string buffer;               // what has been typed for the range
    Captions* captions = nullptr;     // the ones on screen, for committing edits

    SkRect editButton = SkRect::MakeEmpty();
    bool editButtonHot = false;
    double mouseX = 0, mouseY = 0;

    std::function<void(bool)> onEditingChanged;

    bool hasSelection() const { return selFirst >= 0; }

    // Put `buffer` back over the words it came from. Nothing happens if it was not changed.
    void commit() {
        if (selFirst >= 0 && captions) captions->replaceRange(selFirst, selLast, buffer);
        selFirst = selLast = anchor = -1;
        buffer.clear();
    }

    // The text of a range, as it would read joined back up.
    std::string rangeText(int first, int last) const {
        std::string text;
        if (!captions) return text;
        for (int i = first; i <= last && i < (int)captions->words().size(); i++) {
            if (!text.empty()) text += ' ';
            text += captions->words()[i].text;
        }
        return text;
    }

    void select(int index) {
        commit();
        if (!captions || index < 0 || index >= (int)captions->words().size()) return;
        selFirst = selLast = anchor = index;
        buffer = rangeText(index, index);
    }

    // Grow or shrink the selection to take in `index`, keeping the anchor put. Whatever was
    // typed is dropped: it was the text of a different span.
    void extendTo(int index) {
        if (!captions || anchor < 0) { select(index); return; }
        const int count = (int)captions->words().size();
        if (index < 0 || index >= count) return;
        selFirst = std::min(anchor, index);
        selLast = std::max(anchor, index);
        buffer = rangeText(selFirst, selLast);
    }

    void setEditing(bool on) {
        if (editing == on) return;
        if (on && captions) captions->clearEditMarker();
        if (!on) {
            commit();
            if (captions && captions->dirty()) captions->save();
        }
        editing = on;
        selFirst = selLast = anchor = -1;
        buffer.clear();
        if (onEditingChanged) onEditingChanged(on);
    }
};

std::unique_ptr<CaptionWindow> CaptionWindow::Create(int width, int height) {
    GLFWwindow* previous = glfwGetCurrentContext();

    glfwWindowHint(GLFW_DECORATED, GLFW_TRUE);
    glfwWindowHint(GLFW_TRANSPARENT_FRAMEBUFFER, GLFW_FALSE);
    glfwWindowHint(GLFW_FLOATING, GLFW_FALSE);
    glfwWindowHint(GLFW_FOCUSED, GLFW_TRUE);
    glfwWindowHint(GLFW_FOCUS_ON_SHOW, GLFW_TRUE);
    GLFWwindow* window = glfwCreateWindow(width, height, "refract — captions", nullptr, nullptr);
    if (!window) {
        std::cerr << "captions: window creation failed\n";
        if (previous) glfwMakeContextCurrent(previous);
        return nullptr;
    }

    auto captions = std::unique_ptr<CaptionWindow>(new CaptionWindow());
    captions->mWindow = window;
    captions->mImpl = std::make_unique<Impl>();

    glfwSetWindowUserPointer(window, captions.get());
    glfwSetCursorPosCallback(window, [](GLFWwindow* w, double x, double y) {
        auto* self = static_cast<CaptionWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        self->mImpl->mouseX = x;
        self->mImpl->mouseY = y;
        self->mImpl->editButtonHot =
            self->mImpl->editButton.contains(static_cast<float>(x), static_cast<float>(y));
    });
    glfwSetMouseButtonCallback(window, [](GLFWwindow* w, int button, int action, int) {
        if (button != GLFW_MOUSE_BUTTON_LEFT || action != GLFW_PRESS) return;
        auto* self = static_cast<CaptionWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        Impl& impl = *self->mImpl;
        const float x = static_cast<float>(impl.mouseX), y = static_cast<float>(impl.mouseY);

        if (impl.editButton.contains(x, y)) {
            impl.setEditing(!impl.editing);
            return;
        }
        if (!impl.editing) return;

        // Hit-test against the layout from the last frame, in its own coordinates.
        const float lx = x - impl.originX;
        const float ly = y - impl.originY;
        const bool shift = (glfwGetKey(w, GLFW_KEY_LEFT_SHIFT) == GLFW_PRESS
                            || glfwGetKey(w, GLFW_KEY_RIGHT_SHIFT) == GLFW_PRESS);
        for (const auto& item : impl.placed) {
            const SkRect box = SkRect::MakeXYWH(item.x - 4, item.y - impl.textSize,
                                                item.width + 8, impl.lineHeight);
            if (box.contains(lx, ly)) {
                if (shift && impl.hasSelection()) impl.extendTo(item.index);
                else                              impl.select(item.index);
                return;
            }
        }
        impl.commit();     // a click on empty space finishes the word being typed
    });

    glfwMakeContextCurrent(window);
    glfwSwapInterval(0);   // a third vsync wait would cost the slide window its frame rate
    captions->mImpl->backend.resize(width, height);
    captions->mImpl->width = width;
    captions->mImpl->height = height;

    if (previous) glfwMakeContextCurrent(previous);
    return captions;
}

CaptionWindow::~CaptionWindow() {
    if (mWindow) {
        GLFWwindow* previous = glfwGetCurrentContext();
        glfwMakeContextCurrent(mWindow);
        mImpl.reset();
        if (previous && previous != mWindow) glfwMakeContextCurrent(previous);
        glfwDestroyWindow(mWindow);
    }
}

bool CaptionWindow::shouldClose() const {
    return mWindow && glfwWindowShouldClose(mWindow);
}

namespace {

// Lay the words out as wrapped running text. Words are placed individually rather than as
// wrapped lines of a string, because each one has to be coloured by whether it has been
// spoken yet — which means knowing where each one sits.
//
// Takes the strings rather than the words so a word being retyped can be laid out at the
// width of what is being typed: the text after it has to move aside as it grows, or a long
// correction is drawn straight through its neighbours.
std::vector<PlacedWord> layout(const std::vector<std::string>& texts, const SkFont& font,
                               float maxWidth, float lineHeight, float* totalHeight) {
    std::vector<PlacedWord> placed;
    placed.reserve(texts.size());
    const float spaceW = textWidth(font, " ");
    float x = 0, y = lineHeight;
    for (size_t i = 0; i < texts.size(); i++) {
        const float w = textWidth(font, texts[i]);
        if (x > 0 && x + w > maxWidth) {
            x = 0;
            y += lineHeight;
        }
        placed.push_back({static_cast<int>(i), x, y, w});
        x += w + spaceW;
    }
    *totalHeight = y;
    return placed;
}

}  // namespace

bool CaptionWindow::isEditing() const { return mImpl && mImpl->editing; }

void CaptionWindow::finishEditing() {
    if (mImpl) mImpl->setEditing(false);
}

void CaptionWindow::setOnEditingChanged(std::function<void(bool)> action) {
    mImpl->onEditingChanged = std::move(action);
}

bool CaptionWindow::handleKey(int key, int action, int mods) {
    if (!mImpl) return false;
    const bool shift = (mods & GLFW_MOD_SHIFT) != 0;
    if (action != GLFW_PRESS && action != GLFW_REPEAT) return mImpl->editing;

    if (!mImpl->editing) {
        if (key == GLFW_KEY_E) {          // the only key this window claims when not editing
            mImpl->setEditing(true);
            return true;
        }
        return false;
    }

    const int count = mImpl->captions ? (int)mImpl->captions->words().size() : 0;
    switch (key) {
        case GLFW_KEY_ESCAPE:
            // Back out one level at a time: the selection first, then edit mode.
            if (mImpl->hasSelection()) {
                mImpl->selFirst = mImpl->selLast = mImpl->anchor = -1;
                mImpl->buffer.clear();
            } else {
                mImpl->setEditing(false);
            }
            return true;
        case GLFW_KEY_ENTER:
        case GLFW_KEY_KP_ENTER:
        case GLFW_KEY_TAB: {
            // Commit and step on: corrections tend to come in runs. The next word is found
            // relative to the *start* of what was replaced, since replacing three words with
            // one moves everything after it.
            const int from = mImpl->selFirst;
            const std::string typed = mImpl->buffer;
            mImpl->commit();
            int next = from < 0 ? 0 : from + 1;
            if (from >= 0) {
                // Count the words the replacement actually left behind.
                int written = 0;
                for (std::size_t i = 0; i < typed.size(); ) {
                    while (i < typed.size() && std::isspace((unsigned char)typed[i])) i++;
                    if (i < typed.size()) written++;
                    while (i < typed.size() && !std::isspace((unsigned char)typed[i])) i++;
                }
                next = from + std::max(0, written);
            }
            const int now = mImpl->captions ? (int)mImpl->captions->words().size() : 0;
            if (next < now) mImpl->select(next);
            return true;
        }
        case GLFW_KEY_RIGHT:
            if (shift) mImpl->extendTo(mImpl->selLast + 1);
            else if (mImpl->selLast + 1 < count) mImpl->select(mImpl->selLast + 1);
            return true;
        case GLFW_KEY_LEFT:
            if (shift) mImpl->extendTo(mImpl->selLast - 1);
            else if (mImpl->selFirst > 0) mImpl->select(mImpl->selFirst - 1);
            return true;
        case GLFW_KEY_BACKSPACE:
            if (!mImpl->buffer.empty()) {
                // Step back over a whole UTF-8 code point, not a byte.
                do { mImpl->buffer.pop_back(); }
                while (!mImpl->buffer.empty() && (mImpl->buffer.back() & 0xC0) == 0x80);
            }
            return true;
        default:
            // Everything else is swallowed: while typing into a word, the player's bindings
            // must not fire.
            return true;
    }
}

void CaptionWindow::handleChar(unsigned int codepoint) {
    if (!mImpl || !mImpl->editing || !mImpl->hasSelection()) return;
    // GLFW hands over a code point; the buffer is UTF-8.
    char utf8[5] = {0};
    if (codepoint < 0x80) {
        utf8[0] = static_cast<char>(codepoint);
    } else if (codepoint < 0x800) {
        utf8[0] = static_cast<char>(0xC0 | (codepoint >> 6));
        utf8[1] = static_cast<char>(0x80 | (codepoint & 0x3F));
    } else if (codepoint < 0x10000) {
        utf8[0] = static_cast<char>(0xE0 | (codepoint >> 12));
        utf8[1] = static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F));
        utf8[2] = static_cast<char>(0x80 | (codepoint & 0x3F));
    } else {
        utf8[0] = static_cast<char>(0xF0 | (codepoint >> 18));
        utf8[1] = static_cast<char>(0x80 | ((codepoint >> 12) & 0x3F));
        utf8[2] = static_cast<char>(0x80 | ((codepoint >> 6) & 0x3F));
        utf8[3] = static_cast<char>(0x80 | (codepoint & 0x3F));
    }
    mImpl->buffer += utf8;
}

void CaptionWindow::render(const App& app, Captions& captions, double playbackTime,
                           bool playing) {
    mImpl->captions = &captions;
    if (!mWindow || !mImpl) return;
    glfwMakeContextCurrent(mWindow);

    int w = 0, h = 0;
    glfwGetWindowSize(mWindow, &w, &h);
    if (w <= 0 || h <= 0) return;
    if (w != mImpl->width || h != mImpl->height) {
        mImpl->backend.resize(w, h);
        mImpl->width = w;
        mImpl->height = h;
    }
    int fbW = 0, fbH = 0;
    glfwGetFramebufferSize(mWindow, &fbW, &fbH);
    if (fbW != mImpl->fbWidth || fbH != mImpl->fbHeight) {
        mImpl->backend.onFramebufferResize(fbW, fbH);
        mImpl->fbWidth = fbW;
        mImpl->fbHeight = fbH;
    }

    SkCanvas* canvas = mImpl->backend.canvas();
    if (!canvas) return;
    canvas->clear(ui::kBg);

    const float pad = std::round(std::min(w, h) * 0.06f);
    SkFont headerFont = uiFont(13, true);

    if (!app.deck.empty()) {
        const Slide& slide = app.deck.at(app.current());
        drawText(canvas, ellipsize(slide.title.empty() ? slide.file : slide.title,
                                   headerFont, w - pad * 2 - 80),
                 pad, pad, headerFont, ui::kDim);
        char counter[32];
        std::snprintf(counter, sizeof(counter), "%d / %d", app.current() + 1, app.deck.size());
        drawTextRight(canvas, counter, w - pad, pad, headerFont, ui::kLine);
    }

    // Edit / Done. Only offered when there is something to correct.
    if (!captions.empty()) {
        SkFont buttonFont = uiFont(12, true);
        const char* label = mImpl->editing ? "Done" : "Edit";
        const float labelW = textWidth(buttonFont, label);
        mImpl->editButton = SkRect::MakeXYWH(w - pad - labelW - 68, pad - 15,
                                             labelW + 24, 24);
        const bool on = mImpl->editing;
        fillRoundRect(canvas, mImpl->editButton, 5,
                      on ? ui::kAccent : (mImpl->editButtonHot ? 0xFF2A3140 : ui::kPanel));
        if (!on) strokeRoundRect(canvas, mImpl->editButton, 5, ui::kLine);
        drawText(canvas, label, mImpl->editButton.left() + 12,
                 mImpl->editButton.centerY() + 4, buttonFont,
                 on ? 0xFF0E1013 : ui::kText);
    } else {
        mImpl->editButton = SkRect::MakeEmpty();
    }

    if (captions.empty()) {
        SkFont font = uiFont(15);
        const char* message = "no captions for this slide";
        drawText(canvas, message, w * 0.5f - textWidth(font, message) * 0.5f, h * 0.5f,
                 font, ui::kLine);
        mImpl->backend.present();
        glfwSwapBuffers(mWindow);
        return;
    }

    // Big enough to read across a desk, and it shrinks on a small window rather than
    // wrapping into a column one word wide.
    const float size = std::max(18.0f, std::min(w * 0.045f, h * 0.11f));
    SkFont font = uiFont(size);
    const float lineHeight = size * 1.5f;
    const float maxWidth = w - pad * 2;

    // What is on screen, in order. Usually one entry per word — but the words being retyped
    // collapse into a single field holding what has been typed for the whole span, because a
    // range can be replaced by a different number of words than it started with.
    std::vector<std::string> texts;
    std::vector<int> firstWordOf;      // parallel: which word each entry starts at
    const int wordCount = static_cast<int>(captions.words().size());
    for (int i = 0; i < wordCount; ) {
        if (mImpl->editing && i == mImpl->selFirst) {
            texts.push_back(mImpl->buffer);
            firstWordOf.push_back(i);
            i = mImpl->selLast + 1;
        } else {
            texts.push_back(captions.words()[i].text);
            firstWordOf.push_back(i);
            i++;
        }
    }

    float totalHeight = 0;
    std::vector<PlacedWord> placed = layout(texts, font, maxWidth, lineHeight, &totalHeight);
    // layout() indexes its own entries; map them back onto words for hit-testing and colour.
    for (auto& item : placed) item.index = firstWordOf[item.index];
    // While the words are being corrected there is no playback to follow, and a highlight
    // moving under the cursor would only be in the way.
    const int current = (playing && !mImpl->editing) ? captions.wordAt(playbackTime) : -1;

    // Keep the line being spoken in view. Eased rather than jumped, so a long narration
    // scrolls instead of snapping a line at a time under the reader.
    const float viewTop = pad + 30;
    const float viewHeight = h - viewTop - pad;
    float target = 0.0f;
    int currentCell = -1;
    for (std::size_t i = 0; i < placed.size(); i++) {
        if (placed[i].index == current) { currentCell = static_cast<int>(i); break; }
    }
    if (totalHeight > viewHeight && currentCell >= 0) {
        target = std::max(0.0f, placed[currentCell].y - viewHeight * 0.45f);
        target = std::min(target, totalHeight - viewHeight + lineHeight);
    }
    if (mImpl->editing) target = mImpl->scroll;   // hold still while words are being changed
    mImpl->scroll += (target - mImpl->scroll) * 0.15f;

    // Kept for the mouse: a click has to be turned back into the word drawn under it.
    mImpl->placed = placed;
    mImpl->lineHeight = lineHeight;
    mImpl->textSize = size;
    mImpl->originX = pad;
    mImpl->originY = viewTop - mImpl->scroll;

    canvas->save();
    canvas->clipRect(SkRect::MakeXYWH(0, viewTop, w, viewHeight));
    canvas->translate(pad, viewTop - mImpl->scroll);

    for (std::size_t cell = 0; cell < placed.size(); cell++) {
        const PlacedWord& item = placed[cell];
        const bool retyping = mImpl->editing && item.index == mImpl->selFirst;

        // Spoken words stay bright, the one being said is lit, and what is still to come is
        // dim — so the eye lands on the right place without reading anything. In edit mode
        // there is nothing being spoken, so every word reads as available to change.
        SkColor color = ui::kDim;
        if (mImpl->editing)                       color = ui::kText;
        else if (current >= 0 && item.index < current) color = ui::kText;
        else if (item.index == current)           color = ui::kAccent;
        else if (current < 0 && !playing)         color = ui::kText;   // idle: plain transcript

        const std::string& text = texts[cell];
        const float width = item.width;

        if (item.index == current) {
            SkRect box = SkRect::MakeXYWH(item.x - 4, item.y - size * 0.92f,
                                          item.width + 8, size * 1.22f);
            fillRoundRect(canvas, box, 4, 0x2E6EA8FF);
        }
        if (retyping) {
            SkRect box = SkRect::MakeXYWH(item.x - 5, item.y - size * 0.92f,
                                          width + 12, size * 1.22f);
            fillRoundRect(canvas, box, 4, 0xFF1E2430);
            strokeRoundRect(canvas, box, 4, ui::kAccent, 1.5f);
            // A caret, so an emptied word still shows where the typing is going.
            fillRect(canvas, SkRect::MakeXYWH(item.x + width + 1, item.y - size * 0.86f,
                                              1.5f, size * 1.1f), ui::kAccent);
        }
        drawText(canvas, text, item.x, item.y, font, color);
    }
    canvas->restore();

    if (mImpl->editing) {
        SkFont hint = uiFont(12);
        const char* text = mImpl->hasSelection()
            ? "type to replace    shift-click or shift-arrows to take in more words    "
              "Enter next    Esc cancel"
            : "click a word to change it    shift-click a second to take in a span    "
              "Done to finish";
        drawText(canvas, text, pad, h - pad * 0.5f, hint, ui::kLine);
    }

    mImpl->backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
