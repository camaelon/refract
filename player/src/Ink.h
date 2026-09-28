// Drawing on a slide with the laser: hold the mouse button and the dot leaves a line.
//
// The strokes are kept per slide for the length of the run, so a slide drawn on and left
// still has its marks when it comes back; nothing is written to disk. Points are fractions
// of the slide's width and height rather than pixels, so a stroke survives the window being
// resized or the deck going fullscreen, and would mean the same thing on another machine.
#pragma once

#include <map>
#include <vector>

namespace refract {

struct InkPoint {
    float x = 0.0f, y = 0.0f;      // fractions of the slide, 0..1
};

struct InkStroke {
    std::vector<InkPoint> points;  // in the order they were drawn; one point is a dot
};

class Ink {
public:
    // The button went down over `slide` at (x, y): a stroke begins.
    void begin(int slide, float x, float y);
    // The mouse moved with the button still down. Ignored when nothing has begun, or when
    // the move is too small to be a new point.
    void extend(float x, float y);
    // The button came up (or the slide changed, or the laser went off).
    void end();
    bool drawing() const { return mDrawing; }

    const std::vector<InkStroke>& strokes(int slide) const;
    bool any(int slide) const;
    void clear(int slide);
    void clearAll();
    // How many slides have marks on them.
    int marked() const;

private:
    std::map<int, std::vector<InkStroke>> mBySlide;
    bool mDrawing = false;
    int mSlide = -1;
};

}  // namespace refract
