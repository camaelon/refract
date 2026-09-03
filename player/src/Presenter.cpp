#include "Presenter.h"

#include "Navigator.h"
#include "Timing.h"
#include "Thumbs.h"
#include "Ui.h"

#include "rcplayer/CpuRenderBackend.h"
#include "rcplayer/Player.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"
#include "include/core/SkPathBuilder.h"
#include "include/core/SkPaint.h"

#include <algorithm>
#include <deque>
#include <functional>
#include <cmath>
#include <iostream>

namespace refract {

// How many level samples the waveform keeps. At the presenter's 20 Hz redraw this is about
// eight seconds of trailing history.
constexpr size_t kLevelHistory = 160;

struct PresenterWindow::Impl {
    CpuRenderBackend backend;
    int width = 0, height = 0;
    int fbWidth = 0, fbHeight = 0;

    std::function<void()> onToggleClock;
    SkRect clockButton = SkRect::MakeEmpty();   // set while drawing, hit-tested on click
    bool buttonHot = false;                     // pointer is over it
    double mouseX = 0, mouseY = 0;

    // Recent input levels, oldest first — a few seconds of history drawn as a waveform.
    // A meter that shows only the current level tells you nothing about whether you have
    // been audible; the trailing shape does.
    std::deque<float> levels;
    float peak = -1.0f;
};

std::unique_ptr<PresenterWindow> PresenterWindow::Create(int width, int height) {
    // Restored before returning: creating a window makes its context current, and the
    // caller is in the middle of driving the slide window's.
    GLFWwindow* previous = glfwGetCurrentContext();

    glfwWindowHint(GLFW_DECORATED, GLFW_TRUE);
    glfwWindowHint(GLFW_TRANSPARENT_FRAMEBUFFER, GLFW_FALSE);
    glfwWindowHint(GLFW_FLOATING, GLFW_FALSE);
    glfwWindowHint(GLFW_FOCUSED, GLFW_TRUE);
    glfwWindowHint(GLFW_FOCUS_ON_SHOW, GLFW_TRUE);
    GLFWwindow* window = glfwCreateWindow(width, height, "refract — presenter", nullptr, nullptr);
    if (!window) {
        std::cerr << "presenter: window creation failed\n";
        if (previous) glfwMakeContextCurrent(previous);
        return nullptr;
    }

    auto presenter = std::unique_ptr<PresenterWindow>(new PresenterWindow());
    presenter->mWindow = window;
    presenter->mImpl = std::make_unique<Impl>();

    glfwSetWindowUserPointer(window, presenter.get());
    glfwSetCursorPosCallback(window, [](GLFWwindow* w, double x, double y) {
        auto* self = static_cast<PresenterWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        self->mImpl->mouseX = x;
        self->mImpl->mouseY = y;
        self->mImpl->buttonHot =
            self->mImpl->clockButton.contains(static_cast<float>(x), static_cast<float>(y));
    });
    glfwSetMouseButtonCallback(window, [](GLFWwindow* w, int button, int action, int) {
        if (button != GLFW_MOUSE_BUTTON_LEFT || action != GLFW_PRESS) return;
        auto* self = static_cast<PresenterWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        if (self->mImpl->clockButton.contains(static_cast<float>(self->mImpl->mouseX),
                                              static_cast<float>(self->mImpl->mouseY))
            && self->mImpl->onToggleClock) {
            self->mImpl->onToggleClock();
        }
    });

    glfwMakeContextCurrent(window);
    // No vsync here. Two vsync-locked windows means two blocking waits per iteration of a
    // single-threaded loop, and the slide window's wait is the one that matters — the
    // presenter is a panel of text and two stills, and tearing in it costs nothing.
    glfwSwapInterval(0);
    presenter->mImpl->backend.resize(width, height);
    presenter->mImpl->width = width;
    presenter->mImpl->height = height;

    if (previous) glfwMakeContextCurrent(previous);
    return presenter;
}

void PresenterWindow::setOnToggleClock(std::function<void()> action) {
    mImpl->onToggleClock = std::move(action);
}

void PresenterWindow::pushAudioLevel(float average, float peak) {
    mImpl->peak = peak;
    if (average < 0.0f) {
        mImpl->levels.clear();
        return;
    }
    mImpl->levels.push_back(average);
    while (mImpl->levels.size() > kLevelHistory) mImpl->levels.pop_front();
}

PresenterWindow::~PresenterWindow() {
    if (mWindow) {
        // The backend owns a GL texture living in this window's context, so it has to go
        // while that context is still current and still exists.
        GLFWwindow* previous = glfwGetCurrentContext();
        glfwMakeContextCurrent(mWindow);
        mImpl.reset();
        if (previous && previous != mWindow) glfwMakeContextCurrent(previous);
        glfwDestroyWindow(mWindow);
    }
}

bool PresenterWindow::shouldClose() const {
    return mWindow && glfwWindowShouldClose(mWindow);
}

namespace {

// The timer's colour is the only ambient signal of how the talk is going, so it only
// changes when it means something: amber in the last fifth, red once over.
SkColor clockColor(const TalkClock& clock) {
    double f = clock.fraction();
    if (f < 0.0)  return ui::kText;
    if (f >= 1.0) return ui::kOver;
    if (f >= 0.8) return ui::kWarn;
    return ui::kText;
}

void drawPaneLabel(SkCanvas* canvas, const SkRect& box, const std::string& label,
                   const std::string& detail) {
    SkFont font = uiFont(13, true);
    float y = box.top() - 10;
    float x = drawText(canvas, label, box.left(), y, font, ui::kDim);
    if (!detail.empty()) {
        SkFont light = uiFont(13);
        drawText(canvas, "  " + detail, box.left() + x, y, light, ui::kDim);
    }
}

// Progress along the deck, with a tick at every section boundary — the shape of the talk
// at a glance, and where in it you are. With a rehearsal trace, a second marker shows where
// that run had got to by now: the gap between the two *is* how far ahead or behind you are,
// which reads faster than a number does.
void drawProgress(SkCanvas* canvas, const SkRect& r, const App& app, float ghostFraction) {
    const Deck& deck = app.deck;
    fillRoundRect(canvas, r, r.height() * 0.5f, ui::kPanel);

    if (deck.size() > 0) {
        float done = static_cast<float>(app.current() + 1) / deck.size();
        SkRect filled = SkRect::MakeLTRB(r.left(), r.top(), r.left() + r.width() * done, r.bottom());
        fillRoundRect(canvas, filled, r.height() * 0.5f, ui::kAccent);
    }
    for (const auto& section : deck.sections()) {
        if (deck.size() <= 1) break;
        float x = r.left() + r.width() * (static_cast<float>(section.firstSlide) / deck.size());
        fillRect(canvas, SkRect::MakeXYWH(x, r.top() - 3, 1.5f, r.height() + 6), ui::kLine);
    }

    if (ghostFraction >= 0.0f) {
        float x = r.left() + r.width() * std::min(1.0f, ghostFraction);
        fillRoundRect(canvas, SkRect::MakeXYWH(x - 1.5f, r.top() - 5, 3, r.height() + 10),
                      1.5f, ui::kText);
    }
}

}  // namespace

// "2:15 behind" / "0:40 ahead" / "on pace". Small differences are noise — a talk is not run
// to the second — so a drift under the deadband reads as on pace and stays grey.
//
// The deadband scales with the talk: half a minute out of forty-five is nothing, half a
// minute out of five is a tenth of the slot. Two per cent of the rehearsal, floored at ten
// seconds so it never twitches, capped at half a minute so a long talk still gets told.
namespace {
struct PaceLabel { std::string text; SkColor color; };

PaceLabel paceLabel(double delta, double talkLength) {
    const double deadband = std::min(30.0, std::max(10.0, talkLength * 0.02));
    if (std::fabs(delta) < deadband) return {"on pace", ui::kDim};
    if (delta < 0) return {formatDuration(-delta) + " ahead", ui::kAhead};
    // Behind by more than a tenth of the talk is a different problem from being a little
    // late, and wants a different colour.
    const double serious = std::max(60.0, talkLength * 0.1);
    return {formatDuration(delta) + " behind", delta < serious ? ui::kWarn : ui::kOver};
}
}  // namespace

namespace {

// A round play/pause control. Drawn as shapes rather than glyphs: the chrome renders through
// one typeface with no fallback, and transport symbols are exactly the sort of character it
// turns out not to carry.
void drawClockButton(SkCanvas* canvas, const SkRect& box, bool running, bool hot) {
    const float r = box.width() * 0.5f;
    SkPaint fill;
    fill.setAntiAlias(true);
    fill.setColor(hot ? 0xFF2A3140 : 0xFF1E2430);
    canvas->drawCircle(box.centerX(), box.centerY(), r, fill);

    SkPaint ring;
    ring.setAntiAlias(true);
    ring.setStyle(SkPaint::kStroke_Style);
    ring.setStrokeWidth(1.5f);
    ring.setColor(hot ? ui::kText : ui::kLine);
    canvas->drawCircle(box.centerX(), box.centerY(), r - 0.75f, ring);

    SkPaint mark;
    mark.setAntiAlias(true);
    mark.setColor(running ? ui::kText : ui::kAhead);
    if (running) {
        // Pause: two bars.
        const float bw = r * 0.22f, bh = r * 0.9f, gap = r * 0.26f;
        canvas->drawRect(SkRect::MakeXYWH(box.centerX() - gap - bw, box.centerY() - bh * 0.5f,
                                          bw, bh), mark);
        canvas->drawRect(SkRect::MakeXYWH(box.centerX() + gap, box.centerY() - bh * 0.5f,
                                          bw, bh), mark);
    } else {
        // Play: a triangle, nudged right so it looks centred rather than measuring centred.
        const float size = r * 0.9f;
        const float cx = box.centerX() + size * 0.12f;
        SkPathBuilder tri;
        tri.moveTo(cx - size * 0.45f, box.centerY() - size * 0.55f);
        tri.lineTo(cx + size * 0.55f, box.centerY());
        tri.lineTo(cx - size * 0.45f, box.centerY() + size * 0.55f);
        tri.close();
        canvas->drawPath(tri.detach(), mark);
    }
}

// The input level over the last few seconds, as a waveform mirrored about a centre line,
// newest at the right. Silence reads as a flat line, which is the failure this is here to
// catch — a talk recorded with the microphone muted looks exactly like one that worked until
// you play it back.
void drawLevels(SkCanvas* canvas, const SkRect& box, const std::deque<float>& levels,
                float peak) {
    fillRoundRect(canvas, box, 4, ui::kPanel);
    const float mid = box.centerY();

    if (levels.empty()) {
        fillRect(canvas, SkRect::MakeXYWH(box.left() + 8, mid - 0.5f, box.width() - 16, 1),
                 ui::kLine);
        return;
    }

    const float inset = 8.0f;
    const float usable = box.width() - inset * 2;
    const float barW = std::max(1.0f, usable / static_cast<float>(kLevelHistory));
    const float maxH = box.height() * 0.42f;

    // Peak feeds the colour, not the shape: clipping is a property of the moment, and it is
    // the one thing worth interrupting for.
    const SkColor color = (peak > 0.97f) ? ui::kOver : ui::kAhead;

    float x = box.right() - inset - barW;
    for (auto it = levels.rbegin(); it != levels.rend() && x > box.left() + inset; ++it) {
        const float hgt = std::max(1.0f, *it * maxH);
        fillRect(canvas, SkRect::MakeXYWH(x, mid - hgt, barW * 0.72f, hgt * 2), color);
        x -= barW;
    }
}

}  // namespace

void PresenterWindow::render(App& app, const sk_sp<SkImage>& live) {
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

    const Deck& deck = app.deck;
    const float pad = std::round(w * 0.022f);
    const float fw  = w - pad * 2;

    // ── Top bar: wall clock, talk timer, position ────────────────────
    const float barY = pad + std::round(h * 0.052f);
    SkFont clockFont = uiFont(std::round(h * 0.075f), true);
    SkFont labelFont = uiFont(13);
    SkFont metaFont  = uiFont(std::round(h * 0.028f), true);

    drawText(canvas, wallClock(), pad, barY, clockFont, ui::kDim);

    // Given a planned length, the big number counts *down*. On stage the number you act on
    // is how long is left, and reading it off an elapsed time means doing arithmetic while
    // talking. Past zero it keeps running negative — "-2:30" says how far over you are, and
    // the colour has already turned by then. Without a plan there is nothing to count down
    // to, so it counts up.
    const bool countdown = app.clock.target > 0.0;
    std::string timer = formatDuration(countdown ? app.clock.remaining() : app.clock.elapsed);
    float timerW = textWidth(clockFont, timer);
    float timerX = w * 0.5f - timerW * 0.5f;
    drawText(canvas, timer, timerX, barY, clockFont, clockColor(app.clock));

    // Play/pause for the talk, sitting against the clock it controls. It starts a recording
    // too, so a rehearsal can be driven without touching the keyboard.
    const float buttonSize = std::min(44.0f, clockFont.getSize() * 0.8f);
    mImpl->clockButton = SkRect::MakeXYWH(timerX - buttonSize - 18,
                                          barY - buttonSize * 0.72f, buttonSize, buttonSize);
    drawClockButton(canvas, mImpl->clockButton, app.clock.running, mImpl->buttonHot);
    // Under the timer: what the big number is not saying. Recording takes the line, since
    // knowing the microphone is live matters more than any of it.
    float subX = timerX;
    if (app.recordArmed) {
        // Armed, not rolling: say what starts it, because nothing is being captured yet and
        // that is not otherwise visible.
        drawText(canvas, "READY — press T to start recording", subX, barY + 18,
                 uiFont(11, true), ui::kWarn);
    } else if (app.timing.recording()) {
        SkFont font = uiFont(11, true);
        const bool live = app.clock.running;
        fillRoundRect(canvas, SkRect::MakeXYWH(subX, barY + 8, 8, 8), 4,
                      live ? ui::kOver : ui::kWarn);
        const char* label = !live ? "RECORDING PAUSED"
                                  : (app.recordAudio ? "RECORDING + AUDIO" : "RECORDING");
        drawText(canvas, label, subX + 14, barY + 18, font, live ? ui::kOver : ui::kWarn);
    } else if (!app.clock.running) {
        drawText(canvas, "PAUSED", subX, barY + 18, uiFont(11, true), ui::kWarn);
    } else {
        SkFont font = uiFont(11);
        if (countdown) {
            // The elapsed time stays visible: it is what the trace and the progress bar are
            // both measured against.
            subX += drawText(canvas, "elapsed " + formatDuration(app.clock.elapsed), subX,
                             barY + 18, font, ui::kDim) + 14;
        }
        double delta = 0.0;
        if (!deck.empty() && paceDelta(app.timing, deck.at(app.current()).file,
                                       app.clock.elapsed, app.timeOnSlide(), &delta)) {
            PaceLabel label = paceLabel(delta, app.timing.total());
            drawText(canvas, label.text, subX, barY + 18, uiFont(11, true), label.color);
        }
    }

    char position[64];
    std::snprintf(position, sizeof(position), "%d / %d", app.current() + 1, std::max(1, deck.size()));
    drawTextRight(canvas, position, w - pad, barY, metaFont, ui::kText);
    int sectionIdx = deck.sectionIndexOf(app.current());
    if (sectionIdx >= 0) {
        const auto& section = deck.sections()[sectionIdx];
        std::string name = std::to_string(section.number) + ". " + section.title;
        drawTextRight(canvas, ellipsize(name, labelFont, fw * 0.4f), w - pad, barY + 18,
                      labelFont, ui::kDim);
    }

    // ── Slide panes: current (live) and next (a still) ───────────────
    // The split is 62/38 rather than even: the current slide is what you glance at, the
    // next one only needs to be recognisable.
    const float panesTop = barY + std::round(h * 0.045f);
    const float panesH   = std::round(h * 0.40f);
    const float gap      = pad * 0.8f;
    const float currentW = std::round((fw - gap) * 0.62f);
    SkRect currentBox = SkRect::MakeXYWH(pad, panesTop, currentW, panesH);
    SkRect nextBox    = SkRect::MakeXYWH(pad + currentW + gap, panesTop, fw - currentW - gap, panesH);

    drawPaneLabel(canvas, currentBox, "NOW",
                  ellipsize(deck.empty() ? "" : deck.at(app.current()).title,
                            uiFont(13), currentBox.width() - 60));
    SkRect drawn = drawImageFit(canvas, live, currentBox);
    strokeRoundRect(canvas, drawn, 2, ui::kLine);
    // Time on this slide, in the corner of the pane it belongs to.
    drawTextRight(canvas, formatDuration(app.timeOnSlide()), currentBox.right(),
                  currentBox.top() - 10, uiFont(13, true), ui::kDim);

    // The audience is looking at a blank screen and the presenter pane is not — say so,
    // or it is genuinely easy to keep talking to a blanked projector.
    if (app.blank) {
        SkFont font = uiFont(12, true);
        std::string label = app.blank == 1 ? "SCREEN BLANK" : "SCREEN WHITE";
        float labelW = textWidth(font, label) + 20;
        SkRect chip = SkRect::MakeXYWH(currentBox.left(), currentBox.top() + 10, labelW, 22);
        fillRoundRect(canvas, chip, 4, ui::kWarn);
        drawText(canvas, label, chip.left() + 10, chip.centerY() + 4, font, 0xFF1A1206);
    }

    int nextIndex = app.current() + 1;
    bool hasNext = nextIndex < deck.size();
    drawPaneLabel(canvas, nextBox, hasNext ? "NEXT" : "END",
                  hasNext ? ellipsize(deck.at(nextIndex).title, uiFont(13),
                                      nextBox.width() - 40)
                          : "last slide");
    sk_sp<SkImage> nextImage;
    if (hasNext) {
        // Stills are rendered at a fixed size and scaled to the pane, so resizing the
        // presenter window does not throw the cache away and re-render the deck. This
        // never blocks: a still that is not finished yet comes back null and the pane
        // says so, rather than freezing the deck to wait for it.
        nextImage = thumbIfReady(deck.at(nextIndex).entry, 640, 360);
    }
    SkRect nextDrawn = drawImageFit(canvas, nextImage, nextBox);
    strokeRoundRect(canvas, nextDrawn, 2, ui::kLine);
    if (hasNext && !nextImage) {
        SkFont font = uiFont(13);
        drawText(canvas, "rendering...", nextBox.centerX() - textWidth(font, "rendering...") * 0.5f,
                 nextBox.centerY(), font, ui::kLine);
    }

    // ── Notes ────────────────────────────────────────────────────────
    const float notesTop = panesTop + panesH + std::round(h * 0.055f);
    const float progressH = 6.0f;
    const bool showLevels = app.timing.recording() && app.recordAudio;
    const float levelsH = showLevels ? 34.0f : 0.0f;
    const float notesBottom = h - pad - progressH - 18 - (showLevels ? levelsH + 10 : 0.0f);
    SkRect notesBox = SkRect::MakeLTRB(pad, notesTop, w - pad, notesBottom);
    if (notesBox.height() > 40) {
        fillRoundRect(canvas, notesBox, 6, ui::kPanel);
        const std::string& notes = app.deck.notesFor(app.current());
        SkFont notesFont = uiFont(std::max(14.0f, std::round(h * 0.030f)));
        float lineHeight = notesFont.getSize() * 1.45f;
        float textLeft = notesBox.left() + 18;
        float maxWidth = notesBox.width() - 36;
        canvas->save();
        canvas->clipRect(notesBox);
        if (notes.empty()) {
            drawText(canvas, "no notes for this slide", textLeft,
                     notesBox.top() + 18 + notesFont.getSize(), uiFont(notesFont.getSize()),
                     ui::kLine);
        } else {
            float y = notesBox.top() + 18 + notesFont.getSize();
            for (const auto& line : wrapText(notes, notesFont, maxWidth)) {
                if (y > notesBox.bottom()) break;
                drawText(canvas, line, textLeft, y, notesFont, ui::kText);
                y += lineHeight;
            }
        }
        canvas->restore();
    }

    // ── Input level ──────────────────────────────────────────────────
    if (showLevels) {
        SkRect box = SkRect::MakeXYWH(pad, h - pad - progressH - 10 - levelsH, fw, levelsH);
        drawLevels(canvas, box, mImpl->levels, mImpl->peak);
        if (mImpl->peak > 0.97f) {
            SkFont font = uiFont(10, true);
            drawTextRight(canvas, "CLIPPING", box.right() - 8,
                          box.top() + 12, font, ui::kOver);
        }
    }

    // ── Progress ─────────────────────────────────────────────────────
    // Where the rehearsal had got to by now, as a fraction of the deck.
    float ghost = -1.0f;
    if (!app.timing.empty() && !deck.empty() && app.clock.running) {
        double through = 0.0;
        std::string file = app.timing.positionAt(app.clock.elapsed, &through);
        int index = file.empty() ? -1 : deck.indexOfFile(file);
        if (index >= 0) {
            ghost = static_cast<float>((index + through) / deck.size());
        }
    }
    drawProgress(canvas, SkRect::MakeXYWH(pad, h - pad - progressH, fw, progressH), app, ghost);

    // The navigator, the help card and a pending jump live here rather than on the slide
    // window whenever this window is open.
    drawOverlays(canvas, app, w, h);

    mImpl->backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
