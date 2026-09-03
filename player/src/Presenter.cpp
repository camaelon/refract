#include "Presenter.h"

#include "Navigator.h"
#include "Thumbs.h"
#include "Ui.h"

#include "rcplayer/CpuRenderBackend.h"
#include "rcplayer/Player.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"

#include <algorithm>
#include <cmath>
#include <iostream>

namespace refract {

struct PresenterWindow::Impl {
    CpuRenderBackend backend;
    int width = 0, height = 0;
    int fbWidth = 0, fbHeight = 0;
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
// at a glance, and where in it you are.
void drawProgress(SkCanvas* canvas, const SkRect& r, const App& app) {
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
    if (!app.clock.running) {
        drawText(canvas, "PAUSED", timerX, barY + 18, uiFont(11, true), ui::kWarn);
    } else if (countdown) {
        // The elapsed time stays visible underneath: it is what you compare against the
        // deck's progress bar to tell whether you are ahead of the material or behind it.
        drawText(canvas, "elapsed " + formatDuration(app.clock.elapsed), timerX, barY + 18,
                 uiFont(11), ui::kDim);
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
    const float notesBottom = h - pad - progressH - 18;
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

    // ── Progress ─────────────────────────────────────────────────────
    drawProgress(canvas, SkRect::MakeXYWH(pad, h - pad - progressH, fw, progressH), app);

    // The navigator, the help card and a pending jump live here rather than on the slide
    // window whenever this window is open.
    drawOverlays(canvas, app, w, h);

    mImpl->backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
