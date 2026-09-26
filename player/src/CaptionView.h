// The caption widget: a slide's narration as running text, each word lit as it is spoken,
// and correctable in place.
//
// A view rather than a window, so the same widget can be the caption window and a tab of
// the presenter: it draws into whatever rectangle it is given and is told about the mouse
// and keyboard by whoever owns the window. Everything the two share — layout, the scroll
// that keeps the spoken line in view, edit mode and its selection — lives here once.
//
// Driven by the audio clock rather than by anything counted on the main thread, so the
// highlight stays on the word actually coming out of the speakers. With no audio playing it
// still shows the transcript, unlit — a serviceable teleprompter for a talk whose narration
// has been written down but is being delivered live.
#pragma once

#include "App.h"
#include "Captions.h"

#include "include/core/SkRect.h"

#include <functional>
#include <string>
#include <vector>

class SkCanvas;

namespace refract {

// One word as it was laid out, kept from the last frame so a click can be turned back into
// the word under it.
struct PlacedWord {
    int index = 0;
    float x = 0, y = 0, width = 0;   // y is the baseline
};

class CaptionView {
public:
    // Draw into `area`, in the canvas's coordinates (the same ones the mouse reports in).
    // `playbackTime` is where the narration has reached; `playing` says whether it is
    // actually running, which is the difference between lighting words and just showing
    // them. `header` adds the slide's title and counter across the top, for a window of its
    // own; a host that already shows them leaves it off. `textSize` fixes the type size, or
    // 0 to size it to the area.
    void draw(SkCanvas* canvas, const SkRect& area, const App& app, Captions& captions,
              double playbackTime, bool playing, bool header, float textSize = 0.0f);

    // The mouse, in the same coordinates. `click` is true when it landed on something of
    // this view's — the Edit button, a word, or anywhere while editing — so a host can
    // tell whether the click is still its own.
    void mouseMove(float x, float y);
    bool click(float x, float y, bool shift);

    // Keyboard. Returns true when the key was consumed, in which case the player's own
    // bindings must not also see it: typing "b" into a word should not blank the projector.
    // When not editing, only E is taken (to start), and only while the view is `active`:
    // a host that is showing something else over it should not have E hijacked.
    bool handleKey(int key, int action, int mods);
    void handleChar(unsigned int codepoint);
    void setActive(bool active) { mActive = active; }

    bool isEditing() const { return mEditing; }

    // Leave edit mode, keeping the word in progress. Used on the way out, so quitting
    // mid-correction is not the one way to lose one.
    void finishEditing() { setEditing(false); }

    // Called when edit mode is entered or left. The narration should stop while the words
    // are being changed — the highlight would be moving under the cursor — and start again
    // from the beginning of the slide afterwards, so the correction can be heard in place.
    void setOnEditingChanged(std::function<void(bool editing)> action) {
        mOnEditingChanged = std::move(action);
    }

private:
    bool hasSelection() const { return mSelFirst >= 0; }
    void commit();
    std::string rangeText(int first, int last) const;
    void select(int index);
    void extendTo(int index);
    void setEditing(bool on);

    float mScroll = 0.0f;                // eased toward keeping the spoken line in view
    std::vector<PlacedWord> mPlaced;     // last frame's layout, for hit-testing
    float mLineHeight = 0;
    float mTextSize = 0;
    float mOriginX = 0, mOriginY = 0;    // where the layout was translated to

    bool mActive = true;
    bool mEditing = false;
    // The words being retyped, inclusive. A range rather than one word because a
    // mis-transcription is often a join or a split — one word heard as two, or two as one —
    // and fixing that means replacing a span with a different number of words.
    int mSelFirst = -1, mSelLast = -1;
    int mAnchor = -1;                    // where a shift-extended selection started
    std::string mBuffer;                 // what has been typed for the range
    Captions* mCaptions = nullptr;       // the ones on screen, for committing edits

    SkRect mEditButton = SkRect::MakeEmpty();
    bool mEditButtonHot = false;

    std::function<void(bool)> mOnEditingChanged;
};

}  // namespace refract
