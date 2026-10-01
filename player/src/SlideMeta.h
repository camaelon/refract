// The `::` line at the top of a slide's markdown, as the editor rewrites it.
//
// A slide's look comes from a theme preset named on that line — `:: as: hero` — and the
// theme panel puts one there. Everything else on the line is somebody's: a pane ratio, a
// transition, an author, a flag. So this replaces the *type* and leaves the rest exactly
// where it was, which is the whole reason it is a unit of its own rather than a line of
// string handling in the window.
#pragma once

#include <string>

namespace refract {

// The theme preset a slide's markdown names (`:: as: hero` → "hero"), or "" for none.
std::string themeOf(const std::string& markdown);

// `markdown` with its theme set to `name` — the `::` line gains or changes an `as:`, and
// everything else on it (overrides, a `[2:3]` ratio, flags, an `@author`) is kept. An empty
// `name` takes the theme away, and with it the whole line when nothing else was on it.
std::string withTheme(const std::string& markdown, const std::string& name);

}  // namespace refract
