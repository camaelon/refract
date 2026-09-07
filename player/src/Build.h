// What refract is asked to do, and what it did.
//
// Its own header because the panel that shows these and the runner that produces them are
// separate: the panel holds the switches, the runner owns the process.
#pragma once

#include <string>

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

}  // namespace refract
