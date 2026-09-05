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

// A frame selection: a rectangle down the lines rather than a run through them. What makes
// it worth having is that the cut is at a *display* column, so it stays square over lines of
// different lengths and lines with multi-byte characters in them.
static void testFrameSelection() {
    TextBuffer buffer = loaded("abcdef\nghijkl\nmnopqr");
    buffer.setCaret({0, 1});
    buffer.setBlockMode(true);
    buffer.setCaret({2, 4}, /*select=*/true);

    CHECK(buffer.blockSelection(), "option makes the selection a rectangle");
    CHECK(buffer.selectedText() == "bcd\nhij\nnop", "one line per row of the rectangle");
    CHECK(buffer.blockColumns().first == 1, "left edge");
    CHECK(buffer.blockColumns().second == 4, "right edge");

    buffer.del();
    checkText(buffer, "aef\ngkl\nmqr", "deleting cuts the column out of each line");
    CHECK(buffer.lineCount() == 3, "and leaves the lines where they were");
    checkCaret(buffer, 0, 1, "with the caret at the rectangle's top-left");
}

static void testFrameSelectionOverShortLines() {
    // The line in the middle stops before the rectangle does. It contributes nothing, and
    // the lines around it are cut all the same.
    TextBuffer buffer = loaded("aaaaaa\nbb\ncccccc");
    buffer.setCaret({0, 2});
    buffer.setBlockMode(true);
    buffer.setCaret({2, 5}, true);
    CHECK(buffer.selectedText() == "aaa\n\nccc", "a short line contributes an empty row");
    CHECK(buffer.blockRangeOn(1).first == 2, "clamped to the end of the short line");
    CHECK(buffer.blockRangeOn(1).second == 2, "which makes its range empty");

    buffer.backspace();
    checkText(buffer, "aaa\nbb\nccc", "and is left alone when the rest is cut");
}

static void testFrameSelectionIsSquareOverUtf8() {
    // "é" is two bytes. A rectangle measured in bytes would come out crooked; measured in
    // characters — which is what a monospaced grid lines up — it does not.
    TextBuffer buffer = loaded("h\xc3\xa9llo\nhello");
    buffer.setCaret({0, 0});
    buffer.setBlockMode(true);
    buffer.setCaret({1, 3}, true);
    CHECK(buffer.selectedText() == "h\xc3\xa9l\nhel", "three characters from each line");
    CHECK(buffer.displayColumn(0, 4) == 3, "four bytes into the accented line is column 3");
    CHECK(buffer.byteColumn(0, 3) == 4, "and column 3 is four bytes in");
}

static void testFrameSelectionExtendsUpwardsToo() {
    TextBuffer buffer = loaded("abcdef\nghijkl\nmnopqr");
    buffer.setCaret({2, 5});
    buffer.setBlockMode(true);
    buffer.setCaret({0, 2}, true);
    CHECK(buffer.selectedText() == "cde\nijk\nopq", "dragged up, the rectangle is the same");
    CHECK(buffer.blockColumns().first == 2, "columns still read left to right");
    CHECK(buffer.blockColumns().second == 5, "columns still read left to right");
}

static void testLettingGoOfOptionGivesARunBack() {
    TextBuffer buffer = loaded("abcdef\nghijkl");
    buffer.setCaret({0, 2});
    buffer.setBlockMode(true);
    buffer.setCaret({1, 4}, true);
    CHECK(buffer.blockSelection(), "a rectangle while option is held");
    buffer.setBlockMode(false);
    buffer.setCaret({1, 4}, true);
    CHECK(!buffer.blockSelection(), "and an ordinary run once it is let go");
    CHECK(buffer.selectedText() == "cdef\nghij", "which runs through the line break");
}

static void testTypingOverAFrame() {
    TextBuffer buffer = loaded("aXXb\ncXXd\neXXf");
    buffer.setCaret({0, 1});
    buffer.setBlockMode(true);
    buffer.setCaret({2, 3}, true);
    buffer.insert("-");
    // The rectangle goes, and what was typed lands at its top-left. Typing on every row is
    // multiple carets, which this is not pretending to be.
    checkText(buffer, "a-b\ncd\nef", "typing replaces the rectangle");
    checkCaret(buffer, 0, 2, "caret after what was typed");
}

