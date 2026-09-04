// The slide editor's text model: caret motion, selection, editing and undo.
//
// It is the part of an editor everyone assumes works and nobody enjoys debugging through a
// window, so it is a plain object with no Skia or GLFW behind it and is tested directly.
//
// Pure logic. Returns 0 on success, 1 on any failed assertion.

#include "TextBuffer.h"

#include <cstdio>
#include <string>

using refract::Caret;
using refract::TextBuffer;

static int failures = 0;

#define CHECK(cond, msg) do { \
    if (!(cond)) { std::fprintf(stderr, "FAIL: %s\n", msg); ++failures; } \
} while (0)

static void checkText(const TextBuffer& buffer, const std::string& want, const char* msg) {
    if (buffer.text() != want) {
        std::fprintf(stderr, "FAIL: %s\n  got  %s\n  want %s\n", msg,
                     buffer.text().c_str(), want.c_str());
        ++failures;
    }
}

static void checkCaret(const TextBuffer& buffer, int line, int col, const char* msg) {
    if (buffer.caret().line != line || buffer.caret().col != col) {
        std::fprintf(stderr, "FAIL: %s (got %d:%d, want %d:%d)\n", msg,
                     buffer.caret().line, buffer.caret().col, line, col);
        ++failures;
    }
}

static TextBuffer loaded(const std::string& text) {
    TextBuffer buffer;
    buffer.setText(text);
    return buffer;
}

static void testLoading() {
    TextBuffer buffer = loaded("# Title\n\nbody\n");
    checkText(buffer, "# Title\n\nbody\n", "text round-trips");
    CHECK(buffer.lineCount() == 4, "a trailing newline leaves an empty last line");
    CHECK(buffer.line(0) == "# Title", "first line");
    CHECK(buffer.line(2) == "body", "third line");
    checkCaret(buffer, 0, 0, "caret starts at the top");
    CHECK(!buffer.dirty(), "loading is not an edit");

    checkText(loaded(""), "", "empty document");
    CHECK(loaded("").lineCount() == 1, "an empty document still has one line");

    // A CRLF file edits as if it were not one; what it is saved as is the writer's business.
    checkText(loaded("a\r\nb\r\n"), "a\nb\n", "carriage returns are dropped on load");

    CHECK(loaded("x").line(9).empty(), "a line past the end reads as empty, not a crash");
}

static void testTyping() {
    TextBuffer buffer = loaded("");
    buffer.insert("hello");
    checkText(buffer, "hello", "typed text");
    checkCaret(buffer, 0, 5, "caret follows what was typed");
    CHECK(buffer.dirty(), "typing dirties the buffer");

    buffer.setCaret({0, 0});
    buffer.insert("say ");
    checkText(buffer, "say hello", "typed at the caret, not the end");
    checkCaret(buffer, 0, 4, "caret after the insertion");

    // Pasted text carries newlines; paste and typing are the same operation.
    buffer = loaded("ab");
    buffer.setCaret({0, 1});
    buffer.insert("X\nY");
    checkText(buffer, "aX\nYb", "a multi-line insert splits the line");
    checkCaret(buffer, 1, 1, "caret at the end of what was pasted");

    buffer = loaded("x");
    buffer.insert("");
    CHECK(!buffer.dirty(), "inserting nothing is not an edit");
}

static void testNewlineKeepsIndent() {
    TextBuffer buffer = loaded("  - a bullet");
    buffer.moveEnd(false);
    buffer.newline();
    checkText(buffer, "  - a bullet\n  ", "the new line starts under the old one's text");
    checkCaret(buffer, 1, 2, "caret past the carried indent");

    // Splitting mid-line takes the tail with it.
    buffer = loaded("abcdef");
    buffer.setCaret({0, 3});
    buffer.newline();
    checkText(buffer, "abc\ndef", "the tail moves to the new line");
    checkCaret(buffer, 1, 0, "caret at the start of it");

    // Splitting *inside* the indent carries only the indent that was passed, not the whole
    // of it — otherwise a break made halfway through would invent spaces.
    buffer = loaded("    x");
    buffer.setCaret({0, 2});
    buffer.newline();
    checkText(buffer, "  \n    x", "the carried indent stops at the caret");
}

static void testBackspaceAndDelete() {
    TextBuffer buffer = loaded("abc");
    buffer.setCaret({0, 2});
    buffer.backspace();
    checkText(buffer, "ac", "backspace removes the character before the caret");
    checkCaret(buffer, 0, 1, "and the caret moves back with it");

    buffer.del();
    checkText(buffer, "a", "delete removes the one after");
    checkCaret(buffer, 0, 1, "and the caret stays put");

    // At the very start and the very end there is nothing to do, and nothing should happen.
    buffer = loaded("abc");
    buffer.setCaret({0, 0});
    buffer.backspace();
    checkText(buffer, "abc", "backspace at the start of the document does nothing");
    CHECK(!buffer.dirty(), "and does not dirty it");
    buffer.moveDocEnd(false);
    buffer.del();
    checkText(buffer, "abc", "delete at the end does nothing");

    // Joining lines, in both directions.
    buffer = loaded("ab\ncd");
    buffer.setCaret({1, 0});
    buffer.backspace();
    checkText(buffer, "abcd", "backspace at column 0 joins the lines");
    checkCaret(buffer, 0, 2, "caret lands where the join happened");

    buffer = loaded("ab\ncd");
    buffer.setCaret({0, 2});
    buffer.del();
    checkText(buffer, "abcd", "delete at end of line joins the next one up");
    checkCaret(buffer, 0, 2, "caret does not move");
}

