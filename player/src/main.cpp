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
#include "AppMenu.h"
#include "AssetWindow.h"
#include "AudioPlayer.h"
#include "CaptionWindow.h"
#include "BuildPanel.h"
#include "BuildRunner.h"
#include "Captions.h"
#include "DeckView.h"
#include "DeckSource.h"
#include "AudioRecorder.h"
#include "Navigator.h"
#include "Options.h"
#include "Presenter.h"
#include "Session.h"
#include "DeckLibrary.h"
#include "StartWindow.h"
#include "SlideRecorder.h"
#include "Tools.h"
#include "SlideEditor.h"
#include "VoiceIndex.h"
#include "Windowing.h"
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
#include <filesystem>
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
refract::VoiceIndex voiceIndex;  // which wav belongs to which slide, across a reorder

// What was open, and where, the last time this deck was played.
refract::Session session;
std::string sessionOnDisk;       // what was last written, so an unchanged session is not rewritten
// The deck's own window. The panels each hold theirs; this one belongs to main, and the
// session captures it from here.
GLFWwindow* slideWindow = nullptr;
std::unique_ptr<refract::DeckViewWindow> deckView;
std::unique_ptr<refract::BuildPanel> buildPanel;
std::unique_ptr<refract::SlideEditor> slideEditor;
std::unique_ptr<refract::AssetWindow> assetWindow;
std::string tracePath;   // where --record will write, once the talk starts
// The deck as the user named it. Kept because reordering rebuilds and reloads it, and the
// reload has to look in the same place the first load did.
std::string deckInput;
// Set when the deck has been reordered on disk. The reload happens at the top of the frame
// rather than in the mouse callback that asked for it: rebuilding the playlist reloads the
// document, and doing that from inside glfwPollEvents — with another window's GL context
// current — is asking for trouble.
bool deckReloadPending = false;
// The outputs the last build actually rewrote, from the tool that ran it. Empty means "no
// idea", and the reload then drops every still rather than guessing.
std::vector<std::string> changedOutputs;

int  presenterMonitor = -1;   // --display for the presenter window, -1 = wherever it lands
bool wantPresenter = false;
bool wantDeckView = false;
bool wantBuildPanel = false;
bool wantEditor = false;

void noteSlideShown();
void startRunIfArmed();
bool captionsEditing();
void toggleTalkClock();
void playSlideAudio(double startAt = 0.0);
void openCaptions();
void captureSession();
void saveSessionIfChanged();
fs::path voiceFileFor(int slide, const char* extension = ".wav");
void refreshVoicePresence();
void toggleSlideRecording();
void stopSlideRecording(bool keep);

// A panel the menu bar has asked for. Menu items fire from inside Cocoa's event handling,
// and opening or closing a GLFW window from there means creating and destroying an NSWindow
// while AppKit is part-way through a menu. The loop does it instead, at the top of a frame.
enum class MenuPanel { None, Presenter, DeckView, Editor, Build, Captions, Navigator, Assets };
MenuPanel menuRequest = MenuPanel::None;

void toggleDeckView();
void toggleBuildPanel();
void toggleSlideEditor();
void toggleAssetWindow();
bool editorHoldsDeck();
void goToSlide(int index);
double voicelessDwell();

// ── Caption processing ───────────────────────────────────────────────
// Transcription and forced alignment are Python's — whisper and whisperx live there — so
// this runs the script that does it. The player supplies the one thing the script cannot
// work out on its own: which directory the narration was recorded into.

// What to actually play, given what somebody named.
//
// A deck is a directory with a slides.md in it; the slides are in the out/ underneath. Being
// handed the deck and told there are no slides in it is a silly answer to give — the deck is
// right there — so the out/ is found, and built when it is not there yet. That is also what
// makes a deck opened from the start window or the file dialog work: what a person picks is
// the deck, not the directory a build happened to put things in.
std::string resolveDeck(const std::string& input) {
    std::error_code ec;
    const fs::path path(input);
    if (!fs::is_directory(path, ec)) return input;               // a .rc or a .zip
    if (!fs::exists(path / "slides.md", ec)) return input;       // already an out/, or not a deck

    const fs::path out = path / "out";
    bool built = false;
    if (fs::is_directory(out, ec)) {
        for (const auto& entry : fs::directory_iterator(out, ec)) {
            if (entry.path().extension() == ".rc") { built = true; break; }
        }
    }
    if (!built) {
        std::cerr << "refractplayer: building " << input << "\n";
        if (refract::runTool("build.py", {out.string()}) != 0) {
            std::cerr << "refractplayer: could not build " << input << "\n";
            return input;
        }
    }
    return out.string();
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
    // Nor while a slide's source is half-rewritten: the editor is showing one slide's
    // markdown, and moving the deck under it would either lose the edit or land it on
    // another slide.
    if (editorHoldsDeck()) {
        std::cerr << "editor: save or revert the slide before changing slides\n";
        return;
    }
    // A take belongs to the slide it was started on; leaving keeps what was said.
    stopSlideRecording(/*keep=*/true);

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
    if (slideEditor) slideEditor->showSlide(g.currentIndex);

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

    app.timing.mark(slide.sourceKey(), slide.file, app.clock.elapsed);

    if (recorder) {
        // Straight to where playback will look for it, so a recorded talk replays with
        // --auto-voice and no renaming in between.
        // The wav is named for the slide's position, as it always was — the transcription
        // and the web export both read them by number and expect NN.txt beside NN.wav. What
        // is written down is which *block* each one belongs to, so the pairing survives the
        // deck being reordered afterwards.
        fs::path wav = voicePathFor(slide.entry);
        if (wav.empty()) {
            std::cerr << "audio: " << slide.file << " has no leading number to key a wav by\n";
            recorder->stop();
        } else {
            recorder->start(wav.string());
            voiceIndex.record(slide.sourceKey(), wav.stem().string());
            if (g.currentIndex < static_cast<int>(app.voice.size())) {
                app.voice[g.currentIndex] = 1;   // it has narration from this moment on
            }
        }
    }
}

