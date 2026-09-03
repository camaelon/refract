// refractplayer — a presenter's player for refract decks.
//
// Playback is rcplayer (the runtime behind rcviewer, from the RemoteCompose players/cpp
// tree): same engine, same Metal/Skia path, same video, web and sub-document embeds. This
// app adds what a person standing in front of a room needs and a viewer does not — a
// second window with the clock, the notes and what is coming next; a navigator to jump to
// a section; a talk timer; blanking; fullscreen.
//
//   refractplayer <deck>/out                 the deck, windowed
//   refractplayer <deck>/out --presenter -f  fullscreen with the presenter window
//   refractplayer talk.zip                   a zipped deck
//
// Press H for the key card.

#include "App.h"
#include "Navigator.h"
#include "Presenter.h"
#include "Thumbs.h"
#include "Ui.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "rcplayer/Callbacks.h"
#include "rcplayer/CpuRenderBackend.h"
#include "rcplayer/MediaTypes.h"
#if defined(__APPLE__)
#include "rcplayer/MetalRenderBackend.h"
#endif
#include "rcplayer/ImageExport.h"
#include "rcplayer/PdfExport.h"
#include "rcplayer/Player.h"
#include "rcplayer/ZipArchive.h"

#include "rccore/CoreDocument.h"

#include "include/core/SkBitmap.h"
#include "include/core/SkCanvas.h"
#include "include/core/SkSurface.h"

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <sys/wait.h>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

namespace fs = std::filesystem;
using namespace rcplayer;

