// The mouse over the slide window: when to hide it, and the laser pointer.
//
// A projected slide should not have an arrow sitting on it, so the pointer goes away after
// a few seconds without moving and comes back on the first move. The laser is the other
// mode: a large red dot in place of the arrow, with a trail that fades behind it, so a
// hand waving at the wall can be followed from the back of the room.
//
// This is the model — where the mouse has been, and when. The drawing is in Navigator.cpp
// with the other overlays.
#pragma once

#include <deque>
#include <vector>

namespace refract {

class Pointer {
public:
    struct Sample {
        double x = 0, y = 0;
        double at = 0;          // seconds, on the caller's clock
    };

    // A cursor event, at `now`. The mouse is inside the window from then on.
    void moved(double x, double y, double now);
    // The cursor left the window (or came back without moving).
    void left();
    void entered();
    bool inside() const { return mInside; }

    // No motion for `after` seconds — time to hide the arrow.
    bool idle(double now, double after) const { return now - mLastMove >= after; }

    void setLaser(bool on);
    bool laser() const { return mLaser; }

    // The laser's trail: the samples younger than `fade` seconds, oldest first. Empty when
    // the laser is off or the mouse is out of the window.
    std::vector<Sample> trail(double now, double fade) const;

    // The newest sample, for the dot itself.
    bool head(Sample* out) const;

private:
    std::deque<Sample> mSamples;
    double mLastMove = 0.0;
    bool mInside = false;
    bool mLaser = false;
};

}  // namespace refract