// The narration for a slide — the wav the recorder wrote for it, whatever number it has
// since been given.
//
// rcplayer derives the path from the slide's own number, which is right up until the deck is
// reordered: refract renumbers every slide after a move, and the wavs do not move with them.
// The index the recorder writes says which wav belongs to which *block*, and a block is what
// a reorder moves. Without an index — a recording made before there was one, on a deck nobody
// has reordered — the number is used, exactly as before.
fs::path voiceFileFor(int slide, const char* extension) {
    if (app.deck.empty()) return {};
    const auto& entry = app.deck.at(slide);
    const fs::path positional = voicePathFor(entry.entry);
    if (positional.empty()) return {};

    const std::string stem = voiceIndex.stemFor(entry.sourceKey());
    fs::path path = stem.empty() ? positional
                                 : positional.parent_path() / (stem + ".wav");
    if (std::string(extension) != ".wav") path.replace_extension(extension);
    return path;
}

// Which slides have narration, for the deck view to show. Done once per deck rather than per
// frame: it is a look at the disk for every slide, and the answer only changes when the deck
// is rebuilt or something is recorded.
void refreshVoicePresence() {
    app.voice.assign(app.deck.size(), 0);
    if (g.voiceDirOverride.empty()) return;
    for (int i = 0; i < app.deck.size(); i++) {
        const fs::path wav = voiceFileFor(i);
        std::error_code ec;
        app.voice[i] = (!wav.empty() && fs::exists(wav, ec)) ? 1 : 0;
    }
}

// ── Re-recording one slide ───────────────────────────────────────────
// The state machine is SlideRecorder's; what is here is the microphone, the file naming and
// what the rest of the player needs told when a take lands.
refract::SlideRecorder slideRecorder;

void stopSlideRecording(bool keep) {
    slideRecorder.stop(keep);
    app.reRecording = false;
    app.reRecordSlide = -1;
}

