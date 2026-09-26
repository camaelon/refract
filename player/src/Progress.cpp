#include "Progress.h"

#include <cstdio>

namespace refract {

bool parseProgressLine(const std::string& line, Progress* progress) {
    static const std::string prefix = "progress: ";
    if (line.compare(0, prefix.size(), prefix) != 0) return false;
    long done = 0, total = 0;
    int consumed = 0;
    if (std::sscanf(line.c_str() + prefix.size(), "%ld/%ld%n", &done, &total, &consumed) != 2) return false;
    std::string rest = line.substr(prefix.size() + consumed);
    while (!rest.empty() && rest.front() == ' ') rest.erase(rest.begin());
    while (!rest.empty() && (rest.back() == ' ' || rest.back() == '\r' || rest.back() == '\n')) rest.pop_back();
    progress->done = done;
    progress->total = total;
    progress->text = rest;
    return true;
}

}  // namespace refract
