// Small Skia drawing toolkit for the player's own chrome — the presenter view and the
// navigator overlay. Nothing here knows about RemoteCompose; it is text, boxes and images.
#pragma once

#include "include/core/SkCanvas.h"
#include "include/core/SkColor.h"
#include "include/core/SkFont.h"
#include "include/core/SkImage.h"
#include "include/core/SkRect.h"
#include "include/core/SkRefCnt.h"

#include <string>
#include <vector>

namespace refract {

// The chrome palette is deliberately *not* the deck's. Presenter output sits next to the
// slide on a second screen, and a tool that borrows the deck's colours reads as part of it.
namespace ui {
constexpr SkColor kBg     = 0xFF0E1013;
constexpr SkColor kPanel  = 0xFF171A20;
constexpr SkColor kLine   = 0xFF2A2F38;
constexpr SkColor kText   = 0xFFE8EAF0;
constexpr SkColor kDim    = 0xFF868D9C;
constexpr SkColor kAccent = 0xFF6EA8FF;
constexpr SkColor kWarn   = 0xFFFFC65C;
constexpr SkColor kOver   = 0xFFFF6B6B;
constexpr SkColor kAhead  = 0xFF6FCF97;   // ahead of the rehearsal — the one good green
constexpr SkColor kScrim  = 0xD8090A0D;  // navigator backdrop over the live slide
// Slides spliced in by an `:: include`. Deliberately none of the four above: the accent
// already means "section heading" in the deck view, and the other three mean pace.
constexpr SkColor kInclude = 0xFF9A82E0;
constexpr SkColor kIncludeBg = 0xFF1B1826;   // the tint their cards sit on
}  // namespace ui

SkFont uiFont(float size, bool bold = false);
// A monospaced face, for the one place the player shows source: the slide editor. Markdown is
// column-sensitive — indentation is what makes a sub-bullet a sub-bullet — and a proportional
// font hides that. Falls back to uiFont where no mono face is installed.
SkFont uiMonoFont(float size, bool bold = false);
float  textWidth(const SkFont& font, const std::string& text);

// Draw `text` with its baseline at (x, y); returns the advance.
float drawText(SkCanvas* canvas, const std::string& text, float x, float y,
               const SkFont& font, SkColor color);
// Same, right-aligned so the text *ends* at x.
float drawTextRight(SkCanvas* canvas, const std::string& text, float x, float y,
                    const SkFont& font, SkColor color);
// Centred in `box`, horizontally and on its vertical middle — for button labels.
float drawTextCentred(SkCanvas* canvas, const std::string& text, const SkRect& box,
                      const SkFont& font, SkColor color);

// Greedy word wrap, honouring newlines already in `text`.
std::vector<std::string> wrapText(const std::string& text, const SkFont& font, float maxWidth);

// `text` shortened with a trailing ellipsis until it fits `maxWidth`.
std::string ellipsize(const std::string& text, const SkFont& font, float maxWidth);

void fillRect(SkCanvas* canvas, const SkRect& r, SkColor color);
// The same colour at a different alpha — for a wash of it behind something.
SkColor withAlpha(SkColor color, unsigned alpha);
void fillRoundRect(SkCanvas* canvas, const SkRect& r, float radius, SkColor color);
void strokeRoundRect(SkCanvas* canvas, const SkRect& r, float radius, SkColor color,
                     float width = 1.0f);

// Aspect-fit `img` inside `box` and return the rect it landed in. A null image draws an
// empty frame instead, so a slide whose thumbnail is still rendering keeps its layout.
SkRect drawImageFit(SkCanvas* canvas, const sk_sp<SkImage>& img, const SkRect& box);

// Durations as m:ss, or h:mm:ss past an hour.
std::string formatDuration(double seconds);
// Local wall-clock time as HH:MM.
std::string wallClock();

}  // namespace refract