namespace {

refract::App app;
std::unique_ptr<refract::PresenterWindow> presenter;

// Where the window sat before it went fullscreen, so F can put it back.
struct WindowedGeometry { int x = 0, y = 0, w = 0, h = 0; bool valid = false; };
WindowedGeometry savedGeometry;

int  presenterMonitor = -1;   // --display for the presenter window, -1 = wherever it lands
bool wantPresenter = false;

// ── Deck navigation ──────────────────────────────────────────────────

// Every slide change goes through here: it is the one place the talk timer, the per-slide
// timer and the playlist stay in step.
void goToSlide(int index) {
    if (app.deck.empty()) return;
    int target = app.deck.clamp(index);
    if (target == g.currentIndex && g.doc) return;

    // The talk starts when you leave the title slide — the point where you have actually
    // begun — so there is no timer to remember to start.
    if (app.autoStartClock && !app.clock.running && g.currentIndex == 0 && target > 0) {
        app.clock.running = true;
    }
    g.currentIndex = target;
    g.timeSinceSwitch = 0.0;
    app.slideEnteredAt = app.clock.elapsed;
    app.sinceSlideChange = 0.0;
    loadCurrentFile();

    // Start the next slide's still now. It is built a little at a time over the following
    // frames, so by the time you press the key again it is already there.
    if (presenter && g.currentIndex + 1 < app.deck.size()) {
        refract::requestThumb(app.deck.at(g.currentIndex + 1).entry, 640, 360);
    }
}

void step(int delta) { goToSlide(g.currentIndex + delta); }

void stepSection(int direction) {
    int target = direction < 0 ? app.deck.prevSectionSlide(g.currentIndex)
                               : app.deck.nextSectionSlide(g.currentIndex);
    if (target >= 0) goToSlide(target);
}

// ── Fullscreen ───────────────────────────────────────────────────────

GLFWmonitor* monitorAt(int wanted) {
    int count = 0;
    GLFWmonitor** monitors = glfwGetMonitors(&count);
    if (count <= 0) return glfwGetPrimaryMonitor();
    if (wanted >= 0 && wanted < count) return monitors[wanted];
    return glfwGetPrimaryMonitor();
}

// The monitor holding most of the window — the one you would expect fullscreen to fill.
GLFWmonitor* monitorForWindow(GLFWwindow* window) {
    int wx, wy, ww, wh;
    glfwGetWindowPos(window, &wx, &wy);
    glfwGetWindowSize(window, &ww, &wh);
    int count = 0;
    GLFWmonitor** monitors = glfwGetMonitors(&count);
    GLFWmonitor* best = glfwGetPrimaryMonitor();
    int bestArea = 0;
    for (int i = 0; i < count; i++) {
        int mx, my;
        glfwGetMonitorPos(monitors[i], &mx, &my);
        const GLFWvidmode* mode = glfwGetVideoMode(monitors[i]);
        if (!mode) continue;
        int overlapW = std::max(0, std::min(wx + ww, mx + mode->width)  - std::max(wx, mx));
        int overlapH = std::max(0, std::min(wy + wh, my + mode->height) - std::max(wy, my));
        if (overlapW * overlapH > bestArea) {
            bestArea = overlapW * overlapH;
            best = monitors[i];
        }
    }
    return best;
}

void setFullscreen(GLFWwindow* window, bool on, GLFWmonitor* preferred = nullptr) {
    bool isFullscreen = glfwGetWindowMonitor(window) != nullptr;
    if (on == isFullscreen) return;
    if (on) {
        glfwGetWindowPos(window, &savedGeometry.x, &savedGeometry.y);
        glfwGetWindowSize(window, &savedGeometry.w, &savedGeometry.h);
        savedGeometry.valid = true;
        GLFWmonitor* monitor = preferred ? preferred : monitorForWindow(window);
        const GLFWvidmode* mode = glfwGetVideoMode(monitor);
        if (!mode) return;
        glfwSetWindowMonitor(window, monitor, 0, 0, mode->width, mode->height, mode->refreshRate);
    } else {
        if (!savedGeometry.valid) { savedGeometry = {100, 100, 1280, 720, true}; }
        glfwSetWindowMonitor(window, nullptr, savedGeometry.x, savedGeometry.y,
                             savedGeometry.w, savedGeometry.h, 0);
    }
}

// ── Presenter window ─────────────────────────────────────────────────

void playerKeyCallback(GLFWwindow* window, int key, int scancode, int action, int mods);

void openPresenter() {
    if (presenter) return;
    presenter = refract::PresenterWindow::Create(1100, 760);
    if (!presenter) return;
    // Both windows take the same keys: you should be able to drive the talk from whichever
    // one has focus, and which one that is depends on where you last clicked.
    glfwSetKeyCallback(presenter->window(), playerKeyCallback);
    if (presenterMonitor >= 0) {
        GLFWmonitor* monitor = monitorAt(presenterMonitor);
        int mx, my;
        glfwGetMonitorPos(monitor, &mx, &my);
        glfwSetWindowPos(presenter->window(), mx + 60, my + 60);
    }
}

void togglePresenter() {
    if (presenter) presenter.reset();
    else openPresenter();
}

// ── Keys ─────────────────────────────────────────────────────────────

void commitJump() {
    if (app.jumpDigits.empty()) return;
    int n = std::atoi(app.jumpDigits.c_str());
    app.jumpDigits.clear();
    if (n >= 1) goToSlide(n - 1);   // slide numbers are 1-based everywhere the user sees them
}

void playerKeyCallback(GLFWwindow* window, int key, int /*scancode*/, int action, int mods) {
    if (action != GLFW_PRESS && action != GLFW_REPEAT) return;
    const bool shift = (mods & GLFW_MOD_SHIFT) != 0;
    g.needsRedraw = true;

    // Digits build up a slide number; Enter commits it. Handled before everything else so a
    // number key never also means something.
    if (key >= GLFW_KEY_0 && key <= GLFW_KEY_9) {
        app.jumpDigits += static_cast<char>('0' + (key - GLFW_KEY_0));
        if (app.jumpDigits.size() > 4) app.jumpDigits.erase(0, 1);
        return;
    }

    // ── Navigator ────────────────────────────────────────────────────
    if (app.navOpen) {
        switch (key) {
            case GLFW_KEY_UP:    refract::navMove(app, -1); return;
            case GLFW_KEY_DOWN:  refract::navMove(app,  1); return;
            case GLFW_KEY_PAGE_UP:   refract::navMove(app, -10); return;
            case GLFW_KEY_PAGE_DOWN: refract::navMove(app,  10); return;
            case GLFW_KEY_LEFT:  refract::navMoveSection(app, -1); return;
            case GLFW_KEY_RIGHT: refract::navMoveSection(app,  1); return;
            case GLFW_KEY_HOME:  app.navCursor = 0; return;
            case GLFW_KEY_END:   app.navCursor = app.deck.size() - 1; return;
            case GLFW_KEY_ENTER:
            case GLFW_KEY_KP_ENTER:
                app.navOpen = false;
                goToSlide(app.navCursor);
                return;
            case GLFW_KEY_ESCAPE:
            case GLFW_KEY_TAB:
            case GLFW_KEY_G:
                app.navOpen = false;
                return;
            default:
                return;   // the navigator swallows everything else while it is up
        }
    }

    switch (key) {
        // ── Moving through the deck ──────────────────────────────────
        // Shift with the horizontal arrows steps by section — the same gesture, one
        // level coarser.
        case GLFW_KEY_RIGHT:
            if (shift) stepSection(1); else step(1);
            break;
        case GLFW_KEY_LEFT:
            if (shift) stepSection(-1); else step(-1);
            break;
        case GLFW_KEY_DOWN: step(1);  break;
        case GLFW_KEY_UP:   step(-1); break;
        case GLFW_KEY_SPACE:
        case GLFW_KEY_PAGE_DOWN:
            step(1);
            break;
        case GLFW_KEY_BACKSPACE:
        case GLFW_KEY_PAGE_UP:
            step(-1);
            break;
        case GLFW_KEY_ENTER:
        case GLFW_KEY_KP_ENTER:
            if (!app.jumpDigits.empty()) commitJump();
            else step(1);
            break;
        case GLFW_KEY_HOME: goToSlide(0); break;
        case GLFW_KEY_END:  goToSlide(app.deck.size() - 1); break;

        // ── Navigator, help ──────────────────────────────────────────
        case GLFW_KEY_TAB:
        case GLFW_KEY_G:
            app.navOpen = true;
            app.navCursor = g.currentIndex;
            app.showHelp = false;
            break;
        case GLFW_KEY_H:
        case GLFW_KEY_SLASH:
            app.showHelp = !app.showHelp;
            break;

        // ── Timer ────────────────────────────────────────────────────
        case GLFW_KEY_T:
            if (shift) {
                app.clock.reset();
                app.slideEnteredAt = 0.0;
                app.autoStartClock = true;
            } else {
                app.clock.toggle();
                // An explicit start or stop is a decision; stop second-guessing it.
                app.autoStartClock = false;
            }
            break;

        // ── Screen ───────────────────────────────────────────────────
        case GLFW_KEY_B: app.blank = (app.blank == 1) ? 0 : 1; break;
        case GLFW_KEY_W: app.blank = (app.blank == 2) ? 0 : 2; break;
        case GLFW_KEY_F: setFullscreen(window, glfwGetWindowMonitor(window) == nullptr); break;
        case GLFW_KEY_P: togglePresenter(); break;

        // ── Playback ─────────────────────────────────────────────────
        case GLFW_KEY_A:
            g.paused = !g.paused;
            if (g.avfPlayer) g.avfPlayer->setPaused(g.paused);
            g.videoHost.setPaused(g.paused);
            break;
        case GLFW_KEY_R:
            refract::clearThumbCache();
            loadCurrentFile();
            break;
        case GLFW_KEY_D:
            g.debug = (g.debug + 1) % 3;
            break;
        case GLFW_KEY_S:
            if (saveScreenshot("/tmp/refractplayer.png"))
                std::cerr << "saved /tmp/refractplayer.png\n";
            break;

        // ── Escape / quit ────────────────────────────────────────────
        // Escape backs out of whatever is on top; it never quits. Losing the deck mid-talk
        // to a stray Escape is not a risk worth the convenience.
        case GLFW_KEY_ESCAPE:
            if (app.showHelp) app.showHelp = false;
            else if (!app.jumpDigits.empty()) app.jumpDigits.clear();
            else if (app.blank) app.blank = 0;
            else if (glfwGetWindowMonitor(window) != nullptr) setFullscreen(window, false);
            break;
        case GLFW_KEY_Q:
            glfwSetWindowShouldClose(window, GLFW_TRUE);
            break;
        default:
            break;
    }
}

// ── Frame capture for the presenter ──────────────────────────────────

// A raster copy of what the slide window just painted. The presenter draws on the CPU, and
// a Metal-backed snapshot cannot be drawn into a raster canvas, so the readback is not
// avoidable — it is throttled instead (the presenter does not need 60 fps of the slide).
sk_sp<SkImage> captureLiveFrame() {
    SkSurface* surface = g.backend ? g.backend->surface() : nullptr;
    if (!surface || g.width <= 0 || g.height <= 0) return nullptr;
    SkBitmap bitmap;
    if (!bitmap.tryAllocPixels(SkImageInfo::MakeN32Premul(g.width, g.height))) return nullptr;
    if (!surface->readPixels(bitmap.pixmap(), 0, 0)) return nullptr;
    bitmap.setImmutable();
    return bitmap.asImage();
}

void usage() {
    std::cerr <<
        "refractplayer — presenter's player for refract decks\n"
        "\n"
        "  refractplayer [options] <deck-out-dir | slide.rc | deck.zip> [width height]\n"
        "\n"
        "Options:\n"
        "  --presenter        open the presenter window (clock, notes, next slide)\n"
        "  --fullscreen, -f   start the slide window fullscreen\n"
        "  --display <n>      monitor for the slide window (0-based); the presenter\n"
        "                     window opens on the next one\n"
        "  --duration <t>     planned talk length for the timer, e.g. 25m, 45, 1h30m\n"
        "  --cpu | --metal    rendering backend (default: Metal on macOS)\n"
        "  --auto <sec>       advance every N seconds\n"
        "  --auto-voice       advance when a slide's voice-over finishes\n"
        "\n"
        "Export:\n"
        "  --pdf <out.pdf>    write the deck to a PDF and exit (one page per slide;\n"
        "                     .rc slides stay vector, videos contribute a first frame)\n"
        "  --images <dir>     write one PNG per slide into <dir> and exit\n"
        "  --export-delay <s> how long each slide animates before it is captured\n"
        "                     (default 2) — long enough that a slide which animates\n"
        "                     in is not caught blank\n"
        "\n"
        "Press H in the player for the key card.\n";
}

// "25m", "45" (minutes), "1h30m", "90s" — a planned talk length in seconds.
double parseDuration(const std::string& text) {
    double total = 0, number = 0;
    bool sawUnit = false, sawDigit = false;
    for (char c : text) {
        if (std::isdigit(static_cast<unsigned char>(c))) {
            number = number * 10 + (c - '0');
            sawDigit = true;
        } else {
            if (c == 'h' || c == 'H') { total += number * 3600; sawUnit = true; }
            else if (c == 'm' || c == 'M') { total += number * 60; sawUnit = true; }
            else if (c == 's' || c == 'S') { total += number; sawUnit = true; }
            number = 0;
        }
    }
    if (!sawUnit) return sawDigit ? number * 60 : 0;   // a bare number is minutes
    return total + number * 60;
}

}  // namespace

