// A file dropped on the slide window: whether it can be included, and what it is called once
// it is in includes/.
//
// Returns 0 on success, 1 on any failed assertion.

#include "DroppedAsset.h"

#include <cstdio>
#include <fstream>

namespace fs = std::filesystem;

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void write(const fs::path& path, const std::string& text) {
    std::ofstream out(path, std::ios::binary);
    out << text;
}

static void testIncludable() {
    CHECK(refract::includable("a/photo.png") && refract::includable("clip.MP4")
          && refract::includable("film.rc") && refract::includable("Main.kt"),
          "what a slide can hold: images, video, documents, code — whatever the case");
    CHECK(!refract::includable("notes.txt") && !refract::includable("deck.pdf")
          && !refract::includable("nameless"), "and what it cannot");
}

static void testPlacing() {
    const fs::path root = fs::temp_directory_path() / "refract-drop-test";
    fs::remove_all(root);
    fs::create_directories(root / "includes");
    const fs::path includes = root / "includes";
    const fs::path source = root / "photo.png";
    write(source, "a picture");

    CHECK(refract::placeFor(source, includes) == includes / "photo.png", "a free name is its own");
    CHECK(refract::includeLine(includes / "photo.png") == "<photo.png>", "the line a slide gets");

    // The same file, dropped again: one file, not two.
    write(includes / "photo.png", "a picture");
    CHECK(refract::placeFor(source, includes) == includes / "photo.png",
          "the same picture under that name is the one already there");

    // A different file of the same name: numbered, never overwritten.
    write(includes / "photo.png", "a different picture");
    CHECK(refract::placeFor(source, includes) == includes / "photo-2.png", "a taken name is numbered");
    write(includes / "photo-2.png", "another different one");
    CHECK(refract::placeFor(source, includes) == includes / "photo-3.png", "and again");
    write(includes / "photo-3.png", "a picture");
    CHECK(refract::placeFor(source, includes) == includes / "photo-3.png",
          "unless one of them is this very file");

    CHECK(refract::sameFile(source, includes / "photo-3.png"), "the same bytes");
    CHECK(!refract::sameFile(source, includes / "photo.png"), "different bytes");
    CHECK(!refract::sameFile(source, includes / "nothing.png"), "nothing there at all");
    fs::remove_all(root);
}

int main() {
    testIncludable();
    testPlacing();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("dropped_asset: all passed\n");
    return 0;
}
