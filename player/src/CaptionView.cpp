#include "CaptionView.h"

#include "Ui.h"

#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstddef>
#include <cstdio>

namespace refract {

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

// ── Editing state ────────────────────────────────────────────────────

// Put the buffer back over the words it came from. Nothing happens if it was not changed.
void CaptionView::commit() {
    if (mSelFirst >= 0 && mCaptions) mCaptions->replaceRange(mSelFirst, mSelLast, mBuffer);
    mSelFirst = mSelLast = mAnchor = -1;
    mBuffer.clear();
}

// The text of a range, as it would read joined back up.
std::string CaptionView::rangeText(int first, int last) const {
    std::string text;
    if (!mCaptions) return text;
    for (int i = first; i <= last && i < (int)mCaptions->words().size(); i++) {
        if (!text.empty()) text += ' ';
        text += mCaptions->words()[i].text;
    }
    return text;
}

void CaptionView::select(int index) {
    commit();
    if (!mCaptions || index < 0 || index >= (int)mCaptions->words().size()) return;
    mSelFirst = mSelLast = mAnchor = index;
    mBuffer = rangeText(index, index);
}

// Grow or shrink the selection to take in `index`, keeping the anchor put. Whatever was
// typed is dropped: it was the text of a different span.
void CaptionView::extendTo(int index) {
    if (!mCaptions || mAnchor < 0) { select(index); return; }
    const int count = (int)mCaptions->words().size();
    if (index < 0 || index >= count) return;
    mSelFirst = std::min(mAnchor, index);
    mSelLast = std::max(mAnchor, index);
    mBuffer = rangeText(mSelFirst, mSelLast);
}

void CaptionView::setEditing(bool on) {
    if (mEditing == on) return;
    if (on && mCaptions) mCaptions->clearEditMarker();
    if (!on) {
        commit();
        if (mCaptions && mCaptions->dirty()) mCaptions->save();
    }
    mEditing = on;
    mSelFirst = mSelLast = mAnchor = -1;
    mBuffer.clear();
    if (mOnEditingChanged) mOnEditingChanged(on);
}

// ── Mouse ────────────────────────────────────────────────────────────

void CaptionView::mouseMove(float x, float y) {
    mEditButtonHot = mEditButton.contains(x, y);
}

bool CaptionView::click(float x, float y, bool shift) {
    if (mEditButton.contains(x, y)) {
        setEditing(!mEditing);
        return true;
    }
    if (!mEditing) return false;

    // Hit-test against the layout from the last frame, in its own coordinates.
    const float lx = x - mOriginX;
    const float ly = y - mOriginY;
    for (const auto& item : mPlaced) {
        const SkRect box = SkRect::MakeXYWH(item.x - 4, item.y - mTextSize, item.width + 8, mLineHeight);
        if (box.contains(lx, ly)) {
            if (shift && hasSelection()) extendTo(item.index);
            else                         select(item.index);
            return true;
        }
    }
    commit();     // a click on empty space finishes the word being typed
    return true;
}

// ── Keyboard ─────────────────────────────────────────────────────────

bool CaptionView::handleKey(int key, int action, int mods) {
    const bool shift = (mods & GLFW_MOD_SHIFT) != 0;
    if (action != GLFW_PRESS && action != GLFW_REPEAT) return mEditing;

    if (!mEditing) {
        if (key == GLFW_KEY_E && mActive && mCaptions && !mCaptions->empty()) {
            setEditing(true);            // the only key claimed when not editing
            return true;
        }
        return false;
    }

    const int count = mCaptions ? (int)mCaptions->words().size() : 0;
    switch (key) {
        case GLFW_KEY_ESCAPE:
            // Back out one level at a time: the selection first, then edit mode.
            if (hasSelection()) {
                mSelFirst = mSelLast = mAnchor = -1;
                mBuffer.clear();
            } else {
                setEditing(false);
            }
            return true;
        case GLFW_KEY_ENTER:
        case GLFW_KEY_KP_ENTER:
        case GLFW_KEY_TAB: {
            // Commit and step on: corrections tend to come in runs. The next word is found
            // relative to the *start* of what was replaced, since replacing three words with
            // one moves everything after it.
            const int from = mSelFirst;
            const std::string typed = mBuffer;
            commit();
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
            const int now = mCaptions ? (int)mCaptions->words().size() : 0;
            if (next < now) select(next);
            return true;
        }
        case GLFW_KEY_RIGHT:
            if (shift) extendTo(mSelLast + 1);
            else if (mSelLast + 1 < count) select(mSelLast + 1);
            return true;
        case GLFW_KEY_LEFT:
            if (shift) extendTo(mSelLast - 1);
            else if (mSelFirst > 0) select(mSelFirst - 1);
            return true;
        case GLFW_KEY_BACKSPACE:
            if (!mBuffer.empty()) {
                // Step back over a whole UTF-8 code point, not a byte.
                do { mBuffer.pop_back(); }
                while (!mBuffer.empty() && (mBuffer.back() & 0xC0) == 0x80);
            }
            return true;
        default:
            // Everything else is swallowed: while typing into a word, the player's bindings
            // must not fire.
            return true;
    }
}

void CaptionView::handleChar(unsigned int codepoint) {
    if (!mEditing || !hasSelection()) return;
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
    mBuffer += utf8;
}

// ── Drawing ──────────────────────────────────────────────────────────

void CaptionView::draw(SkCanvas* canvas, const SkRect& area, const App& app, Captions& captions,
                       double playbackTime, bool playing, bool header, float textSize) {
    mCaptions = &captions;
    const float w = area.width(), h = area.height();
    if (w <= 0 || h <= 0) return;

    // A window of its own breathes at the edges; a pane inside another window is already
    // framed and keeps its type close to its border.
    const float pad = header ? std::round(std::min(w, h) * 0.06f) : 18.0f;
    const float headerY = area.top() + (header ? pad : 24.0f);     // the baseline of the top row
    SkFont headerFont = uiFont(13, true);

    if (header && !app.deck.empty()) {
        const Slide& slide = app.deck.at(app.current());
        drawText(canvas, ellipsize(slide.title.empty() ? slide.file : slide.title,
                                   headerFont, w - pad * 2 - 80),
                 area.left() + pad, headerY, headerFont, ui::kDim);
        char counter[32];
        std::snprintf(counter, sizeof(counter), "%d / %d", app.current() + 1, app.deck.size());
        drawTextRight(canvas, counter, area.right() - pad, headerY, headerFont, ui::kDim);
    }

    // Edit / Done. Only offered when there is something to correct.
    if (!captions.empty()) {
        SkFont buttonFont = uiFont(12, true);
        const char* label = mEditing ? "Done" : "Edit";
        const float labelW = textWidth(buttonFont, label);
        const float right = header ? area.right() - pad - 68 : area.right() - pad;
        mEditButton = SkRect::MakeXYWH(right - labelW - 24, headerY - 15, labelW + 24, 24);
        const bool on = mEditing;
        fillRoundRect(canvas, mEditButton, 5, on ? ui::kAccent : (mEditButtonHot ? 0xFF2A3140 : ui::kPanel));
        if (!on) strokeRoundRect(canvas, mEditButton, 5, ui::kLine);
        drawText(canvas, label, mEditButton.left() + 12, mEditButton.centerY() + 4, buttonFont,
                 on ? 0xFF0E1013 : ui::kText);
    } else {
        mEditButton = SkRect::MakeEmpty();
    }

    if (captions.empty()) {
        SkFont font = uiFont(15);
        const char* message = "no captions for this slide";
        drawText(canvas, message, area.centerX() - textWidth(font, message) * 0.5f, area.centerY(),
                 font, ui::kLine);
        mPlaced.clear();
        return;
    }

    // Big enough to read across a desk, and it shrinks on a small window rather than
    // wrapping into a column one word wide.
    const float size = textSize > 0.0f ? textSize : std::max(18.0f, std::min(w * 0.045f, h * 0.11f));
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
        if (mEditing && i == mSelFirst) {
            texts.push_back(mBuffer);
            firstWordOf.push_back(i);
            i = mSelLast + 1;
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
    const int current = (playing && !mEditing) ? captions.wordAt(playbackTime) : -1;

    // Keep the line being spoken in view. Eased rather than jumped, so a long narration
    // scrolls instead of snapping a line at a time under the reader.
    const float viewTop = headerY + (header ? 30.0f : 18.0f);
    const float hintH = mEditing ? 24.0f : 0.0f;
    const float viewHeight = area.bottom() - viewTop - (header ? pad : 12.0f) - hintH;
    float target = 0.0f;
    int currentCell = -1;
    for (std::size_t i = 0; i < placed.size(); i++) {
        if (placed[i].index == current) { currentCell = static_cast<int>(i); break; }
    }
    if (totalHeight > viewHeight && currentCell >= 0) {
        target = std::max(0.0f, placed[currentCell].y - viewHeight * 0.45f);
        target = std::min(target, totalHeight - viewHeight + lineHeight);
    }
    if (mEditing) target = mScroll;   // hold still while words are being changed
    mScroll += (target - mScroll) * 0.15f;

    // Kept for the mouse: a click has to be turned back into the word drawn under it.
    mPlaced = placed;
    mLineHeight = lineHeight;
    mTextSize = size;
    mOriginX = area.left() + pad;
    mOriginY = viewTop - mScroll;

    canvas->save();
    canvas->clipRect(SkRect::MakeLTRB(area.left(), viewTop, area.right(), viewTop + viewHeight));
    canvas->translate(mOriginX, mOriginY);

    for (std::size_t cell = 0; cell < placed.size(); cell++) {
        const PlacedWord& item = placed[cell];
        const bool retyping = mEditing && item.index == mSelFirst;

        // Spoken words stay bright, the one being said is lit, and what is still to come is
        // dim — so the eye lands on the right place without reading anything. In edit mode
        // there is nothing being spoken, so every word reads as available to change.
        SkColor color = ui::kDim;
        if (mEditing)                                  color = ui::kText;
        else if (current >= 0 && item.index < current) color = ui::kText;
        else if (item.index == current)                color = ui::kAccent;
        else if (current < 0 && !playing)              color = ui::kText;   // idle: plain transcript

        const std::string& text = texts[cell];
        const float width = item.width;

        if (item.index == current) {
            SkRect box = SkRect::MakeXYWH(item.x - 4, item.y - size * 0.92f, item.width + 8, size * 1.22f);
            fillRoundRect(canvas, box, 4, 0x2E6EA8FF);
        }
        if (retyping) {
            SkRect box = SkRect::MakeXYWH(item.x - 5, item.y - size * 0.92f, width + 12, size * 1.22f);
            fillRoundRect(canvas, box, 4, 0xFF1E2430);
            strokeRoundRect(canvas, box, 4, ui::kAccent, 1.5f);
            // A caret, so an emptied word still shows where the typing is going.
            fillRect(canvas, SkRect::MakeXYWH(item.x + width + 1, item.y - size * 0.86f, 1.5f, size * 1.1f),
                     ui::kAccent);
        }
        drawText(canvas, text, item.x, item.y, font, color);
    }
    canvas->restore();

    if (mEditing) {
        SkFont hint = uiFont(12);
        const char* text = hasSelection()
            ? "type to replace    shift-click or shift-arrows to take in more words    "
              "Enter next    Esc cancel"
            : "click a word to change it    shift-click a second to take in a span    "
              "Done to finish";
        drawText(canvas, text, area.left() + pad, area.bottom() - (header ? pad * 0.5f : 10.0f), hint, ui::kDim);
    }
}

}  // namespace refract
