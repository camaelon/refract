#include "CaptionWindow.h"

#include "Ui.h"

#include "rcplayer/CpuRenderBackend.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <vector>

namespace refract {

struct CaptionWindow::Impl {
    CpuRenderBackend backend;
    int width = 0, height = 0;
    int fbWidth = 0, fbHeight = 0;
    float scroll = 0.0f;       // eased toward keeping the spoken line in view
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

struct PlacedWord {
    int index = 0;
    float x = 0, y = 0, width = 0;   // y is the baseline
};

// Lay the words out as wrapped running text. Words are placed individually rather than as
// wrapped lines of a string, because each one has to be coloured by whether it has been
// spoken yet — which means knowing where each one sits.
std::vector<PlacedWord> layout(const std::vector<CaptionWord>& words, const SkFont& font,
                               float maxWidth, float lineHeight, float* totalHeight) {
    std::vector<PlacedWord> placed;
    placed.reserve(words.size());
    const float spaceW = textWidth(font, " ");
    float x = 0, y = lineHeight;
    for (size_t i = 0; i < words.size(); i++) {
        const float w = textWidth(font, words[i].text);
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

void CaptionWindow::render(const App& app, const Captions& captions, double playbackTime,
                           bool playing) {
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

    float totalHeight = 0;
    std::vector<PlacedWord> placed = layout(captions.words(), font, maxWidth, lineHeight,
                                            &totalHeight);
    const int current = playing ? captions.wordAt(playbackTime) : -1;

    // Keep the line being spoken in view. Eased rather than jumped, so a long narration
    // scrolls instead of snapping a line at a time under the reader.
    const float viewTop = pad + 30;
    const float viewHeight = h - viewTop - pad;
    float target = 0.0f;
    if (totalHeight > viewHeight && current >= 0 && current < (int)placed.size()) {
        target = std::max(0.0f, placed[current].y - viewHeight * 0.45f);
        target = std::min(target, totalHeight - viewHeight + lineHeight);
    }
    mImpl->scroll += (target - mImpl->scroll) * 0.15f;

    canvas->save();
    canvas->clipRect(SkRect::MakeXYWH(0, viewTop, w, viewHeight));
    canvas->translate(pad, viewTop - mImpl->scroll);

    for (const auto& item : placed) {
        // Spoken words stay bright, the one being said is lit, and what is still to come is
        // dim — so the eye lands on the right place without reading anything.
        SkColor color = ui::kDim;
        if (current >= 0 && item.index < current) color = ui::kText;
        else if (item.index == current)           color = ui::kAccent;
        else if (current < 0 && !playing)         color = ui::kText;   // idle: plain transcript

        if (item.index == current) {
            SkRect box = SkRect::MakeXYWH(item.x - 4, item.y - size * 0.92f,
                                          item.width + 8, size * 1.22f);
            fillRoundRect(canvas, box, 4, 0x2E6EA8FF);
        }
        drawText(canvas, captions.words()[item.index].text, item.x, item.y, font, color);
    }
    canvas->restore();

    mImpl->backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
