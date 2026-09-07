#include "Session.h"

#include "Deck.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include <nlohmann/json.hpp>

#include <fstream>

namespace fs = std::filesystem;

namespace refract {

namespace {
constexpr int kVersion = 1;
}

bool Session::load(const std::string& source) {
    std::string text;
    if (!readDeckSidecar(source, ".refract-session.json", &text) || text.empty()) return false;
    auto doc = nlohmann::json::parse(text, nullptr, /*allow_exceptions=*/false);
    // A session that cannot be read costs a window position, so it is not worth a word.
    if (doc.is_discarded() || doc.value("version", 0) != kVersion) return false;

    const auto& panels = doc["panels"];
    if (panels.is_object()) {
        presenter = panels.value("presenter", false);
        deckView  = panels.value("deckView", false);
        editor    = panels.value("editor", false);
        build     = panels.value("build", false);
        captions  = panels.value("captions", false);
        assets    = panels.value("assets", false);
    }
    if (doc["windows"].is_object()) {
        for (auto it = doc["windows"].begin(); it != doc["windows"].end(); ++it) {
            const auto& w = it.value();
            if (!w.is_object()) continue;
            windows[it.key()] = {w.value("x", 0), w.value("y", 0),
                                 w.value("w", 0), w.value("h", 0)};
        }
    }
    editorAutoSave = doc.value("editorAutoSave", false);
    buildWatch = doc.value("buildWatch", false);
    if (doc["build"].is_object()) {
        buildTransitions = doc["build"].value("transitions", false);
        buildDebug = doc["build"].value("debug", false);
        buildForce = doc["build"].value("force", false);
        buildKeepJson = doc["build"].value("keepJson", false);
    }
    if (doc["folded"].is_array()) {
        for (const auto& key : doc["folded"]) {
            if (key.is_string()) folded.push_back(key.get<std::string>());
        }
    }
    return true;
}

std::string Session::serialise() const {
    nlohmann::ordered_json doc;
    doc["version"] = kVersion;
    doc["panels"] = {{"presenter", presenter}, {"deckView", deckView}, {"editor", editor},
                     {"build", build}, {"captions", captions},
                     {"assets", assets}};
    doc["windows"] = nlohmann::ordered_json::object();
    for (const auto& [name, place] : windows) {
        if (!place.placed()) continue;
        doc["windows"][name] = {{"x", place.x}, {"y", place.y},
                                {"w", place.w}, {"h", place.h}};
    }
    doc["editorAutoSave"] = editorAutoSave;
    doc["buildWatch"] = buildWatch;
    doc["build"] = {{"transitions", buildTransitions}, {"debug", buildDebug},
                    {"force", buildForce}, {"keepJson", buildKeepJson}};
    doc["folded"] = folded;
    return doc.dump(2);
}

bool Session::save(const std::string& source) const {
    const fs::path path = deckSidecarPath(source, ".refract-session.json");
    if (path.empty()) return false;   // a zip bundle has nowhere to write
    std::ofstream out(path);
    if (!out) return false;
    out << serialise() << "\n";
    return true;
}

void Session::capture(const std::string& name, GLFWwindow* window) {
    if (!window) return;
    WindowPlace place;
    glfwGetWindowPos(window, &place.x, &place.y);
    glfwGetWindowSize(window, &place.w, &place.h);
    if (place.placed()) windows[name] = place;
}

void Session::restore(const std::string& name, GLFWwindow* window) const {
    if (!window) return;
    auto it = windows.find(name);
    if (it == windows.end() || !it->second.placed()) return;
    // Size before position: a window that is resized after being placed can be nudged by the
    // window server to keep it on screen, and the position is the part worth being exact.
    glfwSetWindowSize(window, it->second.w, it->second.h);
    glfwSetWindowPos(window, it->second.x, it->second.y);
}

}  // namespace refract