int main(int argc, char* argv[]) {
    if (argc < 2) { usage(); return 1; }

    bool useMetal = true;
    bool startFullscreen = false;
    int slideMonitor = -1;
    int initW = 1600, initH = 900;
    std::string pdfOutput;
    std::string imagesOutput;
    double exportDelay = 2.0;
    std::string input;
    std::vector<std::string> positional;

    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];
        auto next = [&](const char* what) -> std::string {
            if (i + 1 >= argc) {
                std::cerr << "refractplayer: " << what << " needs a value\n";
                std::exit(1);
            }
            return argv[++i];
        };
        if (arg == "--presenter") wantPresenter = true;
        else if (arg == "--fullscreen" || arg == "-f") startFullscreen = true;
        else if (arg == "--display") slideMonitor = std::atoi(next("--display").c_str());
        else if (arg == "--duration") app.clock.target = parseDuration(next("--duration"));
        else if (arg == "--cpu") useMetal = false;
        else if (arg == "--metal") useMetal = true;
        else if (arg == "--auto") {
            g.autoAdvanceSec = std::atof(next("--auto").c_str());
            if (g.autoAdvanceSec <= 0) g.autoAdvanceSec = 5.0;
        }
        else if (arg == "--auto-voice") g.autoAdvanceOnVoice = true;
        else if (arg == "--pdf") pdfOutput = next("--pdf");
        else if (arg == "--images") imagesOutput = next("--images");
        else if (arg == "--export-delay" || arg == "--pdf-delay")
            exportDelay = std::atof(next(arg.c_str()).c_str());
        else if (arg == "--help" || arg == "-h") { usage(); return 0; }
        else if (!arg.empty() && arg[0] == '-') {
            std::cerr << "refractplayer: unknown option " << arg << "\n";
            usage();
            return 1;
        }
        else positional.push_back(arg);
    }

    if (positional.empty()) { usage(); return 1; }
    input = positional[0];
    if (positional.size() >= 3) {
        initW = std::atoi(positional[1].c_str());
        initH = std::atoi(positional[2].c_str());
    }

    // ── Export ───────────────────────────────────────────────────────
    // Headless: no window, no GLFW, no playlist — the exporters walk the deck themselves.
    // Size follows the window size, which defaults to the deck's design size; a PDF page
    // takes an .rc slide's own size over it, so there it only matters for media pages.
    if (!pdfOutput.empty() || !imagesOutput.empty()) {
        int failures = 0;
        if (!pdfOutput.empty()) {
            auto result = exportDeckToPdf(input, pdfOutput, initW, initH, exportDelay);
            if (result.pages == 0) failures++;
        }
        if (!imagesOutput.empty()) {
            auto result = exportDeckToImages(input, imagesOutput, initW, initH, exportDelay);
            if (result.images == 0 || result.failures > 0) failures++;
        }
        return failures > 0 ? 1 : 0;
    }

    // ── Playlist ─────────────────────────────────────────────────────
    if (getExt(input) == ".zip") {
        g.zip = std::make_unique<ZipArchive>();
        if (!g.zip->open(input)) {
            std::cerr << "refractplayer: cannot open " << input << "\n";
            return 1;
        }
        g.files = collectZipFiles(*g.zip);
    } else {
        fs::path path(input);
        if (!fs::exists(path)) {
            std::cerr << "refractplayer: no such deck: " << input << "\n";
            return 1;
        }
        // Voice-overs live in <deck>/voice, beside the out/ directory holding the slides.
        fs::path deckDir = fs::is_directory(path) ? path.parent_path()
                                                  : path.parent_path().parent_path();
        if (fs::is_directory(deckDir / "voice")) g.voiceDirOverride = deckDir / "voice";
        g.files = collectRcFiles(input);
    }
    if (g.files.empty()) {
        std::cerr << "refractplayer: no playable slides in " << input << "\n";
        return 1;
    }

    app.deck.build(g.files, input);
    std::cerr << "refractplayer: " << app.deck.size() << " slides, "
              << app.deck.sections().size() << " sections"
              << (app.deck.hasManifest() ? " (deck.json)" : " (no deck.json — filenames only)")
              << "\n";

    // ── Window ───────────────────────────────────────────────────────
    if (!glfwInit()) {
        std::cerr << "refractplayer: GLFW init failed\n";
        return 1;
    }
    glfwWindowHint(GLFW_CONTEXT_VERSION_MAJOR, 2);
    glfwWindowHint(GLFW_CONTEXT_VERSION_MINOR, 1);

    GLFWwindow* window = glfwCreateWindow(initW, initH, "refract", nullptr, nullptr);
    if (!window) {
        std::cerr << "refractplayer: window creation failed\n";
        glfwTerminate();
        return 1;
    }
    if (slideMonitor >= 0) {
        GLFWmonitor* monitor = monitorAt(slideMonitor);
        int mx, my;
        glfwGetMonitorPos(monitor, &mx, &my);
        glfwSetWindowPos(window, mx + 40, my + 40);
        // The presenter window belongs on a *different* screen from the slides.
        presenterMonitor = slideMonitor + 1;
        int count = 0;
        glfwGetMonitors(&count);
        if (presenterMonitor >= count) presenterMonitor = -1;
    }

    glfwMakeContextCurrent(window);
    glfwSwapInterval(1);

