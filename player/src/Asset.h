// One file under a deck's includes/, and what uses it.
//
// Its own header because two unrelated things need the shape: the window that lists assets,
// and the source layer that asks the tool for them.
#pragma once

#include <string>
#include <vector>

namespace refract {

struct Asset {
    std::string path;              // relative to the deck
    std::string name;
    std::string kind;              // image, video, document, code, shader, deck, other
    long long   size = 0;
    std::vector<int> slides;       // 1-based; 0 means the deck's settings rather than a slide
    bool used = false;
};

}  // namespace refract
