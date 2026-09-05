// The editing model behind the slide editor: lines, a caret, a selection and an undo stack.
//
// Deliberately free of Skia, GLFW and refract — it is a string and an insertion point, and
// every rule that is easy to get wrong (what backspace does to a selection, where the caret
// lands after joining two lines, how far "left" is in UTF-8) is decided here where it can be
// tested without opening a window.
#pragma once

#include <string>
#include <utility>
#include <vector>

namespace refract {

// Line and *byte* column. Byte, not character: the renderer measures byte prefixes and the
// buffer stores UTF-8, so a column that counted characters would have to be converted at
// every use. Motion still moves by whole characters — see moveLeft/moveRight.
struct Caret {
    int line = 0;
    int col = 0;
    bool operator==(const Caret& o) const { return line == o.line && col == o.col; }
    bool operator!=(const Caret& o) const { return !(*this == o); }
    bool operator<(const Caret& o) const {
        return line != o.line ? line < o.line : col < o.col;
    }
};

class TextBuffer {
public:
    TextBuffer() : mLines{""} {}

    // Replace everything, discarding the undo history: this is a *different document*, not
    // an edit to the current one.
    void setText(const std::string& text);
    std::string text() const;

    const std::vector<std::string>& lines() const { return mLines; }
    int lineCount() const { return static_cast<int>(mLines.size()); }
    const std::string& line(int i) const;

    Caret caret() const { return mCaret; }
    void setCaret(Caret caret, bool select = false);

    bool hasSelection() const { return mAnchor != mCaret && mSelecting; }
    // The selection in document order, or (caret, caret) when there is none.
    std::pair<Caret, Caret> selection() const;
    std::string selectedText() const;
    void selectAll();
    void clearSelection() { mSelecting = false; }

    // ── Frame selection ──────────────────────────────────────────────
    //
    // A rectangle rather than a run: every line between the anchor and the caret, cut at the
    // two columns they sit in. Holding option while extending switches to it, which is how a
    // column of a markdown table or the indent down a bullet list gets selected at all.
    //
    // The rectangle is measured in *display* columns — characters, not bytes — because that
    // is what lines up on screen in a monospaced font, and a byte column would slice a
    // rectangle crooked the moment a line above had an accent in it.
    void setBlockMode(bool block) { mBlockMode = block; }
    bool blockMode() const { return mBlockMode; }
    bool blockSelection() const { return mBlock && hasSelection(); }

    // The rectangle's column span, in display columns, left first.
    std::pair<int, int> blockColumns() const;
    // The byte range of the rectangle on `line` — empty when the line stops short of it.
    std::pair<int, int> blockRangeOn(int line) const;

    // Characters before `byteCol` on `line`, and the inverse. Clamped to the line.
    int displayColumn(int line, int byteCol) const;
    int byteColumn(int line, int displayCol) const;

    // Every one of these replaces the selection first, which is what makes typing over a
    // selection work without each caller remembering to.
    void insert(const std::string& utf8);
    void newline();
    void indent();                 // a tab is spaces: refract's markdown is space-indented
    void backspace();
    void del();
    void deleteSelection();

    // `select` extends the selection instead of dropping it — the shift key.
    void moveLeft(bool select);
    void moveRight(bool select);
    void moveUp(bool select);
    void moveDown(bool select);
    void moveHome(bool select);    // first non-blank, then column 0: the usual two-step
    void moveEnd(bool select);
    void moveDocStart(bool select);
    void moveDocEnd(bool select);
    // A word at a time, the way option+arrow does on a Mac. Stops at the far edge of the
    // word it passes through, so repeated presses walk word by word rather than landing
    // between every run of punctuation.
    void moveWordLeft(bool select);
    void moveWordRight(bool select);

    // What the successive clicks of a multi-click select. Each is around the caret.
    void selectWord();
    void selectLine();       // the line's text, without its break
    void selectParagraph();  // the run of non-blank lines the caret is in

    bool undo();
    bool redo();

    // True when the text differs from the last setText() or markClean().
    bool dirty() const { return mDirty; }
    void markClean() { mDirty = false; }

private:
    struct Snapshot {
        std::vector<std::string> lines;
        Caret caret;
    };
    // What kind of edit produced the current undo group. Consecutive typing coalesces into
    // one undo step; anything else starts a new one, so a single undo takes back a word
    // rather than a letter.
    enum class Edit { None, Insert, Delete, Structural };

    void begin(Edit kind);
    void clampCaret();
    Caret clamp(Caret caret) const;
    int stepLeft(int line, int col) const;    // one character back, in bytes
    int stepRight(int line, int col) const;
    // The word around `col`, as a byte range. A run of word characters, or — when the caret
    // is not in one — the single character it is on.
    std::pair<int, int> wordAt(int line, int col) const;

    std::vector<std::string> mLines;
    Caret mCaret;
    Caret mAnchor;
    bool  mSelecting = false;
    bool  mBlock = false;             // this selection is a rectangle
    bool  mBlockMode = false;         // ...and the next extend will be one too
    bool  mDirty = false;
    // Remembered *display* column for up/down across short lines. Display, not bytes: moving
    // down a line with an accent in it would otherwise drift sideways.
    int   mGoalCol = -1;

    std::vector<Snapshot> mUndo;
    std::vector<Snapshot> mRedo;
    Edit  mLastEdit = Edit::None;
    Caret mLastEditCaret;
};

}  // namespace refract
