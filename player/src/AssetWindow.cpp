#include "AssetWindow.h"

#include "Scrolling.h"
#include "Thumbs.h"
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
#include "include/core/SkPathBuilder.h"
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
// The pane down the right, showing the selected asset at a size worth looking at. Dropped
// when the window is too narrow for it and the list — the list is what the window is for.
constexpr float kPaneW   = 250.0f;
constexpr float kPaneMinList = 300.0f;

// What the still worker can turn into a picture, as opposed to what is decoded here. A
// document is the deck's own format and a clip contributes its opening frame; both are the
// engine's work, on its thread.
bool renderable(const std::string& path) {
    const std::string ext = rcplayer::getExt(path);
    return ext == ".rc" || ext == ".rcd" || ext == ".json"
           || rcplayer::isCodecVideoExt(ext) || rcplayer::isAvfVideoExt(ext);
}

bool isClip(const std::string& path) {
    const std::string ext = rcplayer::getExt(path);
    return rcplayer::isCodecVideoExt(ext) || rcplayer::isAvfVideoExt(ext);
}

// A ▸ over the corner of a frame, so a clip does not read as a photograph.
void drawClipMark(SkCanvas* canvas, const SkRect& over) {
    const float r = std::min(11.0f, over.height() * 0.18f);
    if (r < 4) return;
    const float cx = over.right() - r - 5, cy = over.bottom() - r - 5;
    SkPaint paint;
    paint.setAntiAlias(true);
    paint.setColor(withAlpha(SK_ColorBLACK, 0xA0));
    canvas->drawCircle(cx, cy, r, paint);
    SkPathBuilder play;
    play.moveTo(cx - r * 0.28f, cy - r * 0.5f);
    play.lineTo(cx + r * 0.5f, cy);
    play.lineTo(cx - r * 0.28f, cy + r * 0.5f);
    play.close();
    paint.setColor(SK_ColorWHITE);
    canvas->drawPath(play.detach(), paint);
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
    // Set when the cursor is *moved*, and cleared by the render that scrolls to it. Without
    // it the list scrolls back to the selection on every frame, which quietly undoes the
    // wheel: scrolling away from the selection lasts until the next redraw and no longer.
    bool followCursor = false;
    double lastScrollAt = -1.0;             // for the full-rate redraw while it is moving
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
    SkRect pane = SkRect::MakeEmpty();      // where the preview column is, when there is one

    std::string fullPath(const std::string& relative) const {
        return deckDir.empty() ? std::string() : deckDir + "/" + relative;
    }

    // The picture for an asset at this size: decoded here for an image, rendered by the
    // still worker for a document or a clip. Null while the worker is still on it.
    sk_sp<SkImage> pictureOf(const Asset& asset, int side, bool urgent) {
        if (asset.kind == "image") return preview(asset.path);
        if (!renderable(asset.path) || deckDir.empty()) return nullptr;
        return urgent ? thumbIfReady(fullPath(asset.path), side, side)
                      : thumbCached(fullPath(asset.path), side, side);
    }

    void setStatus(const std::string& text, bool bad) { status = text; statusError = bad; }

    void moveCursor(int to) {
        cursor = to;
        followCursor = true;
    }

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
                                              impl.scroll - scrollPixels(dy, kRowH)));
        impl.lastScrollAt = glfwGetTime();
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
            impl.moveCursor(static_cast<int>(i));
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

bool AssetWindow::scrolling() const {
    return mImpl && mImpl->lastScrollAt > 0
           && glfwGetTime() - mImpl->lastScrollAt < kScrollingFor;
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
    impl.moveCursor(std::max(0, std::min(impl.cursor,
                                         static_cast<int>(impl.assets.size()) - 1)));
    impl.armedRemove = -1;
    // Nothing about a file survives a rescan: it may be a different file under the same
    // name, and a still of what it used to be is worse than none.
    std::vector<std::string> stale;
    for (const Asset& asset : impl.assets) stale.push_back(impl.fullPath(asset.path));
    dropThumbs(stale);
    impl.previews.clear();
}

