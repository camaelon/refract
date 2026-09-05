#include "DeckView.h"

#include "DeckOrder.h"
#include "Thumbs.h"
#include "Ui.h"

#include "rcplayer/CpuRenderBackend.h"
#include "rcplayer/Player.h"

#define GL_SILENCE_DEPRECATION
#include <GLFW/glfw3.h>

#include "include/core/SkCanvas.h"
#include "include/core/SkPaint.h"
#include "include/core/SkRRect.h"
#include "include/core/SkSamplingOptions.h"

#include <algorithm>
#include <cmath>
#include <iostream>
#include <set>
#include <vector>

namespace refract {

namespace {

// Stills are cached by size, so every card asks for the same one whatever the window is
// doing. 16:9 at a size that still reads when a 60-slide deck is on screen at once.
constexpr int kThumbW = 384;
constexpr int kThumbH = 216;

constexpr float kMinCardW   = 190.0f;   // below this the titles stop being readable
constexpr float kDragSlop   = 5.0f;     // pointer travel before a press becomes a drag
constexpr double kDoubleClickSec = 0.35;

std::vector<SlideGroup> buildGroups(const Deck& deck) {
    std::vector<SlideSource> sources;
    sources.reserve(deck.slides().size());
    for (const auto& slide : deck.slides()) sources.push_back({slide.srcFile, slide.srcIndex});
    return groupSlides(sources);
}

std::string groupLabel(const SlideGroup& g) {
    if (g.count() == 1) return std::to_string(g.first + 1);
    return std::to_string(g.first + 1) + "-" + std::to_string(g.last + 1);
}

}  // namespace

struct DeckViewWindow::Impl {
    CpuRenderBackend backend;
    int width = 0, height = 0;
    int fbWidth = 0, fbHeight = 0;

    std::function<void(int)> onOpen;
    std::function<bool(int, int, std::string*)> onMove;
    std::function<bool(const std::string&, int, int, int, std::string*)> onMoveRun;

    float scroll = 0.0f;
    float scrollMax = 0.0f;
    int   cursor = 0;               // the *cell* the keyboard cursor is on
    // Set when the cursor is *moved*, and cleared by the render that scrolls to it. Without
    // this the view scrolls to the cursor on every frame, which quietly undoes the wheel:
    // scrolling away from the selection lasts until the next redraw and no longer.
    bool  followCursor = false;
    int   hover = -1;               // cell under the pointer

    double mouseX = 0, mouseY = 0;
    bool   pressed = false;
    float  pressX = 0, pressY = 0;
    int    pressCell = -1;          // the card that was pressed
    int    pressSlide = -1;         // the slide it stands for
    int    pressBar = -1;           // a run was grabbed: a grip bar, or a folded card
    int    hoverBar = -1;
    SkRect foldButton = SkRect::MakeEmpty();   // set while drawing, hit-tested on click
    bool   foldButtonHot = false;
    bool   dragging = false;
    int    dropGroup = -1;          // insertion point: before this group (== size() means end)
    int    dropChunk = -1;          // while dragging a bar: the root block under the pointer
    bool   dropAfter = false;       // ...and which side of it
    double lastClickAt = -1.0;
    int    lastClickCell = -1;

    std::string status;
    bool        statusError = false;

    // Set when a move succeeds; the deck is rebuilt underneath us, so the selection is put
    // back on the next frame, once the new deck has been laid out.
    int pendingSelectSlide = -1;

    // Last frame's layout, so the pointer can be hit-tested against what is on screen.
    std::vector<SlideGroup> groups;
    std::vector<int>   groupOfSlide;
    std::vector<SourceRun> runs;
    std::vector<int>   runOfSlide;
    std::vector<RunBar> bars;
    std::vector<DeckCell> cells;         // the grid's tiles: a slide, or a folded run
    std::vector<char> foldedBar;         // per bar, this frame
    std::vector<char> barHidden;         // swallowed by a folded run above it
    // Which runs are folded, by the key that survives a rebuild. Folding is a way of reading
    // a long deck, so it has to outlive the reorder that made you want to fold it.
    std::set<std::string> folded;
    // One rect per drawn segment of a bar (a run wrapping across rows draws several), with
    // the bar it belongs to — the grid's row wrapping is exactly why this is not one rect.
    std::vector<std::pair<SkRect, int>> barHits;
    int barRows = 0;                // how many bar lines the label strip has to make room for

    int barAt(double x, double y) const {
        for (const auto& hit : barHits) {
            if (hit.first.contains(static_cast<float>(x), static_cast<float>(y))) {
                return hit.second;
            }
        }
        return -1;
    }
    std::vector<SkRect> cards;      // one per *cell*, in window coordinates
    int   columns = 1;
    float cardW = 0, cardH = 0, thumbH = 0;
    bool  canReorder = false;

