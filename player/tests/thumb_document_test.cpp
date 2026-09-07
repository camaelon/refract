// Previewing a RemoteCompose document — an `.rc` include, or one written as JSON.
//
// A deck is mostly made of these, so a preview that cannot show them is a preview of the
// wrong half of the folder. Both go through the still worker: the binary form straight in,
// the JSON form compiled first by json2rc and cached. What this checks is that a picture
// actually comes back and that it is not a blank square — the two ways this quietly fails.
//
// Needs json2rc built (prebuilt/json2rc) for the JSON half; without it that half is skipped
// rather than failed, since the launcher is not part of this repo's build.
//
// Returns 0 on success, 1 on any failed assertion.

#include "Thumbs.h"
#include "Tools.h"

#include "include/core/SkBitmap.h"
#include "include/core/SkImage.h"

#include <chrono>
#include <cstdio>
#include <filesystem>
#include <string>
#include <thread>

namespace fs = std::filesystem;

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

// The example deck ships one of each: a compiled .rc and two documents written as JSON.
static fs::path deckIncludes() {
    return fs::path(__FILE__).parent_path().parent_path().parent_path()
           / "examples" / "deck" / "includes";
}

// Ask, then pump the collector until the worker has delivered — the same loop the player
// runs, without the window.
static sk_sp<SkImage> render(const std::string& path, int side, double timeoutSec) {
    sk_sp<SkImage> image = refract::thumbIfReady(path, side, side);
    const auto start = std::chrono::steady_clock::now();
    while (!image) {
        std::this_thread::sleep_for(std::chrono::milliseconds(20));
        refract::collectThumbs();
        image = refract::thumbCached(path, side, side);
        // A file that cannot be rendered is answered with *no* picture, and that answer is
        // final — the queue empties and nothing more is coming. Waiting out the timeout for
        // it would make this suite five seconds slower for no more certainty.
        if (!image && !refract::thumbsPending()) break;
        const double waited = std::chrono::duration<double>(
            std::chrono::steady_clock::now() - start).count();
        if (waited > timeoutSec) break;
    }
    return image;
}

// A still that came back entirely one colour is a still of nothing: the document failed to
// load and what was drawn is the cleared surface.
static bool hasContent(const sk_sp<SkImage>& image) {
    if (!image) return false;
    SkBitmap bitmap;
    if (!bitmap.tryAllocPixels(image->imageInfo().makeColorType(kBGRA_8888_SkColorType))) {
        return false;
    }
    if (!image->readPixels(nullptr, bitmap.pixmap(), 0, 0)) return false;
    const SkColor first = bitmap.getColor(0, 0);
    for (int y = 0; y < bitmap.height(); y++) {
        for (int x = 0; x < bitmap.width(); x++) {
            if (bitmap.getColor(x, y) != first) return true;
        }
    }
    return false;
}

static void testACompiledDocument() {
    const fs::path rc = deckIncludes() / "widget.rc";
    if (!fs::exists(rc)) { std::fprintf(stderr, "FAIL: %s missing\n", rc.c_str()); ++failures; return; }
    const sk_sp<SkImage> image = render(rc.string(), 128, 10.0);
    CHECK(image != nullptr, "an .rc include renders to a still");
    CHECK(image && image->width() == 128, "at the size that was asked for");
    CHECK(hasContent(image), "and the still is not a blank square");
}

static void testADocumentWrittenAsJson() {
    if (refract::findJson2Rc().empty()) {
        std::printf("thumb_document: json2rc not built, skipping the JSON half\n");
        return;
    }
    const fs::path json = deckIncludes() / "card.json";
    if (!fs::exists(json)) { std::fprintf(stderr, "FAIL: %s missing\n", json.c_str()); ++failures; return; }
    // Generous: the first one pays for a JVM start.
    const sk_sp<SkImage> image = render(json.string(), 128, 30.0);
    CHECK(image != nullptr, "a .json document renders to a still");
    CHECK(hasContent(image), "and the still is not a blank square");

    // Compiled once: the second ask is served from the cache on disk and is quick.
    const auto start = std::chrono::steady_clock::now();
    const sk_sp<SkImage> again = render((deckIncludes() / "widget.json").string(), 64, 30.0);
    CHECK(again != nullptr, "a second JSON document renders too");
    const double took = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - start).count();
    std::printf("thumb_document: second JSON document took %.2fs\n", took);
}

static void testSomethingThatIsNotADocument() {
    // A failure is cached as "no picture", not retried forever and not a crash.
    const sk_sp<SkImage> image = render((deckIncludes() / "nothing-here.rc").string(), 64, 5.0);
    CHECK(image == nullptr, "a document that is not there has no still");
}

// Run it with paths to check particular files: `thumb_document_test a.mp4 b.json`. Useful
// for a deck that is not in this repo — a clip whose opening frame is black previews as a
// black square, and that is worth knowing about a real deck rather than a fixture.
static int checkTheseFiles(int argc, char** argv) {
    for (int i = 1; i < argc; i++) {
        const sk_sp<SkImage> image = render(argv[i], 128, 30.0);
        std::printf("%-56s %s", fs::path(argv[i]).filename().c_str(),
                    image ? "rendered" : "NO PICTURE");
        if (image) {
            std::printf("  %dx%d  %s", image->width(), image->height(),
                        hasContent(image) ? "has content" : "BLANK");
        }
        std::printf("\n");
    }
    refract::stopThumbs();
    return 0;
}

int main(int argc, char** argv) {
    if (argc > 1) return checkTheseFiles(argc, argv);
    testACompiledDocument();
    testADocumentWrittenAsJson();
    testSomethingThatIsNotADocument();
    refract::stopThumbs();
    if (failures == 0) std::printf("thumb_document: ok\n");
    return failures == 0 ? 0 : 1;
}
