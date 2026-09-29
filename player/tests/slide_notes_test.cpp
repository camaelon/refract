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

static void testAddingContent() {
    CHECK(refract::withContentAdded("# A slide\n\n- a point\n", "<photo.png>")
          == "# A slide\n\n- a point\n\n<photo.png>\n", "an include after the content");
    CHECK(refract::withContentAdded("# A slide\n\n???\n\nSay this.\n", "<photo.png>")
          == "# A slide\n\n<photo.png>\n\n???\n\nSay this.\n",
          "above the notes, which have to stay last");
    CHECK(refract::withContentAdded("# A slide\n", "  ") == "# A slide\n", "nothing to add");
    CHECK(refract::withContentAdded("", "<a.png>") == "<a.png>\n", "an empty slide");
    CHECK(refract::withContentAdded("# A\n\n<a.png>\n", "<b.png>") == "# A\n\n<a.png>\n\n<b.png>\n",
          "a second one goes after the first");
}

static void testAdding() {
    CHECK(refract::appendNotes("", "From the transcript.") == "From the transcript.",
          "nothing to add to: the addition alone");
    CHECK(refract::appendNotes("Mine.", "") == "Mine.", "nothing to add: what was there");
    CHECK(refract::appendNotes("Mine.\n", "  Theirs.  ") == "Mine.\n\nTheirs.",
          "a blank line between what was written and what was said");
    CHECK(refract::notesContain("Mine.\n\nFrom the transcript.", "From the transcript."),
          "a transcript already copied in is found");
    CHECK(!refract::notesContain("Mine.", "From the transcript."), "and one that is not, is not");
    CHECK(!refract::notesContain("Mine.", ""), "nothing is never already there");
    // What the button does to a slide that has notes: the transcript after them.
    const std::string md = "# A slide\n\n???\n\nMine.\n";
    CHECK(refract::withNotes(md, refract::appendNotes(refract::notesOf(md), "Said this."))
          == "# A slide\n\n???\n\nMine.\n\nSaid this.\n", "the notes kept, the transcript added");
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
    testAddingContent();
    testAdding();
    testTranscript();
    if (failures) { std::fprintf(stderr, "%d failure(s)\n", failures); return 1; }
    std::printf("slide_notes: all passed\n");
    return 0;
}
