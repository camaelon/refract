#include "ViewGeometry.h"

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
