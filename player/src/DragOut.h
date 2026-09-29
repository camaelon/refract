// Dragging a slide out of the player, as a picture.
//
// The presenter shows the slide that is on the wall; sometimes what you want is that picture
// somewhere else — on the desktop, in a message, in a browser tab. So the "now" pane is a
// drag source: press it and drag, and a PNG of the slide comes away under the pointer, as
// though it had been a file all along.
//
// Starting a drag is the window system's business, not GLFW's, so this is the one call into
// Cocoa. It has to be made while a mouse-drag event is being handled — which is exactly when
// the window's cursor callback runs — because the drag session needs that event.
#pragma once

#include <string>

struct GLFWwindow;

namespace refract {

// Begin dragging `file` out of `window`, with the file's own image under the pointer.
// False when there is no drag to begin (no file, not inside a mouse-drag event, or a
// platform that does not do this).
bool beginFileDrag(GLFWwindow* window, const std::string& file);

// The same for a piece of text — the notes, a transcript — which lands in whatever it is
// dropped on: an editor, a message, a text field. `label` is what shows under the pointer.
bool beginTextDrag(GLFWwindow* window, const std::string& text, const std::string& label);

}  // namespace refract
