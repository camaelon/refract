#include "ProcessingWindow.h"

#include "Ui.h"

#include "rcplayer/CpuRenderBackend.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"

#include <algorithm>
#include <cmath>
#include <iostream>

namespace refract {

struct ProcessingWindow::Impl {
    CpuRenderBackend backend;
    int width = 0, height = 0;
    int fbWidth = 0, fbHeight = 0;
};

std::unique_ptr<ProcessingWindow> ProcessingWindow::Create(int width, int height) {
    GLFWwindow* previous = glfwGetCurrentContext();
    glfwWindowHint(GLFW_DECORATED, GLFW_TRUE);
    glfwWindowHint(GLFW_TRANSPARENT_FRAMEBUFFER, GLFW_FALSE);
    glfwWindowHint(GLFW_FLOATING, GLFW_FALSE);
    // Not focused: it opens by itself when a task starts, and must not take the keyboard
    // from whatever window the talk is being driven from.
    glfwWindowHint(GLFW_FOCUSED, GLFW_FALSE);
    glfwWindowHint(GLFW_FOCUS_ON_SHOW, GLFW_FALSE);
    GLFWwindow* window = glfwCreateWindow(width, height, "refract — processing", nullptr, nullptr);
    if (!window) {
        std::cerr << "processing: window creation failed\n";
        if (previous) glfwMakeContextCurrent(previous);
        return nullptr;
    }
    auto self = std::unique_ptr<ProcessingWindow>(new ProcessingWindow());
    self->mWindow = window;
    self->mImpl = std::make_unique<Impl>();
    glfwMakeContextCurrent(window);
    glfwSwapInterval(0);
    self->mImpl->backend.resize(width, height);
    self->mImpl->width = width;
    self->mImpl->height = height;
    if (previous) glfwMakeContextCurrent(previous);
    return self;
}

ProcessingWindow::~ProcessingWindow() {
    if (mWindow) {
        GLFWwindow* previous = glfwGetCurrentContext();
        glfwMakeContextCurrent(mWindow);
        mImpl.reset();
        if (previous && previous != mWindow) glfwMakeContextCurrent(previous);
        glfwDestroyWindow(mWindow);
    }
}

bool ProcessingWindow::shouldClose() const { return mWindow && glfwWindowShouldClose(mWindow); }

void ProcessingWindow::render(const std::vector<TaskView>& tasks) {
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

    const float pad = 18.0f;
    SkFont title = uiFont(13, true);
    int running = 0;
    for (const auto& t : tasks) running += t.running ? 1 : 0;
    drawText(canvas, running ? (std::to_string(running) + (running == 1 ? " task running" : " tasks running"))
                             : "nothing running", pad, pad + 6, title, ui::kDim);

    if (tasks.empty()) {
        SkFont font = uiFont(14);
        const char* message = "exports and transcriptions show up here as they run";
        drawText(canvas, message, w * 0.5f - textWidth(font, message) * 0.5f, h * 0.5f, font, ui::kLine);
    }

    // One card per task: the name, what it is doing, and a bar — filling when the tool has
    // said how far it is, sweeping when it has not.
    float y = pad + 26;
    const float rowH = 74.0f;
    SkFont nameFont = uiFont(14, true);
    SkFont statusFont = uiFont(12);
    for (const auto& t : tasks) {
        if (y + rowH > h) break;
        SkRect card = SkRect::MakeXYWH(pad, y, w - pad * 2, rowH - 8);
        fillRoundRect(canvas, card, 6, ui::kPanel);
        drawText(canvas, ellipsize(t.name, nameFont, card.width() - 24), card.left() + 12, card.top() + 22, nameFont,
                 t.failed ? ui::kOver : ui::kText);
        const SkColor statusTone = t.failed ? ui::kOver : (t.running ? ui::kDim : ui::kAhead);
        drawText(canvas, ellipsize(t.status, statusFont, card.width() - 24), card.left() + 12, card.top() + 40,
                 statusFont, statusTone);
        SkRect track = SkRect::MakeXYWH(card.left() + 12, card.top() + 50, card.width() - 24, 6);
        fillRoundRect(canvas, track, 3, ui::kLine);
        if (!t.running) {
            fillRoundRect(canvas, track, 3, t.failed ? ui::kOver : ui::kAhead);
        } else if (t.fraction >= 0.0f) {
            const float bw = std::max(6.0f, track.width() * std::min(1.0f, t.fraction));
            fillRoundRect(canvas, SkRect::MakeXYWH(track.left(), track.top(), bw, 6), 3, ui::kAccent);
            char pct[16];
            std::snprintf(pct, sizeof(pct), "%d%%", static_cast<int>(std::lround(std::min(1.0f, t.fraction) * 100)));
            drawTextRight(canvas, pct, card.right() - 12, card.top() + 22, statusFont, ui::kDim);
        } else {
            const float span = track.width() - 60;
            const float p = static_cast<float>(std::fmod(glfwGetTime(), 2.0) / 2.0);
            const float x = track.left() + span * (p < 0.5f ? p * 2 : (1 - p) * 2);
            fillRoundRect(canvas, SkRect::MakeXYWH(x, track.top(), 60, 6), 3, ui::kAccent);
        }
        y += rowH;
    }

    mImpl->backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
