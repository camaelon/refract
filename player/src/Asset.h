// One file under a deck's includes/, and what uses it.
//
// Its own header because two unrelated things need the shape: the window that lists assets,
// and the source layer that asks the tool for them.
#pragma once

#include <string>
#include <vector>

namespace refract {

// One of the deck's theme presets (`theme/<name>.toml`, named by `:: as: <name>`), as the
// editor's theme panel lists them: what it is called and what it looks like, so a swatch can
// be drawn without reading TOML.
struct ThemePreset {
    std::string name;
    std::string file;          // relative to the deck
    std::string type;          // the slide type it makes: content, title, section, …
    std::string background;    // #AARRGGBB, as refract writes colours
    std::string titleColor;
    std::string bodyColor;
    std::string accent;
    double titleSize = 0.0;
    double bodySize = 0.0;
    int keys = 0;              // how much the preset actually sets
    std::vector<int> slides;   // the slides it is on, 1-based
};

struct Asset {
    std::string path;              // relative to the deck
    std::string name;
    std::string kind;              // image, video, document, code, shader, deck, other
    long long   size = 0;
    std::vector<int> slides;       // 1-based; 0 means the deck's settings rather than a slide
    bool used = false;
};

}  // namespace refract
