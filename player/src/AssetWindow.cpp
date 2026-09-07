#include "AssetWindow.h"

#include "Ui.h"

#include "rcplayer/CpuRenderBackend.h"
#include "rcplayer/MediaTypes.h"
#include "rcplayer/Player.h"

#include "include/core/SkImage.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"
#include "include/core/SkData.h"
#include "include/core/SkImage.h"
#include "include/core/SkRRect.h"
#include "include/core/SkSamplingOptions.h"

#include <algorithm>
#include <cmath>
#include <cstdio>
#include <iostream>
#include <map>

namespace refract {

namespace {

constexpr float kHeaderH = 74.0f;
constexpr float kRowH    = 44.0f;
constexpr float kPreview = 34.0f;   // the thumbnail down the left of a row

// "1.4 MB", "812 KB", "377 B" — a size somebody can act on rather than count digits in.
std::string humanSize(long long bytes) {
    char buf[32];
    if (bytes >= 1024 * 1024) std::snprintf(buf, sizeof(buf), "%.1f MB", bytes / 1048576.0);
    else if (bytes >= 1024)   std::snprintf(buf, sizeof(buf), "%lld KB", bytes / 1024);
    else                      std::snprintf(buf, sizeof(buf), "%lld B", bytes);
    return buf;
}

// Which slides use it, in the space a row has. "slides 1, 4, 9" — and past a few, a count,
// because the list stops meaning anything once it wraps.
std::string usedLabel(const Asset& asset) {
    if (asset.slides.empty()) return "unused";
    std::vector<int> real;
    bool settings = false;
    for (int n : asset.slides) {
        if (n == 0) settings = true;
        else real.push_back(n);
    }
    if (real.empty()) return settings ? "the deck's settings" : "unused";
    if (real.size() > 4) return std::to_string(real.size()) + " slides";
    std::string out = real.size() == 1 ? "slide " : "slides ";
    for (size_t i = 0; i < real.size(); i++) {
        if (i) out += ", ";
        out += std::to_string(real[i]);
    }
    if (settings) out += " + settings";
    return out;
}

SkColor kindColour(const std::string& kind) {
    if (kind == "image") return ui::kAhead;
    if (kind == "video") return ui::kWarn;
    if (kind == "deck") return ui::kInclude;
    if (kind == "shader") return ui::kOver;
    return ui::kAccent;
}

}  // namespace

struct AssetWindow::Impl {
    CpuRenderBackend backend;
    int width = 0, height = 0;
    int fbWidth = 0, fbHeight = 0;

    Scanner scanner;
    Remover remover;

    std::vector<Asset> assets;
    std::string error;
    std::string status;
    bool statusError = false;

    int cursor = 0;
    int armedRemove = -1;      // the row a second ⌫ would remove
    float scroll = 0.0f, scrollMax = 0.0f;
    double mouseX = 0, mouseY = 0;
    int hover = -1;
    std::vector<SkRect> rows;
    SkRect removeButton = SkRect::MakeEmpty();

    // Decoded previews, by path. Images only, and only the ones on screen — a folder of 4K
    // screenshots should not be decoded because a window opened.
    std::map<std::string, sk_sp<SkImage>> previews;
    std::string deckDir;

    void setStatus(const std::string& text, bool bad) { status = text; statusError = bad; }

