// Monitors, and going fullscreen on the right one.
//
// Small, but fiddly enough to be worth keeping in one place: which screen a window is
// mostly on, and where it was before it took one over. GLFW gives neither.
#pragma once

struct GLFWwindow;
struct GLFWmonitor;

namespace refract {

// The n-th monitor, 0-based, or the primary one when there is no such screen.
GLFWmonitor* monitorAt(int wanted);

// The monitor holding most of the window — the one you would expect fullscreen to fill.
GLFWmonitor* monitorForWindow(GLFWwindow* window);

// Take a screen, or give it back. Going fullscreen remembers where the window was, so
// leaving puts it back there rather than somewhere GLFW picks.
void setFullscreen(GLFWwindow* window, bool on, GLFWmonitor* preferred = nullptr);

// Where the window sits when it is not filling a screen — live if it is windowed now, and
// the geometry it would return to if it is not. False when the window has never been
// windowed here, which is nothing worth remembering.
bool windowedGeometry(GLFWwindow* window, int* x, int* y, int* w, int* h);

}  // namespace refract
