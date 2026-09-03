// State the player owns on top of rcplayer's: which slide of the deck we are on, the talk
// timer, and the transient UI (navigator, blanked screen, pending jump).
//
// rcplayer::g stays the source of truth for *what is playing* — this is everything a
// presenter needs that a viewer does not.
#pragma once

#include "Deck.h"

#include <string>

namespace refract {

// The talk timer. Deliberately separate from the animation clock in rcplayer::g: pausing a
// slide's animation must not stop the clock you are presenting against, and a slide that
// reloads must not rewind it.
struct TalkClock {
    bool   running = false;
    double elapsed = 0.0;
    double target  = 0.0;   // planned talk length in seconds; 0 = untimed

    void tick(double dt) { if (running) elapsed += dt; }
    void toggle()        { running = !running; }
    void reset()         { elapsed = 0.0; running = false; }

    // Elapsed as a fraction of the planned length, or -1 when untimed.
    double fraction() const { return target > 0.0 ? elapsed / target : -1.0; }
    // Time left against the plan; negative once over. Meaningless when untimed.
    double remaining() const { return target - elapsed; }
};

struct App {
    Deck      deck;
    TalkClock clock;

    // The timer starts itself when you leave the title slide — the moment a talk actually
    // begins — so there is nothing to remember to press. Explicitly starting or stopping it
    // (T) takes over from then on.
    bool autoStartClock = true;

    int    blank = 0;              // 0 = showing, 1 = black, 2 = white
    double slideEnteredAt = 0.0;   // clock.elapsed when the current slide came up
    // Wall-clock seconds since the last slide change, independent of the talk clock and of
    // whether animation is paused. Used to keep background work off the transition.
    double sinceSlideChange = 0.0;

    // Navigator overlay.
    bool  navOpen = false;
    int   navCursor = 0;           // slide index the overlay is highlighting
    float navScroll = 0.0f;        // pixels, animated toward keeping the cursor in view

    // Digits typed for a "jump to slide N" (committed on Enter, dropped on Esc).
    std::string jumpDigits;

    bool showHelp = false;

    int current() const;
    // Seconds spent on the current slide.
    double timeOnSlide() const { return clock.elapsed - slideEnteredAt; }
};

}  // namespace refract
