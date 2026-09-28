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

// How long after "delete recording" is clicked the red delete button stays dead.
constexpr double kConfirmArmSec = 0.8;

struct PresenterWindow::Impl {
    CpuRenderBackend backend;
    int width = 0, height = 0;
    int fbWidth = 0, fbHeight = 0;

    std::function<void()> onToggleClock;
    std::function<void()> onRecordSlide;
    std::function<void()> onDiscardTake;
    std::function<void()> onStopRun;
    SkRect stopButton = SkRect::MakeEmpty();
    std::function<void(int)> onDeleteRecording;
    bool deleteGoesToTrash = false;
    double confirmShownAt = 0.0;               // when the question went up; delete is dead for a moment
    SkRect deleteButton = SkRect::MakeEmpty();
    // The question shown in place of the row after "delete recording": which slide it was
    // asked for, so it goes away by itself when the slide changes under it.
    int confirmDeleteSlide = -1;
    SkRect confirmDelete = SkRect::MakeEmpty(), confirmKeep = SkRect::MakeEmpty();
    int deleteSlide = -1;                       // the slide the delete button was drawn for
    std::function<void()> onToggleAutoplay;
    SkRect autoplayBox = SkRect::MakeEmpty();
    std::function<void()> onTranscribeSlide;
    SkRect transcribeButton = SkRect::MakeEmpty();
    bool transcribing = false;
    std::string transcribeStatus;
    std::string syncStatus;
    float transcribeFraction = -1.0f;
    PresenterWindow::Narration narration;
    PresenterWindow::Tab tab = PresenterWindow::Tab::Notes;
    SkRect notesTab = SkRect::MakeEmpty(), captionsTab = SkRect::MakeEmpty();
    CaptionView captionView;
    Captions* captions = nullptr;
    double playbackTime = 0.0;
    bool playing = false;
    SkRect clockButton = SkRect::MakeEmpty();   // set while drawing, hit-tested on click
    SkRect recordButton = SkRect::MakeEmpty();
    SkRect discardButton = SkRect::MakeEmpty();
    bool buttonHot = false;                     // pointer is over it
    double mouseX = 0, mouseY = 0;

    bool over(const SkRect& box) const {
        return box.contains(static_cast<float>(mouseX), static_cast<float>(mouseY));
    }

    // Recent input levels, oldest first — a few seconds of history drawn as a waveform.
    // A meter that shows only the current level tells you nothing about whether you have
    // been audible; the trailing shape does.
    std::deque<float> levels;
    float peak = -1.0f;

