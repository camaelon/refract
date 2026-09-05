// The build panel: a narrow column that rebuilds the deck without leaving the player.
//
// Editing a deck means going back to a terminal to re-run refract, and then back to the
// player to see it. This closes that loop: the options refract was given are on screen, one
// button re-runs it, and the deck reloads underneath the slides when it is done.
//
// It is deliberately a *column*. Given a deck view or a presenter window to attach to it sits
// flush against its right edge and matches its height, so the two read as one panel — GLFW
// has no docking, but a window that tracks another one is close enough at this size.
#pragma once

#include "App.h"

#include <functional>
#include <memory>
#include <string>

struct GLFWwindow;

namespace refract {

// What refract will be told. Seeded from the `build` record deck.json carries, so the panel
// opens showing how the deck on screen was actually built rather than a set of defaults.
struct BuildOptions {
    bool transitions = false;
    bool debug = false;
    bool force = false;        // recompile every slide, ignoring the incremental cache
    bool keepJson = false;
};

// What the last (or current) build is doing. The panel only displays this; the build itself
// belongs to the app, which owns the process and the deck it reloads.
struct BuildState {
    bool running = false;
    bool ran = false;          // a build has finished at least once this session
    bool ok = true;
    int  rebuilt = 0, reused = 0, removed = 0;
    double seconds = 0.0;
    std::string error;
};

class BuildPanel {
public:
    static std::unique_ptr<BuildPanel> Create(int width, int height);
    ~BuildPanel();

    GLFWwindow* window() const { return mWindow; }
    bool shouldClose() const;

    // Start a build with these options. Returning false means it could not be started, and
    // the panel goes back to idle.
    void setOnBuild(std::function<bool(const BuildOptions&)> action);

    BuildOptions& options();
    void setOptions(const BuildOptions& options);
    void setState(const BuildState& state);

    // Rebuild whenever the deck's markdown changes. The panel only holds the switch; the
    // watching is the app's, which is where the deck's files are known.
    bool watching() const;

    // The window to sit against, or null to float free. Passed every frame because the
    // window it attaches to can be opened and closed while the panel is up.
    void setHost(GLFWwindow* host);

    bool handleKey(int key, int action, int mods);
    void render(App& app);

private:
    BuildPanel() = default;

    struct Impl;
    std::unique_ptr<Impl> mImpl;
    GLFWwindow* mWindow = nullptr;
};

}  // namespace refract
