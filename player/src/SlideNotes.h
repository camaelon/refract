// A slide's presenter notes, inside its markdown.
//
// Notes are the part of a slide's chunk after a `???` line, to the end (refract's grammar —
// see refractkit/markdown.py). The player writes them when a transcript is copied into them:
// what was actually said, kept as what to say. The surgery is here, away from the window and
// the file handling, because the one thing that matters is that rewriting the notes leaves
// the rest of the slide exactly as it was.
#pragma once

#include <string>

namespace refract {

// The notes in `markdown`, trimmed, or "" when it has none.
std::string notesOf(const std::string& markdown);

// `markdown` with its notes replaced by `notes` — appended after a `???` when it had none,
// and removed entirely when `notes` is empty. Everything before the notes is untouched.
std::string withNotes(const std::string& markdown, const std::string& notes);

// A transcript as notes: one sentence per line. A transcript arrives as a single unbroken
// paragraph, which is unreadable both in the markdown and in a glance at the presenter; a
// line per sentence is how someone reads their own words back.
std::string transcriptAsNotes(const std::string& transcript);

}  // namespace refract
