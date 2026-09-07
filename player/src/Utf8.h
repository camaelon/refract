// Making arbitrary bytes safe to draw.
//
// Skia counts the code points in a UTF-8 run to size its glyph buffer, and answers -1 when
// the run is not valid UTF-8 — which becomes an enormous allocation and an `abort()`, taking
// the whole player down. That is a real risk rather than a theoretical one: anything drawn
// in the chrome can come from a file, and a file can be Latin-1, can be binary, or can have
// been cut in half by something that counted bytes rather than characters.
//
// So text is checked before it is measured or drawn. Nothing here knows about Skia, which is
// the point — this is byte arithmetic, and it is where a mistake is invisible.
#pragma once

#include <cstddef>
#include <string>

namespace refract {

// Whole, well-formed UTF-8 from end to end. A truncated sequence at the end counts as bad:
// it is exactly the case a naive substr() produces, and the one Skia aborts on.
bool validUtf8(const std::string& text);

// The same text with every byte that is not part of a whole code point replaced by `?`.
// Returns the text unchanged when it is already valid, so the ordinary case costs one scan
// and no copy.
std::string displayable(const std::string& text);

// The largest offset at or before `at` that does not fall inside a code point — where to cut
// a string so both halves stay valid.
size_t utf8Boundary(const std::string& text, size_t at);

// The text with its last whole code point removed. Not the last *byte*: taking one byte off
// the end of a multi-byte character leaves its lead byte dangling, which is invalid UTF-8 and
// is what Skia aborts on.
std::string dropLastChar(const std::string& text);

}  // namespace refract
