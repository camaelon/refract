// The app's menu bar: a way to reach the player's panels that does not need a key.
//
// The panels are the useful half of this program and every one of them was a single letter —
// fine once you know, and invisible until you do. A menu is where a Mac application says what
// it can do, and it is also where somebody finds out that the shortcut exists.
//
// GLFW builds no menus of its own beyond the ones AppKit insists on, so this is Cocoa
// directly. Everywhere else it does nothing, and the keys are the whole story.
#pragma once

#include <functional>
#include <string>
#include <vector>

namespace refract {

struct MenuItem {
    std::string title;
    // The key that opens it with Command. Empty for no shortcut.
    std::string key;
    // Run when the item is chosen. Called on the main thread, from inside the event pump.
    std::function<void()> action;
    // Whether the panel is open, for the tick beside the item. Asked each time the menu is
    // opened, so it is always the truth rather than a copy of it.
    std::function<bool()> open;
};

// Add these to the menu bar's "Window" menu, under a separator. Safe to call once, after the
// windowing system is up. Does nothing off macOS.
void installWindowMenu(std::vector<MenuItem> items);

}  // namespace refract
