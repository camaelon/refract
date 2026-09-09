#include "DeckSource.h"

#include "Tools.h"

#include <nlohmann/json.hpp>

#include <filesystem>
#include <fstream>
#include <unistd.h>

namespace fs = std::filesystem;

namespace refract {

namespace {

// Run a tool that answers a question, and read its JSON. Every one of them reports the same
// shape — `{"ok": true, …}` or `{"ok": false, "error": "…"}` — so a run that fails, prints
// nothing, or prints something that is not that at all all arrive here as one error the
// caller can show.
bool ask(const std::string& tool, const std::vector<std::string>& args,
         nlohmann::json* answer, const std::string& fallback, std::string* error) {
    std::string output;
    const int rc = runTool(tool, args, &output);
    *answer = nlohmann::json::parse(output, nullptr, /*allow_exceptions=*/false);
    const bool shaped = !answer->is_discarded() && answer->is_object();
    if (rc != 0 || !shaped || !answer->value("ok", false)) {
        *error = (shaped && answer->contains("error")) ? (*answer)["error"].get<std::string>()
                                                       : fallback;
        return false;
    }
    return true;
}

// Text on its way to a tool, parked in a file. Named for the job so two of them cannot
// collide, and for the process so two players cannot either.
bool spill(const char* what, const std::string& text, std::string* path, std::string* error) {
    const fs::path scratch = fs::temp_directory_path()
                             / ("refractplayer_" + std::string(what) + "_"
                                + std::to_string(::getpid()) + ".md");
    std::ofstream file(scratch, std::ios::binary);
    if (!file) {
        *error = "cannot write a temporary file";
        return false;
    }
    file << text;
    if (!text.empty() && text.back() != '\n') file << "\n";
    *path = scratch.string();
    return true;
}

}  // namespace

void DeckSource::setOutDir(const std::string& outDir) {
    mOutDir = outDir;
    mEdits.setDeck(outDir);
}

std::string DeckSource::deckDir() const {
    return mOutDir.empty() ? std::string() : fs::path(mOutDir).parent_path().string();
}

void DeckSource::setOnChanged(std::function<void(std::vector<std::string>)> onChanged) {
    mOnChanged = std::move(onChanged);
}

bool DeckSource::start(const std::string& tool, std::vector<std::string> args,
                       std::string doneMessage, Report report, std::string* status) {
    return mEdits.start(tool, std::move(args), std::move(doneMessage),
                        [this, report](const EditRunner::Result& result) {
                            if (result.ok && result.changed && mOnChanged) {
                                mOnChanged(result.outputs);
                            }
                            if (report) report(result.ok, result.status);
                        },
                        status);
}

bool DeckSource::writeThroughTemp(const char* what, std::vector<std::string> args,
                                  const std::string& text, const std::string& doneMessage,
                                  std::string* error) {
    std::string path;
    if (!spill(what, text, &path, error)) return false;
    args.push_back("--write");
    args.push_back(path);
    Report onSave = mOnSave;
    return start("slide.py", std::move(args), doneMessage,
                 [path, onSave](bool ok, const std::string& done) {
                     std::error_code ec;
                     fs::remove(path, ec);
                     if (onSave) onSave(ok, done);
                 }, error);
}

// ── Block edits ──────────────────────────────────────────────────────

bool DeckSource::moveSlide(int from, int to, std::string* status) {
    return start("reorder.py",
                 {"--move", std::to_string(from), "--to", std::to_string(to)},
                 "moved slide " + std::to_string(from + 1), mOnEdit, status);
}

bool DeckSource::moveRun(const std::string& file, int first, int last, int dst,
                         std::string* status) {
    const int blocks = last - first + 1;
    return start("reorder.py",
                 {"--file", file, "--chunks", std::to_string(first), std::to_string(last),
                  "--to-chunk", std::to_string(dst)},
                 "moved " + std::to_string(blocks) + (blocks == 1 ? " block" : " blocks"),
                 mOnEdit, status);
}

bool DeckSource::addSlide(int slide, bool before, std::string* status) {
    std::vector<std::string> args{"--slide", std::to_string(slide), "--new"};
    if (before) args.push_back("--before");
    return start("slide.py", std::move(args), "added a slide", mOnEdit, status);
}

bool DeckSource::duplicateSlide(int slide, std::string* status) {
    return start("slide.py", {"--slide", std::to_string(slide), "--duplicate"},
                 "duplicated", mOnEdit, status);
}

bool DeckSource::mergeSlide(int slide, std::string* status) {
    return start("slide.py", {"--slide", std::to_string(slide), "--merge"},
                 "merged", mOnEdit, status);
}

bool DeckSource::deleteSlide(int slide, std::string* status) {
    return start("slide.py", {"--slide", std::to_string(slide), "--delete"},
                 "deleted", mOnEdit, status);
}

bool DeckSource::undo(bool redo, std::string* status) {
    return start("history.py", {redo ? "--redo" : "--undo"}, redo ? "redone" : "undone",
                 mOnEdit, status);
}

// ── The editor's files ───────────────────────────────────────────────

bool DeckSource::readSlide(int slide, std::string* text, std::string* file, int* shared,
                           std::string* error) {
    if (!available()) {
        *error = "this deck has no markdown behind it";
        return false;
    }
    nlohmann::json doc;
    if (!ask("slide.py", {mOutDir, "--slide", std::to_string(slide), "--read"}, &doc,
             "cannot read this slide's source", error)) {
        return false;
    }
    *text = doc.value("text", std::string());
    *file = doc.value("file", std::string());
    *shared = doc.value("slides", 1);
    return true;
}

bool DeckSource::writeSlide(int slide, const std::string& text, std::string* error) {
    return writeThroughTemp("slide", {"--slide", std::to_string(slide)}, text, "saved", error);
}

bool DeckSource::splitSlide(int slide, const std::string& text, int line, std::string* error) {
    std::string path;
    if (!spill("split", text, &path, error)) return false;
    Report onSave = mOnSave;
    return start("slide.py",
                 {"--slide", std::to_string(slide), "--write", path,
                  "--split", std::to_string(line)},
                 "split",
                 [path, onSave](bool ok, const std::string& done) {
                     std::error_code ec;
                     fs::remove(path, ec);
                     if (onSave) onSave(ok, done);
                 }, error);
}

bool DeckSource::readFile(const std::string& path, std::string* text, std::string* error) {
    if (!available()) {
        *error = "this deck has no files behind it";
        return false;
    }
    nlohmann::json doc;
    if (!ask("slide.py", {mOutDir, "--file", path, "--read"}, &doc,
             "cannot read " + path, error)) {
        return false;
    }
    *text = doc.value("text", std::string());
    return true;
}

bool DeckSource::writeFile(const std::string& path, const std::string& text,
                           std::string* error) {
    return writeThroughTemp("file", {"--file", path}, text, "saved", error);
}

// ── The `::` line ────────────────────────────────────────────────────

bool DeckSource::metaVocabulary(MetaVocabulary* out, std::string* error) {
    nlohmann::json doc;
    if (!ask("meta.py", {"--list"}, &doc, "cannot read refract's `::` vocabulary", error)) {
        return false;
    }
    auto words = [](const nlohmann::json& list) {
        std::vector<MetaWord> out;
        if (!list.is_array()) return out;
        for (const auto& rec : list) {
            MetaWord word;
            word.name = rec.value("name", std::string());
            word.doc = rec.value("doc", std::string());
            if (rec.contains("values") && rec["values"].is_array()) {
                for (const auto& v : rec["values"]) word.values.push_back(v.get<std::string>());
            }
            if (rec.contains("kinds") && rec["kinds"].is_array()) {
                for (const auto& k : rec["kinds"]) word.kinds.push_back(k.get<std::string>());
            }
            word.takesValue = rec.value("takes_value", true);
            if (!word.name.empty()) out.push_back(std::move(word));
        }
        return out;
    };
    out->types = words(doc["types"]);
    out->flags = words(doc["flags"]);
    out->keys = words(doc["keys"]);
    out->includeOpts = words(doc["include_opts"]);
    return true;
}

// ── Assets ───────────────────────────────────────────────────────────

bool DeckSource::scanAssets(std::vector<Asset>* out, std::string* dir, std::string* error) {
    if (!available()) {
        *error = "a zip bundle carries no includes/ to look at";
        return false;
    }
    nlohmann::json doc;
    if (!ask("assets.py", {mOutDir, "--list"}, &doc, "cannot read this deck's assets",
             error)) {
        return false;
    }
    *dir = doc.value("dir", std::string());
    out->clear();
    for (const auto& rec : doc["assets"]) {
        Asset asset;
        asset.path = rec.value("path", std::string());
        asset.name = rec.value("name", std::string());
        asset.kind = rec.value("kind", std::string("other"));
        asset.size = rec.value("size", 0LL);
        asset.used = rec.value("used", false);
        if (rec["slides"].is_array()) {
            for (const auto& n : rec["slides"]) asset.slides.push_back(n.get<int>());
        }
        out->push_back(std::move(asset));
    }
    return true;
}

bool DeckSource::removeAsset(const std::string& path, bool force, std::string* status) {
    if (!available()) {
        *status = "this deck has no includes/ to change";
        return false;
    }
    std::vector<std::string> args{mOutDir, "--remove", path};
    if (force) args.push_back("--force");
    nlohmann::json doc;
    if (!ask("assets.py", args, &doc, "could not move it", status)) return false;
    *status = "moved to " + doc.value("trash", std::string("the trash"));
    return true;
}

}  // namespace refract
