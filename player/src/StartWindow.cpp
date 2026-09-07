#include "StartWindow.h"

#include "DeckLibrary.h"

#include "FileDialog.h"
#include "Ui.h"

#include "rcplayer/CpuRenderBackend.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>

namespace fs = std::filesystem;

namespace refract {

// ── The window ───────────────────────────────────────────────────────

namespace {

struct Choice {
    std::string deck;      // what was picked
    bool done = false;     // ...or the window was closed
};

struct Row {
    SkRect box;
    std::string deck;      // empty for the two buttons
    int action = 0;        // 1 = open, 2 = new
};

}  // namespace

std::string runStartWindow() {
    GLFWwindow* previous = glfwGetCurrentContext();
    glfwWindowHint(GLFW_DECORATED, GLFW_TRUE);
    glfwWindowHint(GLFW_FOCUSED, GLFW_TRUE);
    GLFWwindow* window = glfwCreateWindow(560, 420, "refract", nullptr, nullptr);
    if (!window) return {};

    Choice choice;
    std::vector<Row> rows;
    double mouseX = 0, mouseY = 0;
    struct State { Choice* choice; std::vector<Row>* rows; double* x; double* y; };
    State state{&choice, &rows, &mouseX, &mouseY};
    glfwSetWindowUserPointer(window, &state);

    glfwSetCursorPosCallback(window, [](GLFWwindow* w, double x, double y) {
        auto* s = static_cast<State*>(glfwGetWindowUserPointer(w));
        *s->x = x;
        *s->y = y;
    });
    glfwSetMouseButtonCallback(window, [](GLFWwindow* w, int button, int action, int) {
        auto* s = static_cast<State*>(glfwGetWindowUserPointer(w));
        if (button != GLFW_MOUSE_BUTTON_LEFT || action != GLFW_PRESS) return;
        for (const Row& row : *s->rows) {
            if (!row.box.contains(static_cast<float>(*s->x), static_cast<float>(*s->y))) continue;
            if (!row.deck.empty()) {
                s->choice->deck = row.deck;
                s->choice->done = true;
            } else if (row.action == 1) {
                // The dialog is modal and runs its own loop; whatever comes back is the answer.
                const std::string picked = chooseDeck();
                if (!picked.empty()) { s->choice->deck = picked; s->choice->done = true; }
            } else if (row.action == 2) {
                const std::string picked = chooseNewDeck();
                if (picked.empty()) return;
                std::string error;
                if (createDeck(picked, &error)) {
                    s->choice->deck = picked;
                    s->choice->done = true;
                } else {
                    std::cerr << "refractplayer: " << error << "\n";
                }
            }
            return;
        }
    });

    glfwMakeContextCurrent(window);
    glfwSwapInterval(1);
    CpuRenderBackend backend;
    int w = 560, h = 420;
    backend.resize(w, h);
    int fbW = 0, fbH = 0;
    glfwGetFramebufferSize(window, &fbW, &fbH);
    backend.onFramebufferResize(fbW, fbH);

    const std::vector<std::string> recent = recentDecks();

    while (!glfwWindowShouldClose(window) && !choice.done) {
        glfwPollEvents();

        int nw = 0, nh = 0;
        glfwGetWindowSize(window, &nw, &nh);
        if (nw > 0 && nh > 0 && (nw != w || nh != h)) {
            w = nw;
            h = nh;
            backend.resize(w, h);
            glfwGetFramebufferSize(window, &fbW, &fbH);
            backend.onFramebufferResize(fbW, fbH);
        }
        SkCanvas* canvas = backend.canvas();
        if (!canvas) break;
        canvas->clear(ui::kBg);
        rows.clear();

        const float pad = 28;
        drawText(canvas, "refract", pad, 52, uiFont(26, true), ui::kText);
        drawText(canvas, "a presenter's player for markdown decks", pad, 74, uiFont(12),
                 ui::kDim);

        float y = 108;
        // The two things you can do, before the list: on a first run the list is empty, and a
        // window whose only content is a heading over nothing is not a welcome.
        const char* labels[] = {"Open a deck…", "New deck…"};
        for (int i = 0; i < 2; i++) {
            SkRect box = SkRect::MakeXYWH(pad, y, 200, 34);
            const bool hot = box.contains(static_cast<float>(mouseX),
                                          static_cast<float>(mouseY));
            const bool able = canChooseFiles();
            fillRoundRect(canvas, box, 8, hot && able ? ui::kPanel : ui::kBg);
            strokeRoundRect(canvas, box, 8, able ? (hot ? ui::kAccent : ui::kLine) : ui::kLine);
            drawTextCentred(canvas, labels[i], box, uiFont(13, true),
                            able ? ui::kText : ui::kLine);
            if (able) rows.push_back({box, {}, i + 1});
            y += 42;
        }
        if (!canChooseFiles()) {
            drawText(canvas, "name a deck on the command line to open one", pad + 212, y - 60,
                     uiFont(12), ui::kDim);
        }

        y += 12;
        drawText(canvas, recent.empty() ? "NO DECKS YET" : "RECENT", pad, y, uiFont(10, true),
                 ui::kDim);
        y += 20;
        canvas->save();
        canvas->clipRect(SkRect::MakeLTRB(0, y - 16, w, h));
        for (const std::string& deck : recent) {
            SkRect box = SkRect::MakeXYWH(pad, y, w - pad * 2, 30);
            const bool hot = box.contains(static_cast<float>(mouseX),
                                          static_cast<float>(mouseY));
            if (hot) fillRoundRect(canvas, box, 6, ui::kPanel);
            const fs::path path(deck);
            SkFont nameFont = uiFont(14, true);
            const float nameW = drawText(canvas, path.filename().string(), box.left() + 10,
                                         box.top() + 20, nameFont, ui::kText);
            drawText(canvas,
                     ellipsize(path.parent_path().string(), uiFont(11),
                               box.width() - nameW - 30),
                     box.left() + 18 + nameW, box.top() + 20, uiFont(11), ui::kDim);
            rows.push_back({box, deck, 0});
            y += 34;
        }
        canvas->restore();

        backend.present();
        glfwSwapBuffers(window);
    }

    glfwMakeContextCurrent(window);
    glfwDestroyWindow(window);
    if (previous) glfwMakeContextCurrent(previous);
    return choice.deck;
}

}  // namespace refract
