// What the player remembers between runs, per deck.
//
// You open the presenter, the deck view and the build panel, arrange them across two screens,
// and quit. Without this, next time is defaults again — and a tool you point at the same deck
// all week should not have to be set up every morning.
//
// Kept beside the build, in out/.refract-session.json, so it is per deck and goes away with
// the generated files. None of it is required: a missing or unreadable session is the same as
// a fresh one, and every value here has a working default.
#pragma once

#include <map>
#include <string>
#include <vector>

struct GLFWwindow;

namespace refract {

// Where a window was, so it comes back there. Zero width means "never placed".
struct WindowPlace {
    int x = 0, y = 0, w = 0, h = 0;
    bool placed() const { return w > 0 && h > 0; }
};

struct Session {
    // Which panels were open.
    bool presenter = false, deckView = false, editor = false, build = false, captions = false;
    // Where each of them was, by the same names.
    std::map<std::string, WindowPlace> windows;

    bool editorAutoSave = false;
    bool buildWatch = false;
    // The build panel's options. Left out of `build_args` territory deliberately: these are
    // what the *panel* was showing, not what the deck was built with.
    bool buildTransitions = false, buildDebug = false, buildForce = false, buildKeepJson = false;
    // Runs the deck view had folded away, by the key that survives a rebuild.
    std::vector<std::string> folded;

    // Read the session beside the deck at `source` (a directory, a slide file, or a zip).
    // False when there is none, which is not an error.
    bool load(const std::string& source);
    bool save(const std::string& source) const;
    // The session as it would be written. Compared against the last write, so a session that
    // has not moved is not rewritten every few seconds for the life of the talk.
    std::string serialise() const;

    // Remember where a window is now, and put one back where it was.
    void capture(const std::string& name, GLFWwindow* window);
    void restore(const std::string& name, GLFWwindow* window) const;
};

}  // namespace refract
