#include "Options.h"

#include <cctype>
#include <cstdlib>

namespace refract {

const std::vector<std::string>& optionFlags() {
    static const std::vector<std::string> flags = {
        "--presenter", "--deck-view", "--build", "--editor", "--assets", "--captions",
        "--fullscreen", "-f", "--display", "--duration", "--cpu", "--metal",
        "--auto", "--auto-voice", "--no-sound",
        "--record", "--record-audio",
        "--pdf", "--images", "--export-delay", "--pdf-delay",
        "--web", "--transcribe", "--caption-model", "--caption-lang",
        "--help", "-h",
    };
    return flags;
}

const std::vector<std::string>& undocumentedFlags() {
    // --pdf-delay was the name before --images existed and the delay stopped being a PDF
    // thing. Scripts still say it; the help text teaches the name that reads right now.
    static const std::vector<std::string> flags = {"--pdf-delay"};
    return flags;
}

Options parseOptions(int argc, char* argv[]) {
    Options o;
    std::vector<std::string> positional;

    for (int i = 1; i < argc; i++) {
        const std::string arg = argv[i];
        bool missing = false;
        // A value is taken from the next argument, or the parse fails saying which option
        // was left dangling — never with the *next* option swallowed as its value.
        auto next = [&](const char* what) -> std::string {
            if (i + 1 >= argc) {
                if (o.error.empty()) o.error = std::string(what) + " needs a value";
                missing = true;
                return std::string();
            }
            return argv[++i];
        };

        if (arg == "--presenter") o.presenter = true;
        else if (arg == "--deck-view") o.deckView = true;
        else if (arg == "--build") o.buildPanel = true;
        else if (arg == "--editor") o.editor = true;
        else if (arg == "--assets") o.assets = true;
        else if (arg == "--captions") o.captions = true;
        else if (arg == "--fullscreen" || arg == "-f") o.fullscreen = true;
        else if (arg == "--display") o.display = std::atoi(next("--display").c_str());
        else if (arg == "--duration") o.duration = parseDuration(next("--duration"));
        else if (arg == "--cpu") o.useMetal = false;
        else if (arg == "--metal") o.useMetal = true;
        else if (arg == "--auto") {
            o.autoAdvanceSec = std::atof(next("--auto").c_str());
            if (o.autoAdvanceSec <= 0) o.autoAdvanceSec = 5.0;
        }
        else if (arg == "--auto-voice") o.autoVoice = true;
        else if (arg == "--no-sound") o.sound = false;
        else if (arg == "--pdf") o.pdf = next("--pdf");
        else if (arg == "--images") o.images = next("--images");
        else if (arg == "--transcribe") o.transcribe = true;
        else if (arg == "--web") o.web = next("--web");
        else if (arg == "--caption-model") o.captionModel = next("--caption-model");
        else if (arg == "--caption-lang") o.captionLanguage = next("--caption-lang");
        else if (arg == "--record") o.record = true;
        else if (arg == "--record-audio") { o.record = true; o.recordAudio = true; }
        else if (arg == "--export-delay" || arg == "--pdf-delay")
            o.exportDelay = std::atof(next(arg.c_str()).c_str());
        else if (arg == "--help" || arg == "-h") o.help = true;
        else if (!arg.empty() && arg[0] == '-') {
            if (o.error.empty()) o.error = "unknown option " + arg;
        }
        else positional.push_back(arg);
        if (missing) break;
    }

    if (!positional.empty()) o.input = positional[0];
    // "<deck> 1920 1080": the window size, said the way the viewer takes it.
    if (positional.size() >= 3) {
        o.width = std::atoi(positional[1].c_str());
        o.height = std::atoi(positional[2].c_str());
        o.sizeGiven = true;
    }
    return o;
}

double parseDuration(const std::string& text) {
    double total = 0, number = 0;
    bool sawUnit = false, sawDigit = false;
    for (char c : text) {
        if (std::isdigit(static_cast<unsigned char>(c))) {
            number = number * 10 + (c - '0');
            sawDigit = true;
        } else {
            if (c == 'h' || c == 'H') { total += number * 3600; sawUnit = true; }
            else if (c == 'm' || c == 'M') { total += number * 60; sawUnit = true; }
            else if (c == 's' || c == 'S') { total += number; sawUnit = true; }
            number = 0;
        }
    }
    if (!sawUnit) return sawDigit ? number * 60 : 0;   // a bare number is minutes
    return total + number * 60;
}

std::string usageText() {
    return
        "refractplayer — presenter's player for refract decks\n"
        "\n"
        "  refractplayer [options] <deck-out-dir | slide.rc | deck.zip> [width height]\n"
        "\n"
        "Options:\n"
        "  --presenter        open the presenter window (clock, notes, next slide)\n"
        "  --deck-view        open the deck view: every slide at once, and where the\n"
        "                     deck is reordered (drag a slide; the markdown is rewritten\n"
        "                     and the deck rebuilt)\n"
        "  --build            open the build panel: refract's options and a rebuild\n"
        "                     button, attached alongside the deck view\n"
        "  --editor           open the slide editor: the markdown behind the slide on\n"
        "                     screen, edited in place and rebuilt on save\n"
        "  --assets           open the asset window: what is in includes/, which\n"
        "                     slides use it, and what nothing uses any more\n"
        "  --fullscreen, -f   start the slide window fullscreen\n"
        "  --display <n>      monitor for the slide window (0-based); the presenter\n"
        "                     window opens on the next one\n"
        "  --duration <t>     planned talk length for the timer, e.g. 25m, 45, 1h30m\n"
        "  --cpu | --metal    rendering backend (default: Metal on macOS)\n"
        "  --auto <sec>       advance every N seconds\n"
        "  --auto-voice       advance when a slide's voice-over finishes (plays the\n"
        "                     wavs a --record-audio run captured)\n"
        "  --no-sound         never play a slide's voice-over, even where one exists\n"
        "  --captions         open the close-caption window (needs timings from\n"
        "                     --transcribe)\n"
        "\n"
        "Captions:\n"
        "  --transcribe       transcribe the recorded narration and align it into\n"
        "                     per-word caption timings, then exit\n"
        "  --caption-model N  whisper model for transcription (default: base)\n"
        "  --caption-lang L   language of the narration (default: en)\n"
        "\n"
        "Web:\n"
        "  --web <dir>        write a self-contained web player of the deck — slides,\n"
        "                     narration and captions — into <dir>, then exit\n"
        "\n"
        "Rehearsing:\n"
        "  --record           time the run: writes timing.json beside the slides, so a\n"
        "                     later run can show whether it is ahead or behind\n"
        "  --record-audio     also record narration, one wav per slide, into the deck's\n"
        "                     voice dir (implies --record; disables voice-over playback)\n"
        "\n"
        "Export:\n"
        "  --pdf <out.pdf>    write the deck to a PDF and exit (one page per slide;\n"
        "                     .rc slides stay vector, videos contribute a first frame)\n"
        "  --images <dir>     write one PNG per slide into <dir> and exit\n"
        "  --export-delay <s> how long each slide animates before it is captured\n"
        "                     (default 2) — long enough that a slide which animates\n"
        "                     in is not caught blank\n"
        "\n"        "  --help, -h         this text\n"
        "\n"
        "Press H in the player for the key card.\n";
}

}  // namespace refract
