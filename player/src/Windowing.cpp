#include "Windowing.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include <algorithm>

namespace refract {

namespace {

// Where the window sat before it went fullscreen, so F can put it back. One window ever
// goes fullscreen — the deck's — so one of these is enough.
struct WindowedGeometry { int x = 0, y = 0, w = 0, h = 0; bool valid = false; };
WindowedGeometry saved;

}  // namespace

GLFWmonitor* monitorAt(int wanted) {
    int count = 0;
    GLFWmonitor** monitors = glfwGetMonitors(&count);
    if (count <= 0) return glfwGetPrimaryMonitor();
    if (wanted >= 0 && wanted < count) return monitors[wanted];
    return glfwGetPrimaryMonitor();
}

GLFWmonitor* monitorForWindow(GLFWwindow* window) {
    int wx, wy, ww, wh;
    glfwGetWindowPos(window, &wx, &wy);
    glfwGetWindowSize(window, &ww, &wh);
    int count = 0;
    GLFWmonitor** monitors = glfwGetMonitors(&count);
    GLFWmonitor* best = glfwGetPrimaryMonitor();
    int bestArea = 0;
    for (int i = 0; i < count; i++) {
        int mx, my;
        glfwGetMonitorPos(monitors[i], &mx, &my);
        const GLFWvidmode* mode = glfwGetVideoMode(monitors[i]);
        if (!mode) continue;
        int overlapW = std::max(0, std::min(wx + ww, mx + mode->width)  - std::max(wx, mx));
        int overlapH = std::max(0, std::min(wy + wh, my + mode->height) - std::max(wy, my));
        if (overlapW * overlapH > bestArea) {
            bestArea = overlapW * overlapH;
            best = monitors[i];
        }
    }
    return best;
}

void setFullscreen(GLFWwindow* window, bool on, GLFWmonitor* preferred) {
    const bool isFullscreen = glfwGetWindowMonitor(window) != nullptr;
    if (on == isFullscreen) return;
    if (on) {
        glfwGetWindowPos(window, &saved.x, &saved.y);
        glfwGetWindowSize(window, &saved.w, &saved.h);
        saved.valid = true;
        GLFWmonitor* monitor = preferred ? preferred : monitorForWindow(window);
        const GLFWvidmode* mode = glfwGetVideoMode(monitor);
        if (!mode) return;
        glfwSetWindowMonitor(window, monitor, 0, 0, mode->width, mode->height,
                             mode->refreshRate);
    } else {
        if (!saved.valid) saved = {100, 100, 1280, 720, true};
        glfwSetWindowMonitor(window, nullptr, saved.x, saved.y, saved.w, saved.h, 0);
    }
}

bool windowedGeometry(GLFWwindow* window, int* x, int* y, int* w, int* h) {
    if (!window) return false;
    if (!glfwGetWindowMonitor(window)) {
        glfwGetWindowPos(window, x, y);
        glfwGetWindowSize(window, w, h);
        return true;
    }
    if (!saved.valid) return false;
    *x = saved.x; *y = saved.y; *w = saved.w; *h = saved.h;
    return true;
}

}  // namespace refract
