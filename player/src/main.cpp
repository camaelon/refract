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
#include "AudioPlayer.h"
#include "CaptionWindow.h"
#include "Captions.h"
#include "AudioRecorder.h"
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
#include <unistd.h>
#include <iostream>
#include <memory>
#include <string>
#include <vector>

#if defined(__APPLE__)
#include <mach-o/dyld.h>
#endif

namespace fs = std::filesystem;
using namespace rcplayer;

namespace {

refract::App app;
std::unique_ptr<refract::PresenterWindow> presenter;
std::unique_ptr<refract::AudioRecorder> recorder;
std::unique_ptr<refract::AudioPlayer> voice;   // null when --no-sound, or off this platform
bool voicePlaying = false;                     // a slide's narration is running
// Set for the one slide change that follows a narration running out, so the outgoing audio
// is left to finish under the incoming one instead of being cut.
bool overlapNextVoice = false;

std::unique_ptr<refract::CaptionWindow> captionWindow;
refract::Captions captions;      // timings for the slide on screen
std::string tracePath;   // where --record will write, once the talk starts

// Where the window sat before it went fullscreen, so F can put it back.
struct WindowedGeometry { int x = 0, y = 0, w = 0, h = 0; bool valid = false; };
WindowedGeometry savedGeometry;

int  presenterMonitor = -1;   // --display for the presenter window, -1 = wherever it lands
bool wantPresenter = false;

void noteSlideShown();
void startRunIfArmed();
bool captionsEditing();
void toggleTalkClock();
void playSlideAudio(double startAt = 0.0);
void openCaptions();
double voicelessDwell();

// ── Caption processing ───────────────────────────────────────────────
// Transcription and forced alignment are Python's — whisper and whisperx live there — so
// this runs the script that does it. The player supplies the one thing the script cannot
// work out on its own: which directory the narration was recorded into.

fs::path executableDir() {
#if defined(__APPLE__)
    char buf[4096];
    uint32_t size = sizeof(buf);
    if (_NSGetExecutablePath(buf, &size) == 0) {
        std::error_code ec;
        fs::path resolved = fs::weakly_canonical(fs::path(buf), ec);
        if (!ec) return resolved.parent_path();
    }
#endif
    return {};
}

// The script sits in the repo beside the player's sources. Both places the binary normally
// lives — prebuilt/ and player/build/ — are a fixed distance from it.
fs::path findCaptionsScript() {
    if (const char* override = std::getenv("REFRACT_CAPTIONS_SCRIPT")) {
        if (fs::exists(override)) return override;
    }
    const fs::path dir = executableDir();
    if (dir.empty()) return {};
    for (const char* rel : {"../player/tools/captions.py",   // prebuilt/refractplayer
                            "../tools/captions.py",          // player/build/refractplayer
                            "tools/captions.py"}) {
        std::error_code ec;
        fs::path candidate = fs::weakly_canonical(dir / rel, ec);
        if (!ec && fs::exists(candidate)) return candidate;
    }
    return {};
}

int runCaptions(const fs::path& voiceDir, const std::string& model,
                const std::string& language) {
    const fs::path script = findCaptionsScript();
    if (script.empty()) {
        std::cerr << "refractplayer: cannot find tools/captions.py — set "
                     "REFRACT_CAPTIONS_SCRIPT to its path\n";
        return 1;
    }

    pid_t pid = ::fork();
    if (pid < 0) return 1;
    if (pid == 0) {
        ::execlp("python3", "python3", script.c_str(), voiceDir.c_str(),
                 "--model", model.c_str(), "--language", language.c_str(), (char*)nullptr);
        std::cerr << "refractplayer: python3 not found\n";
        ::_exit(127);
    }
    int status = 0;
    ::waitpid(pid, &status, 0);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}

// ── Deck navigation ──────────────────────────────────────────────────

// Every slide change goes through here: it is the one place the talk timer, the per-slide
// timer and the playlist stay in step.
void goToSlide(int index) {
    if (app.deck.empty()) return;

    // Not while the transcript is being corrected. The words on screen belong to the slide
    // on screen: moving to another one under them would either throw the edit away or land
    // it on the wrong slide. Every route to a slide change comes through here — the keys in
    // any of the three windows, the navigator, a typed slide number, auto-advance — so this
    // is the one place it has to be said.
    if (captionsEditing()) {
        std::cerr << "captions: finish the edit (Done, or Esc) before changing slides\n";
        return;
    }

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
    playSlideAudio();
    loadCurrentFile();
    noteSlideShown();

    // Start the next slide's still now. It is built a little at a time over the following
    // frames, so by the time you press the key again it is already there.
    if (presenter && g.currentIndex + 1 < app.deck.size()) {
        refract::requestThumb(app.deck.at(g.currentIndex + 1).entry, 640, 360);
    }
}

// Everything that has to happen when a slide comes up in a recorded run: the trace gets the
// time it appeared, and the microphone moves to that slide's wav. Called after the slide is
// loaded, so the file name is the one being shown.
void noteSlideShown() {
    if (app.deck.empty() || !app.timing.recording()) return;
    const auto& slide = app.deck.at(g.currentIndex);

    app.timing.mark(slide.file, app.clock.elapsed);

    if (recorder) {
        // Straight to where playback will look for it, so a recorded talk replays with
        // --auto-voice and no renaming in between.
        fs::path wav = voicePathFor(slide.entry);
        if (wav.empty()) {
            std::cerr << "audio: " << slide.file << " has no leading number to key a wav by\n";
            recorder->stop();
        } else {
            recorder->start(wav.string());
        }
    }
}

// Start this slide's narration, then open the *next* slide's file so the following change
// costs nothing. Opening a file and readying the output device takes long enough to hear as a
// gap at a slide boundary — which is exactly where a recorded narration runs continuously and
// must not be broken — so it is paid for in advance, on a slide already being talked over.
//
// Called before the slide itself is loaded: the picture can afford the couple of
// milliseconds, the audio cannot.
void playSlideAudio(double startAt) {
    if (!voice || app.deck.empty()) return;
    voicePlaying = false;

    captions.loadFor(app.deck.at(g.currentIndex).entry);

    const bool overlap = overlapNextVoice;
    overlapNextVoice = false;

    const fs::path wav = voicePathFor(app.deck.at(g.currentIndex).entry);
    if (!wav.empty()) voicePlaying = voice->play(wav.string(), overlap, startAt);
    else if (!overlap) voice->stop();

    if (g.currentIndex + 1 < app.deck.size()) {
        const fs::path next = voicePathFor(app.deck.at(g.currentIndex + 1).entry);
        if (!next.empty()) voice->preload(next.string());
    }
}

// The talk starts when the clock does — pressing T, or advancing off the opening slide.
// Recording waits for that moment rather than for launch, which also gives the microphone
// permission prompt time to be answered before anything is being captured.
// Start or pause the talk — the T key and the presenter's button are the same action, so
// they stay in step. An explicit press is a decision, so the auto-start stops second-guessing
// it from then on.
void toggleTalkClock() {
    // The presenter's button reaches this by mouse, which the keyboard guard does not cover.
    if (captionsEditing()) return;
    app.clock.toggle();
    app.autoStartClock = false;
    // The microphone follows the talk: a pause is a break, and a break belongs in neither
    // the slide's wav nor its recorded duration.
    if (recorder) recorder->setPaused(!app.clock.running);
    if (voice) voice->setPaused(!app.clock.running);
}

void startRunIfArmed() {
    if (!app.recordArmed || !app.clock.running) return;
    app.recordArmed = false;
    app.timing.beginRecording(tracePath);
    noteSlideShown();
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
    presenter->setOnToggleClock(toggleTalkClock);
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

bool captionsEditing() {
    return captionWindow && captionWindow->isEditing();
}

void openCaptions() {
    if (captionWindow) return;
    captionWindow = refract::CaptionWindow::Create(900, 420);
    if (!captionWindow) return;

    // The caption window gets first refusal on the keyboard: while a word is being retyped,
    // every key belongs to it, and only what it does not want reaches the player's bindings.
    glfwSetKeyCallback(captionWindow->window(),
                       [](GLFWwindow* w, int key, int scancode, int action, int mods) {
        if (captionWindow && captionWindow->handleKey(key, action, mods)) return;
        playerKeyCallback(w, key, scancode, action, mods);
    });
    glfwSetCharCallback(captionWindow->window(), [](GLFWwindow*, unsigned int codepoint) {
        if (captionWindow) captionWindow->handleChar(codepoint);
    });

    captionWindow->setOnEditingChanged([](bool editing) {
        if (!voice) return;
        if (editing) {
            // Nothing should be playing while the words are being changed.
            voice->stop();
            voicePlaying = false;
        } else {
            // Pick up shortly before the first correction rather than at the top of the
            // slide. The point of replaying is to hear the change against the audio it was
            // made for, and a long narration should not have to be sat through to reach it.
            // With nothing changed there is nothing to hear, so it starts from the top.
            constexpr double kLeadInSec = 1.5;
            const double edited = captions.earliestEdit();
            playSlideAudio(edited < 0.0 ? 0.0 : std::max(0.0, edited - kLeadInSec));
        }
    });
}

void toggleCaptions() {
    if (captionWindow) captionWindow.reset();
    else openCaptions();
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

    // While a transcript is being corrected, the player's bindings are off — in every window,
    // not just the caption one. GLFW delivers keys to whichever window has focus, so a
    // keystroke aimed at a word lands on the slide window's bindings if that is what was
    // clicked last, and "b" blanks the projector instead of going into the word. The caption
    // window handles its own keys before this is reached, so nothing here is needed while it
    // has focus either.
    if (captionsEditing()) {
        static double lastSaid = 0.0;
        const double now = glfwGetTime();
        if (now - lastSaid > 2.0) {
            lastSaid = now;
            std::cerr << "captions: editing — the player's keys are off until you finish "
                         "(Done, or Esc in the caption window)\n";
        }
        return;
    }

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
                toggleTalkClock();
            }
            break;

        // ── Screen ───────────────────────────────────────────────────
        case GLFW_KEY_B: app.blank = (app.blank == 1) ? 0 : 1; break;
        case GLFW_KEY_W: app.blank = (app.blank == 2) ? 0 : 2; break;
        case GLFW_KEY_F: setFullscreen(window, glfwGetWindowMonitor(window) == nullptr); break;
        case GLFW_KEY_P: togglePresenter(); break;
        case GLFW_KEY_C: toggleCaptions(); break;

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

// How long --auto-voice holds a slide that has neither a voice-over nor an entry in the
// trace. Without this the deck stops dead on the first such slide with nothing said about
// why, which is the opposite of what "advance on its own" was asked for. --auto's interval
// wins when one was given, since that is an explicit statement of pace.
double voicelessDwell() {
    static bool explained = false;
    if (!explained) {
        explained = true;
        std::cerr << "auto-voice: slides with no voice-over and no recorded time hold for "
                  << (g.autoAdvanceSec > 0 ? g.autoAdvanceSec : 5.0) << "s\n";
    }
    return g.autoAdvanceSec > 0 ? g.autoAdvanceSec : 5.0;
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
        "  --auto-voice       advance when a slide's voice-over finishes (plays the\n"
        "                     wavs a --record-audio run captured)\n"
        "  --no-sound         never play a slide's voice-over, even where one exists\n"
        "  --captions         open the close-caption window (needs timings from\n"
        "                     --transcribe)\n"
        "\n"
        "Captions:\n"
        "  --transcribe       transcribe the recorded narration and align it into\n"
        "                     per-word caption timings, then exit\n"
        "  --caption-model N  whisper model for transcription (default: base)\n"
        "  --caption-lang L   language of the narration (default: en)\n"
        "\n"
        "Rehearsing:\n"
        "  --record           time the run: writes timing.json beside the slides, so a\n"
        "                     later run can show whether it is ahead or behind\n"
        "  --record-audio     also record narration, one wav per slide, into the deck's\n"
        "                     voice dir (implies --record; disables voice-over playback)\n"
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
    bool record = false;
    bool wantCaptions = false;
    bool transcribe = false;
    std::string captionModel = "base";
    std::string captionLanguage = "en";
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
        else if (arg == "--no-sound") g.voiceOverEnabled = false;
        else if (arg == "--pdf") pdfOutput = next("--pdf");
        else if (arg == "--images") imagesOutput = next("--images");
        else if (arg == "--captions") wantCaptions = true;
        else if (arg == "--transcribe") transcribe = true;
        else if (arg == "--caption-model") captionModel = next("--caption-model");
        else if (arg == "--caption-lang") captionLanguage = next("--caption-lang");
        else if (arg == "--record") record = true;
        else if (arg == "--record-audio") { record = true; app.recordAudio = true; }
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

    // ── Transcription ────────────────────────────────────────────────
    // Needs the playlist — that is what says where the narration was recorded — but no
    // window, so it runs before one is opened and exits.
    if (transcribe) {
        const fs::path wav = voicePathFor(g.files.front());
        if (wav.empty()) {
            std::cerr << "refractplayer: slides are not numbered, so there are no voice "
                         "files to transcribe\n";
            return 1;
        }
        return runCaptions(wav.parent_path(), captionModel, captionLanguage);
    }

    app.deck.build(g.files, input);

    // Voice-over is played here rather than by the library: its afplay-per-slide path cannot
    // preload, and the spawn latency is audible at every boundary. Switching the library's
    // off also stops it being played twice.
    if (g.voiceOverEnabled) {
        voice = refract::AudioPlayer::Create();
        if (voice) g.voiceOverEnabled = false;
    }
    std::cerr << "refractplayer: " << app.deck.size() << " slides, "
              << app.deck.sections().size() << " sections"
              << (app.deck.hasManifest() ? " (deck.json)" : " (no deck.json — filenames only)")
              << "\n";

    // ── Rehearsal ────────────────────────────────────────────────────
    if (record) {
        fs::path tracePathFor = refract::deckSidecarPath(input, "timing.json");
        if (tracePathFor.empty()) {
            std::cerr << "refractplayer: cannot record a trace for a zip bundle\n";
            return 1;
        }
        app.timing.setDeckName(app.deck.name());
        tracePath = tracePathFor.string();
        app.recordArmed = true;
        std::cerr << "refractplayer: armed — recording starts when the talk does "
                     "(press T, or advance off the first slide)\n";

        if (app.recordAudio) {
            // Created now, so the microphone permission prompt is answered while you are
            // still setting up rather than in the first seconds of the talk. Nothing is
            // captured until startRunIfArmed() opens the first slide's wav.
            recorder = refract::AudioRecorder::Create();
            if (!recorder) std::cerr << "refractplayer: continuing without audio\n";
            // Playing the previous take back through the speakers while recording the next
            // one puts it straight into the new wav. Both playback paths go: the library's
            // and the one this player just took over.
            g.voiceOverEnabled = false;
            voice.reset();
        }
    } else if (app.timing.loadForDeck(input)) {
        // A trace from an earlier run: the presenter shows the pace against it.
    }

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
    if (wantCaptions) openCaptions();

    loadCurrentFile();
    app.slideEnteredAt = 0.0;
    playSlideAudio();
    noteSlideShown();

    // ── Loop ─────────────────────────────────────────────────────────
    auto startTime = std::chrono::steady_clock::now();
    double lastFrame = 0.0;
    double lastCapture = -1.0;
    int lastCapturedSlide = -1;
    double lastPresenterDraw = -1.0;
    double lastCaptionDraw = -1.0;
    // Fast enough that a word lights on the syllable, cheap enough to be free.
    constexpr double kCaptionInterval = 1.0 / 30.0;
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

            // Auto-advance is held rather than blocked: it fires on a timer, and letting it
            // run into the guard every frame would say so hundreds of times.
            const bool holdForEdit = captionsEditing();

            if (g.autoAdvanceSec > 0 && !holdForEdit) {
                g.timeSinceSwitch += dt;
                if (g.timeSinceSwitch >= g.autoAdvanceSec) {
                    // Reset here too: at the last slide step() has nowhere to go, and
                    // without this the timer would sit expired and retry every frame.
                    g.timeSinceSwitch = 0.0;
                    step(1);
                }
            }
            if (holdForEdit) {
                // Nothing to do: the deck stays where it is until the edit is finished.
            } else if (g.autoAdvanceOnVoice && voicePlaying && voice) {
                // Hand over a moment *before* the narration ends rather than after it has.
                // Waiting for the file to stop means noticing a frame late, and a frame of
                // silence at every slide boundary is the seam this is trying to remove. The
                // outgoing audio finishes underneath the incoming one, so the join is
                // continuous rather than merely short.
                constexpr double kHandoverLead = 0.05;
                const bool ending = !voice->isPlaying() || voice->remaining() <= kHandoverLead;
                if (ending) {
                    overlapNextVoice = voice->isPlaying();
                    voicePlaying = false;
                    step(1);
                }
            } else if (g.autoAdvanceOnVoice && !voicePlaying && !app.deck.empty()) {
                // A slide with no wav would otherwise hold the deck forever — and a
                // recording always has gaps, if only the slide that was up while the
                // microphone permission was still being granted. With a trace loaded, fall
                // back to the time that run spent on the slide, so a recorded talk replays
                // end to end whether or not every slide got audio.
                const auto* entry = app.timing.find(app.deck.at(g.currentIndex).file);
                double dwell = (entry && entry->duration > 0.0) ? entry->duration
                                                                : voicelessDwell();
                if (app.sinceSlideChange >= dwell) step(1);
            }
        }
        app.clock.tick(dt);
        app.sinceSlideChange += dt;
        startRunIfArmed();
        app.timing.tick(app.clock.elapsed);

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
                // Sampled here rather than inside the window: the recorder belongs to the
                // app, and the level is only wanted at the rate the meter is drawn.
                if (recorder) {
                    recorder->updateLevels();
                    presenter->pushAudioLevel(recorder->averageLevel(), recorder->peakLevel());
                } else {
                    presenter->pushAudioLevel(-1.0f, -1.0f);
                }
                presenter->render(app, liveFrame);
                lastPresenterDraw = elapsed;
            }
        }

        if (captionWindow) {
            if (captionWindow->shouldClose()) {
                captionWindow.reset();
            } else if (elapsed - lastCaptionDraw >= kCaptionInterval) {
                // The audio clock, not the frame clock: the highlight has to sit on the word
                // coming out of the speakers, and the two drift.
                const double at = voice ? voice->currentTime() : 0.0;
                captionWindow->render(app, captions, at, voice && voice->isPlaying());
                lastCaptionDraw = elapsed;
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

    // An edit in progress is finished rather than dropped: it is saved on leaving edit mode,
    // and quitting mid-word should not be the one way to lose it.
    if (captionWindow && captionWindow->isEditing()) captionWindow->finishEditing();

    if (app.timing.recording()) app.timing.finish(app.clock.elapsed);
    if (recorder) recorder->stop();
    recorder.reset();
    if (voice) voice->stop();
    voice.reset();
    captionWindow.reset();
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
