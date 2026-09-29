// Dragging a file out of a window is the window system's business, and only the Cocoa one is
// implemented. Elsewhere the pane is simply not a drag source.
#include "DragOut.h"

namespace refract {

bool beginFileDrag(GLFWwindow*, const std::string&) { return false; }
bool beginTextDrag(GLFWwindow*, const std::string&, const std::string&) { return false; }

}  // namespace refract
