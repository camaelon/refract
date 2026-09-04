#include "Navigator.h"

#include "Thumbs.h"
#include "Ui.h"

#include <algorithm>
#include <cmath>

namespace refract {

namespace {

constexpr float kRowHeight = 30.0f;

// Geometry, recomputed each frame so a window resize needs no invalidation.
struct Layout {
    SkRect panel;
    SkRect list;
    SkRect preview;
    float  rowHeight = kRowHeight;
};

Layout layoutFor(int width, int height) {
    Layout l;
    float pad = std::round(std::min(width, height) * 0.06f);
    l.panel = SkRect::MakeLTRB(pad, pad, width - pad, height - pad);
    float listW = std::round(l.panel.width() * 0.52f);
    l.list    = SkRect::MakeLTRB(l.panel.left() + 24, l.panel.top() + 76,
                                 l.panel.left() + 24 + listW, l.panel.bottom() - 56);
    l.preview = SkRect::MakeLTRB(l.list.right() + 28, l.panel.top() + 76,
                                 l.panel.right() - 24, l.panel.bottom() - 56);
    return l;
}

}  // namespace

void navMove(App& app, int delta) {
    if (app.deck.empty()) return;
    app.navCursor = std::max(0, std::min(app.navCursor + delta, app.deck.size() - 1));
}

void navMoveSection(App& app, int direction) {
    if (app.deck.empty()) return;
    int target = direction < 0 ? app.deck.prevSectionSlide(app.navCursor)
                               : app.deck.nextSectionSlide(app.navCursor);
    if (target >= 0) app.navCursor = target;
    else app.navCursor = direction < 0 ? 0 : app.deck.size() - 1;
}

void drawNavigator(SkCanvas* canvas, App& app, int width, int height) {
    if (!app.navOpen || app.deck.empty()) return;

    Layout l = layoutFor(width, height);
    fillRect(canvas, SkRect::MakeWH(width, height), ui::kScrim);
    fillRoundRect(canvas, l.panel, 10, ui::kBg);
    strokeRoundRect(canvas, l.panel, 10, ui::kLine);

    // ── Header ───────────────────────────────────────────────────────
    drawText(canvas, app.deck.name(), l.panel.left() + 24, l.panel.top() + 40,
             uiFont(20, true), ui::kText);
    char counts[96];
    std::snprintf(counts, sizeof(counts), "%d slides   %d sections",
                  app.deck.size(), static_cast<int>(app.deck.sections().size()));
    drawTextRight(canvas, counts, l.panel.right() - 24, l.panel.top() + 40, uiFont(13), ui::kDim);

    // ── Scroll ───────────────────────────────────────────────────────
    // Keep the cursor inside the list with a two-row margin, so you can see what is coming
    // rather than driving the highlight along the bottom edge.
    float visibleRows = std::floor(l.list.height() / l.rowHeight);
    float cursorTop = app.navCursor * l.rowHeight;
    float margin = l.rowHeight * 2;
    if (cursorTop - margin < app.navScroll) app.navScroll = std::max(0.0f, cursorTop - margin);
    if (cursorTop + margin > app.navScroll + l.list.height() - l.rowHeight)
        app.navScroll = cursorTop + margin - l.list.height() + l.rowHeight;
    float maxScroll = std::max(0.0f, app.deck.size() * l.rowHeight - l.list.height());
    app.navScroll = std::max(0.0f, std::min(app.navScroll, maxScroll));

    // ── Rows ─────────────────────────────────────────────────────────
    canvas->save();
    canvas->clipRect(l.list);
    SkFont numberFont = uiFont(12);
    SkFont rowFont    = uiFont(15);
    SkFont sectionFont = uiFont(15, true);

    int first = std::max(0, static_cast<int>(app.navScroll / l.rowHeight) - 1);
    int last  = std::min(app.deck.size() - 1, first + static_cast<int>(visibleRows) + 2);
    for (int i = first; i <= last; i++) {
        const Slide& slide = app.deck.at(i);
        float top = l.list.top() + i * l.rowHeight - app.navScroll;
        SkRect row = SkRect::MakeLTRB(l.list.left(), top, l.list.right(), top + l.rowHeight);

        bool isCursor  = (i == app.navCursor);
        bool isCurrent = (i == app.current());
        bool isSection = slide.sectionNumber > 0 || slide.type == "section";

        if (isCursor) fillRoundRect(canvas, row.makeInset(0, 1), 5, 0xFF232833);
        if (isCurrent) {
            // A slim bar, not a fill: the row you are *on* has to stay distinguishable from
            // the row you are *choosing*, and both can be the same row. It sits inside the
            // list rect, which is clipped — a marker in the gutter would be invisible.
            fillRoundRect(canvas, SkRect::MakeXYWH(row.left() + 3, row.top() + 5, 3,
                                                   l.rowHeight - 10), 1.5f, ui::kAccent);
        }

        float baseline = row.top() + l.rowHeight * 0.5f + rowFont.getSize() * 0.36f;
        drawTextRight(canvas, std::to_string(i + 1), row.left() + 38, baseline, numberFont,
                      isCursor ? ui::kText : ui::kLine);

        const SkFont& font = isSection ? sectionFont : rowFont;
        SkColor color = isSection ? ui::kAccent : (isCursor || isCurrent ? ui::kText : ui::kDim);
        std::string label = slide.title.empty() ? slide.file : slide.title;
        if (isSection && slide.sectionNumber > 0)
            label = std::to_string(slide.sectionNumber) + ".  " + label;
        else if (!isSection)
            label = "    " + label;   // indent the body under its section heading
        drawText(canvas, ellipsize(label, font, row.width() - 100), row.left() + 52, baseline,
                 font, color);

        if (slide.hasNotes)
            drawTextRight(canvas, "notes", row.right() - 4, baseline, uiFont(11), ui::kLine);
    }
    canvas->restore();

    // ── Preview of the highlighted slide ─────────────────────────────
    const Slide& target = app.deck.at(app.navCursor);
    SkRect box = SkRect::MakeLTRB(l.preview.left(), l.preview.top(), l.preview.right(),
                                  l.preview.top() + l.preview.width() * 9.0f / 16.0f);
    box.intersect(l.preview);
    sk_sp<SkImage> preview = thumbIfReady(target.entry, 640, 360);
    SkRect drawn = drawImageFit(canvas, preview, box);
    strokeRoundRect(canvas, drawn, 3, ui::kLine);
    if (!preview) {
        SkFont font = uiFont(13);
        drawText(canvas, "rendering...", box.centerX() - textWidth(font, "rendering...") * 0.5f,
                 box.centerY(), font, ui::kLine);
    }

    float y = box.bottom() + 30;
    drawText(canvas, ellipsize(target.title.empty() ? target.file : target.title,
                               uiFont(18, true), l.preview.width()),
             l.preview.left(), y, uiFont(18, true), ui::kText);
    y += 22;
    std::string meta = target.file;
    if (target.inSection > 0 && !app.deck.sections().empty()) {
        int idx = app.deck.sectionIndexOf(app.navCursor);
        if (idx >= 0) meta += "   /   " + app.deck.sections()[idx].title;
    }
    drawText(canvas, ellipsize(meta, uiFont(13), l.preview.width()), l.preview.left(), y,
             uiFont(13), ui::kDim);

    // Notes preview, so you can tell two similar-looking slides apart before jumping.
    const std::string& notes = app.deck.notesFor(app.navCursor);
    if (!notes.empty()) {
        SkFont font = uiFont(13);
        y += 26;
        for (const auto& line : wrapText(notes, font, l.preview.width())) {
            if (y > l.preview.bottom()) break;
            drawText(canvas, line, l.preview.left(), y, font, ui::kDim);
            y += font.getSize() * 1.4f;
        }
    }

    // ── Footer ───────────────────────────────────────────────────────
    drawText(canvas, "up/down  move        left/right  section        "
                     "Enter  jump        Esc  close",
             l.panel.left() + 24, l.panel.bottom() - 22, uiFont(13), ui::kLine);
}

namespace {

// The pending "jump to slide N". Shown as a chip rather than echoed into the window title,
// because the window title is on the projector and this is a keystroke in progress.
void drawJumpChip(SkCanvas* canvas, const App& app, int width, int height) {
    if (app.jumpDigits.empty()) return;
    SkFont font = uiFont(28, true);
    std::string label = "slide " + app.jumpDigits;
    float w = textWidth(font, label) + 36;
    SkRect chip = SkRect::MakeXYWH(width * 0.5f - w * 0.5f, height - 96, w, 52);
    fillRoundRect(canvas, chip, 8, 0xF0181B21);
    strokeRoundRect(canvas, chip, 8, ui::kAccent);
    drawText(canvas, label, chip.left() + 18, chip.centerY() + font.getSize() * 0.36f, font,
             ui::kText);
}

struct HelpRow { const char* keys; const char* action; };

const HelpRow kHelp[] = {
    {"Right  Space  PgDn", "next slide"},
    {"Left  Up  PgUp", "previous slide"},
    {"Shift Left / Right", "previous / next section"},
    {"Home  End", "first / last slide"},
    {"digits, Enter", "jump to a slide number"},
    {"Tab  G", "navigator"},
    {"P", "presenter window"},
    {"C", "captions window"},
    {"V", "deck view (drag to reorder)"},
    {"Z  /  Shift Z", "fold a run / all of them (deck view)"},
    {"M", "build panel (rebuild the deck)"},
    {"E", "slide editor (edit the markdown)"},
    {"T  /  Shift T", "start-pause timer / reset it"},
    {"B  W", "blank to black / white"},
    {"F", "fullscreen"},
    {"A", "pause the slide's animation"},
    {"R", "reload the slide"},
    {"D", "debug overlay"},
    {"S", "screenshot to /tmp"},
    {"H  ?", "this card"},
    {"Q", "quit"},
};

void drawHelp(SkCanvas* canvas, const App& app, int width, int height) {
    if (!app.showHelp) return;
    const int rows = static_cast<int>(sizeof(kHelp) / sizeof(kHelp[0]));
    SkFont keyFont = uiFont(14, true);
    SkFont actFont = uiFont(14);
    const float rowHeight = 26;
    const float panelW = std::min(520.0f, width * 0.8f);
    const float panelH = rows * rowHeight + 76;
    SkRect panel = SkRect::MakeXYWH((width - panelW) * 0.5f, (height - panelH) * 0.5f,
                                    panelW, panelH);
    fillRect(canvas, SkRect::MakeWH(width, height), ui::kScrim);
    fillRoundRect(canvas, panel, 10, ui::kBg);
    strokeRoundRect(canvas, panel, 10, ui::kLine);
    drawText(canvas, "keys", panel.left() + 24, panel.top() + 40, uiFont(18, true), ui::kText);
    float y = panel.top() + 72;
    for (const auto& row : kHelp) {
        drawTextRight(canvas, row.keys, panel.left() + 190, y, keyFont, ui::kAccent);
        drawText(canvas, row.action, panel.left() + 208, y, actFont, ui::kDim);
        y += rowHeight;
    }
}

}  // namespace

void drawOverlays(SkCanvas* canvas, App& app, int width, int height) {
    drawNavigator(canvas, app, width, height);
    drawHelp(canvas, app, width, height);
    drawJumpChip(canvas, app, width, height);
}

}  // namespace refract