    sk_sp<SkImage> preview(const std::string& relative) {
        auto it = previews.find(relative);
        if (it != previews.end()) return it->second;
        sk_sp<SkImage> image;
        std::vector<uint8_t> bytes;
        if (!deckDir.empty()
            && rcplayer::readFileBytes(deckDir + "/" + relative, bytes) && !bytes.empty()) {
            image = SkImages::DeferredFromEncodedData(
                SkData::MakeWithCopy(bytes.data(), bytes.size()));
        }
        previews[relative] = image;   // a null is remembered too: it failed once, it will again
        return image;
    }
};

std::unique_ptr<AssetWindow> AssetWindow::Create(int width, int height) {
    GLFWwindow* previous = glfwGetCurrentContext();

    glfwWindowHint(GLFW_DECORATED, GLFW_TRUE);
    glfwWindowHint(GLFW_FOCUSED, GLFW_TRUE);
    GLFWwindow* window = glfwCreateWindow(width, height, "refract — assets", nullptr, nullptr);
    if (!window) {
        std::cerr << "assets: window creation failed\n";
        if (previous) glfwMakeContextCurrent(previous);
        return nullptr;
    }

    auto view = std::unique_ptr<AssetWindow>(new AssetWindow());
    view->mWindow = window;
    view->mImpl = std::make_unique<Impl>();

    glfwSetWindowUserPointer(window, view.get());
    glfwSetCursorPosCallback(window, [](GLFWwindow* w, double x, double y) {
        auto* self = static_cast<AssetWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        self->mImpl->mouseX = x;
        self->mImpl->mouseY = y;
    });
    glfwSetScrollCallback(window, [](GLFWwindow* w, double, double dy) {
        auto* self = static_cast<AssetWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        Impl& impl = *self->mImpl;
        impl.scroll = std::max(0.0f, std::min(impl.scrollMax,
                                              impl.scroll - static_cast<float>(dy) * 44.0f));
    });
    glfwSetMouseButtonCallback(window, [](GLFWwindow* w, int button, int action, int) {
        auto* self = static_cast<AssetWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl || button != GLFW_MOUSE_BUTTON_LEFT
            || action != GLFW_PRESS) {
            return;
        }
        Impl& impl = *self->mImpl;
        const float x = static_cast<float>(impl.mouseX), y = static_cast<float>(impl.mouseY);
        if (impl.removeButton.contains(x, y)) {
            self->handleKey(GLFW_KEY_BACKSPACE, GLFW_PRESS, 0);
            return;
        }
        for (size_t i = 0; i < impl.rows.size(); i++) {
            if (!impl.rows[i].contains(x, y)) continue;
            impl.cursor = static_cast<int>(i);
            impl.armedRemove = -1;    // a new selection is not a confirmation of the old one
            return;
        }
    });

    glfwMakeContextCurrent(window);
    glfwSwapInterval(0);
    view->mImpl->backend.resize(width, height);
    view->mImpl->width = width;
    view->mImpl->height = height;

    if (previous) glfwMakeContextCurrent(previous);
    return view;
}

AssetWindow::~AssetWindow() {
    if (mWindow) {
        GLFWwindow* previous = glfwGetCurrentContext();
        glfwMakeContextCurrent(mWindow);
        mImpl.reset();
        if (previous && previous != mWindow) glfwMakeContextCurrent(previous);
        glfwDestroyWindow(mWindow);
    }
}

bool AssetWindow::shouldClose() const {
    return mWindow && glfwWindowShouldClose(mWindow);
}

void AssetWindow::setScanner(Scanner scanner) { mImpl->scanner = std::move(scanner); }
void AssetWindow::setRemover(Remover remover) { mImpl->remover = std::move(remover); }

void AssetWindow::refresh() {
    Impl& impl = *mImpl;
    if (!impl.scanner) return;
    std::vector<Asset> found;
    std::string dir, error;
    if (impl.scanner(&found, &dir, &error)) {
        impl.assets = std::move(found);
        impl.deckDir = dir;
        impl.error.clear();
    } else {
        impl.assets.clear();
        impl.error = error.empty() ? "cannot read this deck's assets" : error;
    }
    impl.cursor = std::max(0, std::min(impl.cursor,
                                       static_cast<int>(impl.assets.size()) - 1));
    impl.armedRemove = -1;
    impl.previews.clear();
}