    int groupAt(int slide) const {
        if (slide < 0 || slide >= static_cast<int>(groupOfSlide.size())) return -1;
        return groupOfSlide[slide];
    }
    int runAt(int slide) const {
        if (slide < 0 || slide >= static_cast<int>(runOfSlide.size())) return -1;
        return runOfSlide[slide];
    }
    // The slide a cell stands for — itself, or the first of a folded run.
    int slideOfCell(int cell) const {
        if (cell < 0 || cell >= static_cast<int>(cells.size())) return -1;
        return cells[cell].firstSlide;
    }
    int cellOfSlide(int slide) const {
        for (size_t i = 0; i < cells.size(); i++) {
            if (slide >= cells[i].firstSlide && slide <= cells[i].lastSlide) return int(i);
        }
        return -1;
    }
    void setCursor(int cell) {
        cursor = cell;
        followCursor = true;
    }
    bool isFolded(const RunBar& bar) const { return folded.count(bar.key) > 0; }
    void toggleFold(const RunBar& bar) {
        if (!folded.erase(bar.key)) folded.insert(bar.key);
    }
    // Nearest *cell* to the pointer, or -1 when there are none.
    int nearestCard(double x, double y) const;
    void setStatus(const std::string& text, bool error) { status = text; statusError = error; }
};

int DeckViewWindow::Impl::nearestCard(double x, double y) const {
    int best = -1;
    float bestDist = 0;
    for (size_t i = 0; i < cards.size(); i++) {
        const SkRect& r = cards[i];
        float dx = static_cast<float>(x) - r.centerX();
        float dy = static_cast<float>(y) - r.centerY();
        // Rows are far apart compared to columns; weighting the vertical distance keeps a
        // pointer between two rows from snapping sideways to a card it is not near.
        float d = dx * dx + dy * dy * 4.0f;
        if (best < 0 || d < bestDist) { best = static_cast<int>(i); bestDist = d; }
    }
    return best;
}

std::unique_ptr<DeckViewWindow> DeckViewWindow::Create(int width, int height) {
    GLFWwindow* previous = glfwGetCurrentContext();

    glfwWindowHint(GLFW_DECORATED, GLFW_TRUE);
    glfwWindowHint(GLFW_TRANSPARENT_FRAMEBUFFER, GLFW_FALSE);
    glfwWindowHint(GLFW_FLOATING, GLFW_FALSE);
    glfwWindowHint(GLFW_FOCUSED, GLFW_TRUE);
    glfwWindowHint(GLFW_FOCUS_ON_SHOW, GLFW_TRUE);
    GLFWwindow* window = glfwCreateWindow(width, height, "refract — deck", nullptr, nullptr);
    if (!window) {
        std::cerr << "deck view: window creation failed\n";
        if (previous) glfwMakeContextCurrent(previous);
        return nullptr;
    }

    auto view = std::unique_ptr<DeckViewWindow>(new DeckViewWindow());
    view->mWindow = window;
    view->mImpl = std::make_unique<Impl>();

    glfwSetWindowUserPointer(window, view.get());
    glfwSetCursorPosCallback(window, [](GLFWwindow* w, double x, double y) {
        auto* self = static_cast<DeckViewWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        Impl& impl = *self->mImpl;
        impl.mouseX = x;
        impl.mouseY = y;
        impl.foldButtonHot = impl.foldButton.contains(static_cast<float>(x),
                                                      static_cast<float>(y));
        impl.hoverBar = impl.pressed ? impl.hoverBar : impl.barAt(x, y);
        if (impl.pressed && !impl.dragging && impl.canReorder
            && (impl.pressCell >= 0 || impl.pressBar >= 0)) {
            const float dx = static_cast<float>(x) - impl.pressX;
            const float dy = static_cast<float>(y) - impl.pressY;
            if (dx * dx + dy * dy > kDragSlop * kDragSlop) impl.dragging = true;
        }
    });
    glfwSetScrollCallback(window, [](GLFWwindow* w, double, double dy) {
        auto* self = static_cast<DeckViewWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl) return;
        self->mImpl->scroll = std::max(0.0f, std::min(self->mImpl->scrollMax,
                                                      self->mImpl->scroll - float(dy) * 48.0f));
    });
    glfwSetMouseButtonCallback(window, [](GLFWwindow* w, int button, int action, int) {
        auto* self = static_cast<DeckViewWindow*>(glfwGetWindowUserPointer(w));
        if (!self || !self->mImpl || button != GLFW_MOUSE_BUTTON_LEFT) return;
        Impl& impl = *self->mImpl;

        if (action == GLFW_PRESS) {
            // The header button is not part of the grid, so it is settled before anything
            // else and never starts a drag.
            if (impl.foldButton.contains(static_cast<float>(impl.mouseX),
                                         static_cast<float>(impl.mouseY))) {
                self->foldAll(!self->allFolded());
                return;
            }
            impl.pressed = true;
            impl.dragging = false;
            impl.pressX = static_cast<float>(impl.mouseX);
            impl.pressY = static_cast<float>(impl.mouseY);
            impl.pressSlide = -1;
            impl.pressCell = -1;
            // The bar wins over the cards: it is drawn in the strip under them, and a press
            // there means "this whole run", not "the slide it happens to sit below".
            impl.pressBar = impl.barAt(impl.pressX, impl.pressY);
            if (impl.pressBar >= 0) {
                impl.setCursor(impl.cellOfSlide(impl.bars[impl.pressBar].firstSlide));
                return;
            }
            for (size_t i = 0; i < impl.cards.size(); i++) {
                if (!impl.cards[i].contains(impl.pressX, impl.pressY)) continue;
                impl.pressCell = static_cast<int>(i);
                impl.pressSlide = impl.slideOfCell(impl.pressCell);
                // Clicking a card selects it but does not scroll to it: it is already under
                // the pointer, and jolting the grid on a click is how a drag misses.
                impl.cursor = impl.pressCell;
                // A folded run is picked up by its card: the card *is* the run, so dragging
                // it is dragging the whole thing.
                if (impl.cells[i].folded()) impl.pressBar = impl.cells[i].bar;
                break;
            }
            return;
        }
        if (action != GLFW_RELEASE) return;

        const bool wasDragging = impl.dragging;
        const int  cell = impl.pressCell;
        const int  slide = impl.pressSlide;
        const int  bar = impl.pressBar;
        const bool onBar = cell < 0 && bar >= 0;     // the grip strip, not a card
        const int  drop = impl.dropGroup;
        const int  atChunk = impl.dropChunk;
        const bool atAfter = impl.dropAfter;
        impl.pressed = false;
        impl.dragging = false;
        impl.dropGroup = -1;
        impl.pressBar = -1;
        impl.pressCell = -1;
        impl.dropChunk = -1;

        if (wasDragging) {
            if (bar >= 0) self->commitRunDrag(bar, atChunk, atAfter);
            else if (slide >= 0) self->commitDrag(slide, drop);
            return;
        }
        // A click on a grip bar folds the run away, and another one brings it back: the bar
        // is the run's handle, and folding is the other thing you want to do to a run.
        if (onBar) {
            if (bar < static_cast<int>(impl.bars.size())) impl.toggleFold(impl.bars[bar]);
            return;
        }
        if (cell < 0) return;

        // A plain click selects; a second one on the same card opens the slide — or unfolds
        // it, when the card stands for a folded run. Opening on a single click would make
        // browsing the deck change what the room is looking at.
        const double now = glfwGetTime();
        const bool doubleClick = impl.lastClickCell == cell
                                 && now - impl.lastClickAt < kDoubleClickSec;
        impl.lastClickAt = now;
        impl.lastClickCell = cell;
        if (!doubleClick) return;
        if (bar >= 0 && bar < static_cast<int>(impl.bars.size())) impl.toggleFold(impl.bars[bar]);
        else if (impl.onOpen && slide >= 0) impl.onOpen(slide);
    });

