#include "BuildPanel.h"

#include "Ui.h"

#include "rcplayer/CpuRenderBackend.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <iostream>
#include <vector>

namespace refract {

namespace {

constexpr float kPanelWidth = 300.0f;      // the column's natural width
constexpr float kRowHeight  = 26.0f;

// One clickable thing in the column, remembered from the last frame so the pointer has
// something to hit. A checkbox toggles a flag; the button and the close have their own ids.
struct Hit {
    SkRect rect;
    bool*  flag = nullptr;     // the option a click flips, or null
    int    action = 0;         // 1 = build
};

}  // namespace

struct BuildPanel::Impl {
    CpuRenderBackend backend;
    int width = 0, height = 0;
    int fbWidth = 0, fbHeight = 0;

    BuildOptions options;
    BuildState   state;
    std::function<bool(const BuildOptions&)> onBuild;

    GLFWwindow* host = nullptr;
    bool attached = true;
    bool watch = false;

    double mouseX = 0, mouseY = 0;
    std::vector<Hit> hits;

    // Where the panel sat before it was attached, so unchecking "attach" puts it back rather
    // than leaving it wherever the host happened to drag it.
    int freeX = 0, freeY = 0, freeH = 0;
    bool freeSaved = false;

    const Hit* hitAt(double x, double y) const {
        for (const auto& hit : hits) {
            if (hit.rect.contains(static_cast<float>(x), static_cast<float>(y))) return &hit;
        }
        return nullptr;
    }
};

std::unique_ptr<BuildPanel> BuildPanel::Create(int width, int height) {
    GLFWwindow* previous = glfwGetCurrentContext();

    glfwWindowHint(GLFW_DECORATED, GLFW_TRUE);
    glfwWindowHint(GLFW_TRANSPARENT_FRAMEBUFFER, GLFW_FALSE);
    glfwWindowHint(GLFW_FLOATING, GLFW_FALSE);
    glfwWindowHint(GLFW_FOCUSED, GLFW_TRUE);
    glfwWindowHint(GLFW_FOCUS_ON_SHOW, GLFW_TRUE);
    GLFWwindow* window = glfwCreateWindow(width, height, "refract — build", nullptr, nullptr);
    if (!window) {
        std::cerr << "build panel: window creation failed\n";
        if (previous) glfwMakeContextCurrent(previous);
        return nullptr;
    }

    auto panel = std::unique_ptr<BuildPanel>(new BuildPanel());
    panel->mWindow = window;
    panel->mImpl = std::make_unique<Impl>();

    glfwSetWindowUserPointer(window, panel.get());
    glfwSetCursorPosCallback(window, [](GLFWwindow* w, double x, double y) {
        auto* self = static_cast<BuildPanel*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        self->mImpl->mouseX = x;
        self->mImpl->mouseY = y;
    });
    glfwSetMouseButtonCallback(window, [](GLFWwindow* w, int button, int action, int) {
        auto* self = static_cast<BuildPanel*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl || button != GLFW_MOUSE_BUTTON_LEFT
            || action != GLFW_PRESS) {
            return;
        }
        Impl& impl = *self->mImpl;
        const Hit* hit = impl.hitAt(impl.mouseX, impl.mouseY);
        if (!hit) return;
        if (hit->flag) {
            *hit->flag = !*hit->flag;
            return;
        }
        // Nothing is started while a build is already running: refract writes into out/, and
        // two of them writing at once is the one way to get a deck that is neither.
        if (hit->action == 1 && !impl.state.running && impl.onBuild) {
            impl.state.running = impl.onBuild(impl.options);
        }
    });

    glfwMakeContextCurrent(window);
    glfwSwapInterval(0);
    panel->mImpl->backend.resize(width, height);
    panel->mImpl->width = width;
    panel->mImpl->height = height;

    if (previous) glfwMakeContextCurrent(previous);
    return panel;
}

BuildPanel::~BuildPanel() {
    if (mWindow) {
        GLFWwindow* previous = glfwGetCurrentContext();
        glfwMakeContextCurrent(mWindow);
        mImpl.reset();
        if (previous && previous != mWindow) glfwMakeContextCurrent(previous);
        glfwDestroyWindow(mWindow);
    }
}

bool BuildPanel::shouldClose() const {
    return mWindow && glfwWindowShouldClose(mWindow);
}

void BuildPanel::setOnBuild(std::function<bool(const BuildOptions&)> action) {
    mImpl->onBuild = std::move(action);
}

BuildOptions& BuildPanel::options() { return mImpl->options; }

void BuildPanel::setOptions(const BuildOptions& options) { mImpl->options = options; }

void BuildPanel::setState(const BuildState& state) { mImpl->state = state; }

