#include "TextBuffer.h"

#include <algorithm>
#include <cctype>

namespace refract {

namespace {

// A UTF-8 continuation byte — the middle of a character, never a place a caret may rest.
bool isContinuation(char c) { return (static_cast<unsigned char>(c) & 0xC0) == 0x80; }

// What counts as part of a word. Bytes above 0x7F are word characters so that an accented
// or non-Latin word is selected whole rather than cut at its first multi-byte character.
bool isWordByte(char c) {
    const unsigned char u = static_cast<unsigned char>(c);
    return u >= 0x80 || std::isalnum(u) || u == '_';
}

bool isSpaceByte(char c) {
    const unsigned char u = static_cast<unsigned char>(c);
    return u < 0x80 && std::isspace(u);
}

constexpr int kIndent = 2;          // refract's markdown nests bullets by two spaces
constexpr size_t kMaxUndo = 200;

}  // namespace

const std::string& TextBuffer::line(int i) const {
    static const std::string kEmpty;
    if (i < 0 || i >= lineCount()) return kEmpty;
    return mLines[i];
}

void TextBuffer::setText(const std::string& text) {
    mLines.clear();
    std::string current;
    for (char c : text) {
        if (c == '\n') {
            mLines.push_back(current);
            current.clear();
        } else if (c != '\r') {     // a CRLF file edits as if it were not one
            current.push_back(c);
        }
    }
    mLines.push_back(current);
    mCaret = mAnchor = {0, 0};
    mSelecting = false;
    mBlock = false;
    mDirty = false;
    mGoalCol = -1;
    mUndo.clear();
    mRedo.clear();
    mLastEdit = Edit::None;
}

std::string TextBuffer::text() const {
    std::string out;
    for (size_t i = 0; i < mLines.size(); i++) {
        if (i) out.push_back('\n');
        out += mLines[i];
    }
    return out;
}

Caret TextBuffer::clamp(Caret caret) const {
    caret.line = std::max(0, std::min(lineCount() - 1, caret.line));
    caret.col = std::max(0, std::min(static_cast<int>(mLines[caret.line].size()), caret.col));
    // Never inside a character: a caret between two bytes of one glyph would delete half of it.
    while (caret.col > 0 && isContinuation(mLines[caret.line][caret.col])) caret.col--;
    return caret;
}

void TextBuffer::clampCaret() {
    mCaret = clamp(mCaret);
    mAnchor = clamp(mAnchor);
}

void TextBuffer::setCaret(Caret caret, bool select) {
    if (!select) {
        mAnchor = caret;
        mSelecting = false;
        mBlock = false;
    } else if (!mSelecting) {
        mAnchor = mCaret;
        mSelecting = true;
    }
    mCaret = clamp(caret);
    if (select) {
        mSelecting = true;
        // Live, not latched: the selection is a rectangle for exactly as long as option is
        // held, so letting go and extending again gives an ordinary run back.
        mBlock = mBlockMode;
    }
    mGoalCol = -1;
}

int TextBuffer::displayColumn(int line, int byteCol) const {
    const std::string& text = this->line(line);
    const int end = std::min(byteCol, static_cast<int>(text.size()));
    int chars = 0;
    for (int i = 0; i < end; i++) {
        if (!isContinuation(text[i])) chars++;
    }
    return chars;
}

int TextBuffer::byteColumn(int line, int displayCol) const {
    const std::string& text = this->line(line);
    if (displayCol <= 0) return 0;
    int chars = 0;
    for (size_t i = 0; i < text.size(); i++) {
        if (isContinuation(text[i])) continue;
        if (chars == displayCol) return static_cast<int>(i);
        chars++;
    }
    return static_cast<int>(text.size());
}

std::pair<int, int> TextBuffer::blockColumns() const {
    const int a = displayColumn(mAnchor.line, mAnchor.col);
    const int b = displayColumn(mCaret.line, mCaret.col);
    return {std::min(a, b), std::max(a, b)};
}

std::pair<int, int> TextBuffer::blockRangeOn(int line) const {
    if (!blockSelection()) return {0, 0};
    const int top = std::min(mAnchor.line, mCaret.line);
    const int bottom = std::max(mAnchor.line, mCaret.line);
    if (line < top || line > bottom) return {0, 0};
    auto [left, right] = blockColumns();
    // A line that stops short of the rectangle contributes nothing — the frame is drawn over
    // it, but there are no characters there to take.
    return {byteColumn(line, left), byteColumn(line, right)};
}

std::pair<Caret, Caret> TextBuffer::selection() const {
    if (!hasSelection()) return {mCaret, mCaret};
    return mAnchor < mCaret ? std::make_pair(mAnchor, mCaret)
                            : std::make_pair(mCaret, mAnchor);
}

std::string TextBuffer::selectedText() const {
    if (!hasSelection()) return {};
    if (mBlock) {
        // One line per row of the rectangle, including the empty ones: a column copied out
        // of a table has to paste back as a column.
        const int top = std::min(mAnchor.line, mCaret.line);
        const int bottom = std::max(mAnchor.line, mCaret.line);
        std::string out;
        for (int i = top; i <= bottom; i++) {
            if (i > top) out += "\n";
            auto [from, to] = blockRangeOn(i);
            out += mLines[i].substr(from, to - from);
        }
        return out;
    }
    auto [from, to] = selection();
    if (from.line == to.line) return mLines[from.line].substr(from.col, to.col - from.col);
    std::string out = mLines[from.line].substr(from.col);
    for (int i = from.line + 1; i < to.line; i++) {
        out += "\n";
        out += mLines[i];
    }
    out += "\n";
    out += mLines[to.line].substr(0, to.col);
    return out;
}

void TextBuffer::selectAll() {
    mBlock = false;
    mAnchor = {0, 0};
    mCaret = {lineCount() - 1, static_cast<int>(mLines.back().size())};
    mSelecting = true;
}

void TextBuffer::begin(Edit kind) {
    // A new undo step whenever the kind of editing changes, or the caret has been moved since
    // the last one: typing "hello" is one step, but typing it in two places is two.
    const bool sameRun = kind == mLastEdit && mCaret == mLastEditCaret;
    if (!sameRun) {
        mUndo.push_back({mLines, mCaret});
        if (mUndo.size() > kMaxUndo) mUndo.erase(mUndo.begin());
    }
    mRedo.clear();
    mLastEdit = kind;
    mDirty = true;
}

void TextBuffer::deleteSelection() {
    if (!hasSelection()) return;
    if (mBlock) {
        // The rectangle is cut out of each line and the lines stay where they are — that is
        // the whole point of a column selection, and joining them would be a run's behaviour.
        const int top = std::min(mAnchor.line, mCaret.line);
        const int bottom = std::max(mAnchor.line, mCaret.line);
        const int left = blockColumns().first;
        for (int i = top; i <= bottom; i++) {
            auto [from, to] = blockRangeOn(i);
            if (to > from) mLines[i].erase(from, to - from);
        }
        mCaret = mAnchor = {top, byteColumn(top, left)};
        mSelecting = false;
        mBlock = false;
        mGoalCol = -1;
        return;
    }
    auto [from, to] = selection();
    std::string head = mLines[from.line].substr(0, from.col);
    std::string tail = mLines[to.line].substr(to.col);
    mLines.erase(mLines.begin() + from.line, mLines.begin() + to.line + 1);
    mLines.insert(mLines.begin() + from.line, head + tail);
    mCaret = mAnchor = from;
    mSelecting = false;
    mGoalCol = -1;
}

void TextBuffer::insert(const std::string& utf8) {
    if (utf8.empty()) return;
    begin(Edit::Insert);
    deleteSelection();
    // Pasted text arrives with newlines in it; splitting here means paste and typing are the
    // same operation rather than two.
    std::vector<std::string> parts{""};
    for (char c : utf8) {
        if (c == '\n') parts.push_back("");
        else if (c != '\r') parts.back().push_back(c);
    }
    std::string& line = mLines[mCaret.line];
    const std::string tail = line.substr(mCaret.col);
    line = line.substr(0, mCaret.col) + parts.front();
    if (parts.size() == 1) {
        mCaret.col = static_cast<int>(line.size());
        line += tail;
    } else {
        for (size_t i = 1; i < parts.size(); i++) {
            mLines.insert(mLines.begin() + mCaret.line + static_cast<int>(i), parts[i]);
        }
        mCaret.line += static_cast<int>(parts.size()) - 1;
        mCaret.col = static_cast<int>(parts.back().size());
        mLines[mCaret.line] += tail;
    }
    mAnchor = mCaret;
    mLastEditCaret = mCaret;
    mGoalCol = -1;
}

void TextBuffer::newline() {
    begin(Edit::Structural);
    deleteSelection();
    std::string& line = mLines[mCaret.line];
    // The new line starts under the old one's text. Markdown is indentation-sensitive — a
    // sub-bullet is two spaces in — and re-typing that indent every line is the sort of thing
    // an editor is for.
    std::string indent;
    for (char c : line) {
        if (c == ' ' || c == '\t') indent.push_back(c);
        else break;
    }
    if (static_cast<int>(indent.size()) > mCaret.col) indent.resize(mCaret.col);
    const std::string tail = line.substr(mCaret.col);
    line = line.substr(0, mCaret.col);
    mLines.insert(mLines.begin() + mCaret.line + 1, indent + tail);
    mCaret = {mCaret.line + 1, static_cast<int>(indent.size())};
    mAnchor = mCaret;
    mLastEdit = Edit::None;      // a line break always ends an undo group
    mGoalCol = -1;
}

void TextBuffer::indent() { insert(std::string(kIndent, ' ')); }

int TextBuffer::stepLeft(int line, int col) const {
    if (col <= 0) return 0;
    col--;
    while (col > 0 && isContinuation(mLines[line][col])) col--;
    return col;
}

int TextBuffer::stepRight(int line, int col) const {
    const std::string& text = mLines[line];
    const int n = static_cast<int>(text.size());
    if (col >= n) return n;
    col++;
    while (col < n && isContinuation(text[col])) col++;
    return col;
}

void TextBuffer::backspace() {
    if (hasSelection()) {
        begin(Edit::Delete);
        deleteSelection();
        mLastEditCaret = mCaret;
        return;
    }
    if (mCaret.col == 0 && mCaret.line == 0) return;
    begin(Edit::Delete);
    if (mCaret.col > 0) {
        const int from = stepLeft(mCaret.line, mCaret.col);
        mLines[mCaret.line].erase(from, mCaret.col - from);
        mCaret.col = from;
    } else {
        // Joining lines: the caret lands where the join happened, which is the end of what
        // used to be the line above.
        const int above = mCaret.line - 1;
        const int col = static_cast<int>(mLines[above].size());
        mLines[above] += mLines[mCaret.line];
        mLines.erase(mLines.begin() + mCaret.line);
        mCaret = {above, col};
    }
    mAnchor = mCaret;
    mLastEditCaret = mCaret;
    mGoalCol = -1;
}

void TextBuffer::del() {
    if (hasSelection()) {
        begin(Edit::Delete);
        deleteSelection();
        mLastEditCaret = mCaret;
        return;
    }
    const int n = static_cast<int>(mLines[mCaret.line].size());
    if (mCaret.col >= n && mCaret.line + 1 >= lineCount()) return;
    begin(Edit::Delete);
    if (mCaret.col < n) {
        const int to = stepRight(mCaret.line, mCaret.col);
        mLines[mCaret.line].erase(mCaret.col, to - mCaret.col);
    } else {
        mLines[mCaret.line] += mLines[mCaret.line + 1];
        mLines.erase(mLines.begin() + mCaret.line + 1);
    }
    mAnchor = mCaret;
    mLastEditCaret = mCaret;
    mGoalCol = -1;
}

void TextBuffer::moveLeft(bool select) {
    // An unshifted arrow with a selection collapses to its near edge rather than moving —
    // what every editor does, and what stops a left-arrow from eating a character.
    if (!select && hasSelection()) {
        setCaret(mBlock ? Caret{std::min(mAnchor.line, mCaret.line),
                                byteColumn(std::min(mAnchor.line, mCaret.line),
                                           blockColumns().first)}
                        : selection().first, false);
        return;
    }
    Caret next = mCaret;
    if (next.col > 0) next.col = stepLeft(next.line, next.col);
    else if (next.line > 0) next = {next.line - 1, static_cast<int>(mLines[next.line - 1].size())};
    setCaret(next, select);
}

void TextBuffer::moveRight(bool select) {
    if (!select && hasSelection()) {
        setCaret(mBlock ? Caret{std::max(mAnchor.line, mCaret.line),
                                byteColumn(std::max(mAnchor.line, mCaret.line),
                                           blockColumns().second)}
                        : selection().second, false);
        return;
    }
    Caret next = mCaret;
    const int n = static_cast<int>(mLines[next.line].size());
    if (next.col < n) next.col = stepRight(next.line, next.col);
    else if (next.line + 1 < lineCount()) next = {next.line + 1, 0};
    setCaret(next, select);
}

void TextBuffer::moveUp(bool select) {
    if (mGoalCol < 0) mGoalCol = displayColumn(mCaret.line, mCaret.col);
    const int goal = mGoalCol;
    if (mCaret.line == 0) {
        setCaret({0, 0}, select);
        mGoalCol = goal;
        return;
    }
    setCaret({mCaret.line - 1, byteColumn(mCaret.line - 1, goal)}, select);
    // Kept across the move: walking through a short line and out the other side should come
    // back to the column you started in, not to the short line's end.
    mGoalCol = goal;
}

void TextBuffer::moveDown(bool select) {
    if (mGoalCol < 0) mGoalCol = displayColumn(mCaret.line, mCaret.col);
    const int goal = mGoalCol;
    if (mCaret.line + 1 >= lineCount()) {
        setCaret({lineCount() - 1, static_cast<int>(mLines.back().size())}, select);
        mGoalCol = goal;
        return;
    }
    setCaret({mCaret.line + 1, byteColumn(mCaret.line + 1, goal)}, select);
    mGoalCol = goal;
}

void TextBuffer::moveHome(bool select) {
    const std::string& text = mLines[mCaret.line];
    int firstText = 0;
    while (firstText < static_cast<int>(text.size())
           && (text[firstText] == ' ' || text[firstText] == '\t')) {
        firstText++;
    }
    // Home goes to the text, and again to the margin — on an indented bullet the text is
    // almost always what was wanted.
    setCaret({mCaret.line, mCaret.col == firstText ? 0 : firstText}, select);
}

void TextBuffer::moveEnd(bool select) {
    setCaret({mCaret.line, static_cast<int>(mLines[mCaret.line].size())}, select);
}

std::pair<int, int> TextBuffer::wordAt(int line, int col) const {
    const std::string& text = this->line(line);
    const int n = static_cast<int>(text.size());
    if (n == 0) return {0, 0};
    // A caret sitting just past a word belongs to that word: double-clicking at the end of
    // one should select it, not the space after it.
    int at = std::min(col, n - 1);
    if (col > 0 && (col >= n || !isWordByte(text[col])) && isWordByte(text[col - 1])) {
        at = col - 1;
    }
    if (!isWordByte(text[at])) {
        // Not in a word: take the run of whitespace, or the single character otherwise —
        // selecting every bracket in a line because one was clicked helps nobody.
        if (isSpaceByte(text[at])) {
            int from = at, to = at;
            while (from > 0 && isSpaceByte(text[from - 1])) from--;
            while (to < n && isSpaceByte(text[to])) to++;
            return {from, to};
        }
        return {at, stepRight(line, at)};
    }
    int from = at, to = at;
    while (from > 0 && isWordByte(text[from - 1])) from--;
    while (to < n && isWordByte(text[to])) to++;
    return {from, to};
}

void TextBuffer::selectWord() {
    auto [from, to] = wordAt(mCaret.line, mCaret.col);
    mBlock = false;
    mAnchor = {mCaret.line, from};
    mCaret = {mCaret.line, to};
    mSelecting = from != to;
    mGoalCol = -1;
}

void TextBuffer::selectLine() {
    mBlock = false;
    mAnchor = {mCaret.line, 0};
    mCaret = {mCaret.line, static_cast<int>(mLines[mCaret.line].size())};
    // An empty line has nothing to select; saying so beats a selection you cannot see.
    mSelecting = mCaret.col > 0;
    mGoalCol = -1;
}

void TextBuffer::selectParagraph() {
    auto blank = [this](int i) {
        const std::string& text = mLines[i];
        return text.find_first_not_of(" \t") == std::string::npos;
    };
    const bool onBlank = blank(mCaret.line);
    int top = mCaret.line, bottom = mCaret.line;
    // Around a blank line the paragraph is the run of blank lines: what is selected is what
    // is the same as what was clicked.
    while (top > 0 && blank(top - 1) == onBlank) top--;
    while (bottom + 1 < lineCount() && blank(bottom + 1) == onBlank) bottom++;

    mBlock = false;
    mAnchor = {top, 0};
    mCaret = {bottom, static_cast<int>(mLines[bottom].size())};
    mSelecting = mAnchor != mCaret;
    mGoalCol = -1;
}

void TextBuffer::moveWordLeft(bool select) {
    Caret next = mCaret;
    if (next.col == 0) {
        if (next.line == 0) { setCaret(next, select); return; }
        setCaret({next.line - 1, static_cast<int>(mLines[next.line - 1].size())}, select);
        return;
    }
    const std::string& text = mLines[next.line];
    // Over whatever is between here and the previous word, then over the word itself.
    while (next.col > 0 && !isWordByte(text[next.col - 1])) next.col = stepLeft(next.line, next.col);
    while (next.col > 0 && isWordByte(text[next.col - 1])) next.col = stepLeft(next.line, next.col);
    setCaret(next, select);
}

void TextBuffer::moveWordRight(bool select) {
    Caret next = mCaret;
    const std::string& text = mLines[next.line];
    const int n = static_cast<int>(text.size());
    if (next.col >= n) {
        if (next.line + 1 >= lineCount()) { setCaret(next, select); return; }
        setCaret({next.line + 1, 0}, select);
        return;
    }
    while (next.col < n && !isWordByte(text[next.col])) next.col = stepRight(next.line, next.col);
    while (next.col < n && isWordByte(text[next.col])) next.col = stepRight(next.line, next.col);
    setCaret(next, select);
}

void TextBuffer::moveDocStart(bool select) { setCaret({0, 0}, select); }

void TextBuffer::moveDocEnd(bool select) {
    setCaret({lineCount() - 1, static_cast<int>(mLines.back().size())}, select);
}

bool TextBuffer::undo() {
    if (mUndo.empty()) return false;
    mRedo.push_back({mLines, mCaret});
    mLines = mUndo.back().lines;
    mCaret = mAnchor = mUndo.back().caret;
    mUndo.pop_back();
    mSelecting = false;
    mDirty = true;
    mLastEdit = Edit::None;
    clampCaret();
    return true;
}

bool TextBuffer::redo() {
    if (mRedo.empty()) return false;
    mUndo.push_back({mLines, mCaret});
    mLines = mRedo.back().lines;
    mCaret = mAnchor = mRedo.back().caret;
    mRedo.pop_back();
    mSelecting = false;
    mDirty = true;
    mLastEdit = Edit::None;
    clampCaret();
    return true;
}

}  // namespace refract
