#include "CaptionWindow.h"

#include "Ui.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"

#include <iostream>

namespace refract {

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
        self->mImpl->view.mouseMove(static_cast<float>(x), static_cast<float>(y));
    });
    glfwSetMouseButtonCallback(window, [](GLFWwindow* w, int button, int action, int) {
        if (button != GLFW_MOUSE_BUTTON_LEFT || action != GLFW_PRESS) return;
        auto* self = static_cast<CaptionWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        const bool shift = (glfwGetKey(w, GLFW_KEY_LEFT_SHIFT) == GLFW_PRESS
                            || glfwGetKey(w, GLFW_KEY_RIGHT_SHIFT) == GLFW_PRESS);
        self->mImpl->view.click(static_cast<float>(self->mImpl->mouseX),
                                static_cast<float>(self->mImpl->mouseY), shift);
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

bool CaptionWindow::isEditing() const { return mImpl && mImpl->view.isEditing(); }
void CaptionWindow::finishEditing() { if (mImpl) mImpl->view.finishEditing(); }
void CaptionWindow::setOnEditingChanged(std::function<void(bool)> action) {
    mImpl->view.setOnEditingChanged(std::move(action));
}
bool CaptionWindow::handleKey(int key, int action, int mods) {
    return mImpl && mImpl->view.handleKey(key, action, mods);
}
void CaptionWindow::handleChar(unsigned int codepoint) {
    if (mImpl) mImpl->view.handleChar(codepoint);
}

void CaptionWindow::render(const App& app, Captions& captions, double playbackTime, bool playing) {
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
    mImpl->view.draw(canvas, SkRect::MakeWH(static_cast<float>(w), static_cast<float>(h)), app,
                     captions, playbackTime, playing, /*header=*/true);
    mImpl->backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