void toggleSlideRecording() {
    if (slideRecorder.running()) { stopSlideRecording(/*keep=*/true); return; }
    if (app.deck.empty() || app.timing.recording()) {
        std::cerr << "audio: not while a whole run is being recorded\n";
        return;
    }
    if (!recorder) recorder = refract::AudioRecorder::Create();
    if (!recorder) return;

    // Playing the old take back through the speakers while recording the new one puts it
    // straight into the new file.
    if (voice) voice->stop();
    voicePlaying = false;

    slideRecorder.configure(
        [](int slide) { return voiceFileFor(slide); },
        [](const std::string& path) { if (recorder) recorder->start(path); },
        [] { if (recorder) recorder->stop(); },
        [](int slide, const std::string& stem) {
            if (slide < 0 || slide >= app.deck.size()) return;
            voiceIndex.record(app.deck.at(slide).sourceKey(), stem);
            if (slide < static_cast<int>(app.voice.size())) app.voice[slide] = 1;
        });

    std::string why;
    if (!slideRecorder.toggle(g.currentIndex, &why)) {
        std::cerr << "audio: " << why << "\n";
        return;
    }
    app.reRecording = true;
    app.reRecordSlide = g.currentIndex;
    std::cerr << "audio: recording over slide " << (g.currentIndex + 1)
              << " — shift+R again to keep it, Esc to drop it\n";
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

    // Captions live beside the wav (NN.words.json), so they follow it through a reorder for
    // the same reason and by the same route.
    captions.loadForVoice(voiceFileFor(g.currentIndex));

    const bool overlap = overlapNextVoice;
    overlapNextVoice = false;

    const fs::path wav = voiceFileFor(g.currentIndex);
    if (!wav.empty()) voicePlaying = voice->play(wav.string(), overlap, startAt);
    else if (!overlap) voice->stop();

    if (g.currentIndex + 1 < app.deck.size()) {
        const fs::path next = voiceFileFor(g.currentIndex + 1);
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

// ── Presenter window ─────────────────────────────────────────────────

void playerKeyCallback(GLFWwindow* window, int key, int scancode, int action, int mods);

void openPresenter() {
    if (presenter) return;
    presenter = refract::PresenterWindow::Create(1100, 760);
    if (!presenter) return;
    presenter->setOnToggleClock(toggleTalkClock);
    session.restore("presenter", presenter->window());
    presenter->setOnRecordSlide(toggleSlideRecording,
                                [] { stopSlideRecording(/*keep=*/false); });
    // Both windows take the same keys: you should be able to drive the talk from whichever
    // one has focus, and which one that is depends on where you last clicked.
    glfwSetKeyCallback(presenter->window(), playerKeyCallback);
    glfwSetCharCallback(presenter->window(), [](GLFWwindow*, unsigned int codepoint) {
        // The navigator draws on this window when it is open, so it is typed into here too.
        if (app.navOpen && app.navFiltering && codepoint >= 0x20 && codepoint != '/') {
            app.navFilter.push_back(static_cast<char>(codepoint < 0x80 ? codepoint : '?'));
        }
    });
    if (presenterMonitor >= 0) {
        GLFWmonitor* monitor = refract::monitorAt(presenterMonitor);
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

    session.restore("captions", captionWindow->window());
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
    saveSessionIfChanged();
}

// ── Deck view ────────────────────────────────────────────────────────

// Re-read the deck from disk. refract renumbers every slide downstream of a change, so a
// rebuild renames files: there is nothing to patch up, the playlist is simply collected
// again. The slide on screen is kept by *position*, which after a reorder is what the deck
// view just moved it to.
bool reloadDeck() {
    if (g.zip || deckInput.empty()) return false;
    std::vector<std::string> files = collectRcFiles(deckInput);
    if (files.empty()) {
        std::cerr << "refractplayer: reload found no slides in " << deckInput << "\n";
        return false;
    }
    g.files = std::move(files);
    app.deck.build(g.files, deckInput);
    refreshVoicePresence();
    // Only the slides the build touched. Re-rendering a sixty-slide deck because one word
    // changed is work nobody asked for, and it is why cards used to blink back to empty.
    if (changedOutputs.empty()) {
        refract::clearThumbCache();
    } else {
        const fs::path out = refract::deckSidecarPath(deckInput, "deck.json").parent_path();
        std::vector<std::string> entries;
        entries.reserve(changedOutputs.size());
        for (const std::string& name : changedOutputs) entries.push_back((out / name).string());
        refract::dropThumbs(entries);
    }
    changedOutputs.clear();
    g.currentIndex = app.deck.clamp(g.currentIndex);
    loadCurrentFile();
    // Nothing to fix up for the trace or the narration: both are keyed by the block a slide
    // was written in rather than by its number, so they follow their slides through the
    // reorder that has just renumbered every file underneath them.
    return true;
}

// ── Editing the deck's source ────────────────────────────────────────
//
// Every read and rewrite of the deck's markdown goes through DeckSource, which runs the
// tools in player/tools/ — the ones off the main thread on a worker. What is left here is
// who to tell when one lands.
refract::DeckSource source;
refract::BuildRunner builder;

void openDeckView() {
    if (deckView) return;
    deckView = refract::DeckViewWindow::Create(1180, 780);
    if (!deckView) return;
    deckView->setOnOpenSlide([](int index) { goToSlide(index); });
    deckView->setOnMoveSlide([](int from, int to, std::string* status) {
        return source.moveSlide(from, to, status);
    });
    deckView->setOnMoveRun([](const std::string& file, int first, int last, int dst,
                          std::string* status) {
        return source.moveRun(file, first, last, dst, status);
    });
    deckView->setOnAddSlide([](int slide, bool before, std::string* status) {
        return source.addSlide(slide, before, status);
    });
    deckView->setOnDeleteSlide([](int slide, std::string* status) {
        return source.deleteSlide(slide, status);
    });
    deckView->setOnUndo([](bool redo, std::string* status) {
        return source.undo(redo, status);
    });
    deckView->setFoldedRuns(session.folded);
    session.restore("deckView", deckView->window());
    deckView->setOnDuplicateSlide([](int slide, std::string* status) {
        return source.duplicateSlide(slide, status);
    });
    deckView->setOnMergeSlide([](int slide, std::string* status) {
        return source.mergeSlide(slide, status);
    });
    // The view takes the keys it uses to walk the grid; everything else still drives the
    // talk, so the deck can be run from this window like any other.
    glfwSetKeyCallback(deckView->window(),
                       [](GLFWwindow* w, int key, int scancode, int action, int mods) {
        if (deckView && deckView->handleKey(key, action, mods)) return;
        playerKeyCallback(w, key, scancode, action, mods);
    });
    // Only while a filter is being typed; otherwise the letters are the view's own bindings.
    glfwSetCharCallback(deckView->window(), [](GLFWwindow*, unsigned int codepoint) {
        if (deckView) deckView->handleChar(codepoint);
    });
}

// Read the live windows into the session — what is open, where, and the few settings each
// panel carries. Cheap: a handful of GLFW queries.
void captureSession() {
    // Where the deck itself is. Fullscreen is deliberately not remembered — a player that
    // took over the screen the moment it opened would be startling, and `--fullscreen` and
    // `F` are how you ask for that. What is kept is where the window was *windowed*, which
    // while fullscreen is the geometry `F` would put it back to.
    int x, y, w, h;
    if (refract::windowedGeometry(slideWindow, &x, &y, &w, &h)) {
        session.windows["slides"] = {x, y, w, h};
    }

    session.presenter = presenter != nullptr;
    session.deckView = deckView != nullptr;
    session.editor = slideEditor != nullptr;
    session.build = buildPanel != nullptr;
    session.captions = captionWindow != nullptr;
    session.assets = assetWindow != nullptr;

    if (assetWindow) session.capture("assets", assetWindow->window());
    if (presenter) session.capture("presenter", presenter->window());
    if (captionWindow) session.capture("captions", captionWindow->window());
    if (deckView) {
        session.capture("deckView", deckView->window());
        session.folded = deckView->foldedRuns();
    }
    if (slideEditor) {
        session.capture("editor", slideEditor->window());
        session.editorAutoSave = slideEditor->autoSave();
    }
    if (buildPanel) {
        session.capture("build", buildPanel->window());
        session.buildWatch = buildPanel->watching();
        const refract::BuildOptions& opts = buildPanel->options();
        session.buildTransitions = opts.transitions;
        session.buildDebug = opts.debug;
        session.buildForce = opts.force;
        session.buildKeepJson = opts.keepJson;
    }
}

// Write it, if it is not what is already written.
//
// Not only on the way out: the way out is not always taken. A player killed from the terminal
// or caught by a crash would otherwise forget the whole arrangement, which is the arrangement
// somebody just spent a minute making.
void saveSessionIfChanged() {
    if (deckInput.empty()) return;
    captureSession();
    const std::string now = session.serialise();
    if (now == sessionOnDisk) return;
    if (session.save(deckInput)) sessionOnDisk = now;
}

void toggleDeckView() {
    if (deckView) deckView.reset();
    else openDeckView();
    saveSessionIfChanged();
}

// ── Assets ───────────────────────────────────────────────────────────

void openAssetWindow() {
    if (assetWindow) return;
    assetWindow = refract::AssetWindow::Create(680, 520);
    if (!assetWindow) return;
    assetWindow->setScanner([](std::vector<refract::Asset>* out, std::string* dir,
                           std::string* error) {
        return source.scanAssets(out, dir, error);
    });
        // The window has already asked, and said what uses it, so the tool does not ask again.
    assetWindow->setRemover([](const std::string& path, std::string* status) {
        return source.removeAsset(path, /*force=*/true, status);
    });
    assetWindow->refresh();
    session.restore("assets", assetWindow->window());
    glfwSetKeyCallback(assetWindow->window(),
                       [](GLFWwindow* w, int key, int scancode, int action, int mods) {
        if (assetWindow && assetWindow->handleKey(key, action, mods)) return;
        playerKeyCallback(w, key, scancode, action, mods);
    });
}

void toggleAssetWindow() {
    if (assetWindow) assetWindow.reset();
    else openAssetWindow();
    saveSessionIfChanged();
}

// ── Build panel ──────────────────────────────────────────────────────

void openBuildPanel() {
    if (buildPanel) return;
    buildPanel = refract::BuildPanel::Create(300, 760);
    if (!buildPanel) return;
    // The options the panel was last showing, or — the first time — how the deck was built.
    refract::BuildOptions options = builder.optionsFromManifest();
    if (!sessionOnDisk.empty() || session.build) {
        // What the panel was last showing, rather than how the deck happens to have been
        // built — they are different questions once somebody has changed one of them.
        options.transitions = session.buildTransitions;
        options.debug = session.buildDebug;
        options.force = session.buildForce;
        options.keepJson = session.buildKeepJson;
    }
    buildPanel->setOptions(options);
    buildPanel->setOnBuild([](const refract::BuildOptions& options) {
        return builder.start(options);
    });
    buildPanel->setWatching(session.buildWatch);
    session.restore("build", buildPanel->window());
    glfwSetKeyCallback(buildPanel->window(),
                       [](GLFWwindow* w, int key, int scancode, int action, int mods) {
        if (buildPanel && buildPanel->handleKey(key, action, mods)) return;
        playerKeyCallback(w, key, scancode, action, mods);
    });
}

void toggleBuildPanel() {
    if (buildPanel) buildPanel.reset();
    else openBuildPanel();
    saveSessionIfChanged();
}

// ── Slide editor ─────────────────────────────────────────────────────

// The deck must not move while a slide's source is half-rewritten: the editor would either
// lose the edit or save it onto the wrong slide.
bool editorHoldsDeck() {
    return slideEditor && slideEditor->dirty();
}

void openSlideEditor() {
    if (slideEditor) return;
    slideEditor = refract::SlideEditor::Create(560, 620);
    if (!slideEditor) return;
    slideEditor->setLoader([](int slide, std::string* text, std::string* file, int* shared,
                          std::string* error) {
        return source.readSlide(slide, text, file, shared, error);
    });
    slideEditor->setSaver([](int slide, const std::string& text, std::string* error) {
        return source.writeSlide(slide, text, error);
    });
    slideEditor->setSplitter([](int slide, const std::string& text, int line,
                            std::string* error) {
        return source.splitSlide(slide, text, line, error);
    });
    slideEditor->setFileAccess(
        [](const std::string& path, std::string* text, std::string* error) {
            return source.readFile(path, text, error);
        },
        [](const std::string& path, const std::string& text, std::string* error) {
            return source.writeFile(path, text, error);
        });
    slideEditor->setAutoSave(session.editorAutoSave);
    session.restore("editor", slideEditor->window());
    slideEditor->showSlide(g.currentIndex);
    // The editor takes the whole keyboard while it has focus — every key is a character in
    // there, and "b" must not blank the projector mid-sentence.
    glfwSetKeyCallback(slideEditor->window(),
                       [](GLFWwindow* w, int key, int scancode, int action, int mods) {
        if (slideEditor && slideEditor->handleKey(key, action, mods)) return;
        playerKeyCallback(w, key, scancode, action, mods);
    });
    glfwSetCharCallback(slideEditor->window(), [](GLFWwindow*, unsigned int codepoint) {
        if (slideEditor) slideEditor->handleChar(codepoint);
    });
}

void toggleSlideEditor() {
    if (slideEditor) slideEditor.reset();
    else openSlideEditor();
    saveSessionIfChanged();
}

void togglePresenter() {
    if (presenter) presenter.reset();
    else openPresenter();
    saveSessionIfChanged();
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
        // A filter being typed owns the keyboard, the same as in the deck view.
        if (app.navFiltering) {
            switch (key) {
                case GLFW_KEY_ESCAPE:
                    app.navFiltering = false;
                    app.navFilter.clear();
                    return;
                case GLFW_KEY_BACKSPACE:
                    if (!app.navFilter.empty()) app.navFilter.pop_back();
                    return;
                case GLFW_KEY_ENTER:
                case GLFW_KEY_KP_ENTER:
                    app.navFiltering = false;
                    // Leaves the filter showing: the list stays narrowed while you look.
                    return;
                case GLFW_KEY_UP:    refract::navMove(app, -1); return;
                case GLFW_KEY_DOWN:  refract::navMove(app, 1); return;
                default: return;
            }
        }
        if (key == GLFW_KEY_SLASH) {
            app.navFiltering = true;
            app.navFilter.clear();
            return;
        }
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
                // The filter is cleared first; a second Esc closes the navigator.
                if (!app.navFilter.empty()) { app.navFilter.clear(); return; }
                [[fallthrough]];
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
        case GLFW_KEY_F: refract::setFullscreen(window, glfwGetWindowMonitor(window) == nullptr); break;
        case GLFW_KEY_P: togglePresenter(); break;
        case GLFW_KEY_C: toggleCaptions(); break;
        case GLFW_KEY_V: toggleDeckView(); break;
        case GLFW_KEY_M: toggleBuildPanel(); break;
        case GLFW_KEY_E: toggleSlideEditor(); break;
        case GLFW_KEY_I: toggleAssetWindow(); break;

        // ── Playback ─────────────────────────────────────────────────
        case GLFW_KEY_A:
            g.paused = !g.paused;
            if (g.avfPlayer) g.avfPlayer->setPaused(g.paused);
            g.videoHost.setPaused(g.paused);
            break;
        case GLFW_KEY_R:
            if (mods & GLFW_MOD_SHIFT) {
                toggleSlideRecording();
            } else {
                refract::clearThumbCache();
                loadCurrentFile();
            }
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
            // A take in progress is dropped first: Esc is "back out of this", and there is
            // nothing else it could mean while the microphone is open.
            if (app.reRecording) { stopSlideRecording(/*keep=*/false); break; }
            if (app.showHelp) app.showHelp = false;
            else if (!app.jumpDigits.empty()) app.jumpDigits.clear();
            else if (app.blank) app.blank = 0;
            else if (glfwGetWindowMonitor(window) != nullptr) refract::setFullscreen(window, false);
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

}  // namespace

int main(int argc, char* argv[]) {
    const refract::Options options = refract::parseOptions(argc, argv);
    if (!options.error.empty()) {
        std::cerr << "refractplayer: " << options.error << "\n" << refract::usageText();
        return 1;
    }
    if (options.help) {
        std::cerr << refract::usageText();
        return 0;
    }

    // What the options say about the run itself, rather than about a window.
    app.clock.target = options.duration;
    app.recordAudio = options.recordAudio;
    g.autoAdvanceSec = options.autoAdvanceSec;
    g.autoAdvanceOnVoice = options.autoVoice;
    g.voiceOverEnabled = options.sound;
    wantPresenter = options.presenter;
    wantDeckView = options.deckView;
    wantBuildPanel = options.buildPanel;
    wantEditor = options.editor;

    int initW = options.width, initH = options.height;
    std::string input = options.input;

    if (input.empty()) {
        // Nothing named. From a terminal the usage text is the useful answer; double-clicked,
        // it was a process that printed into nowhere and exited. So say it, then ask — the
        // player can write a deck as well as play one, and "start a new one" is now something
        // it can offer.
        std::cerr << refract::usageText();
        if (!options.headless()) {
            if (!glfwInit()) return 1;
            input = refract::runStartWindow();
        }
        if (input.empty()) {
            glfwTerminate();
            return 1;
        }
    }

    // ── Export ───────────────────────────────────────────────────────
    // Headless: no window, no GLFW, no playlist — the exporters walk the deck themselves.
    // Size follows the window size, which defaults to the deck's design size; a PDF page
    // takes an .rc slide's own size over it, so there it only matters for media pages.
    if (!options.pdf.empty() || !options.images.empty()) {
        int failures = 0;
        if (!options.pdf.empty()) {
            auto result = exportDeckToPdf(input, options.pdf, initW, initH, options.exportDelay);
            if (result.pages == 0) failures++;
        }
        if (!options.images.empty()) {
            auto result = exportDeckToImages(input, options.images, initW, initH, options.exportDelay);
            if (result.images == 0 || result.failures > 0) failures++;
        }
        return failures > 0 ? 1 : 0;
    }

    // ── Playlist ─────────────────────────────────────────────────────
    input = resolveDeck(input);
    refract::rememberDeck(fs::path(input).filename() == "out"
                              ? fs::path(input).parent_path().string() : input);
    deckInput = input;
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

    // ── Web player ───────────────────────────────────────────────────
    // The deck, its narration and its captions, assembled into a page that plays them.
    if (!options.web.empty()) {
        if (g.zip) {
            std::cerr << "refractplayer: --web needs a deck directory, not a zip\n";
            return 1;
        }
        const fs::path slidesDir = fs::is_directory(input)
                                       ? fs::path(input)
                                       : fs::path(g.files.front()).parent_path();
        return refract::runTool("web.py", {slidesDir.string(), options.web});
    }

    // ── Transcription ────────────────────────────────────────────────
    // Needs the playlist — that is what says where the narration was recorded — but no
    // window, so it runs before one is opened and exits.
    if (options.transcribe) {
        const fs::path wav = voicePathFor(g.files.front());
        if (wav.empty()) {
            std::cerr << "refractplayer: slides are not numbered, so there are no voice "
                         "files to transcribe\n";
            return 1;
        }
        return refract::runTool("captions.py", {wav.parent_path().string(),
                                       "--model", options.captionModel,
                                       "--language", options.captionLanguage});
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
    // Which wav belongs to which slide. Loaded before anything plays, because after a reorder
    // the numbers on the files are no longer the numbers on the slides.
    if (!g.voiceDirOverride.empty()) voiceIndex.load(g.voiceDirOverride);

    if (options.record) {
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
            // The recording writes its own index as it goes, so a run that is killed part
            // way still leaves the slides it did record correctly paired.
            const fs::path first = voicePathFor(g.files.front());
            if (!first.empty()) {
                std::error_code ec;
                fs::create_directories(first.parent_path(), ec);
                voiceIndex.setPath(first.parent_path() / "index.json");
            }
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
    // What was open last time, and where. Read before any window is made, because the first
    // of them is the deck's own and it wants putting back too.
    // Where the edit tools are pointed. Empty for a zip bundle, which has no markdown.
    {
        const fs::path out = refract::deckSidecarPath(input, "deck.json");
        if (!out.empty()) {
            source.setOutDir(out.parent_path().string());
            builder.setOutDir(out.parent_path().string());
        }
        // A finished write changed the deck on disk: reload it, and remember which stills
        // the rebuild actually rewrote so the rest can be kept.
        source.setOnChanged([](std::vector<std::string> outputs) {
            changedOutputs = std::move(outputs);
            deckReloadPending = true;
        });
        source.setOnEditFinished([](bool ok, const std::string& done) {
            if (deckView) deckView->editFinished(ok, done);
        });
        source.setOnSaveFinished([](bool ok, const std::string& done) {
            if (slideEditor) slideEditor->saveFinished(ok, done);
        });
    }

    if (session.load(input)) sessionOnDisk = session.serialise();

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
    slideWindow = window;
    // Where it was last time. A size on the command line or a `--display` outranks it, the
    // same way an explicitly opened panel does: asking for something beats a memory of it.
    if (!options.sizeGiven && options.display < 0) session.restore("slides", window);

    if (options.display >= 0) {
        GLFWmonitor* monitor = refract::monitorAt(options.display);
        int mx, my;
        glfwGetMonitorPos(monitor, &mx, &my);
        glfwSetWindowPos(window, mx + 40, my + 40);
        // The presenter window belongs on a *different* screen from the slides.
        presenterMonitor = options.display + 1;
        int count = 0;
        glfwGetMonitors(&count);
        if (presenterMonitor >= count) presenterMonitor = -1;
    }

    glfwMakeContextCurrent(window);
    glfwSwapInterval(1);

#if defined(__APPLE__)
    if (options.useMetal) {
        g.backend = MetalRenderBackend::Create(window);
        if (!g.backend) {
            std::cerr << "refractplayer: Metal unavailable, using CPU\n";
            g.backend = std::make_unique<CpuRenderBackend>();
        }
    } else {
        g.backend = std::make_unique<CpuRenderBackend>();
    }
#else
    (void)options.useMetal;
    g.backend = std::make_unique<CpuRenderBackend>();
#endif
    // Hands the window to the player *and* to the hosts that put native views over the
    // slide — embedded web pages are real WKWebViews in this window's content view.
    attachWindow(window);

    // Pointer, resize and framebuffer handling are the viewer's — documents are interactive
    // and should behave identically here. Only the keys are ours.
    installDefaultCallbacks(window);
    glfwSetKeyCallback(window, playerKeyCallback);
    // The only text this window takes: a name typed at the navigator.
    glfwSetCharCallback(window, [](GLFWwindow*, unsigned int codepoint) {
        if (app.navOpen && app.navFiltering && codepoint >= 0x20 && codepoint != '/') {
            app.navFilter.push_back(static_cast<char>(codepoint < 0x80 ? codepoint : '?'));
        }
    });

    int fbW = 0, fbH = 0;
    glfwGetFramebufferSize(window, &fbW, &fbH);
    g.backend->onFramebufferResize(fbW, fbH);
    int winW = 0, winH = 0;
    glfwGetWindowSize(window, &winW, &winH);
    ensureSurface(winW, winH);

    if (options.fullscreen) {
        refract::setFullscreen(window, true, options.display >= 0 ? refract::monitorAt(options.display) : nullptr);
        glfwGetWindowSize(window, &winW, &winH);
        ensureSurface(winW, winH);
    }
    // A flag on the command line still opens a panel the session had closed — asking for
    // something explicitly outranks a memory of not having wanted it.
    if (wantPresenter || session.presenter) openPresenter();
    if (options.captions || session.captions) openCaptions();
    if (wantDeckView || session.deckView) openDeckView();
    if (wantBuildPanel || session.build) openBuildPanel();
    if (wantEditor || session.editor) openSlideEditor();
    if (options.assets || session.assets) openAssetWindow();

    // The panels, in the menu bar. Chosen from a menu they arrive on Cocoa's thread of
    // control rather than GLFW's, in the middle of the event pump — so the item only asks,
    // and the loop opens the window a moment later where every other window is opened.
    refract::installWindowMenu({
        {"Presenter",    "1", [] { menuRequest = MenuPanel::Presenter; },
                              [] { return presenter != nullptr; }},
        {"Deck View",    "2", [] { menuRequest = MenuPanel::DeckView; },
                              [] { return deckView != nullptr; }},
        {"Slide Editor", "3", [] { menuRequest = MenuPanel::Editor; },
                              [] { return slideEditor != nullptr; }},
        {"Build",        "4", [] { menuRequest = MenuPanel::Build; },
                              [] { return buildPanel != nullptr; }},
        {"Captions",     "5", [] { menuRequest = MenuPanel::Captions; },
                              [] { return captionWindow != nullptr; }},
        {"Assets",       "7", [] { menuRequest = MenuPanel::Assets; },
                              [] { return assetWindow != nullptr; }},
        {"Navigator",    "6", [] { menuRequest = MenuPanel::Navigator; },
                              [] { return app.navOpen; }},
    });

    refreshVoicePresence();
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
    double lastDeckViewDraw = -1.0;
    double lastBuildDraw = -1.0;
    // Watching the deck's sources. Sampled on a timer rather than every frame: it is a walk
    // of includes/, and a second's latency on a rebuild nobody asked for is not felt.
    double lastSessionCheck = -1.0;
    constexpr double kSessionInterval = 4.0;
    double lastWatchCheck = -1.0;
    double watchedMtime = 0.0;
    constexpr double kWatchInterval = 1.0;
    double lastEditorDraw = -1.0;
    double lastAssetDraw = -1.0;
    // A finished build is acted on once, not every frame it stays finished.
    bool buildReloaded = true;
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

        // A panel asked for from the menu bar.
        if (menuRequest != MenuPanel::None) {
            const MenuPanel want = menuRequest;
            menuRequest = MenuPanel::None;
            switch (want) {
                case MenuPanel::Presenter: togglePresenter(); break;
                case MenuPanel::DeckView:  toggleDeckView(); break;
                case MenuPanel::Editor:    toggleSlideEditor(); break;
                case MenuPanel::Build:     toggleBuildPanel(); break;
                case MenuPanel::Captions:  toggleCaptions(); break;
                case MenuPanel::Navigator: app.navOpen = !app.navOpen; break;
                case MenuPanel::Assets:    toggleAssetWindow(); break;
                case MenuPanel::None:      break;
            }
        }

        source.collect();

        if (deckReloadPending) {
            deckReloadPending = false;
            glfwMakeContextCurrent(window);
            if (!reloadDeck()) std::cerr << "refractplayer: reload failed\n";
            // What the deck uses may have changed with it.
            if (assetWindow) assetWindow->refresh();
            liveFrame.reset();
            lastCapturedSlide = -1;
        }

        auto now = std::chrono::steady_clock::now();
        double elapsed = std::chrono::duration<double>(now - startTime).count();
        double dt = elapsed - lastFrame;
        lastFrame = elapsed;

        // Window geometry moves without any toggle to notice it, so the session is looked at
        // on a slow timer too. It is written only when it has actually changed.
        if (elapsed - lastSessionCheck >= kSessionInterval) {
            lastSessionCheck = elapsed;
            saveSessionIfChanged();
        }

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
                const auto* entry = app.timing.find(app.deck.at(g.currentIndex).sourceKey(),
                                                    app.deck.at(g.currentIndex).file);
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
                const bool listening = recorder && (app.timing.recording() || app.reRecording);
                if (listening) {
                    recorder->updateLevels();
                    presenter->pushAudioLevel(recorder->averageLevel(), recorder->peakLevel());
                } else {
                    presenter->pushAudioLevel(-1.0f, -1.0f);
                }
                presenter->render(app, liveFrame);
                lastPresenterDraw = elapsed;
            }
        }

        if (slideEditor) {
            if (slideEditor->shouldClose()) {
                slideEditor.reset();
            } else if (elapsed - lastEditorDraw >= kCaptionInterval) {
                // At the caption window's rate rather than the presenter's: a caret that
                // blinks at 20 Hz is a caret that stutters while you type.
                slideEditor->render(app);
                lastEditorDraw = elapsed;
            }
        }

        if (assetWindow) {
            if (assetWindow->shouldClose()) {
                assetWindow.reset();
                saveSessionIfChanged();
            } else if (elapsed - lastAssetDraw >= kPresenterInterval) {
                assetWindow->render(app);
                lastAssetDraw = elapsed;
            }
        }

        if (buildPanel) {
            if (buildPanel->shouldClose()) {
                buildPanel.reset();
            } else {
                // A build that has just finished changed the deck on disk; reload it the same
                // way a reorder does, so the slides on screen are the ones just built.
                const refract::BuildState state = builder.state();
                if (state.ran && !state.running && !buildReloaded) {
                    buildReloaded = true;
                    if (state.ok) deckReloadPending = true;
                }
                if (state.running) buildReloaded = false;
                buildPanel->setState(state);

                // Rebuild when the markdown moves under us. The first sample after the
                // switch is turned on only records where things stand — turning it on is
                // not itself a change.
                if (buildPanel->watching() && !state.running && !source.running()
                    && elapsed - lastWatchCheck >= kWatchInterval) {
                    lastWatchCheck = elapsed;
                    const double now = builder.sourceMtime();
                    if (watchedMtime != 0.0 && now > watchedMtime) {
                        builder.start(buildPanel->options());
                    }
                    watchedMtime = now;
                } else if (!buildPanel->watching()) {
                    watchedMtime = 0.0;
                }
                // The column sits against whichever panel window is open, and floats free
                // when neither is.
                buildPanel->setHost(deckView ? deckView->window()
                                             : presenter ? presenter->window() : nullptr);
                if (elapsed - lastBuildDraw >= kPresenterInterval) {
                    buildPanel->render(app);
                    lastBuildDraw = elapsed;
                }
            }
        }

        if (deckView) {
            if (deckView->shouldClose()) {
                deckView.reset();
            } else if (elapsed - lastDeckViewDraw >= kPresenterInterval) {
                deckView->render(app);
                lastDeckViewDraw = elapsed;
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

        // Collect whatever the still worker finished. The rendering itself is on its own
        // thread — a heavy slide takes over a second, and that used to be a second of frozen
        // window landing exactly when a key was pressed — so this is a lock and a move.
        refract::collectThumbs();
    }

    // An edit in progress is finished rather than dropped: it is saved on leaving edit mode,
    // and quitting mid-word should not be the one way to lose it.
    if (captionWindow && captionWindow->isEditing()) captionWindow->finishEditing();

    stopSlideRecording(/*keep=*/true);
    if (app.timing.recording()) app.timing.finish(app.clock.elapsed);
    if (recorder) recorder->stop();
    recorder.reset();
    if (voice) voice->stop();
    voice.reset();
    refract::stopThumbs();
    // What is still open at the end is what was open, so it comes back next time. The same
    // capture the timer takes while the player runs — a clean quit should not remember
    // anything different from a kill.
    captureSession();
    session.save(deckInput);

    captionWindow.reset();
    assetWindow.reset();
    deckView.reset();
    buildPanel.reset();
    slideEditor.reset();
    builder.join();
    source.join();
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
