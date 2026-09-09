// Turning a scroll event into a distance.
//
// A wheel notch and a swipe of two fingers arrive through the same GLFW callback with
// nothing to say which is which. What separates them is the shape of the number: GLFW passes
// a wheel's notch count straight through, so it arrives as a whole ±1, while a trackpad's
// pixel delta is scaled by a tenth and arrives as a stream of small fractions.
//
// They want completely different distances. A notch is a discrete "move down a bit" and
// should cover a few lines — a notch that moves one line is the scroll wheel that feels
// broken. A swipe is already a distance, and only wants a gain on it.
#pragma once

namespace refract {

// Pixels to scroll for one event, given the height of a line (or row, or card) in the view
// being scrolled. Positive `delta` is up, as GLFW reports it — the caller subtracts.
float scrollPixels(double delta, float lineHeight);

// How long after a scroll a view should keep redrawing at full rate. Scrolling a panel drawn
// at 20Hz is what "slow scrolling" usually turns out to be: the distance is right and the
// picture arrives in steps.
constexpr double kScrollingFor = 0.4;

}  // namespace refract
