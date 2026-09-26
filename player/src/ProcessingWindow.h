// The processing window: what the player is doing in the background, and how far it is.
//
// An export or a transcription runs for minutes on a worker, and until now the only sign
// of it was the terminal. This is a small window with one row per task — its name, what it
// is doing, a bar — opened when a task starts and left up, with the outcome, until closed.
#pragma once

#include "Tasks.h"

#include <memory>
#include <vector>

struct GLFWwindow;

namespace refract {

class ProcessingWindow {
public:
    static std::unique_ptr<ProcessingWindow> Create(int width, int height);
    ~ProcessingWindow();

    GLFWwindow* window() const { return mWindow; }
    bool shouldClose() const;

    void render(const std::vector<TaskView>& tasks);

private:
    ProcessingWindow() = default;
    struct Impl;
    std::unique_ptr<Impl> mImpl;
    GLFWwindow* mWindow = nullptr;
};

}  // namespace refract
