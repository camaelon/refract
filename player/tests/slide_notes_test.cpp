// A slide's presenter notes, inside its markdown.
//
// Returns 0 on success, 1 on any failed assertion.

#include "SlideNotes.h"

#include <cstdio>

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void testReading() {
    CHECK(refract::notesOf("# A slide\n\n- a point\n").empty(), "a slide without notes has none");
    CHECK(refract::notesOf("# A slide\n\n???\n\nSay this.\nThen this.\n") == "Say this.\nThen this.",
          "everything after the marker, trimmed");
    CHECK(refract::notesOf("# A slide\n??? on the marker's own line\nand after it\n")
          == "on the marker's own line\nand after it", "a note on the ??? line counts too");
    CHECK(refract::notesOf("# A slide\n\n???\n").empty(), "a marker with nothing after it");
}

static void testWriting() {
    CHECK(refract::withNotes("# A slide\n\n- a point\n", "Say this.")
          == "# A slide\n\n- a point\n\n???\n\nSay this.\n", "notes added after the content");
    CHECK(refract::withNotes("# A slide\n\n- a point\n\n\n", "Say this.")
          == "# A slide\n\n- a point\n\n???\n\nSay this.\n", "however much blank space there was");
    CHECK(refract::withNotes("# A slide\n\n???\n\nOld notes.\n", "New notes.")
          == "# A slide\n\n???\n\nNew notes.\n", "notes replaced, the slide kept");
    CHECK(refract::withNotes("# A slide\n??? old\nmore old\n", "New.")
          == "# A slide\n\n???\n\nNew.\n", "an inline marker is replaced the same way");
    CHECK(refract::withNotes("# A slide\n\n???\n\nOld notes.\n", "  ")
          == "# A slide\n", "empty notes take the block away");
    // A slide with sections: only the notes at the end are touched.
    const std::string sectioned = "# One\n\n===\n\n:: content\n# Two\n\n???\n\nOld.\n";
    CHECK(refract::withNotes(sectioned, "New.") == "# One\n\n===\n\n:: content\n# Two\n\n???\n\nNew.\n",
          "the sections are left alone");
}

static void testTranscript() {
    CHECK(refract::transcriptAsNotes("So this is the part where we talk about it. And then we move on. Right?")
          == "So this is the part where we talk about it.\nAnd then we move on.\nRight?",
          "a sentence to a line");
    CHECK(refract::transcriptAsNotes("  ragged   spacing\n\nand newlines  ") == "ragged spacing and newlines",
          "whitespace collapsed");
    CHECK(refract::transcriptAsNotes("We asked J. R. about the design. He agreed.")
          == "We asked J. R. about the design.\nHe agreed.", "an initial is not the end of a sentence");
    CHECK(refract::transcriptAsNotes("").empty(), "nothing said, nothing written");
}

int main() {
    testReading();
    testWriting();
    testTranscript();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("slide_notes: all passed\n");
    return 0;
}