static void testAnUnshiftedArrowCollapsesAFrame() {
    TextBuffer buffer = loaded("abcdef\nghijkl");
    buffer.setCaret({0, 1});
    buffer.setBlockMode(true);
    buffer.setCaret({1, 4}, true);
    buffer.moveLeft(false);
    checkCaret(buffer, 0, 1, "left collapses to the rectangle's top-left");
    CHECK(!buffer.hasSelection(), "and drops it");

    buffer.setCaret({0, 1});
    buffer.setCaret({1, 4}, true);
    buffer.moveRight(false);
    checkCaret(buffer, 1, 4, "right collapses to its bottom-right");
}

static void testUndoOfAFrameDelete() {
    TextBuffer buffer = loaded("abcdef\nghijkl\nmnopqr");
    buffer.setCaret({0, 1});
    buffer.setBlockMode(true);
    buffer.setCaret({2, 4}, true);
    buffer.del();
    CHECK(buffer.undo(), "a rectangle delete is one undo step");
    checkText(buffer, "abcdef\nghijkl\nmnopqr", "and puts every line back");
}

static void testSelectAllIsNeverAFrame() {
    TextBuffer buffer = loaded("abc\ndef");
    buffer.setBlockMode(true);
    buffer.selectAll();
    CHECK(!buffer.blockSelection(), "select all is a run, whatever option is doing");
    CHECK(buffer.selectedText() == "abc\ndef", "and takes the line break with it");
}

static void testVerticalMotionKeepsItsColumnAcrossUtf8() {
    // The goal column is a display column, so walking down past an accented line does not
    // drift sideways — which also keeps a frame square while it is being extended.
    TextBuffer buffer = loaded("h\xc3\xa9llo there\nhello there\nhello there");
    buffer.setCaret({0, 0});
    for (int i = 0; i < 6; i++) buffer.moveRight(false);
    CHECK(buffer.displayColumn(0, buffer.caret().col) == 6, "six characters in");
    buffer.moveDown(false);
    CHECK(buffer.displayColumn(1, buffer.caret().col) == 6, "still six on the plain line");
    buffer.moveDown(false);
    CHECK(buffer.displayColumn(2, buffer.caret().col) == 6, "and on the next");
}

// What the successive clicks of a multi-click take.
static void testSelectWord() {
    TextBuffer buffer = loaded("the quick brown fox");
    buffer.setCaret({0, 6});                    // inside "quick"
    buffer.selectWord();
    CHECK(buffer.selectedText() == "quick", "a click inside a word takes the word");

    buffer.setCaret({0, 4});                    // on its first character
    buffer.selectWord();
    CHECK(buffer.selectedText() == "quick", "and so does one at its start");

    // A caret just past a word belongs to it: double-clicking at the end of a word should
    // take the word, not the space after it.
    buffer.setCaret({0, 9});
    buffer.selectWord();
    CHECK(buffer.selectedText() == "quick", "and one just past its end");

    // In the space between words, the run of spaces.
    buffer = loaded("a    b");
    buffer.setCaret({0, 3});
    buffer.selectWord();
    CHECK(buffer.selectedText() == "    ", "whitespace selects as a run");

    // A caret between two punctuation marks takes just the one it is on — selecting every
    // bracket in a line because one was clicked helps nobody.
    buffer = loaded("a ++ b");
    buffer.setCaret({0, 3});
    buffer.selectWord();
    CHECK(buffer.selectedText() == "+", "punctuation selects on its own");

    // Next to a word, though, the word wins: clicking the edge of "f(" is almost always
    // meant for "f".
    buffer = loaded("f(x);");
    buffer.setCaret({0, 1});
    buffer.selectWord();
    CHECK(buffer.selectedText() == "f", "a caret against a word takes the word");

    // Markdown's own punctuation is not part of a word.
    buffer = loaded("  - a bullet");
    buffer.setCaret({0, 5});
    buffer.selectWord();
    CHECK(buffer.selectedText() == "a", "a one-letter word");

    // A multi-byte word comes out whole rather than cut at its first accented character.
    buffer = loaded("caf\xc3\xa9 noir");
    buffer.setCaret({0, 1});
    buffer.selectWord();
    CHECK(buffer.selectedText() == "caf\xc3\xa9", "an accented word is one word");

    buffer = loaded("");
    buffer.selectWord();
    CHECK(!buffer.hasSelection(), "an empty line has no word to take");
}

static void testSelectLine() {
    TextBuffer buffer = loaded("first line\nsecond line\nthird");
    buffer.setCaret({1, 3});
    buffer.selectLine();
    CHECK(buffer.selectedText() == "second line", "the line's text");
    CHECK(!buffer.selectedText().empty() && buffer.selectedText().find('\n') == std::string::npos,
          "without its break");

    buffer = loaded("a\n\nb");
    buffer.setCaret({1, 0});
    buffer.selectLine();
    CHECK(!buffer.hasSelection(), "an empty line has nothing to select");
}

