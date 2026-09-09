// What is in the deck's includes/, and which of it is still used.
//
// A talk's includes/ collects things over its life — the screenshot that was replaced, the
// diagram from the version that got cut, the clip nobody played. Nothing in the player showed
// you that folder, so the only way to tidy it was to read the markdown and guess.
//
// Usage is not guessed here: it comes from loading the deck with refract's own resolver, so
// it is the same answer the build gives. Removing an asset moves it to out/.trash/ rather
// than deleting it — everything else the player does can be taken back, and an asset is the
// one thing the undo history, which stores text, cannot hold.
#pragma once

#include "App.h"
#include "Asset.h"

#include <functional>
#include <memory>
#include <string>
#include <vector>

struct GLFWwindow;

namespace refract {

class AssetWindow {
public:
    static std::unique_ptr<AssetWindow> Create(int width, int height);
    ~AssetWindow();

    GLFWwindow* window() const { return mWindow; }
    bool shouldClose() const;

    // Being scrolled right now. Drawing a panel at twenty frames a second is fine for a
    // clock and wrong for a moving list — the distance is right and the picture arrives in
    // steps, which is what "slow scrolling" usually turns out to mean. The loop draws it
    // every frame while this is true.
    bool scrolling() const;

    // Ask the deck what it has. Called when the window opens and after anything is removed.
    // `deckDir` comes back with them: the window reads the image files themselves to draw a
    // thumbnail, and only the scan knows where the deck actually lives.
    using Scanner = std::function<bool(std::vector<Asset>* out, std::string* deckDir,
                                       std::string* error)>;
    // Move one to the trash. True when the work was started; `status` says what happened.
    using Remover = std::function<bool(const std::string& path, std::string* status)>;
    void setScanner(Scanner scanner);
    void setRemover(Remover remover);

    // Re-read the list — after a removal, or after the deck was rebuilt and what is used may
    // have changed.
    void refresh();

    bool handleKey(int key, int action, int mods);
    void render(App& app);

private:
    AssetWindow() = default;

    struct Impl;
    std::unique_ptr<Impl> mImpl;
    GLFWwindow* mWindow = nullptr;
};

}  // namespace refract