void BuildPanel::setHost(GLFWwindow* host) { mImpl->host = host; }

bool BuildPanel::watching() const { return mImpl->watch; }

bool BuildPanel::handleKey(int key, int action, int mods) {
    if (action != GLFW_PRESS && action != GLFW_REPEAT) return false;
    Impl& impl = *mImpl;
    switch (key) {
        case GLFW_KEY_ENTER:
        case GLFW_KEY_KP_ENTER:
            if (!impl.state.running && impl.onBuild) {
                impl.state.running = impl.onBuild(impl.options);
            }
            return true;
        case GLFW_KEY_ESCAPE:
            glfwSetWindowShouldClose(mWindow, GLFW_TRUE);
            return true;
        default:
            return false;   // everything else still drives the talk
    }
}

namespace {

// A checkbox with its label and a line of explanation under it. Returns the y to carry on at.
float drawOption(SkCanvas* canvas, std::vector<Hit>& hits, float x, float y, float w,
                 const char* label, const char* note, bool* flag, bool enabled) {
    SkRect row = SkRect::MakeXYWH(x, y, w, kRowHeight);
    SkRect box = SkRect::MakeXYWH(x, y + 5, 15, 15);
    const SkColor tone = enabled ? ui::kText : ui::kDim;

    fillRoundRect(canvas, box, 3, *flag ? ui::kAccent : ui::kPanel);
    strokeRoundRect(canvas, box, 3, *flag ? ui::kAccent : ui::kLine, 1.0f);
    if (*flag) {
        // A tick drawn as two bars: the chrome renders through one typeface with no
        // fallback, and a check glyph is exactly the sort of thing that comes out as tofu.
        canvas->save();
        canvas->translate(box.centerX(), box.centerY());
        canvas->rotate(45);
        fillRect(canvas, SkRect::MakeXYWH(-1.5f, -4.5f, 3, 9), ui::kBg);
        fillRect(canvas, SkRect::MakeXYWH(-4.5f, 1.5f, 6, 3), ui::kBg);
        canvas->restore();
    }
    drawText(canvas, label, x + 24, y + 17, uiFont(13), tone);
    if (enabled) hits.push_back({row, flag, 0});

    float next = y + kRowHeight;
    if (note && *note) {
        SkFont small = uiFont(11);
        for (const auto& line : wrapText(note, small, w - 24)) {
            drawText(canvas, line, x + 24, next + 11, small, ui::kDim);
            next += 15;
        }
        next += 5;
    }
    return next;
}

std::string plural(int n, const char* one, const char* many) {
    return std::to_string(n) + " " + (n == 1 ? one : many);
}

}  // namespace