    glfwMakeContextCurrent(window);
    glfwSwapInterval(0);
    view->mImpl->backend.resize(width, height);
    view->mImpl->width = width;
    view->mImpl->height = height;

    if (previous) glfwMakeContextCurrent(previous);
    return view;
}

DeckViewWindow::~DeckViewWindow() {
    if (mWindow) {
        GLFWwindow* previous = glfwGetCurrentContext();
        glfwMakeContextCurrent(mWindow);
        mImpl.reset();
        if (previous && previous != mWindow) glfwMakeContextCurrent(previous);
        glfwDestroyWindow(mWindow);
    }
}

bool DeckViewWindow::shouldClose() const {
    return mWindow && glfwWindowShouldClose(mWindow);
}

void DeckViewWindow::setOnOpenSlide(std::function<void(int)> action) {
    mImpl->onOpen = std::move(action);
}

void DeckViewWindow::setOnMoveSlide(std::function<bool(int, int, std::string*)> action) {
    mImpl->onMove = std::move(action);
}

void DeckViewWindow::setOnMoveRun(
        std::function<bool(const std::string&, int, int, int, std::string*)> action) {
    mImpl->onMoveRun = std::move(action);
}

// Apply a drag of a run's grip bar: the whole section or sub-deck goes where the pointer left
// it. The block arithmetic is planRunDrop's; this only decides whether there is anything to do
// and puts the answer back on screen.
void DeckViewWindow::commitRunDrag(int bar, int atChunk, bool after) {
    Impl& impl = *mImpl;
    if (bar < 0 || bar >= static_cast<int>(impl.bars.size()) || !impl.onMoveRun) return;
    const RunBar& run = impl.bars[bar];
    if (atChunk < 0) return;

    const int dst = planRunDrop(run, atChunk, after);
    if (dst < 0) return;                       // dropped back on itself

    std::string status;
    const bool ok = impl.onMoveRun(run.file, run.firstChunk, run.lastChunk, dst, &status);
    impl.setStatus(status, !ok);
    if (ok) impl.dropChunk = -1;   // the deck is rebuilt next frame; the cursor re-lands there
}

// Turn "the group holding `slide`, dropped before group `drop`" into the (from, to) pair of
// deck positions the reorder tool takes, and run it.
//
// The target is the group that will *end up* at the new position: dropping before group 5
// while coming from group 2 means landing after group 4, because removing the dragged group
// closes the gap behind it. Getting this wrong is an off-by-one that moves the slide one
// place too far in one direction only, which is why it is written down here rather than
// spread through the mouse handler.
void DeckViewWindow::commitDrag(int slide, int drop) {
    Impl& impl = *mImpl;
    const int from = impl.groupAt(slide);
    if (from < 0 || !impl.onMove) return;

    int fromSlide = 0, toSlide = 0;
    std::string why;
    if (!planMove(impl.groups, from, drop, &fromSlide, &toSlide, &why)) {
        if (!why.empty()) impl.setStatus(why, true);
        return;
    }

    std::string status;
    const bool ok = impl.onMove(fromSlide, toSlide, &status);
    impl.setStatus(status, !ok);
    if (ok) {
        // The deck has been rebuilt and every slide renumbered; the moved block is now the
        // group at the landing position, whatever its slides ended up being called.
        const int landing = drop > from ? drop - 1 : drop;
        impl.pendingSelectSlide = landing < static_cast<int>(impl.groups.size())
                                      ? impl.groups[landing].first : -1;
        impl.dropGroup = -1;
    }
}

// Fold or unfold whatever run the cursor is sitting in. An include inside a section folds
// first: it is the smaller thing, and folding the section from inside it would take the
// cursor with it.
void DeckViewWindow::foldAtCursor() {
    Impl& impl = *mImpl;
    const int slide = impl.slideOfCell(impl.cursor);
    if (slide < 0) return;
    if (impl.cells[impl.cursor].folded()) {
        impl.toggleFold(impl.bars[impl.cells[impl.cursor].bar]);
        return;
    }
    const RunBar* best = nullptr;
    for (const auto& bar : impl.bars) {
        if (slide < bar.firstSlide || slide > bar.lastSlide) continue;
        if (!best || bar.slides() < best->slides()) best = &bar;
    }
    if (best) impl.toggleFold(*best);
    else impl.setStatus("nothing to fold here", false);
}