static void testUtf8() {
    // "héllo" — the é is two bytes, and a caret must never land between them.
    TextBuffer buffer = loaded("h\xc3\xa9llo");
    buffer.setCaret({0, 1});
    buffer.moveRight(false);
    checkCaret(buffer, 0, 3, "right moves over a two-byte character in one step");
    buffer.moveLeft(false);
    checkCaret(buffer, 0, 1, "and left comes back over it in one step");

    buffer.setCaret({0, 3});
    buffer.backspace();
    checkText(buffer, "hllo", "backspace removes the whole character, not half of it");

    buffer = loaded("h\xc3\xa9llo");
    buffer.setCaret({0, 1});
    buffer.del();
    checkText(buffer, "hllo", "delete removes the whole character too");

    // A caret set into the middle of a character is pulled back to its start.
    buffer = loaded("h\xc3\xa9llo");
    buffer.setCaret({0, 2});
    checkCaret(buffer, 0, 1, "a caret cannot rest inside a character");
}

static void testMotion() {
    TextBuffer buffer = loaded("one\ntwo\nthree");
    buffer.moveDown(false);
    checkCaret(buffer, 1, 0, "down a line");
    buffer.moveEnd(false);
    checkCaret(buffer, 1, 3, "end of line");
    buffer.moveRight(false);
    checkCaret(buffer, 2, 0, "right at end of line wraps to the next");
    buffer.moveLeft(false);
    checkCaret(buffer, 1, 3, "and left wraps back");

    buffer.moveDocStart(false);
    checkCaret(buffer, 0, 0, "document start");
    buffer.moveDocEnd(false);
    checkCaret(buffer, 2, 5, "document end");
    buffer.moveUp(false);
    buffer.moveUp(false);
    buffer.moveUp(false);
    checkCaret(buffer, 0, 0, "up past the top stops at the top");
    buffer.moveDown(false);
    buffer.moveDown(false);
    buffer.moveDown(false);
    checkCaret(buffer, 2, 5, "down past the bottom stops at the end");
}

static void testVerticalMotionRemembersItsColumn() {
    // Walking down through a short line and out the other side should come back to the
    // column you started in — otherwise a blank line in the middle of a slide swallows it.
    TextBuffer buffer = loaded("longer line\n\nlonger line");
    buffer.setCaret({0, 8});
    buffer.moveDown(false);
    checkCaret(buffer, 1, 0, "the short line has nowhere else to be");
    buffer.moveDown(false);
    checkCaret(buffer, 2, 8, "and the column comes back on the far side");

    // Any horizontal move forgets it, as it should.
    buffer = loaded("longer line\n\nlonger line\nlast");
    buffer.setCaret({0, 8});
    buffer.moveDown(false);      // 1:0, remembering column 8
    buffer.moveRight(false);     // wraps to 2:0 and gives the column up
    buffer.moveDown(false);
    checkCaret(buffer, 3, 0, "a sideways move gives up the remembered column");
}

static void testHomeIsTwoStep() {
    TextBuffer buffer = loaded("    - bullet");
    buffer.moveEnd(false);
    buffer.moveHome(false);
    checkCaret(buffer, 0, 4, "home goes to the text first");
    buffer.moveHome(false);
    checkCaret(buffer, 0, 0, "and to the margin second");
    buffer.moveHome(false);
    checkCaret(buffer, 0, 4, "and back again");
}

static void testSelection() {
    TextBuffer buffer = loaded("hello world");
    buffer.setCaret({0, 0});
    for (int i = 0; i < 5; i++) buffer.moveRight(true);
    CHECK(buffer.hasSelection(), "shift+right selects");
    CHECK(buffer.selectedText() == "hello", "the right five characters");

    // Typing over a selection replaces it.
    buffer.insert("goodbye");
    checkText(buffer, "goodbye world", "typing replaces the selection");
    CHECK(!buffer.hasSelection(), "and clears it");

    // Backspace over a selection removes the selection, not a character.
    buffer = loaded("hello world");
    buffer.setCaret({0, 0});
    for (int i = 0; i < 6; i++) buffer.moveRight(true);
    buffer.backspace();
    checkText(buffer, "world", "backspace removes the selection whole");

    // Across lines.
    buffer = loaded("one\ntwo\nthree");
    buffer.setCaret({0, 1});
    buffer.setCaret({2, 2}, /*select=*/true);
    CHECK(buffer.selectedText() == "ne\ntwo\nth", "a selection spanning lines");
    buffer.del();
    checkText(buffer, "oree", "and deleting it joins what is left");
    checkCaret(buffer, 0, 1, "with the caret at the join");

    // Backwards selections read the same way.
    buffer = loaded("abcdef");
    buffer.setCaret({0, 4});
    for (int i = 0; i < 3; i++) buffer.moveLeft(true);
    CHECK(buffer.selectedText() == "bcd", "a selection made right-to-left");
    CHECK(buffer.selection().first.col == 1, "reads in document order");

    buffer.selectAll();
    CHECK(buffer.selectedText() == "abcdef", "select all");
}