#if defined(__APPLE__)
    if (useMetal) {
        g.backend = MetalRenderBackend::Create(window);
        if (!g.backend) {
            std::cerr << "refractplayer: Metal unavailable, using CPU\n";
            g.backend = std::make_unique<CpuRenderBackend>();
        }
    } else {
        g.backend = std::make_unique<CpuRenderBackend>();
    }
#else
    (void)useMetal;
    g.backend = std::make_unique<CpuRenderBackend>();
#endif
    // Hands the window to the player *and* to the hosts that put native views over the
    // slide — embedded web pages are real WKWebViews in this window's content view.
    attachWindow(window);

    // Pointer, resize and framebuffer handling are the viewer's — documents are interactive
    // and should behave identically here. Only the keys are ours.
    installDefaultCallbacks(window);
    glfwSetKeyCallback(window, playerKeyCallback);

    int fbW = 0, fbH = 0;
    glfwGetFramebufferSize(window, &fbW, &fbH);
    g.backend->onFramebufferResize(fbW, fbH);
    int winW = 0, winH = 0;
    glfwGetWindowSize(window, &winW, &winH);
    ensureSurface(winW, winH);

    if (startFullscreen) {
        setFullscreen(window, true, slideMonitor >= 0 ? monitorAt(slideMonitor) : nullptr);
        glfwGetWindowSize(window, &winW, &winH);
        ensureSurface(winW, winH);
    }
    if (wantPresenter) openPresenter();

    loadCurrentFile();
    app.slideEnteredAt = 0.0;

    // ── Loop ─────────────────────────────────────────────────────────
    auto startTime = std::chrono::steady_clock::now();
    double lastFrame = 0.0;
    double lastCapture = -1.0;
    int lastCapturedSlide = -1;
    double lastPresenterDraw = -1.0;
    sk_sp<SkImage> liveFrame;
    // The presenter shows a clock, a timer and two stills. Drawing it at the slide window's
    // frame rate costs several milliseconds a frame to show the same pixels; 20 Hz is past
    // the point where a wall clock reads as live, and it leaves the machine to the deck.
    constexpr double kPresenterInterval = 1.0 / 20.0;
    // Long enough to cover the transitions refract emits (0.6-0.9s) plus the content
    // reveal that follows them.
    constexpr double kTransitionQuietSec = 1.2;
    // The presenter's live pane refreshes at 12 Hz: a full-surface readback per frame is
    // real work, and nobody reads their own slide at 60.
    constexpr double kCaptureInterval = 1.0 / 12.0;

    while (!glfwWindowShouldClose(window)) {
        glfwPollEvents();

        auto now = std::chrono::steady_clock::now();
        double elapsed = std::chrono::duration<double>(now - startTime).count();
        double dt = elapsed - lastFrame;
        lastFrame = elapsed;

        if (!g.paused) {
            g.animTime += dt;
            g.needsRedraw = true;

            if (g.autoAdvanceSec > 0) {
                g.timeSinceSwitch += dt;
                if (g.timeSinceSwitch >= g.autoAdvanceSec) {
                    // Reset here too: at the last slide step() has nowhere to go, and
                    // without this the timer would sit expired and retry every frame.
                    g.timeSinceSwitch = 0.0;
                    step(1);
                }
            }
            if (g.autoAdvanceOnVoice && g.audioPid > 0) {
                int status = 0;
                pid_t finished = ::waitpid(g.audioPid, &status, WNOHANG);
                if (finished == g.audioPid) {
                    g.audioPid = 0;
                    step(1);
                }
            }
        }
        app.clock.tick(dt);
        app.sinceSlideChange += dt;

        // A document can ask for the next frame two ways: on a schedule (getRepaintDelay)
        // and, for animations the schedule knows nothing about — a fling in flight — by
        // setting a repaint request on the paint context. Both have to be honoured.
        if (g.context) {
            int64_t nowMs = std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count();
            if (g.context->getRepaintDelay(nowMs) > 0) g.needsRedraw = true;
            if (rccore::PaintContext* pc = g.context->getPaintContext()) {
                if (pc->doesNeedsRepaint()) g.needsRedraw = true;
            }
        }

        if (g.needsRedraw) {
            glfwMakeContextCurrent(window);
            glfwGetWindowSize(window, &winW, &winH);
            ensureSurface(winW, winH);
            renderFrame(dt);

            // Grab the frame for the presenter *before* blanking. Blanking is for the room;
            // the presenter should keep seeing the slide it is about to bring back.
            // A slide change always captures, however recently the last one was: the
            // throttle is there to spare the readback, not to show the wrong slide.
            if (presenter && (g.currentIndex != lastCapturedSlide
                              || elapsed - lastCapture >= kCaptureInterval)) {
                liveFrame = captureLiveFrame();
                lastCapture = elapsed;
                lastCapturedSlide = g.currentIndex;
            }

            SkCanvas* canvas = g.backend->canvas();
            if (canvas && app.blank) {
                refract::fillRect(canvas, SkRect::MakeWH(winW, winH),
                                  app.blank == 1 ? SK_ColorBLACK : SK_ColorWHITE);
            }
            // Overlays go on the presenter window when there is one — a navigator or a help
            // card projected onto the wall defeats the point of having them.
            if (canvas && !presenter) {
                refract::drawOverlays(canvas, app, winW, winH);
            }

            g.backend->present();
            glfwSwapBuffers(window);
            g.needsRedraw = false;

            char title[256];
            std::snprintf(title, sizeof(title), "refract — %s  [%d/%d]  %s",
                          app.deck.name().c_str(), g.currentIndex + 1, app.deck.size(),
                          app.deck.at(g.currentIndex).title.c_str());
            glfwSetWindowTitle(window, title);
        }

        if (presenter) {
            if (presenter->shouldClose()) {
                presenter.reset();
            } else if (elapsed - lastPresenterDraw >= kPresenterInterval) {
                presenter->render(app, liveFrame);
                lastPresenterDraw = elapsed;
            }
        }

        // Build pending stills a slice at a time. The budget is what keeps a heavy slide
        // from stalling the deck: without it one still is a second of frozen window,
        // landing exactly when a key was pressed.
        //
        // A single document paint cannot be split, so the first one — the expensive one,
        // with shader compilation and a cold layout — will overrun the budget whenever it
        // lands. Hold off until the slide that was just put up has finished animating in,
        // and it lands on a still frame nobody is watching instead of in the middle of the
        // transition. The navigator is the exception: it is waiting on a preview now.
        if (app.navOpen || app.sinceSlideChange > kTransitionQuietSec) {
            refract::pumpThumbs(0.004);
        }
    }

    stopVoiceOver();
    cleanupTempFile();
    presenter.reset();
    glfwMakeContextCurrent(window);
    g.avfPlayer.reset();
    g.webpPlayer.reset();
    g.paintCtx.reset();
    g.context.reset();
    g.doc.reset();
    g.zip.reset();
    g.backend.reset();
    glfwDestroyWindow(window);
    glfwTerminate();
    return 0;
}