bool DeckViewWindow::allFolded() const {
    Impl& impl = *mImpl;
    if (impl.bars.empty()) return false;
    for (size_t bi = 0; bi < impl.bars.size(); bi++) {
        // Only what is actually reachable counts: a bar hidden inside a folded run is neither
        // folded nor unfolded as far as the reader is concerned.
        if (bi < impl.barHidden.size() && impl.barHidden[bi]) continue;
        if (!impl.isFolded(impl.bars[bi])) return false;
    }
    return true;
}

void DeckViewWindow::foldAll(bool shut) {
    Impl& impl = *mImpl;
    for (const auto& bar : impl.bars) {
        if (shut) impl.folded.insert(bar.key);
        else impl.folded.erase(bar.key);
    }
}

// Move the cursor's group one place earlier or later — the keyboard equivalent of a drag.
void DeckViewWindow::nudge(int delta) {
    Impl& impl = *mImpl;
    if (!impl.canReorder) {
        impl.setStatus("this deck has no source information, so it cannot be reordered", true);
        return;
    }
    const int from = impl.groupAt(impl.slideOfCell(impl.cursor));
    if (from < 0) return;
    const int to = from + delta;
    if (to < 0 || to >= static_cast<int>(impl.groups.size())) return;
    // `commitDrag` takes an insertion point, and moving one place later means inserting
    // *past* the group being stepped over.
    commitDrag(impl.slideOfCell(impl.cursor), delta > 0 ? to + 1 : to);
}

bool DeckViewWindow::handleKey(int key, int action, int mods) {
    if (action != GLFW_PRESS && action != GLFW_REPEAT) return false;
    Impl& impl = *mImpl;
    const int last = static_cast<int>(impl.cards.size()) - 1;
    if (last < 0) return false;

    const bool shift = (mods & GLFW_MOD_SHIFT) != 0;
    auto moveCursor = [&](int delta) {
        impl.setCursor(std::max(0, std::min(last, impl.cursor + delta)));
    };

    switch (key) {
        case GLFW_KEY_LEFT:
            if (shift) nudge(-1); else moveCursor(-1);
            return true;
        case GLFW_KEY_RIGHT:
            if (shift) nudge(1); else moveCursor(1);
            return true;
        case GLFW_KEY_UP:    moveCursor(-impl.columns); return true;
        case GLFW_KEY_DOWN:  moveCursor(impl.columns);  return true;
        case GLFW_KEY_HOME:  impl.setCursor(0);    return true;
        case GLFW_KEY_END:   impl.setCursor(last); return true;
        case GLFW_KEY_PAGE_UP:
            impl.scroll = std::max(0.0f, impl.scroll - impl.height * 0.8f);
            return true;
        case GLFW_KEY_PAGE_DOWN:
            impl.scroll = std::min(impl.scrollMax, impl.scroll + impl.height * 0.8f);
            return true;
        case GLFW_KEY_ENTER:
        case GLFW_KEY_KP_ENTER:
            // Enter on a folded run opens it; on a slide it puts it on the projector. In
            // both cases it is "show me what this is".
            if (impl.cursor < static_cast<int>(impl.cells.size())
                && impl.cells[impl.cursor].folded()) {
                impl.toggleFold(impl.bars[impl.cells[impl.cursor].bar]);
            } else if (impl.onOpen) {
                impl.onOpen(impl.slideOfCell(impl.cursor));
            }
            return true;
        case GLFW_KEY_Z:
            if (shift) foldAll(!allFolded());
            else foldAtCursor();
            return true;
        case GLFW_KEY_ESCAPE:
            glfwSetWindowShouldClose(mWindow, GLFW_TRUE);
            return true;
        default:
            return false;   // everything else is the player's
    }
}