bool AssetWindow::handleKey(int key, int action, int mods) {
    if (action != GLFW_PRESS && action != GLFW_REPEAT) return false;
    Impl& impl = *mImpl;
    const int last = static_cast<int>(impl.assets.size()) - 1;

    if (key != GLFW_KEY_BACKSPACE && key != GLFW_KEY_DELETE) impl.armedRemove = -1;

    switch (key) {
        case GLFW_KEY_UP:    impl.moveCursor(std::max(0, impl.cursor - 1)); return true;
        case GLFW_KEY_DOWN:  impl.moveCursor(std::min(last, impl.cursor + 1)); return true;
        case GLFW_KEY_HOME:  impl.moveCursor(0); return true;
        case GLFW_KEY_END:   impl.moveCursor(std::max(0, last)); return true;
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
                  static_cast<int>(impl.assets.size()), humanBytes(total).c_str());
    drawTextRight(canvas, summary, w - pad, 32, uiFont(13), ui::kDim);
    if (unused) {
        char note[128];
        std::snprintf(note, sizeof(note), "%d unused   %s", unused, humanBytes(wasted).c_str());
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
    // The pane down the right takes its width off the list. Below a certain width there is
    // no room for both, and the list wins: this window is a list first.
    const bool withPane = w - kPaneW - pad >= kPaneMinList && !impl.assets.empty();
    const float listRight = withPane ? w - kPaneW - pad : w - pad;
    const float listBottom = h - (impl.status.empty() ? 8.0f : 28.0f);
    const float viewH = listBottom - kHeaderH;
    impl.scrollMax = std::max(0.0f, impl.assets.size() * kRowH - viewH + 8);

    if (impl.followCursor) {   // ...only when it was actually moved. See followCursor.
        impl.followCursor = false;
        const float top = impl.cursor * kRowH;
        if (top < impl.scroll) impl.scroll = top;
        else if (top + kRowH > impl.scroll + viewH) impl.scroll = top + kRowH - viewH;
    }
    impl.scroll = std::max(0.0f, std::min(impl.scrollMax, impl.scroll));

    canvas->save();
    canvas->clipRect(SkRect::MakeLTRB(0, kHeaderH, listRight, listBottom));
    impl.rows.assign(impl.assets.size(), SkRect::MakeEmpty());
    impl.hover = -1;

    for (size_t i = 0; i < impl.assets.size(); i++) {
        const Asset& asset = impl.assets[i];
        const float y = kHeaderH + i * kRowH - impl.scroll;
        SkRect row = SkRect::MakeLTRB(pad, y + 3, listRight, y + kRowH - 3);
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
        // Asked for unhurriedly: a list scrolling past should not push the row under the
        // cursor out of the queue, and a row with no picture yet simply shows its kind.
        const int rowSide = static_cast<int>(kPreview * 1.6f);
        sk_sp<SkImage> image = impl.pictureOf(asset, rowSide, /*urgent=*/false);
        if (!image && renderable(asset.path) && !impl.deckDir.empty()) {
            requestThumb(impl.fullPath(asset.path), rowSide, rowSide);
        }
        if (image) {
            fillRoundRect(canvas, box, 4, ui::kBg);
            canvas->save();
            canvas->clipRRect(SkRRect::MakeRectXY(box, 4, 4), true);
            const SkRect drawn = drawImageFit(canvas, image, box);
            if (isClip(asset.path)) drawClipMark(canvas, drawn);
            canvas->restore();
        } else {
            fillRoundRect(canvas, box, 4, ui::kBg);
            strokeRoundRect(canvas, box, 4, ui::kLine, 1.0f);
            drawTextCentred(canvas, asset.kind, box, uiFont(9, true), kindColour(asset.kind));
        }

        const float textLeft = box.right() + 12;
        const float baseline = row.centerY() - 1;
        const SkColor tone = asset.used ? ui::kText : ui::kDim;
        const std::string name = ellipsize(asset.name, uiFont(14, true),
                                           row.right() - textLeft - 90);
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
        drawTextRight(canvas, humanBytes(asset.size), row.right() - 14, baseline, uiFont(12),
                      ui::kDim);
    }
    canvas->restore();

    // ── The preview pane ─────────────────────────────────────────────
    // What the row under the cursor actually is, at a size worth looking at: a row's
    // thumbnail is enough to tell two photographs apart and not enough for anything else,
    // and a deck is mostly documents.
    impl.pane = SkRect::MakeEmpty();
    if (withPane && impl.cursor >= 0 && impl.cursor < static_cast<int>(impl.assets.size())) {
        const Asset& asset = impl.assets[impl.cursor];
        impl.pane = SkRect::MakeLTRB(listRight + pad * 0.5f, kHeaderH + 12, w - pad,
                                     h - 38);   // clear of the trash button
        fillRect(canvas, SkRect::MakeXYWH(listRight + 4, kHeaderH, 1,
                                          listBottom - kHeaderH), ui::kLine);

        const float side = impl.pane.width();
        const SkRect art = SkRect::MakeXYWH(impl.pane.left(), impl.pane.top(), side, side);
        fillRoundRect(canvas, art, 6, ui::kBg);
        strokeRoundRect(canvas, art, 6, ui::kLine, 1.0f);

        // Urgent here: this is the one the cursor is on, and the rows behind it are
        // speculative by comparison.
        sk_sp<SkImage> image = impl.pictureOf(asset, static_cast<int>(side), /*urgent=*/true);
        std::string measured;
        if (image) {
            canvas->save();
            canvas->clipRRect(SkRRect::MakeRectXY(art.makeInset(1, 1), 6, 6), true);
            const SkRect drawn = drawImageFit(canvas, image, art.makeInset(6, 6));
            if (isClip(asset.path)) drawClipMark(canvas, drawn);
            canvas->restore();
            // A document's still is square because the pane is; only a picture's own size
            // is worth reporting.
            if (asset.kind == "image" || isClip(asset.path)) {
                measured = std::to_string(image->width()) + " × "
                           + std::to_string(image->height());
            }
        } else {
            drawTextCentred(canvas, renderable(asset.path) ? "rendering…" : asset.kind, art,
                            uiFont(12, true),
                            renderable(asset.path) ? ui::kDim : kindColour(asset.kind));
        }

        float y = art.bottom() + 22;
        drawText(canvas, ellipsize(asset.name, uiFont(13, true), impl.pane.width()),
                 impl.pane.left(), y, uiFont(13, true), ui::kText);
        y += 16;
        drawText(canvas, ellipsize(asset.path, uiFont(10), impl.pane.width()),
                 impl.pane.left(), y, uiFont(10), withAlpha(ui::kDim, 0xC0));
        y += 18;
        std::string facts = asset.kind + "   " + humanBytes(asset.size);
        if (!measured.empty()) facts += "   " + measured;
        drawText(canvas, facts, impl.pane.left(), y, uiFont(11), ui::kDim);
        y += 20;
        // The whole list, not the row's four: the pane has the room, and "which slides
        // would I break" is the question somebody about to delete something is asking.
        drawText(canvas, asset.used ? "used by" : "used by nothing", impl.pane.left(), y,
                 uiFont(11, true), asset.used ? ui::kDim : ui::kWarn);
        y += 15;
        std::string line;
        for (int slide : asset.slides) {
            const std::string one = slide == 0 ? "settings" : "slide " + std::to_string(slide);
            const std::string next = line.empty() ? one : line + ", " + one;
            if (textWidth(uiFont(11), next) > impl.pane.width()) {
                drawText(canvas, line, impl.pane.left(), y, uiFont(11), ui::kDim);
                y += 14;
                line = one;
                if (y > impl.pane.bottom() - 4) break;
            } else {
                line = next;
            }
        }
        if (!line.empty() && y <= impl.pane.bottom()) {
            drawText(canvas, line, impl.pane.left(), y, uiFont(11), ui::kDim);
        }
    }

    if (impl.assets.empty()) {
        const std::string message = impl.error.empty()
            ? "nothing in includes/ — images, sub-decks and clips live there"
            : impl.error;
        drawText(canvas, message, pad, kHeaderH + 34, uiFont(13),
                 impl.error.empty() ? ui::kDim : ui::kOver);
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
