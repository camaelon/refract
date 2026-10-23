// The build panel: a narrow column that rebuilds the deck without leaving the player.
//
// Editing a deck means going back to a terminal to re-run refract, and then back to the
// player to see it. This closes that loop: the options refract was given are on screen, one
// button re-runs it, and the deck reloads underneath the slides when it is done.
#pragma once

#include "App.h"
#include "Build.h"

#include <functional>
#include <memory>
#include <string>

struct GLFWwindow;

namespace refract {

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
    void setWatching(bool watch);

    bool handleKey(int key, int action, int mods);
    void render(App& app);

private:
    BuildPanel() = default;

    struct Impl;
    std::unique_ptr<Impl> mImpl;
    GLFWwindow* mWindow = nullptr;
};

}  // namespace refract
