// The processing window: what the player is doing in the background, and how far it is.
//
// An export or a transcription runs for minutes on a worker, and until now the only sign
// of it was the terminal. This is a small window with one row per task — its name, what it
// is doing, a bar — opened when a task starts and left up, with the outcome, until closed.
#pragma once

#include <memory>
#include <string>
#include <vector>

struct GLFWwindow;

namespace refract {

// One background task as the window shows it.
struct TaskView {
    std::string name;          // "Export video talk.mp4"
    std::string status;        // "slide 3/23 05_between.rc", "done", "failed: …"
    float fraction = -1.0f;    // 0..1, or negative when unknown
    bool running = false;
    bool failed = false;       // finished, badly
};

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
