// Running the Python tools that own refract's markdown.
//
// The player never parses a slides.md itself: block numbering has to agree exactly with
// refract's parser, and a second implementation would drift and rewrite the wrong slide. So
// every edit to a deck's source goes out to a script in player/tools/, and this is how.
#pragma once

#include <filesystem>
#include <string>
#include <vector>

namespace refract {

// The directory the running binary is in — the tools sit at a fixed distance from it.
std::filesystem::path executableDir();

// Where `player/tools/<name>` is, or empty when it cannot be found.
std::filesystem::path findTool(const std::string& name);

// Run one, waiting for it.
//
// Its output is the user's and goes to the terminal, unless `out` is given — the tools report
// in JSON, and a caller that is going to parse it wants it back rather than on screen. `errors`
// captures stderr *as well as* passing it through, so a window can show the last line of it:
// "see the terminal" is no help when the player was started from Finder.
int runTool(const std::string& name, const std::vector<std::string>& args,
            std::string* out = nullptr, std::string* errors = nullptr);

// The last line of a tool's error output, or `fallback` when it said nothing useful. Trimmed
// to something a status line can hold.
std::string errorTail(const std::string& errors, const std::string& fallback);

}  // namespace refract