void DeckViewWindow::render(App& app) {
    if (!mWindow || !mImpl) return;
    Impl& impl = *mImpl;
    glfwMakeContextCurrent(mWindow);

    int w = 0, h = 0;
    glfwGetWindowSize(mWindow, &w, &h);
    if (w <= 0 || h <= 0) return;
    if (w != impl.width || h != impl.height) {
        impl.backend.resize(w, h);
        impl.width = w;
        impl.height = h;
    }
    int fbW = 0, fbH = 0;
    glfwGetFramebufferSize(mWindow, &fbW, &fbH);
    if (fbW != impl.fbWidth || fbH != impl.fbHeight) {
        impl.backend.onFramebufferResize(fbW, fbH);
        impl.fbWidth = fbW;
        impl.fbHeight = fbH;
    }

    SkCanvas* canvas = impl.backend.canvas();
    if (!canvas) return;
    canvas->clear(ui::kBg);

    const Deck& deck = app.deck;

    // ── Model ────────────────────────────────────────────────────────
    impl.groups = buildGroups(deck);
    impl.groupOfSlide = groupOfSlide(impl.groups, deck.size());
    impl.runs = sourceRuns(impl.groups);
    {
        std::vector<SlideOrigin> origins;
        origins.reserve(deck.slides().size());
        for (const auto& slide : deck.slides()) {
            origins.push_back({slide.sourcePath(), slide.sectionNumber, slide.title});
        }
        impl.bars = runBars(origins);
    }
    // Folded runs stand in for their slides, so the grid is laid out over *cells* rather
    // than slides: a folded section is one tile like any other, which is what keeps the deck
    // a plain uniform grid whether or not anything is folded.
    impl.foldedBar.assign(impl.bars.size(), 0);
    for (size_t bi = 0; bi < impl.bars.size(); bi++) {
        impl.foldedBar[bi] = impl.isFolded(impl.bars[bi]) ? 1 : 0;
    }
    impl.cells = layoutCells(deck.size(), impl.bars, impl.foldedBar);
    // A bar inside a folded run has nothing to draw under: its slides are not on screen.
    impl.barHidden.assign(impl.bars.size(), 0);
    for (size_t bi = 0; bi < impl.bars.size(); bi++) {
        const int cell = impl.cellOfSlide(impl.bars[bi].firstSlide);
        if (cell < 0) { impl.barHidden[bi] = 1; continue; }
        const DeckCell& c = impl.cells[cell];
        impl.barHidden[bi] = (c.folded() && c.bar != static_cast<int>(bi)) ? 1 : 0;
    }

    // Two lines of bars at most, and only the ones this deck actually has: an include bar
    // nearest the cards, a section bar under it. Reserved on every row so the grid stays a
    // grid — cards of different heights would be a worse trade than a few unused pixels.
    impl.barRows = 0;
    for (size_t bi = 0; bi < impl.bars.size(); bi++) {
        if (impl.barHidden[bi]) continue;
        impl.barRows = std::max(impl.barRows, impl.bars[bi].included ? 1 : 2);
    }
    impl.runOfSlide.assign(deck.size(), -1);
    for (size_t ri = 0; ri < impl.runs.size(); ri++) {
        const int from = impl.groups[impl.runs[ri].firstGroup].first;
        const int to   = impl.groups[impl.runs[ri].lastGroup].last;
        for (int s = from; s <= to && s < deck.size(); s++) impl.runOfSlide[s] = int(ri);
    }
    impl.canReorder = deck.reorderable();


    // ── Header ───────────────────────────────────────────────────────
    const float pad = std::round(w * 0.02f);
    const float headerH = 74.0f;
    SkFont titleFont = uiFont(19, true);
    SkFont smallFont = uiFont(12);

    drawText(canvas, deck.name(), pad, 32, titleFont, ui::kText);

    // Collapse / expand everything. The label says what a click will *do* rather than what
    // the deck currently is — a button that reads "collapsed" leaves you guessing.
    float countRight = w - pad;
    impl.foldButton = SkRect::MakeEmpty();
    if (!impl.bars.empty()) {
        const bool shut = allFolded();
        SkFont buttonFont = uiFont(12, true);
        const std::string label = shut ? "expand all" : "collapse all";
        const float bw = textWidth(buttonFont, label) + 26;
        impl.foldButton = SkRect::MakeXYWH(w - pad - bw, 14, bw, 24);
        fillRoundRect(canvas, impl.foldButton, 12,
                      impl.foldButtonHot ? ui::kLine : ui::kPanel);
        strokeRoundRect(canvas, impl.foldButton, 12,
                        impl.foldButtonHot ? ui::kAccent : ui::kLine, 1.0f);
        SkFont chevron = uiFont(11, true);
        drawText(canvas, shut ? "v" : ">", impl.foldButton.left() + 10, 31, chevron,
                 impl.foldButtonHot ? ui::kAccent : ui::kDim);
        drawText(canvas, label, impl.foldButton.left() + 22, 31, buttonFont,
                 impl.foldButtonHot ? ui::kText : ui::kDim);
        countRight = impl.foldButton.left() - 14;
    }
    drawTextRight(canvas, std::to_string(deck.size()) + " slides", countRight, 32,
                  uiFont(13), ui::kDim);

    std::string hint = impl.canReorder
        ? "drag a slide to reorder  ~  shift+left/right nudges  ~  double-click opens"
        : "read-only: this deck has no source information, so it cannot be reordered";
    float hintEnd = pad + drawText(canvas, hint, pad, 54, smallFont,
                                   impl.canReorder ? ui::kDim : ui::kWarn);
    // Only say it when there is one to say it about; a deck with no includes should not be
    // told about a rule it cannot run into.
    const bool anyIncluded = std::any_of(impl.runs.begin(), impl.runs.end(),
                                         [](const SourceRun& r) { return r.included; });
    if (impl.canReorder && !impl.bars.empty()) {
        drawText(canvas, "  ~  ", hintEnd, 54, smallFont, ui::kDim);
        drawText(canvas, "drag a bar to move a whole run, click it to fold  ~  Z / shift+Z",
                 hintEnd + 20, 54, smallFont, anyIncluded ? ui::kInclude : ui::kAccent);
    }
    if (!impl.status.empty()) {
        drawTextRight(canvas, ellipsize(impl.status, smallFont, w * 0.5f), w - pad, 54,
                      smallFont, impl.statusError ? ui::kOver : ui::kAhead);
    }
    fillRect(canvas, SkRect::MakeXYWH(0, headerH - 1, w, 1), ui::kLine);

    if (deck.empty()) {
        impl.cards.clear();
        impl.backend.present();
        glfwSwapBuffers(mWindow);
        return;
    }

    // ── Grid layout ──────────────────────────────────────────────────
    const float gutter = 14.0f;
    const float gridW = w - pad * 2;
    int columns = std::max(1, static_cast<int>((gridW + gutter) / (kMinCardW + gutter)));
    const int cellCount = static_cast<int>(impl.cells.size());
    columns = std::min(columns, cellCount);
    impl.columns = columns;
    const float cardW = (gridW - gutter * (columns - 1)) / columns;
    const float thumbH = cardW * static_cast<float>(kThumbH) / kThumbW;
    const float labelH = 34.0f + impl.barRows * 13.0f;
    const float cardH = thumbH + labelH;
    impl.cardW = cardW;
    impl.cardH = cardH;
    impl.thumbH = thumbH;

    const int rows = (cellCount + columns - 1) / columns;
    const float contentH = rows * cardH + std::max(0, rows - 1) * gutter + pad;
    const float viewH = h - headerH;
    impl.scrollMax = std::max(0.0f, contentH - viewH + pad);

    // Scroll to the cursor when it has just been *moved* — the keyboard walks it off the
    // bottom otherwise, and the view would show the same rows while the selection left. Only
    // then: doing it every frame is doing it to the wheel as well.
    if (impl.followCursor) {
        impl.followCursor = false;
        const int row = impl.cursor / columns;
        const float top = row * (cardH + gutter);
        if (top < impl.scroll) impl.scroll = top;
        else if (top + cardH > impl.scroll + viewH - pad)
            impl.scroll = top + cardH - viewH + pad;
    }
    impl.scroll = std::max(0.0f, std::min(impl.scrollMax, impl.scroll));

    impl.cards.assign(cellCount, SkRect::MakeEmpty());
    for (int i = 0; i < cellCount; i++) {
        const int row = i / columns, col = i % columns;
        const float x = pad + col * (cardW + gutter);
        const float y = headerH + pad * 0.4f + row * (cardH + gutter) - impl.scroll;
        impl.cards[i] = SkRect::MakeXYWH(x, y, cardW, cardH);
    }

    // The selection follows a moved run once the rebuilt deck has been laid out.
    if (impl.pendingSelectSlide >= 0) {
        const int cell = impl.cellOfSlide(std::min(impl.pendingSelectSlide, deck.size() - 1));
        if (cell >= 0) impl.setCursor(cell);
        impl.pendingSelectSlide = -1;
    }
    impl.cursor = std::max(0, std::min(cellCount - 1, impl.cursor));

    impl.hover = -1;
    for (int i = 0; i < cellCount; i++) {
        if (impl.cards[i].contains(static_cast<float>(impl.mouseX),
                                   static_cast<float>(impl.mouseY))) {
            impl.hover = i;
            break;
        }
    }

    // Where a drop would land, recomputed every frame because the pointer keeps moving.
    if (impl.dragging && impl.pressBar >= 0) {
        // Dragging a whole run: the target is a *block* of the file the run lives in, taken
        // from the slide under the pointer. A slide that sits in another file at this level
        // (inside some other include) offers no block, so the pointer passes over it.
        const int near = impl.nearestCard(impl.mouseX, impl.mouseY);
        const RunBar& run = impl.bars[impl.pressBar];
        if (near >= 0) {
            // The far edge of a folded cell is its *last* slide's block, not its first: a run
            // dropped past a folded section has to clear the whole of it.
            const bool after = impl.mouseX > impl.cards[near].centerX();
            const int slide = after ? impl.cells[near].lastSlide : impl.cells[near].firstSlide;
            const auto path = deck.at(slide).sourcePath();
            if (!path.empty() && path.front().file == run.file) {
                impl.dropChunk = path.front().index;
                impl.dropAfter = after;
            }
        }
    } else if (impl.dragging) {
        const int near = impl.nearestCard(impl.mouseX, impl.mouseY);
        if (near >= 0) {
            const bool after = impl.mouseX > impl.cards[near].centerX();
            const int gi = impl.groupAt(after ? impl.cells[near].lastSlide
                                              : impl.cells[near].firstSlide);
            // Confined to the file the dragged slide is written in. A slide spliced in by an
            // `:: include` belongs to the sub-deck, not to this one, so rather than let the
            // caret land where the move would be refused, it snaps to the nearest place the
            // slide can actually go — which is what the rails around the run are saying.
            impl.dropGroup = snapDrop(impl.groups, impl.groupAt(impl.pressSlide),
                                      gi + (after ? 1 : 0));
        }
    }

    // ── Cards ────────────────────────────────────────────────────────
    canvas->save();
    canvas->clipRect(SkRect::MakeLTRB(0, headerH, w, h));

    const int draggedGroup = impl.dragging ? impl.groupAt(impl.pressSlide) : -1;
    SkFont numFont = uiFont(12, true);
    SkFont nameFont = uiFont(13);

    for (int ci = 0; ci < cellCount; ci++) {
        const SkRect& card = impl.cards[ci];
        if (card.bottom() < headerH || card.top() > h) continue;   // off screen

        const DeckCell& cell = impl.cells[ci];
        const int i = cell.firstSlide;
        const Slide& slide = deck.at(i);
        const int gi = impl.groupAt(i);
        // A folded run is "current" whenever the projector is anywhere inside it — the whole
        // point of folding is that its slides are not on screen to say so themselves.
        const bool isCurrent = app.current() >= cell.firstSlide
                               && app.current() <= cell.lastSlide;
        const bool isCursor  = ci == impl.cursor;
        const bool inDragged = gi == draggedGroup;

        const int ri = impl.runAt(i);
        const bool included = cell.folded() ? impl.bars[cell.bar].included
                                            : (ri >= 0 && impl.runs[ri].included);
        const SkColor foldTone = cell.folded()
                                     ? (included ? ui::kInclude : ui::kAccent) : ui::kLine;

        SkRect thumb = SkRect::MakeXYWH(card.left(), card.top(), cardW, thumbH);
        // A folded run is drawn as a stack: two edges peeking out behind the front card, so
        // it reads as several slides without needing a second layout.
        if (cell.folded()) {
            for (int layer = 2; layer >= 1; layer--) {
                const float off = layer * 3.5f;
                SkRect back = thumb.makeOffset(off, -off).makeInset(off, off);
                fillRoundRect(canvas, back, 6, ui::kPanel);
                strokeRoundRect(canvas, back, 6, ui::kLine, 1.0f);
            }
        }
        fillRoundRect(canvas, thumb, 6, included ? ui::kIncludeBg : ui::kPanel);

        // Stills are read from the cache rather than demanded: a screenful of cards asking
        // urgently every frame would keep reshuffling the render queue instead of letting
        // any one still finish. The request is placed once and picked up when it is done.
        sk_sp<SkImage> image = thumbCached(slide.entry, kThumbW, kThumbH);
        if (image) {
            SkPaint paint;
            paint.setAlphaf(inDragged ? 0.35f : 1.0f);
            SkRect fit = thumb.makeInset(1, 1);
            canvas->save();
            canvas->clipRRect(SkRRect::MakeRectXY(thumb, 6, 6), true);
            canvas->drawImageRect(image, fit, SkSamplingOptions(SkFilterMode::kLinear), &paint);
            canvas->restore();
        } else {
            requestThumb(slide.entry, kThumbW, kThumbH);
        }

        SkColor border = cell.folded() ? foldTone : ui::kLine;
        float borderWidth = cell.folded() ? 1.5f : 1.0f;
        if (isCurrent) { border = ui::kAhead; borderWidth = 2.0f; }
        if (isCursor)  { border = ui::kAccent; borderWidth = 2.0f; }
        else if (ci == impl.hover) border = ui::kDim;
        strokeRoundRect(canvas, thumb, 6, border, borderWidth);

        // How many slides went into the fold, so a folded run is not mistaken for a slide.
        if (cell.folded()) {
            SkFont badgeFont = uiFont(11, true);
            const std::string count = std::to_string(cell.slides());
            SkRect badge = SkRect::MakeXYWH(thumb.right() - textWidth(badgeFont, count) - 20,
                                            thumb.bottom() - 24, textWidth(badgeFont, count) + 16,
                                            18);
            fillRoundRect(canvas, badge, 9, withAlpha(foldTone, 0xE0));
            drawText(canvas, count, badge.left() + 8, badge.bottom() - 5, badgeFont, ui::kBg);
        }

        // A section heading gets a bar down its left edge: the deck's structure has to be
        // visible in a grid, or a long deck is an undifferentiated wall of slides.
        if (slide.sectionNumber > 0) {
            fillRect(canvas, SkRect::MakeXYWH(thumb.left(), thumb.top() + 6, 3,
                                              thumb.height() - 12), ui::kAccent);
        }

        const float textY = card.top() + thumbH + 15;
        std::string num = std::to_string(i + 1);
        std::string name = slide.title;
        if (cell.folded()) {
            num += "-" + std::to_string(cell.lastSlide + 1);
            name = impl.bars[cell.bar].label;
        } else if (gi >= 0 && impl.groups[gi].count() > 1 && i == impl.groups[gi].first) {
            num = groupLabel(impl.groups[gi]);
        }
        const float numW = drawText(canvas, num, card.left() + 2, textY, numFont,
                                    isCurrent ? ui::kAhead : ui::kDim);
        drawText(canvas, ellipsize(name, nameFont, cardW - numW - 12),
                 card.left() + numW + 8, textY, nameFont, ui::kText);
        if (!cell.folded() && slide.hasNotes) {
            drawTextRight(canvas, "note", card.right() - 2, textY + 14, uiFont(10), ui::kDim);
        }

        // Slides expanded from one markdown block are tied together by a rule under them:
        // they move as a unit, and the view has to say so before something is dragged.
        if (!cell.folded() && gi >= 0 && impl.groups[gi].count() > 1) {
            const bool first = i == impl.groups[gi].first;
            const bool last  = i == impl.groups[gi].last;
            SkRect tie = SkRect::MakeLTRB(card.left() + (first ? 2 : -gutter),
                                          card.top() + thumbH + 22,
                                          card.right() - (last ? 2 : -gutter),
                                          card.top() + thumbH + 23.5f);
            fillRect(canvas, tie, ui::kLine);
        }

        // An included sub-deck is walled off by a rail in the gutter at each end of the run.
        // Its slides can be reordered among themselves but cannot leave, so the run has to
        // read as a boundary and not merely as a colour.
        if (included && !cell.folded() && ri >= 0) {
            const SourceRun& run = impl.runs[ri];
            const float railTop = thumb.top() + 4, railBottom = thumb.bottom() - 4;
            if (i == impl.groups[run.firstGroup].first) {
                fillRect(canvas, SkRect::MakeLTRB(card.left() - gutter * 0.5f - 1, railTop,
                                                  card.left() - gutter * 0.5f + 1, railBottom),
                         ui::kInclude);
            }
            if (i == impl.groups[run.lastGroup].last) {
                fillRect(canvas, SkRect::MakeLTRB(card.right() + gutter * 0.5f - 1, railTop,
                                                  card.right() + gutter * 0.5f + 1, railBottom),
                         ui::kInclude);
            }
        }
    }

    // ── Grip bars ────────────────────────────────────────────────────
    // The handle for moving a whole sub-deck or a whole section. Drawn in the strip already
    // reserved under the cards, so picking up a run costs the grid nothing — which is the
    // point: the deck stays a plain grid of slides, and the runs are marked on top of it.
    impl.barHits.clear();
    for (size_t bi = 0; bi < impl.bars.size(); bi++) {
        if (impl.barHidden[bi]) continue;     // its slides are inside a folded run
        const RunBar& bar = impl.bars[bi];
        const SkColor tone = bar.included ? ui::kInclude : ui::kAccent;
        const bool live = static_cast<int>(bi) == impl.hoverBar
                          || static_cast<int>(bi) == impl.pressBar;
        const bool shut = impl.foldedBar[bi] != 0;
        const int firstCell = impl.cellOfSlide(bar.firstSlide);
        const int lastCell  = impl.cellOfSlide(bar.lastSlide);
        if (firstCell < 0 || lastCell < 0) continue;

        // A run wrapping across rows gets one bar per row, so its extent stays visible even
        // when it is broken up; the name goes on the first of them only.
        for (int cell = firstCell; cell <= lastCell;) {
            const int row = cell / columns;
            const int rowEnd = std::min(lastCell, row * columns + columns - 1);
            const SkRect& a = impl.cards[cell];
            const SkRect& b = impl.cards[rowEnd];
            const float y = a.top() + thumbH + 26 + (bar.included ? 0.0f : 13.0f);
            SkRect strip = SkRect::MakeLTRB(a.left(), y, b.right(), y + 12);
            if (strip.bottom() > headerH && strip.top() < h) {
                fillRoundRect(canvas, strip, 6, live ? withAlpha(tone, 0x33) : ui::kPanel);
                float x = strip.left() + 7;
                SkFont tag = uiFont(9, true);
                // The chevron says which way a click will go, and doubles as the bar's own
                // marker: this strip is a thing you can grab, not a rule under the cards.
                x += drawText(canvas, shut ? ">" : "v", x, y + 9, tag, tone) + 5;
                if (cell == firstCell) {
                    const std::string text = bar.label + "  " + std::to_string(bar.slides());
                    drawText(canvas, ellipsize(text, tag, strip.width() - 26), x, y + 9, tag,
                             tone);
                }
                impl.barHits.push_back({strip, static_cast<int>(bi)});
            }
            cell = rowEnd + 1;
        }
        // While it is being carried, outline every card it will take with it.
        if (live) {
            for (int cell = firstCell; cell <= lastCell; cell++) {
                SkRect thumb = SkRect::MakeXYWH(impl.cards[cell].left(),
                                                impl.cards[cell].top(), cardW, thumbH);
                strokeRoundRect(canvas, thumb, 6, tone, 2.0f);
            }
        }
    }

    // ── Drop caret ───────────────────────────────────────────────────
    if (impl.dragging && impl.pressBar >= 0 && impl.dropChunk >= 0) {
        const RunBar& bar = impl.bars[impl.pressBar];
        // Where the run would land, shown against the slide the pointer is over. planRunDrop
        // says whether it is a move at all; a drop inside the run's own span draws nothing,
        // because nothing would happen.
        if (planRunDrop(bar, impl.dropChunk, impl.dropAfter) >= 0) {
            // Against the outermost card holding that block — its left edge when the run
            // would go before it, its right edge when after.
            int mark = -1;
            for (int c = 0; c < cellCount; c++) {
                const auto path = deck.at(impl.cells[c].firstSlide).sourcePath();
                const auto tail = deck.at(impl.cells[c].lastSlide).sourcePath();
                const bool holds = (!path.empty() && path.front().file == bar.file
                                    && path.front().index == impl.dropChunk)
                                   || (!tail.empty() && tail.front().file == bar.file
                                       && tail.front().index == impl.dropChunk);
                if (!holds) continue;
                mark = c;
                if (!impl.dropAfter) break;      // the first such card
            }
            if (mark >= 0) {
                const SkRect& c = impl.cards[mark];
                const float x = impl.dropAfter ? c.right() + gutter * 0.5f
                                               : c.left() - gutter * 0.5f;
                fillRoundRect(canvas, SkRect::MakeXYWH(x - 1.5f, c.top(), 3, thumbH), 1.5f,
                              bar.included ? ui::kInclude : ui::kAccent);
            }
        }
    } else if (impl.dragging && impl.dropGroup >= 0) {
        const int gi = impl.dropGroup;
        const int cell = gi < static_cast<int>(impl.groups.size())
                             ? impl.cellOfSlide(impl.groups[gi].first) : cellCount - 1;
        if (cell >= 0) {
            const SkRect& c = impl.cards[cell];
            const bool end = gi >= static_cast<int>(impl.groups.size());
            const float x = end ? c.right() + gutter * 0.5f : c.left() - gutter * 0.5f;
            fillRoundRect(canvas, SkRect::MakeXYWH(x - 1.5f, c.top(), 3, thumbH), 1.5f,
                          ui::kAccent);
        }
    }
    canvas->restore();

    // The dragged card rides the pointer, so the pointer is unambiguously carrying
    // something even when the caret is far away.
    if (impl.dragging && impl.pressBar >= 0) {
        const RunBar& bar = impl.bars[impl.pressBar];
        SkFont tag = uiFont(11, true);
        const std::string text = bar.label + "  " + std::to_string(bar.slides()) + " slides";
        const float gw = textWidth(tag, text) + 22;
        SkRect ghost = SkRect::MakeXYWH(static_cast<float>(impl.mouseX) - gw * 0.5f,
                                        static_cast<float>(impl.mouseY) - 11, gw, 22);
        const SkColor tone = bar.included ? ui::kInclude : ui::kAccent;
        fillRoundRect(canvas, ghost, 11, ui::kPanel);
        strokeRoundRect(canvas, ghost, 11, tone, 2.0f);
        drawText(canvas, text, ghost.left() + 11, ghost.centerY() + 4, tag, tone);
    } else if (impl.dragging && impl.pressSlide >= 0) {
        const Slide& slide = deck.at(impl.pressSlide);
        const float gw = cardW * 0.6f, gh = thumbH * 0.6f;
        SkRect ghost = SkRect::MakeXYWH(static_cast<float>(impl.mouseX) - gw * 0.5f,
                                        static_cast<float>(impl.mouseY) - gh * 0.5f, gw, gh);
        fillRoundRect(canvas, ghost, 5, ui::kPanel);
        if (sk_sp<SkImage> image = thumbCached(slide.entry, kThumbW, kThumbH)) {
            SkPaint paint;
            paint.setAlphaf(0.9f);
            canvas->save();
            canvas->clipRRect(SkRRect::MakeRectXY(ghost, 5, 5), true);
            canvas->drawImageRect(image, ghost, SkSamplingOptions(SkFilterMode::kLinear), &paint);
            canvas->restore();
        }
        strokeRoundRect(canvas, ghost, 5, ui::kAccent, 2.0f);
    }

    impl.backend.present();
    glfwSwapBuffers(mWindow);
}

}  // namespace refract
