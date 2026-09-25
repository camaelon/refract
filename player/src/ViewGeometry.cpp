#include "ViewGeometry.h"

#include "Utf8.h"

#include <algorithm>
#include <cmath>

namespace refract {

Grid layoutGrid(const GridSpec& spec, int cells) {
    Grid grid;
    grid.cells = std::max(0, cells);
    grid.gutter = spec.gutter;
    grid.pad = spec.pad;
    grid.headerH = spec.headerH;

    const float gridW = spec.width - spec.pad * 2;
    grid.columns = std::max(1, static_cast<int>((gridW + spec.gutter)
                                                / (spec.minCardW + spec.gutter)));
    if (grid.cells > 0) grid.columns = std::min(grid.columns, grid.cells);

    grid.cardW = (gridW - spec.gutter * (grid.columns - 1)) / grid.columns;
    grid.thumbH = grid.cardW * spec.thumbAspect;
    grid.cardH = grid.thumbH + spec.labelH;

    const int rows = (grid.cells + grid.columns - 1) / grid.columns;
    const float contentH = rows * grid.cardH + std::max(0, rows - 1) * spec.gutter + spec.pad;
    grid.viewH = spec.height - spec.headerH;
    grid.scrollMax = std::max(0.0f, contentH - grid.viewH + spec.pad);
    return grid;
}

Box Grid::card(int cell, float scroll) const {
    if (cell < 0 || cell >= cells) return {};
    const int row = cell / columns, col = cell % columns;
    const float x = pad + col * (cardW + gutter);
    // The grid starts a little below the header, so the first row is not against the rule.
    const float y = headerH + pad * 0.4f + row * (cardH + gutter) - scroll;
    return {x, y, x + cardW, y + cardH};
}

int Grid::cellAt(float x, float y, float scroll) const {
    for (int i = 0; i < cells; i++) {
        if (card(i, scroll).contains(x, y)) return i;
    }
    return -1;
}

int Grid::nearestCell(float x, float y, float scroll) const {
    int best = -1;
    float bestDist = 0;
    for (int i = 0; i < cells; i++) {
        const Box box = card(i, scroll);
        const float dx = x - box.centerX();
        const float dy = y - box.centerY();
        const float d = dx * dx + dy * dy * 4.0f;
        if (best < 0 || d < bestDist) { best = i; bestDist = d; }
    }
    return best;
}

float Grid::scrollToShow(int cell, float scroll) const {
    if (cell < 0 || cell >= cells) return scroll;
    const float top = (cell / columns) * (cardH + gutter);
    if (top < scroll) return clampScroll(top);
    if (top + cardH > scroll + viewH - pad) return clampScroll(top + cardH - viewH + pad);
    return clampScroll(scroll);
}

float Grid::clampScroll(float scroll) const {
    return std::max(0.0f, std::min(scrollMax, scroll));
}

bool matchesFilter(const std::string& title, const std::string& filter) {
    if (filter.empty()) return true;
    // Lowercased by hand rather than by locale: a deck's titles and what is typed at them are
    // the same alphabet, and a locale-aware fold would be a dependency for nothing.
    auto fold = [](const std::string& text) {
        std::string out = text;
        for (char& c : out) {
            if (c >= 'A' && c <= 'Z') c = static_cast<char>(c - 'A' + 'a');
        }
        return out;
    };
    return fold(title).find(fold(filter)) != std::string::npos;
}

float settleScroll(const Grid& grid, float scroll, int cursor, bool cursorMoved) {
    return cursorMoved ? grid.scrollToShow(cursor, scroll) : grid.clampScroll(scroll);
}

Box lineBox(const Lines& lines, int line, float scroll, float left, float right) {
    const float baseline = lines.baselineTop + line * lines.height - scroll;
    return {left, baseline - lines.height + lines.gap, right, baseline + lines.gap};
}

int lineAt(const Lines& lines, float y, float scroll, int lineCount) {
    if (lineCount <= 0) return 0;
    // Measured from the top of line 0's *box*. Measuring from its baseline — which is a line
    // lower — is what put every click a line above where it was aimed.
    const float top = lines.baselineTop - lines.height + lines.gap;
    const float row = (y - top + scroll) / std::max(1.0f, lines.height);
    return std::max(0, std::min(lineCount - 1, static_cast<int>(std::floor(row))));
}

// ── Wrapping ─────────────────────────────────────────────────────────

std::vector<WrapRow> wrapLines(const std::vector<std::string>& lines, float width,
                               const MeasureRange& measure) {
    std::vector<WrapRow> rows;
    for (size_t index = 0; index < lines.size(); index++) {
        const int line = static_cast<int>(index);
        const std::string& text = lines[index];
        const int length = static_cast<int>(text.size());
        int at = 0;
        bool first = true;
        do {
            if (width <= 0 || measure(line, at, length) <= width) {
                rows.push_back({line, at, length, first});
                break;                          // the rest of the line fits
            }
            // The last byte that still fits. Walked forward rather than divided out: with a
            // fallback face the width is not linear in the byte count, and the measurement
            // is the only honest answer.
            int fits = at;
            for (int end = static_cast<int>(utf8Advance(text, at)); end <= length;
                 end = static_cast<int>(utf8Advance(text, end))) {
                if (measure(line, at, end) > width) break;
                fits = end;
                if (end == length) break;
            }
            // Break after the last space inside what fits, so a word stays whole. A word
            // longer than the whole width — a path, a URL — has nothing to break at, and is
            // cut where it has to be rather than left running off the edge.
            int cut = -1;
            for (int i = fits; i > at; i--) {
                if (text[i - 1] == ' ' || text[i - 1] == '\t') { cut = i; break; }
            }
            if (cut <= at) cut = fits;
            // Never a row of nothing: a single character wider than the view still gets its
            // own row, or the loop would not end.
            if (cut <= at) cut = static_cast<int>(utf8Advance(text, at));
            if (cut <= at) cut = length;
            rows.push_back({line, at, cut, first});
            at = cut;
            first = false;
        } while (at < length);
    }
    return rows;
}

int rowOfCaret(const std::vector<WrapRow>& rows, int line, int col) {
    int fallback = -1;
    for (size_t i = 0; i < rows.size(); i++) {
        if (rows[i].line != line) continue;
        if (fallback < 0) fallback = static_cast<int>(i);
        // A caret at a row's end sits on the *next* row when the line continues: that is
        // where the character it types will appear.
        if (col >= rows[i].from && col < rows[i].to) return static_cast<int>(i);
        if (col == rows[i].to && (i + 1 >= rows.size() || rows[i + 1].line != line)) {
            return static_cast<int>(i);
        }
        fallback = static_cast<int>(i);
    }
    return fallback;
}

int firstRowOfLine(const std::vector<WrapRow>& rows, int line) {
    for (size_t i = 0; i < rows.size(); i++) {
        if (rows[i].line == line) return static_cast<int>(i);
    }
    return rows.empty() ? 0 : static_cast<int>(rows.size()) - 1;
}

float scrollToShowLine(const Lines& lines, int line, float scroll, float viewH) {
    const float top = line * lines.height;
    if (top < scroll) return std::max(0.0f, top);
    // A line of slack at the bottom, so the caret is never typing on the last visible row.
    if (top + lines.height > scroll + viewH - lines.height) {
        return std::max(0.0f, top + lines.height * 2 - viewH);
    }
    return std::max(0.0f, scroll);
}

}  // namespace refract
