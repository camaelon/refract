// The command line: what was asked for, before anything has been opened.
//
// Kept apart from main because it is the one part of startup that is pure — a vector of
// strings in, a struct out, no window, no deck, no globals touched. That makes it the one
// part that can be tested, which matters more than the line count: an option that silently
// stops being accepted, or one that is accepted but never documented, is exactly the sort of
// thing nobody notices by hand.
#pragma once

#include <string>
#include <vector>

namespace refract {

struct Options {
    // Panels to open on top of the deck. A flag here outranks the session's memory of what
    // was closed: asking for something explicitly beats a memory of not having wanted it.
    bool presenter = false;
    bool deckView = false;
    bool buildPanel = false;
    bool editor = false;
    bool captions = false;
    bool assets = false;

    bool fullscreen = false;
    int  display = -1;              // monitor for the slide window; -1 = wherever it lands
    bool useMetal = true;
    double duration = 0.0;          // planned talk length, seconds; 0 = no timer target

    double autoAdvanceSec = 0.0;    // 0 = stay on the slide
    bool autoVoice = false;
    bool sound = true;              // --no-sound clears it

    bool record = false;
    bool recordAudio = false;       // implies record

    // The modes that do their work and exit, in the order main runs them.
    std::string pdf;
    std::string images;
    double exportDelay = 2.0;
    std::string web;
    bool transcribe = false;
    std::string captionModel = "base";
    std::string captionLanguage = "en";

    std::string input;              // the deck, as it was named; empty means none was
    int width = 1600, height = 900;
    bool sizeGiven = false;         // a width and height on the command line outrank the session

    bool help = false;              // --help, -h
    std::string error;              // empty unless the command line was wrong

    // True for the modes that never open a window, and so never need a deck picked for them.
    bool headless() const {
        return !pdf.empty() || !images.empty() || !web.empty() || transcribe;
    }
};

// Parse argv. Never exits and never prints: a bad command line comes back as `error`, and
// the caller decides what to say about it.
Options parseOptions(int argc, char* argv[]);

// The help text, as a string rather than a print, so a test can read it too.
std::string usageText();

// Every option this accepts, and the few of those that are deliberately left out of the
// help: old spellings kept working for scripts, which nobody should be told to type. What
// is in the first list and not the second has to appear in the help text.
const std::vector<std::string>& optionFlags();
const std::vector<std::string>& undocumentedFlags();

// "25m", "45" (minutes), "1h30m", "90s" — a planned talk length in seconds.
double parseDuration(const std::string& text);

}  // namespace refract