static void testSelectParagraph() {
    TextBuffer buffer = loaded("one\ntwo\n\nthree\nfour\n\nfive");
    buffer.setCaret({3, 2});                    // inside the middle paragraph
    buffer.selectParagraph();
    CHECK(buffer.selectedText() == "three\nfour", "the run of non-blank lines around it");

    buffer.setCaret({0, 1});
    buffer.selectParagraph();
    CHECK(buffer.selectedText() == "one\ntwo", "the first paragraph stops at the blank line");

    buffer.setCaret({6, 1});
    buffer.selectParagraph();
    CHECK(buffer.selectedText() == "five", "and the last runs to the end");

    // Clicked on a blank line, the paragraph is the run of blank lines: what comes back is
    // the same kind of thing as what was clicked.
    buffer = loaded("a\n\n\n\nb");
    buffer.setCaret({2, 0});
    buffer.selectParagraph();
    CHECK(buffer.selectedText() == "\n\n", "a run of blank lines");

    // A whole document with no blank line in it is one paragraph.
    buffer = loaded("only\ntwo lines");
    buffer.setCaret({0, 0});
    buffer.selectParagraph();
    CHECK(buffer.selectedText() == "only\ntwo lines", "no blank lines, one paragraph");
}

static void testMultiClickSelectionsAreNeverFrames() {
    TextBuffer buffer = loaded("word here\nand more");
    buffer.setBlockMode(true);
    buffer.setCaret({0, 1});
    buffer.selectWord();
    CHECK(!buffer.blockSelection(), "a double-click is a run even with option held");
    buffer.selectParagraph();
    CHECK(!buffer.blockSelection(), "and so is a paragraph");
}

static void testWordMotion() {
    TextBuffer buffer = loaded("the quick brown");
    buffer.setCaret({0, 0});
    buffer.moveWordRight(false);
    checkCaret(buffer, 0, 3, "to the end of the first word");
    buffer.moveWordRight(false);
    checkCaret(buffer, 0, 9, "then the second");
    buffer.moveWordLeft(false);
    checkCaret(buffer, 0, 4, "back to the start of it");
    buffer.moveWordLeft(false);
    checkCaret(buffer, 0, 0, "and the first");
    buffer.moveWordLeft(false);
    checkCaret(buffer, 0, 0, "with nowhere further to go");

    // Punctuation is stepped over rather than stopped at every time.
    buffer = loaded("f(x, y)");
    buffer.setCaret({0, 0});
    buffer.moveWordRight(false);
    checkCaret(buffer, 0, 1, "the first word");
    buffer.moveWordRight(false);
    checkCaret(buffer, 0, 3, "over the bracket to the next");

    // Across lines.
    buffer = loaded("one\ntwo");
    buffer.moveEnd(false);
    buffer.moveWordRight(false);
    checkCaret(buffer, 1, 0, "at the end of a line, to the start of the next");
    buffer.moveWordLeft(false);
    checkCaret(buffer, 0, 3, "and back to the end of the one before");

    // And it extends a selection like any other motion.
    buffer = loaded("the quick brown");
    buffer.setCaret({0, 0});
    buffer.moveWordRight(true);
    CHECK(buffer.selectedText() == "the", "shifted, it selects a word at a time");
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
    testSelectWord();
    testSelectLine();
    testSelectParagraph();
    testMultiClickSelectionsAreNeverFrames();
    testWordMotion();
    testFrameSelection();
    testFrameSelectionOverShortLines();
    testFrameSelectionIsSquareOverUtf8();
    testFrameSelectionExtendsUpwardsToo();
    testLettingGoOfOptionGivesARunBack();
    testTypingOverAFrame();
    testAnUnshiftedArrowCollapsesAFrame();
    testUndoOfAFrameDelete();
    testSelectAllIsNeverAFrame();
    testVerticalMotionKeepsItsColumnAcrossUtf8();
    testUndo();
    testDirtyTracking();
    testIndent();
    testEditingAnEmptyDocument();

    if (failures == 0) std::fprintf(stderr, "text_buffer_test: all checks passed\n");
    else std::fprintf(stderr, "text_buffer_test: %d failure(s)\n", failures);
    return failures == 0 ? 0 : 1;
}
