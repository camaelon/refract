// Hiding the system cursor over the slide window.
//
// GLFW's cursor mode only takes effect while the window is the focused one, and in a talk
// the slide window on the projector is rarely that: the presenter window on the laptop is
// where the clicks go. So the arrow is hidden at the system level while the pointer is
// over the slide, whichever window has focus.
#pragma once

namespace refract {

// Hide or show the system cursor. Balanced: calling with the same value twice is a no-op.
void setSystemCursorHidden(bool hidden);

}  // namespace refract