bool AssetWindow::handleKey(int key, int action, int mods) {
    if (action != GLFW_PRESS && action != GLFW_REPEAT) return false;
    Impl& impl = *mImpl;
    const int last = static_cast<int>(impl.assets.size()) - 1;

    if (key != GLFW_KEY_BACKSPACE && key != GLFW_KEY_DELETE) impl.armedRemove = -1;

    switch (key) {
        case GLFW_KEY_UP:    impl.cursor = std::max(0, impl.cursor - 1); return true;
        case GLFW_KEY_DOWN:  impl.cursor = std::min(last, impl.cursor + 1); return true;
        case GLFW_KEY_HOME:  impl.cursor = 0; return true;
        case GLFW_KEY_END:   impl.cursor = std::max(0, last); return true;
        case GLFW_KEY_R:     refresh(); return true;
        case GLFW_KEY_ESCAPE:
            glfwSetWindowShouldClose(mWindow, GLFW_TRUE);
            return true;
        case GLFW_KEY_BACKSPACE:
        case GLFW_KEY_DELETE: {
            if (impl.cursor < 0 || impl.cursor > last || !impl.remover) return true;
            const Asset& asset = impl.assets[impl.cursor];
            if (impl.armedRemove != impl.cursor) {
                impl.armedRemove = impl.cursor;
                impl.setStatus(asset.used
                    ? "used by " + usedLabel(asset) + " — press again to move it out anyway"
                    : "move " + asset.name + " to the trash? press again", asset.used);
                return true;
            }
            impl.armedRemove = -1;
            std::string status;
            const bool ok = impl.remover(asset.path, &status);
            impl.setStatus(status, !ok);
            if (ok) refresh();
            return true;
        }
        default:
            return false;   // everything else still drives the talk
    }
}