    // One frame's geometry, computed once in render() and handed to each part.
    struct Frame {
        SkCanvas* canvas = nullptr;
        App* app = nullptr;
        int w = 0, h = 0;
        float pad = 0, fw = 0;
        float barY = 0, panesTop = 0, panesH = 0;
        float notesTop = 0, notesBottom = 0, progressH = 0;
        bool showLevels = false, showRecord = false, showWave = false;
        float levelsH = 0, waveH = 0;
    };
    void drawTopBar(const Frame& F);
    void drawPanes(const Frame& F, const sk_sp<SkImage>& live);
    void drawPane(const Frame& F);             // tabs, then the notes or the captions
    void drawMeter(const Frame& F);            // the microphone's level, while recording
    void drawNarrationStrip(const Frame& F);
    void drawButtonsRow(const Frame& F);
    void drawFooter(const Frame& F);           // the progress bar and the overlays
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
        self->mImpl->captionView.mouseMove(static_cast<float>(x), static_cast<float>(y));
    });
    glfwSetMouseButtonCallback(window, [](GLFWwindow* w, int button, int action, int) {
        if (button != GLFW_MOUSE_BUTTON_LEFT || action != GLFW_PRESS) return;
        auto* self = static_cast<PresenterWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        Impl& impl = *self->mImpl;
        if (impl.over(impl.notesTab)) { self->showTab(Tab::Notes); return; }
        if (impl.over(impl.captionsTab)) { self->showTab(Tab::Captions); return; }
        if (impl.tab == Tab::Captions) {
            const bool shift = (glfwGetKey(w, GLFW_KEY_LEFT_SHIFT) == GLFW_PRESS
                                || glfwGetKey(w, GLFW_KEY_RIGHT_SHIFT) == GLFW_PRESS);
            if (impl.captionView.click(static_cast<float>(impl.mouseX), static_cast<float>(impl.mouseY), shift)) return;
        }
        if (impl.over(impl.clockButton) && impl.onToggleClock) impl.onToggleClock();
        else if (impl.over(impl.recordButton) && impl.onRecordSlide) impl.onRecordSlide();
        else if (impl.over(impl.discardButton) && impl.onDiscardTake) impl.onDiscardTake();
        else if (impl.over(impl.stopButton) && impl.onStopRun) impl.onStopRun();
        else if (impl.over(impl.deleteButton)) {
            impl.confirmDeleteSlide = impl.deleteSlide;
            impl.confirmShownAt = glfwGetTime();
        }
        else if (impl.over(impl.confirmKeep)) impl.confirmDeleteSlide = -1;
        else if (impl.over(impl.confirmDelete)) {
            // Not in the first moments: a second click where the first one landed — a
            // double-click, or a click repeated because nothing seemed to happen — must not
            // be the confirmation. The button is drawn dead until then.
            if (glfwGetTime() - impl.confirmShownAt < kConfirmArmSec) return;
            const int slide = impl.confirmDeleteSlide;
            impl.confirmDeleteSlide = -1;
            if (impl.onDeleteRecording) impl.onDeleteRecording(slide);
        }
        else if (impl.over(impl.autoplayBox) && impl.onToggleAutoplay) impl.onToggleAutoplay();
        else if (impl.over(impl.transcribeButton) && impl.onTranscribeSlide && !impl.transcribing) impl.onTranscribeSlide();
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

void PresenterWindow::setOnRecordSlide(std::function<void()> record,
                                       std::function<void()> discard) {
    mImpl->onRecordSlide = std::move(record);
    mImpl->onDiscardTake = std::move(discard);
}

void PresenterWindow::setOnStopRun(std::function<void()> stop) {
    mImpl->onStopRun = std::move(stop);
}

void PresenterWindow::setOnDeleteRecording(std::function<void(int)> remove) {
    mImpl->onDeleteRecording = std::move(remove);
}

void PresenterWindow::setDeleteGoesToTrash(bool trash) { mImpl->deleteGoesToTrash = trash; }

void PresenterWindow::setOnToggleAutoplay(std::function<void()> toggle) {
    mImpl->onToggleAutoplay = std::move(toggle);
}

void PresenterWindow::setOnTranscribeSlide(std::function<void()> transcribe) {
    mImpl->onTranscribeSlide = std::move(transcribe);
}

void PresenterWindow::setTranscribing(bool busy, const std::string& status, float fraction) {
    mImpl->transcribing = busy;
    mImpl->transcribeStatus = status;
    mImpl->transcribeFraction = fraction;
}

void PresenterWindow::setSyncStatus(const std::string& status) { mImpl->syncStatus = status; }

void PresenterWindow::setCaptions(Captions* captions, double playbackTime, bool playing) {
    mImpl->captions = captions;
    mImpl->playbackTime = playbackTime;
    mImpl->playing = playing;
}

void PresenterWindow::showTab(Tab tab) {
    if (mImpl->tab == tab) return;
    // An edit in progress belongs to the captions tab; leaving it finishes (and saves) it.
    if (tab != Tab::Captions) mImpl->captionView.finishEditing();
    mImpl->tab = tab;
    mImpl->captionView.setActive(tab == Tab::Captions);
}

PresenterWindow::Tab PresenterWindow::tab() const { return mImpl->tab; }

CaptionView& PresenterWindow::captionView() { return mImpl->captionView; }

void PresenterWindow::setNarration(const Narration& narration) { mImpl->narration = narration; }

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
void drawProgress(SkCanvas* canvas, const SkRect& r, const App& app, float ghostFraction,
                  bool ghostIsPlan) {
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
        // A rehearsal is what the talk *did* take and reads as solid; a plan is what it is
        // *meant* to take, and is drawn quieter so the two are never confused.
        fillRoundRect(canvas, SkRect::MakeXYWH(x - 1.5f, r.top() - 5, 3, r.height() + 10),
                      1.5f, ghostIsPlan ? ui::kDim : ui::kText);
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

namespace {

// A pill button: the row's shape for everything but the record button.
void pillButton(SkCanvas* canvas, const SkRect& box, const std::string& text, const SkFont& font,
                SkColor fill, SkColor stroke, SkColor tone) {
    fillRoundRect(canvas, box, 13, fill);
    strokeRoundRect(canvas, box, 13, stroke, 1.0f);
    drawTextCentred(canvas, text, box, font, tone);
}

}  // namespace

// ── The window, part by part ─────────────────────────────────────────
// Each part takes the frame's geometry and draws its own region; the order they are
// called in is the order they stack on screen.

void PresenterWindow::Impl::drawTopBar(const Frame& F) {
    SkCanvas* canvas = F.canvas;
    App& app = *F.app;
    const Deck& deck = app.deck;
    const int w = F.w, h = F.h;
    const float pad = F.pad, fw = F.fw;
    const float barY = F.barY, panesTop = F.panesTop, panesH = F.panesH;
    const float notesTop = F.notesTop, notesBottom = F.notesBottom, progressH = F.progressH;
    const bool showLevels = F.showLevels, showRecord = F.showRecord, showWave = F.showWave;
    const float levelsH = F.levelsH, waveH = F.waveH;
    (void)deck; (void)w; (void)h; (void)pad; (void)fw; (void)barY; (void)panesTop; (void)panesH;
    (void)notesTop; (void)notesBottom; (void)progressH; (void)showLevels; (void)showRecord;
    (void)showWave; (void)levelsH; (void)waveH;

    // ── Top bar: wall clock, talk timer, position ────────────────────
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
    clockButton = SkRect::MakeXYWH(timerX - buttonSize - 18,
                                          barY - buttonSize * 0.72f, buttonSize, buttonSize);
    drawClockButton(canvas, clockButton, app.clock.running, buttonHot);
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
        if (!deck.empty() && paceDelta(app.timing, deck.at(app.current()).sourceKey(),
                                       deck.at(app.current()).file,
                                       app.clock.elapsed, app.timeOnSlide(), &delta)) {
            PaceLabel label = paceLabel(delta, app.timing.total());
            drawText(canvas, label.text, subX, barY + 18, uiFont(11, true), label.color);
        } else if (!deck.empty() && deck.plannedLength() > 0) {
            // No rehearsal, but the deck says how long its parts should take. Behind is
            // being further back in the deck than the plan expects, measured in the time
            // the plan would have spent covering the difference.
            const float should = plannedFraction(deck.plan(), deck.size(), app.clock.elapsed);
            if (should >= 0.0f) {
                const double here = static_cast<double>(app.current() + 1) / deck.size();
                const double drift = (should - here) * deck.plannedLength();
                PaceLabel label = paceLabel(drift, deck.plannedLength());
                drawText(canvas, label.text, subX, barY + 18, uiFont(11, true), label.color);
            }
        }
    }

    char position[64];
    std::snprintf(position, sizeof(position), "%d / %d", app.current() + 1, std::max(1, deck.size()));
    drawTextRight(canvas, position, w - pad, barY, metaFont, ui::kText);
    // Kept in step with other players: said beside the counter, since it is the counter
    // that another machine may change under you.
    if (!syncStatus.empty()) {
        const bool linked = syncStatus.find("connecting") == std::string::npos;
        drawTextRight(canvas, syncStatus, w - pad - textWidth(metaFont, position) - 16, barY,
                      uiFont(11, true), linked ? ui::kAccent : ui::kWarn);
    }
    int sectionIdx = deck.sectionIndexOf(app.current());
    if (sectionIdx >= 0) {
        const auto& section = deck.sections()[sectionIdx];
        std::string name = std::to_string(section.number) + ". " + section.title;
        // What this part of the talk is meant to be worth, when it says. Beside its name,
        // because "twelve minutes" is only useful attached to what it is twelve minutes of.
        if (section.duration > 0) name += "  ·  " + formatDuration(section.duration);
        drawTextRight(canvas, ellipsize(name, labelFont, fw * 0.4f), w - pad, barY + 18,
                      labelFont, ui::kDim);
    }

}

void PresenterWindow::Impl::drawPanes(const Frame& F, const sk_sp<SkImage>& live) {
    SkCanvas* canvas = F.canvas;
    App& app = *F.app;
    const Deck& deck = app.deck;
    const int w = F.w, h = F.h;
    const float pad = F.pad, fw = F.fw;
    const float barY = F.barY, panesTop = F.panesTop, panesH = F.panesH;
    const float notesTop = F.notesTop, notesBottom = F.notesBottom, progressH = F.progressH;
    const bool showLevels = F.showLevels, showRecord = F.showRecord, showWave = F.showWave;
    const float levelsH = F.levelsH, waveH = F.waveH;
    (void)deck; (void)w; (void)h; (void)pad; (void)fw; (void)barY; (void)panesTop; (void)panesH;
    (void)notesTop; (void)notesBottom; (void)progressH; (void)showLevels; (void)showRecord;
    (void)showWave; (void)levelsH; (void)waveH;

    // ── Slide panes: current (live) and next (a still) ───────────────
    // The split is 62/38 rather than even: the current slide is what you glance at, the
    // next one only needs to be recognisable.
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

}

void PresenterWindow::Impl::drawPane(const Frame& F) {
    SkCanvas* canvas = F.canvas;
    App& app = *F.app;
    const Deck& deck = app.deck;
    const int w = F.w, h = F.h;
    const float pad = F.pad, fw = F.fw;
    const float barY = F.barY, panesTop = F.panesTop, panesH = F.panesH;
    const float notesTop = F.notesTop, notesBottom = F.notesBottom, progressH = F.progressH;
    const bool showLevels = F.showLevels, showRecord = F.showRecord, showWave = F.showWave;
    const float levelsH = F.levelsH, waveH = F.waveH;
    (void)deck; (void)w; (void)h; (void)pad; (void)fw; (void)barY; (void)panesTop; (void)panesH;
    (void)notesTop; (void)notesBottom; (void)progressH; (void)showLevels; (void)showRecord;
    (void)showWave; (void)levelsH; (void)waveH;

    // ── Tabs: notes | captions ───────────────────────────────────────
    // Two labels in the pane's top-left, the way the slide panes are labelled; the one
    // showing is bright with a line under it.
    {
        SkFont tabFont = uiFont(13, true);
        float x = pad;
        const float ty = notesTop - 8;
        const struct { const char* text; Tab tab; SkRect* box; } tabs[] = {
            {"NOTES", Tab::Notes, &notesTab}, {"CAPTIONS", Tab::Captions, &captionsTab}};
        for (const auto& t : tabs) {
            const float tw = textWidth(tabFont, t.text);
            *t.box = SkRect::MakeXYWH(x - 6, ty - 18, tw + 12, 26);
            const bool on = tab == t.tab;
            const bool hot = !on && over(*t.box);
            drawText(canvas, t.text, x, ty, tabFont, on ? ui::kText : (hot ? ui::kText : ui::kDim));
            if (on) fillRect(canvas, SkRect::MakeXYWH(x, ty + 5, tw, 2), ui::kAccent);
            x += tw + 22;
        }
    }
    captionView.setActive(tab == Tab::Captions);
    SkRect notesBox = SkRect::MakeLTRB(pad, notesTop, w - pad, notesBottom);
    if (notesBox.height() > 40 && tab == Tab::Captions) {
        fillRoundRect(canvas, notesBox, 6, ui::kPanel);
        const float size = std::max(14.0f, std::round(h * 0.030f));
        if (captions && (!captions->empty() || !transcribing)) {
            captionView.draw(canvas, notesBox, app, *captions, playbackTime,
                                    playing, /*header=*/false, size);
        } else {
            // Nothing yet, and a transcription on its way: say where it has got to rather
            // than "no captions", with a bar when the tool has said how many slides it has.
            SkFont font = uiFont(15);
            const std::string message = transcribeStatus.empty()
                ? std::string("transcribing\u2026") : "transcribing\u2026  " + transcribeStatus;
            drawText(canvas, message, notesBox.centerX() - textWidth(font, message) * 0.5f,
                     notesBox.centerY(), font, ui::kDim);
            const float bw = std::min(320.0f, notesBox.width() * 0.5f);
            SkRect track = SkRect::MakeXYWH(notesBox.centerX() - bw * 0.5f, notesBox.centerY() + 16, bw, 6);
            drawProgressTrack(canvas, track, transcribeFraction, glfwGetTime());
        }
    } else if (notesBox.height() > 40) {
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

}

void PresenterWindow::Impl::drawMeter(const Frame& F) {
    SkCanvas* canvas = F.canvas;
    App& app = *F.app;
    const Deck& deck = app.deck;
    const int w = F.w, h = F.h;
    const float pad = F.pad, fw = F.fw;
    const float barY = F.barY, panesTop = F.panesTop, panesH = F.panesH;
    const float notesTop = F.notesTop, notesBottom = F.notesBottom, progressH = F.progressH;
    const bool showLevels = F.showLevels, showRecord = F.showRecord, showWave = F.showWave;
    const float levelsH = F.levelsH, waveH = F.waveH;
    (void)deck; (void)w; (void)h; (void)pad; (void)fw; (void)barY; (void)panesTop; (void)panesH;
    (void)notesTop; (void)notesBottom; (void)progressH; (void)showLevels; (void)showRecord;
    (void)showWave; (void)levelsH; (void)waveH;

    // ── Input level ──────────────────────────────────────────────────
    if (showLevels) {
        SkRect box = SkRect::MakeXYWH(pad, h - pad - progressH - 10 - levelsH, fw, levelsH);
        drawLevels(canvas, box, levels, peak);
        if (peak > 0.97f) {
            SkFont font = uiFont(10, true);
            drawTextRight(canvas, "CLIPPING", box.right() - 8,
                          box.top() + 12, font, ui::kOver);
        }
    }

}

void PresenterWindow::Impl::drawNarrationStrip(const Frame& F) {
    SkCanvas* canvas = F.canvas;
    App& app = *F.app;
    const Deck& deck = app.deck;
    const int w = F.w, h = F.h;
    const float pad = F.pad, fw = F.fw;
    const float barY = F.barY, panesTop = F.panesTop, panesH = F.panesH;
    const float notesTop = F.notesTop, notesBottom = F.notesBottom, progressH = F.progressH;
    const bool showLevels = F.showLevels, showRecord = F.showRecord, showWave = F.showWave;
    const float levelsH = F.levelsH, waveH = F.waveH;
    (void)deck; (void)w; (void)h; (void)pad; (void)fw; (void)barY; (void)panesTop; (void)panesH;
    (void)notesTop; (void)notesBottom; (void)progressH; (void)showLevels; (void)showRecord;
    (void)showWave; (void)levelsH; (void)waveH;

    // ── Narration ────────────────────────────────────────────────────
    // Under the buttons row, so neither sits on the other: the shape of what was said,
    // mirrored about a centre line the way a sound editor draws it, the part already
    // played in the accent colour, and the playhead with the time it has reached.
    if (showWave) {
        const Narration& n = narration;
        const float top = notesBottom + 6 + (showRecord ? 34.0f : 0.0f);
        SkRect box = SkRect::MakeXYWH(pad, top, fw, waveH);
        fillRoundRect(canvas, box, 6, ui::kPanel);
        SkFont label = uiFont(11, true);
        std::string caption = n.label;
        if (n.duration > 0.0) caption += "  ·  " + formatDuration(n.duration);
        drawText(canvas, caption, box.left() + 10, box.top() + 14, label, ui::kDim);
        const float played = (n.position >= 0.0 && n.duration > 0.0)
            ? static_cast<float>(std::min(1.0, n.position / n.duration)) : -1.0f;
        if (played >= 0.0f) {
            drawTextRight(canvas, formatDuration(n.position) + " / " + formatDuration(n.duration),
                          box.right() - 10, box.top() + 14, label, ui::kAccent);
        }
        const float waveTop = box.top() + 22, waveBottom = box.bottom() - 6;
        const float mid = std::round((waveTop + waveBottom) * 0.5f), half = (waveBottom - waveTop) * 0.5f;
        const float left = box.left() + 10, width = box.width() - 20;
        // The centre line, faint, so a silent stretch still reads as a stretch.
        fillRect(canvas, SkRect::MakeLTRB(left, mid - 0.5f, left + width, mid + 0.5f), ui::kLine);
        const size_t bins = n.envelope->size();
        // Scaled to the recording's own loudest moment: a quiet take is still a shape,
        // and what matters here is where the speech is, not how loud the room was.
        float loudest = 0.0f;
        for (float v : *n.envelope) loudest = std::max(loudest, v);
        const float gain = loudest > 0.0f ? 1.0f / loudest : 1.0f;
        // As many bars as fit at three pixels each; wider strips get a bar per bin.
        const size_t bars = std::max<size_t>(1, std::min(bins, static_cast<size_t>(width / 3.0f)));
        SkPaint bar;
        bar.setAntiAlias(true);
        for (size_t i = 0; i < bars; i++) {
            // The loudest bin under this bar.
            const size_t b0 = i * bins / bars, b1 = std::max(b0 + 1, (i + 1) * bins / bars);
            float peak = 0.0f;
            for (size_t b = b0; b < b1 && b < bins; b++) peak = std::max(peak, (*n.envelope)[b]);
            // Quiet speech is most of a recording; lifting the low end keeps it visible
            // without flattening the loud parts.
            const float a = std::max(1.5f, std::pow(std::min(1.0f, peak * gain), 0.6f) * half);
            const float x0 = left + width * i / bars, x1 = left + width * (i + 1) / bars;
            const float f = static_cast<float>(i + 0.5f) / bars;
            bar.setColor(played >= 0.0f && f <= played ? ui::kAccent : 0xFF5A6273);
            const float bw = std::max(1.0f, x1 - x0 - 1.0f);
            canvas->drawRoundRect(SkRect::MakeLTRB(x0, mid - a, x0 + bw, mid + a), bw * 0.5f, bw * 0.5f, bar);
        }
        if (played >= 0.0f) {
            SkPaint head;
            head.setAntiAlias(true);
            head.setColor(ui::kWarn);
            head.setStrokeWidth(2.0f);
            const float x = left + width * played;
            canvas->drawLine(x, waveTop - 2, x, waveBottom + 2, head);
            canvas->drawCircle(x, waveTop - 2, 3.5f, head);
        }
    }

}

void PresenterWindow::Impl::drawButtonsRow(const Frame& F) {
    SkCanvas* canvas = F.canvas;
    App& app = *F.app;
    const Deck& deck = app.deck;
    const int w = F.w, h = F.h;
    const float pad = F.pad, fw = F.fw;
    const float barY = F.barY, panesTop = F.panesTop, panesH = F.panesH;
    const float notesTop = F.notesTop, notesBottom = F.notesBottom, progressH = F.progressH;
    const bool showLevels = F.showLevels, showRecord = F.showRecord, showWave = F.showWave;
    const float levelsH = F.levelsH, waveH = F.waveH;
    (void)deck; (void)w; (void)h; (void)pad; (void)fw; (void)barY; (void)panesTop; (void)panesH;
    (void)notesTop; (void)notesBottom; (void)progressH; (void)showLevels; (void)showRecord;
    (void)showWave; (void)levelsH; (void)waveH;

    // ── Re-record this slide ─────────────────────────────────────────
    // A take over one slide's narration. It is here rather than only on a key because it
    // overwrites a recording: what it will do should be visible before it is done, and what
    // it is doing should be unmistakable while it happens.
    recordButton = SkRect::MakeEmpty();
    discardButton = SkRect::MakeEmpty();
    autoplayBox = SkRect::MakeEmpty();
    stopButton = SkRect::MakeEmpty();
    // ── Stop the run ─────────────────────────────────────────────────
    // While a whole run is being recorded, the row holds one thing: the way to end it. Until
    // now the only ways were the next slide (which only closes this slide's wav) and quitting.
    if (app.timing.recording() && onStopRun) {
        SkFont label = uiFont(12, true);
        const std::string text = "stop recording";
        const float bw = textWidth(label, text) + 44;
        const float by = notesBottom + 6;
        stopButton = SkRect::MakeXYWH(pad, by, bw, 26);
        const bool hot = over(stopButton);
        fillRoundRect(canvas, stopButton, 13, ui::kPanel);
        strokeRoundRect(canvas, stopButton, 13, hot ? ui::kOver : ui::kLine, 1.0f);
        // A square, the stop glyph, in the recording colour.
        fillRoundRect(canvas, SkRect::MakeXYWH(stopButton.left() + 12,
                                               stopButton.centerY() - 5, 10, 10), 2, ui::kOver);
        drawText(canvas, text, stopButton.left() + 30, stopButton.centerY() + 4, label,
                 hot ? ui::kText : ui::kOver);
    }
    // ── Autoplay narration ───────────────────────────────────────────
    // On the same row, at the right: a slide that has a wav advances when it ends, so a
    // recorded talk plays itself; a slide without one waits for you as usual.
    if (onToggleAutoplay && showRecord && !app.deck.empty()) {
        SkFont label = uiFont(12, true);
        const std::string text = "autoplay narration";
        const float tw = textWidth(label, text);
        const float box = 16.0f;
        const float by = notesBottom + 6;
        const float right = w - pad;
        autoplayBox = SkRect::MakeXYWH(right - tw - 10 - box, by + 5, box + 10 + tw, box);
        const bool hot = over(autoplayBox);
        const SkColor tone = app.autoplayVoice ? ui::kText : (hot ? ui::kText : ui::kDim);
        SkRect square = SkRect::MakeXYWH(autoplayBox.left(), by + 5, box, box);
        fillRoundRect(canvas, square, 3, ui::kPanel);
        strokeRoundRect(canvas, square, 3, app.autoplayVoice ? ui::kText : (hot ? ui::kDim : ui::kLine), 1.0f);
        if (app.autoplayVoice) {
            // A tick, drawn: the chrome has one typeface and a check glyph is not in it.
            SkPaint tick;
            tick.setAntiAlias(true);
            tick.setStyle(SkPaint::kStroke_Style);
            tick.setStrokeWidth(2.0f);
            tick.setColor(ui::kText);
            SkPathBuilder path;
            path.moveTo(square.left() + 3.5f, square.centerY() + 0.5f);
            path.lineTo(square.left() + 6.5f, square.bottom() - 4.0f);
            path.lineTo(square.right() - 3.5f, square.top() + 4.0f);
            canvas->drawPath(path.detach(), tick);
        }
        drawText(canvas, text, square.right() + 10, square.centerY() + 4, label, tone);
    }
    deleteButton = SkRect::MakeEmpty();
    confirmDelete = SkRect::MakeEmpty();
    confirmKeep = SkRect::MakeEmpty();
    deleteSlide = app.deck.empty() ? -1 : app.current();
    if (confirmDeleteSlide >= 0 && confirmDeleteSlide != deleteSlide) {
        confirmDeleteSlide = -1;          // asked about a slide no longer on screen
    }
    // ── Delete this slide's recording? ───────────────────────────────
    // Asked in the row itself rather than in a dialog. The layout is the safety: keep sits
    // where the delete-recording button was, so a repeated click there keeps; the red
    // delete is at the far end of the row and dead for the first moments. Never one click.
    if (confirmDeleteSlide >= 0 && !app.timing.recording() && !app.reRecording) {
        SkFont label = uiFont(12, true);
        const float by = notesBottom + 6;
        const std::string question = deleteGoesToTrash
            ? "move " + narration.label + " and its transcript to the Trash?"
            : "delete " + narration.label + " and its transcript? this cannot be undone";
        const float kw = textWidth(label, "keep") + 24;
        confirmKeep = SkRect::MakeXYWH(pad, by, kw, 26);
        const bool khot = over(confirmKeep);
        pillButton(canvas, confirmKeep, "keep", label, ui::kPanel, khot ? ui::kText : ui::kDim, ui::kText);
        float x = confirmKeep.right() + 14;
        x += drawText(canvas, question, x, by + 17, label, ui::kWarn) + 40;
        const float dw = textWidth(label, "delete") + 24;
        confirmDelete = SkRect::MakeXYWH(x, by, dw, 26);
        const bool armed = glfwGetTime() - confirmShownAt >= kConfirmArmSec;
        const bool dhot = armed && over(confirmDelete);
        pillButton(canvas, confirmDelete, "delete", label, dhot ? ui::kOver : ui::kPanel,
                   armed ? ui::kOver : ui::kLine, dhot ? 0xFF1A0606 : (armed ? ui::kOver : ui::kLine));
    } else if (onRecordSlide && !app.timing.recording() && !app.deck.empty()) {
        SkFont label = uiFont(12, true);
        const std::string text = app.reRecording
            ? "stop recording"
            : "re-record slide " + std::to_string(app.current() + 1);
        const float bw = textWidth(label, text) + 44;
        const float by = notesBottom + 6;
        recordButton = SkRect::MakeXYWH(pad, by, bw, 26);

        const bool hot = over(recordButton);
        const SkColor tone = app.reRecording ? ui::kOver : (hot ? ui::kText : ui::kDim);
        fillRoundRect(canvas, recordButton, 13, ui::kPanel);
        strokeRoundRect(canvas, recordButton, 13,
                        app.reRecording ? ui::kOver : (hot ? ui::kDim : ui::kLine), 1.0f);

        // A filled dot, drawn rather than written: the chrome has one typeface and a record
        // glyph would come out as an empty box. It pulses while the take is running.
        SkPaint dot;
        dot.setAntiAlias(true);
        dot.setColor(app.reRecording ? ui::kOver : tone);
        if (app.reRecording) {
            dot.setAlphaf(0.45f + 0.55f * static_cast<float>(
                0.5 + 0.5 * std::sin(glfwGetTime() * 4.0)));
        }
        canvas->drawCircle(recordButton.left() + 17,
                           recordButton.centerY(), 5.5f, dot);
        drawText(canvas, text, recordButton.left() + 30,
                 recordButton.centerY() + 4, label, tone);

        if (!app.reRecording && onTranscribeSlide && showWave) {
            std::string ttext = "transcribe slide " + std::to_string(app.current() + 1);
            if (transcribing) {
                ttext = "transcribing\u2026";
                if (!transcribeStatus.empty()) ttext += "  " + transcribeStatus;
            }
            const float tw = textWidth(label, ttext) + 24;
            transcribeButton = SkRect::MakeXYWH(recordButton.right() + 8, by, tw, 26);
            const bool thot = over(transcribeButton) && !transcribing;
            pillButton(canvas, transcribeButton, ttext, label, ui::kPanel, thot ? ui::kDim : ui::kLine,
                       transcribing ? ui::kDim : (thot ? ui::kText : ui::kDim));
        } else {
            transcribeButton = SkRect::MakeEmpty();
        }
        if (!app.reRecording && onDeleteRecording && showWave && !transcribing) {
            const std::string dtext = "delete recording";
            const float dw = textWidth(label, dtext) + 24;
            const SkRect& before = transcribeButton.isEmpty() ? recordButton
                                                                     : transcribeButton;
            deleteButton = SkRect::MakeXYWH(before.right() + 8, by, dw, 26);
            const bool dhot = over(deleteButton);
            pillButton(canvas, deleteButton, dtext, label, ui::kPanel, dhot ? ui::kOver : ui::kLine,
                       dhot ? ui::kOver : ui::kDim);
        }
        if (app.reRecording) {
            const float dw = textWidth(label, "discard") + 24;
            discardButton =
                SkRect::MakeXYWH(recordButton.right() + 8, by, dw, 26);
            const bool dhot = over(discardButton);
            pillButton(canvas, discardButton, "discard", label, ui::kPanel, dhot ? ui::kDim : ui::kLine,
                       dhot ? ui::kText : ui::kDim);
        }
    }

}

void PresenterWindow::Impl::drawFooter(const Frame& F) {
    SkCanvas* canvas = F.canvas;
    App& app = *F.app;
    const Deck& deck = app.deck;
    const int w = F.w, h = F.h;
    const float pad = F.pad, fw = F.fw;
    const float barY = F.barY, panesTop = F.panesTop, panesH = F.panesH;
    const float notesTop = F.notesTop, notesBottom = F.notesBottom, progressH = F.progressH;
    const bool showLevels = F.showLevels, showRecord = F.showRecord, showWave = F.showWave;
    const float levelsH = F.levelsH, waveH = F.waveH;
    (void)deck; (void)w; (void)h; (void)pad; (void)fw; (void)barY; (void)panesTop; (void)panesH;
    (void)notesTop; (void)notesBottom; (void)progressH; (void)showLevels; (void)showRecord;
    (void)showWave; (void)levelsH; (void)waveH;

    // ── Progress ─────────────────────────────────────────────────────
    // Where you should be by now. A rehearsal is the better answer — it is what this talk
    // actually took — so it wins; the deck's own `:: section duration=` plan stands in when
    // there has been no rehearsal, which is every talk until the first one.
    float ghost = -1.0f;
    bool ghostIsPlan = false;
    if (!app.timing.empty() && !deck.empty() && app.clock.running) {
        double through = 0.0;
        std::string file = app.timing.positionAt(app.clock.elapsed, &through);
        int index = file.empty() ? -1 : deck.indexOfFile(file);
        if (index >= 0) {
            ghost = static_cast<float>((index + through) / deck.size());
        }
    } else if (!deck.empty() && app.clock.running) {
        ghost = plannedFraction(deck.plan(), deck.size(), app.clock.elapsed);
        ghostIsPlan = ghost >= 0.0f;
    }
    drawProgress(canvas, SkRect::MakeXYWH(pad, h - pad - progressH, fw, progressH), app, ghost,
                 ghostIsPlan);

    // The navigator, the help card and a pending jump live here rather than on the slide
    // window whenever this window is open.
    drawOverlays(canvas, app, w, h);

}

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

    Impl::Frame F;
    F.canvas = canvas;
    F.app = &app;
    F.w = w;
    F.h = h;
    F.pad = std::round(w * 0.022f);
    F.fw = w - F.pad * 2;
    F.barY = F.pad + std::round(h * 0.052f);
    mImpl->drawTopBar(F);

    F.panesTop = F.barY + std::round(h * 0.045f);
    F.panesH = std::round(h * 0.40f);
    mImpl->drawPanes(F, live);

    // What sits under the panes — the notes pane, the buttons row, the narration strip, the
    // meter, the progress bar — is laid out from the bottom up, each part claiming its
    // height only when it is shown.
    {
        const float pad = F.pad, panesTop = F.panesTop, panesH = F.panesH;
    // ── Notes ────────────────────────────────────────────────────────
    const float notesTop = panesTop + panesH + std::round(h * 0.055f);
    const float progressH = 6.0f;
    // The meter is up whenever the microphone is: for a whole rehearsal, and for a single
    // slide being recorded over.
    const bool showLevels = (app.timing.recording() && app.recordAudio) || app.reRecording;
    const float levelsH = showLevels ? 34.0f : 0.0f;
    // Room for the buttons row under the notes — the record button, or the stop button
    // while a whole run is being recorded — and for the meter when it is up.
    const bool showRecord = !app.timing.recording() || mImpl->onStopRun != nullptr;
    // The slide's narration, when it has one and the microphone is not on it: the shape of
    // what was said, its name and length, and where playback has got to.
    const bool showWave = mImpl->narration.envelope && !mImpl->narration.envelope->empty()
                          && !showLevels && !app.reRecording;
    const float waveH = showWave ? 72.0f : 0.0f;
    const float notesBottom = h - pad - progressH - 18 - (showLevels ? levelsH + 10 : 0.0f)
                              - (showRecord ? 34.0f : 0.0f) - (showWave ? waveH + 8 : 0.0f);
        F.notesTop = notesTop;
        F.notesBottom = notesBottom;
        F.progressH = progressH;
        F.showLevels = showLevels;
        F.levelsH = levelsH;
        F.showRecord = showRecord;
        F.showWave = showWave;
        F.waveH = waveH;
    }
    mImpl->drawPane(F);
    mImpl->drawMeter(F);
    mImpl->drawNarrationStrip(F);
    mImpl->drawButtonsRow(F);
    mImpl->drawFooter(F);

    mImpl->backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
