// Where a deck's narration lives, and the files that make up one slide's.
//
// Narration is part of the deck — hours of someone's voice — so it belongs beside
// slides.md, not inside out/, which is a build product people clear without a thought.
// These are the rules, apart from the player that applies them, so they can be checked on
// a folder rather than a talk.
#pragma once

#include <filesystem>
#include <string>
#include <vector>

namespace refract {

// The voice directory for a deck opened as `input` (its out/ directory): <deck>/voice when
// the parent holds a slides.md or already has a voice/, else empty — a directory that is
// not a refract deck keeps the player's own rule (out/voice), and so does a zip.
std::filesystem::path deckVoiceDir(const std::filesystem::path& input);

// Recordings made before the player kept narration in <deck>/voice sit in out/voice. This
// moves them up once, whole, when `target` does not exist yet and out/voice holds a wav.
// Left alone when the deck already has a voice directory: two sets of takes are not
// something to merge quietly.
struct Adoption {
    enum class Outcome { Nothing, Moved, Failed };
    Outcome outcome = Outcome::Nothing;
    std::filesystem::path from, to;
    std::string error;           // when it failed
};
Adoption adoptVoiceDir(const std::filesystem::path& input, const std::filesystem::path& target);

// A slide's narration is its wav and what was made from it: the transcript and the word
// timings. Deleting or moving one means all three.
std::vector<std::filesystem::path> narrationFiles(const std::filesystem::path& wav);

}  // namespace refract