void AssetWindow::render(App& app) {
    if (!mWindow || !mImpl) return;
    Impl& impl = *mImpl;
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

    const float pad = 20;
    long long total = 0, wasted = 0;
    int unused = 0;
    for (const Asset& a : impl.assets) {
        total += a.size;
        if (!a.used) { unused++; wasted += a.size; }
    }

    // ── Header ───────────────────────────────────────────────────────
    drawText(canvas, "Assets", pad, 32, uiFont(19, true), ui::kText);
    drawText(canvas, app.deck.name(), pad + textWidth(uiFont(19, true), "Assets") + 12, 32,
             uiFont(12), ui::kDim);
    char summary[128];
    std::snprintf(summary, sizeof(summary), "%d files   %s",
                  static_cast<int>(impl.assets.size()), humanSize(total).c_str());
    drawTextRight(canvas, summary, w - pad, 32, uiFont(13), ui::kDim);
    if (unused) {
        char note[128];
        std::snprintf(note, sizeof(note), "%d unused   %s", unused, humanSize(wasted).c_str());
        drawTextRight(canvas, note, w - pad, 52, uiFont(12), ui::kWarn);
    }
    drawText(canvas, "up/down selects  ~  backspace moves one to the trash  ~  R rescans",
             pad, 52, uiFont(11), ui::kDim);
    fillRect(canvas, SkRect::MakeXYWH(0, kHeaderH - 1, w, 1), ui::kLine);

    if (!impl.status.empty()) {
        drawText(canvas, ellipsize(impl.status, uiFont(12), w - pad * 2), pad, h - 14,
                 uiFont(12), impl.statusError ? ui::kOver : ui::kAhead);
    }

    // ── Rows ─────────────────────────────────────────────────────────
    const float listBottom = h - (impl.status.empty() ? 8.0f : 28.0f);
    const float viewH = listBottom - kHeaderH;
    impl.scrollMax = std::max(0.0f, impl.assets.size() * kRowH - viewH + 8);

    {   // Keep the cursor in view when it has been moved by a key.
        const float top = impl.cursor * kRowH;
        if (top < impl.scroll) impl.scroll = top;
        else if (top + kRowH > impl.scroll + viewH) impl.scroll = top + kRowH - viewH;
        impl.scroll = std::max(0.0f, std::min(impl.scrollMax, impl.scroll));
    }

    canvas->save();
    canvas->clipRect(SkRect::MakeLTRB(0, kHeaderH, w, listBottom));
    impl.rows.assign(impl.assets.size(), SkRect::MakeEmpty());
    impl.hover = -1;

    for (size_t i = 0; i < impl.assets.size(); i++) {
        const Asset& asset = impl.assets[i];
        const float y = kHeaderH + i * kRowH - impl.scroll;
        SkRect row = SkRect::MakeLTRB(pad, y + 3, w - pad, y + kRowH - 3);
        impl.rows[i] = row;
        if (row.bottom() < kHeaderH || row.top() > listBottom) continue;

        const bool selected = static_cast<int>(i) == impl.cursor;
        const bool hot = row.contains(static_cast<float>(impl.mouseX),
                                      static_cast<float>(impl.mouseY));
        if (hot) impl.hover = static_cast<int>(i);
        if (selected) fillRoundRect(canvas, row, 6, ui::kPanel);
        else if (hot) fillRoundRect(canvas, row, 6, withAlpha(ui::kPanel, 0x80));

        // A thumbnail for what has one; a coloured chip naming the kind for what does not.
        SkRect box = SkRect::MakeXYWH(row.left() + 8, row.centerY() - kPreview * 0.5f,
                                      kPreview * 1.6f, kPreview);
        sk_sp<SkImage> image = asset.kind == "image" ? impl.preview(asset.path) : nullptr;
        if (image) {
            fillRoundRect(canvas, box, 4, ui::kBg);
            canvas->save();
            canvas->clipRRect(SkRRect::MakeRectXY(box, 4, 4), true);
            drawImageFit(canvas, image, box);
            canvas->restore();
        } else {
            fillRoundRect(canvas, box, 4, ui::kBg);
            strokeRoundRect(canvas, box, 4, ui::kLine, 1.0f);
            drawTextCentred(canvas, asset.kind, box, uiFont(9, true), kindColour(asset.kind));
        }

        const float textLeft = box.right() + 12;
        const float baseline = row.centerY() - 1;
        const SkColor tone = asset.used ? ui::kText : ui::kDim;
        const std::string name = ellipsize(asset.name, uiFont(14, true), w - textLeft - 260);
        drawText(canvas, name, textLeft, baseline, uiFont(14, true), tone);
        // The folder it is in, when it is not the top one — a sub-deck's assets are its own,
        // and two decks can each have a diagram.png. Beside the name rather than under it:
        // the second line of a row belongs to what uses the file.
        std::string folder = asset.path.substr(0, asset.path.rfind('/') + 1);
        if (folder != "includes/") {
            if (folder.rfind("includes/", 0) == 0) folder = folder.substr(9);
            if (!folder.empty()) folder.pop_back();      // the trailing slash
            drawText(canvas, folder, textLeft + textWidth(uiFont(14, true), name) + 8, baseline,
                     uiFont(11), ui::kDim);
        }
        drawText(canvas, usedLabel(asset), textLeft, baseline + 14,
                 uiFont(11), asset.used ? ui::kDim : ui::kWarn);
        drawTextRight(canvas, humanSize(asset.size), row.right() - 14, baseline, uiFont(12),
                      ui::kDim);
    }
    canvas->restore();

    if (impl.assets.empty()) {
        const std::string message = impl.error.empty()
            ? "nothing in includes/ — images, sub-decks and clips live there"
            : impl.error;
        drawText(canvas, message, pad, kHeaderH + 34, uiFont(13),
                 impl.error.empty() ? ui::kLine : ui::kOver);
    }

    // The button beside the keyboard's ⌫, so removing is not a key you have to know.
    impl.removeButton = SkRect::MakeEmpty();
    if (!impl.assets.empty() && impl.cursor >= 0
        && impl.cursor < static_cast<int>(impl.assets.size())) {
        SkFont label = uiFont(11, true);
        const bool armed = impl.armedRemove == impl.cursor;
        const std::string text = armed ? "move it — sure?" : "move to trash";
        const float bw = textWidth(label, text) + 24;
        impl.removeButton = SkRect::MakeXYWH(w - pad - bw, h - 30, bw, 22);
        const bool hot = impl.removeButton.contains(static_cast<float>(impl.mouseX),
                                                    static_cast<float>(impl.mouseY));
        fillRoundRect(canvas, impl.removeButton, 11, ui::kPanel);
        strokeRoundRect(canvas, impl.removeButton, 11,
                        armed ? ui::kOver : (hot ? ui::kDim : ui::kLine), 1.0f);
        drawTextCentred(canvas, text, impl.removeButton, label,
                        armed ? ui::kOver : (hot ? ui::kText : ui::kDim));
    }

    impl.backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