void BuildPanel::render(App& app) {
    if (!mWindow || !mImpl) return;
    Impl& impl = *mImpl;

    // ── Attach ───────────────────────────────────────────────────────
    // Tracked every frame rather than once: the host can be moved, resized, or closed while
    // the panel is up, and a column that drifts off its window is worse than one that floats.
    if (impl.attached && impl.host) {
        if (!impl.freeSaved) {
            glfwGetWindowPos(mWindow, &impl.freeX, &impl.freeY);
            int fw = 0;
            glfwGetWindowSize(mWindow, &fw, &impl.freeH);
            impl.freeSaved = true;
        }
        int hx = 0, hy = 0, hw = 0, hh = 0;
        glfwGetWindowPos(impl.host, &hx, &hy);
        glfwGetWindowSize(impl.host, &hw, &hh);
        int px = 0, py = 0, pw = 0, ph = 0;
        glfwGetWindowPos(mWindow, &px, &py);
        glfwGetWindowSize(mWindow, &pw, &ph);
        const int wantX = hx + hw, wantY = hy;
        if (px != wantX || py != wantY) glfwSetWindowPos(mWindow, wantX, wantY);
        if (ph != hh) glfwSetWindowSize(mWindow, pw, hh);
    } else if (!impl.attached && impl.freeSaved) {
        glfwSetWindowPos(mWindow, impl.freeX, impl.freeY);
        int pw = 0, ph = 0;
        glfwGetWindowSize(mWindow, &pw, &ph);
        glfwSetWindowSize(mWindow, pw, impl.freeH);
        impl.freeSaved = false;
    }

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
    impl.hits.clear();

    const float pad = 18;
    const float colW = w - pad * 2;
    float y = 34;

    // ── The deck ─────────────────────────────────────────────────────
    drawText(canvas, "Build", pad, y, uiFont(19, true), ui::kText);
    y += 22;
    drawText(canvas, ellipsize(app.deck.name(), uiFont(12), colW), pad, y, uiFont(12),
             ui::kDim);
    y += 16;
    drawText(canvas, plural(app.deck.size(), "slide", "slides"), pad, y, uiFont(12), ui::kDim);
    y += 26;
    fillRect(canvas, SkRect::MakeXYWH(pad, y, colW, 1), ui::kLine);
    y += 20;

    // ── Options ──────────────────────────────────────────────────────
    drawText(canvas, "OPTIONS", pad, y, uiFont(10, true), ui::kDim);
    y += 18;

    const bool idle = !impl.state.running;
    y = drawOption(canvas, impl.hits, pad, y, colW, "transitions",
                   "Crossfade, push and graph magic-move between slides.",
                   &impl.options.transitions, idle);
    y = drawOption(canvas, impl.hits, pad, y, colW, "debug outlines",
                   "A 1px red border on every component.",
                   &impl.options.debug, idle);
    y = drawOption(canvas, impl.hits, pad, y, colW, "keep intermediate JSON",
                   "Leave out/json/ in place instead of discarding it.",
                   &impl.options.keepJson, idle);
    y = drawOption(canvas, impl.hits, pad, y, colW, "force full rebuild",
                   "Recompile every slide. Builds are incremental otherwise, and only what "
                   "changed is recompiled.",
                   &impl.options.force, idle);

    y += 2;
    y = drawOption(canvas, impl.hits, pad, y, colW, "rebuild on change",
                   "Watch slides.md, settings.toml and includes/, and build when they change.",
                   &impl.watch, idle);

    y += 6;
    fillRect(canvas, SkRect::MakeXYWH(pad, y, colW, 1), ui::kLine);
    y += 20;

    // ── Rebuild ──────────────────────────────────────────────────────
    SkRect button = SkRect::MakeXYWH(pad, y, colW, 38);
    const bool hot = button.contains(static_cast<float>(impl.mouseX),
                                     static_cast<float>(impl.mouseY));
    const SkColor face = (!impl.state.running && hot) ? ui::kAccent : ui::kPanel;
    fillRoundRect(canvas, button, 8, face);
    strokeRoundRect(canvas, button, 8, impl.state.running ? ui::kLine : ui::kAccent, 1.5f);
    SkFont buttonFont = uiFont(14, true);
    const std::string label = impl.state.running ? "building…" : "Rebuild";
    drawTextCentred(canvas, label, button, buttonFont,
                    impl.state.running ? ui::kDim : (hot ? ui::kBg : ui::kText));
    if (!impl.state.running) impl.hits.push_back({button, nullptr, 1});
    y += 46;
    drawText(canvas, "Enter", pad, y, uiFont(10), ui::kDim);
    y += 24;

    // ── What the last build did ──────────────────────────────────────
    if (impl.state.ran || impl.state.running) {
        fillRect(canvas, SkRect::MakeXYWH(pad, y - 8, colW, 1), ui::kLine);
        y += 14;
        drawText(canvas, "LAST BUILD", pad, y, uiFont(10, true), ui::kDim);
        y += 20;
        if (impl.state.running) {
            drawText(canvas, impl.watch ? "a change landed — building…" : "running refract…",
                     pad, y, uiFont(13), ui::kText);
            y += 20;
        } else if (impl.state.ok) {
            // The reused count is the point of the incremental build, so it is said out loud
            // rather than left to be inferred from how long it took.
            drawText(canvas, plural(impl.state.rebuilt, "file", "files") + " rebuilt", pad, y,
                     uiFont(13), impl.state.rebuilt ? ui::kText : ui::kDim);
            y += 18;
            drawText(canvas, plural(impl.state.reused, "file", "files") + " reused", pad, y,
                     uiFont(13), ui::kAhead);
            y += 18;
            if (impl.state.removed) {
                drawText(canvas, plural(impl.state.removed, "file", "files") + " removed", pad,
                         y, uiFont(13), ui::kDim);
                y += 18;
            }
            char timing[64];
            std::snprintf(timing, sizeof(timing), "%.2fs", impl.state.seconds);
            drawText(canvas, timing, pad, y, uiFont(12), ui::kDim);
            y += 22;
        } else {
            SkFont small = uiFont(12);
            drawText(canvas, "build failed", pad, y, uiFont(13, true), ui::kOver);
            y += 18;
            for (const auto& line : wrapText(impl.state.error, small, colW)) {
                drawText(canvas, line, pad, y, small, ui::kDim);
                y += 16;
            }
            y += 6;
        }
    }

    // ── Attach ───────────────────────────────────────────────────────
    const float footer = h - 34;
    fillRect(canvas, SkRect::MakeXYWH(pad, footer - 14, colW, 1), ui::kLine);
    drawOption(canvas, impl.hits, pad, footer, colW, "attach to the panel", nullptr,
               &impl.attached, impl.host != nullptr);

    impl.backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