static void testUnshiftedArrowCollapsesTheSelection() {
    TextBuffer buffer = loaded("abcdef");
    buffer.setCaret({0, 1});
    buffer.setCaret({0, 4}, true);
    buffer.moveLeft(false);
    checkCaret(buffer, 0, 1, "left collapses to the near edge rather than moving");
    CHECK(!buffer.hasSelection(), "and drops the selection");

    buffer.setCaret({0, 1});
    buffer.setCaret({0, 4}, true);
    buffer.moveRight(false);
    checkCaret(buffer, 0, 4, "right collapses to the far edge");
}

static void testUndo() {
    TextBuffer buffer = loaded("start");
    buffer.moveDocEnd(false);
    buffer.insert("a");
    buffer.insert("b");
    buffer.insert("c");
    checkText(buffer, "startabc", "three characters typed");
    CHECK(buffer.undo(), "undo");
    // Typed in one run, so one undo takes the run — not a letter at a time.
    checkText(buffer, "start", "consecutive typing is one undo step");
    CHECK(!buffer.undo(), "and there was only the one");

    CHECK(buffer.redo(), "redo");
    checkText(buffer, "startabc", "redo puts it back");
    CHECK(!buffer.redo(), "and there is no more to redo");

    // Moving the caret between edits starts a new step.
    buffer = loaded("ab");
    buffer.setCaret({0, 2});
    buffer.insert("X");
    buffer.setCaret({0, 0});
    buffer.insert("Y");
    checkText(buffer, "YabX", "typed in two places");
    buffer.undo();
    checkText(buffer, "abX", "the second run undone on its own");
    buffer.undo();
    checkText(buffer, "ab", "then the first");

    // A new edit throws away the redo stack, the way every editor does.
    buffer = loaded("a");
    buffer.moveDocEnd(false);
    buffer.insert("b");
    buffer.undo();
    buffer.insert("c");
    CHECK(!buffer.redo(), "editing after an undo drops the redo history");
    checkText(buffer, "ac", "and keeps the new edit");

    // Loading a document is not an edit to the previous one.
    buffer.setText("fresh");
    CHECK(!buffer.undo(), "loading clears the history");
    CHECK(!buffer.dirty(), "and the dirty flag");
}

static void testDirtyTracking() {
    TextBuffer buffer = loaded("x");
    CHECK(!buffer.dirty(), "clean on load");
    buffer.moveDocEnd(false);
    CHECK(!buffer.dirty(), "moving the caret is not an edit");
    buffer.insert("y");
    CHECK(buffer.dirty(), "typing is");
    buffer.markClean();
    CHECK(!buffer.dirty(), "saving clears it");
    buffer.backspace();
    CHECK(buffer.dirty(), "and the next edit sets it again");
    // Undoing back to the saved text still counts as dirty: the buffer tracks edits, not
    // equality, and claiming a document is saved when it is not is the worse mistake.
    buffer.undo();
    CHECK(buffer.dirty(), "undo does not claim the file is saved");
}

static void testIndent() {
    TextBuffer buffer = loaded("bullet");
    buffer.setCaret({0, 0});
    buffer.indent();
    checkText(buffer, "  bullet", "tab inserts spaces, not a tab");
    checkCaret(buffer, 0, 2, "caret past them");
}

static void testEditingAnEmptyDocument() {
    TextBuffer buffer = loaded("");
    buffer.backspace();
    buffer.del();
    buffer.moveLeft(false);
    buffer.moveUp(false);
    buffer.moveEnd(false);
    checkText(buffer, "", "an empty document survives being poked at");
    buffer.newline();
    checkText(buffer, "\n", "and can still be typed into");
}

int main() {
    testLoading();
    testTyping();
    testNewlineKeepsIndent();
    testBackspaceAndDelete();
    testUtf8();
    testMotion();
    testVerticalMotionRemembersItsColumn();
    testHomeIsTwoStep();
    testSelection();
    testUnshiftedArrowCollapsesTheSelection();
    testUndo();
    testDirtyTracking();
    testIndent();
    testEditingAnEmptyDocument();

    if (failures == 0) std::fprintf(stderr, "text_buffer_test: all checks passed\n");
    else std::fprintf(stderr, "text_buffer_test: %d failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
