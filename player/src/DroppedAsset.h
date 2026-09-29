// A file dropped on the slide window, on its way into the deck.
//
// The deck's assets live in `<deck>/includes/` and a slide refers to one by name — so a drop
// is two steps: put the file there, then write `<name>` into the slide's markdown. What is
// here is the first step's decisions, which are the ones worth being sure about: whether the
// thing dropped is something a slide can hold at all, and what to call it once it is in a
// directory that may already have a file of that name.
#pragma once

#include <filesystem>
#include <string>

namespace refract {

// Whether a slide can include this file, by its extension — the kinds refract resolves:
// images, videos, RemoteCompose documents, and source files it renders as code.
bool includable(const std::filesystem::path& path);

// Where `source` should land inside `includes`. Its own name when nothing is there, or when
// what is there is the same file already (dropping the same photo twice adds one file, not
// two). Otherwise the name with a number: `photo-2.png`. Never overwrites.
std::filesystem::path placeFor(const std::filesystem::path& source,
                               const std::filesystem::path& includes);

// The line a slide gets for a file that has landed: `<photo.png>`.
std::string includeLine(const std::filesystem::path& placed);

// Whether two files hold the same bytes. False when either cannot be read.
bool sameFile(const std::filesystem::path& a, const std::filesystem::path& b);

}  // namespace refract
