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

// `existing` with `addition` after it, a blank line between them. Either being empty gives
// the other. Notes are somebody's own writing: a transcript joins them, it does not take
// their place.
std::string appendNotes(const std::string& existing, const std::string& addition);

// Whether `notes` already has `addition` in it — the same text copied twice is nobody's
// intention, and the button is one click.
bool notesContain(const std::string& notes, const std::string& addition);

// `markdown` with its notes set to `notes` — written after a `???` when it had none, and
// removed entirely when `notes` is empty. Everything before the notes is untouched. To add
// to what is there, pass appendNotes(notesOf(markdown), addition).
std::string withNotes(const std::string& markdown, const std::string& notes);

// A transcript as notes: one sentence per line. A transcript arrives as a single unbroken
// paragraph, which is unreadable both in the markdown and in a glance at the presenter; a
// line per sentence is how someone reads their own words back.
std::string transcriptAsNotes(const std::string& transcript);

}  // namespace refract
