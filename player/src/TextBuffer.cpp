#include "TextBuffer.h"

#include <algorithm>

namespace refract {

namespace {

// A UTF-8 continuation byte — the middle of a character, never a place a caret may rest.
bool isContinuation(char c) { return (static_cast<unsigned char>(c) & 0xC0) == 0x80; }

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
    } else if (!mSelecting) {
        mAnchor = mCaret;
        mSelecting = true;
    }
    mCaret = clamp(caret);
    if (select) mSelecting = true;
    mGoalCol = -1;
}

std::pair<Caret, Caret> TextBuffer::selection() const {
    if (!hasSelection()) return {mCaret, mCaret};
    return mAnchor < mCaret ? std::make_pair(mAnchor, mCaret)
                            : std::make_pair(mCaret, mAnchor);
}

std::string TextBuffer::selectedText() const {
    if (!hasSelection()) return {};
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
        setCaret(selection().first, false);
        return;
    }
    Caret next = mCaret;
    if (next.col > 0) next.col = stepLeft(next.line, next.col);
    else if (next.line > 0) next = {next.line - 1, static_cast<int>(mLines[next.line - 1].size())};
    setCaret(next, select);
}

void TextBuffer::moveRight(bool select) {
    if (!select && hasSelection()) {
        setCaret(selection().second, false);
        return;
    }
    Caret next = mCaret;
    const int n = static_cast<int>(mLines[next.line].size());
    if (next.col < n) next.col = stepRight(next.line, next.col);
    else if (next.line + 1 < lineCount()) next = {next.line + 1, 0};
    setCaret(next, select);
}

void TextBuffer::moveUp(bool select) {
    if (mGoalCol < 0) mGoalCol = mCaret.col;
    const int goal = mGoalCol;
    if (mCaret.line == 0) {
        setCaret({0, 0}, select);
        mGoalCol = goal;
        return;
    }
    setCaret({mCaret.line - 1, goal}, select);
    // Kept across the move: walking through a short line and out the other side should come
    // back to the column you started in, not to the short line's end.
    mGoalCol = goal;
}

void TextBuffer::moveDown(bool select) {
    if (mGoalCol < 0) mGoalCol = mCaret.col;
    const int goal = mGoalCol;
    if (mCaret.line + 1 >= lineCount()) {
        setCaret({lineCount() - 1, static_cast<int>(mLines.back().size())}, select);
        mGoalCol = goal;
        return;
    }
    setCaret({mCaret.line + 1, goal}, select);
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
