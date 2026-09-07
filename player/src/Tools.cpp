#include "Tools.h"

#include <cstdlib>
#include <iostream>
#include <sys/wait.h>
#include <unistd.h>

#if defined(__APPLE__)
#include <mach-o/dyld.h>
#endif

namespace fs = std::filesystem;

namespace refract {

fs::path executableDir() {
#if defined(__APPLE__)
    char buf[4096];
    uint32_t size = sizeof(buf);
    if (_NSGetExecutablePath(buf, &size) == 0) {
        std::error_code ec;
        fs::path resolved = fs::weakly_canonical(fs::path(buf), ec);
        if (!ec) return resolved.parent_path();
    }
#endif
    return {};
}

// The scripts sit in the repo beside the player's sources. Both places the binary normally
// lives — prebuilt/ and player/build/ — are a fixed distance from them.
fs::path findTool(const std::string& name) {
    if (name == "captions.py") {
        if (const char* override = std::getenv("REFRACT_CAPTIONS_SCRIPT")) {
            if (fs::exists(override)) return override;
        }
    }
    const fs::path dir = executableDir();
    if (dir.empty()) return {};
    for (const char* rel : {"../player/tools/",   // prebuilt/refractplayer
                            "../tools/",          // player/build/refractplayer
                            "tools/"}) {
        std::error_code ec;
        fs::path candidate = fs::weakly_canonical(dir / rel / name, ec);
        if (!ec && fs::exists(candidate)) return candidate;
    }
    return {};
}

// Run one of the Python tools, waiting for it. Its output is the user's, not ours: it goes
// straight to the terminal — unless `out` is given, in which case stdout is captured for the
// caller and only what the tool wrote to stderr reaches the terminal.
// The last line of a tool's error output, or `fallback` when it said nothing useful. What a
// window shows instead of "see the terminal" — which is no help at all when the player was
// started from Finder and there is no terminal to see.
std::string errorTail(const std::string& errors, const std::string& fallback) {
    size_t end = errors.find_last_not_of(" \t\r\n");
    if (end == std::string::npos) return fallback;
    const size_t start = errors.find_last_of('\n', end);
    std::string line = errors.substr(start == std::string::npos ? 0 : start + 1,
                                     end - (start == std::string::npos ? 0 : start));
    // Long enough to say what went wrong, short enough for a status line.
    if (line.size() > 160) line = line.substr(0, 157) + "...";
    return line.empty() ? fallback : line;
}

int runTool(const std::string& name, const std::vector<std::string>& args,
            std::string* out, std::string* errors) {
    const fs::path script = findTool(name);
    if (script.empty()) {
        std::cerr << "refractplayer: cannot find tools/" << name << "\n";
        return 1;
    }

    std::vector<char*> argv;
    std::string python = "python3";
    std::string path = script.string();
    argv.push_back(python.data());
    argv.push_back(path.data());
    std::vector<std::string> owned = args;
    for (auto& arg : owned) argv.push_back(arg.data());
    argv.push_back(nullptr);

    int pipeFds[2] = {-1, -1};
    int errFds[2] = {-1, -1};
    if (out && ::pipe(pipeFds) != 0) return 1;
    // Captured as well as shown: the terminal still gets it (it is the user's output), and a
    // window gets the last line to put on screen.
    if (errors && ::pipe(errFds) != 0) {
        if (out) { ::close(pipeFds[0]); ::close(pipeFds[1]); }
        return 1;
    }

    pid_t pid = ::fork();
    if (pid < 0) {
        if (out) { ::close(pipeFds[0]); ::close(pipeFds[1]); }
        if (errors) { ::close(errFds[0]); ::close(errFds[1]); }
        return 1;
    }
    if (pid == 0) {
        if (out) {
            ::close(pipeFds[0]);
            ::dup2(pipeFds[1], STDOUT_FILENO);
            ::close(pipeFds[1]);
        }
        if (errors) {
            ::close(errFds[0]);
            ::dup2(errFds[1], STDERR_FILENO);
            ::close(errFds[1]);
        }
        ::execvp("python3", argv.data());
        std::cerr << "refractplayer: python3 not found\n";
        ::_exit(127);
    }
    // Drained before waiting: a tool that fills a pipe would block forever otherwise. Both
    // are drained together, or one filling up would stall the other.
    if (out) { ::close(pipeFds[1]); out->clear(); }
    if (errors) { ::close(errFds[1]); errors->clear(); }
    while ((out && pipeFds[0] >= 0) || (errors && errFds[0] >= 0)) {
        char buf[4096];
        bool progress = false;
        if (out && pipeFds[0] >= 0) {
            const ssize_t n = ::read(pipeFds[0], buf, sizeof(buf));
            if (n > 0) { out->append(buf, n); progress = true; }
            else { ::close(pipeFds[0]); pipeFds[0] = -1; }
        }
        if (errors && errFds[0] >= 0) {
            const ssize_t n = ::read(errFds[0], buf, sizeof(buf));
            if (n > 0) {
                errors->append(buf, n);
                std::cerr.write(buf, n);   // still the user's output
                progress = true;
            } else { ::close(errFds[0]); errFds[0] = -1; }
        }
        if (!progress && pipeFds[0] < 0 && errFds[0] < 0) break;
    }
    int status = 0;
    ::waitpid(pid, &status, 0);
    return WIFEXITED(status) ? WEXITSTATUS(status) : 1;
}

}  // namespace refract
