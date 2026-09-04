#include "Ui.h"

#include "include/core/SkFontMetrics.h"
#include "include/core/SkFontMgr.h"
#include "include/core/SkFontStyle.h"
#include "include/core/SkPaint.h"
#include "include/core/SkRRect.h"
#include "include/core/SkSamplingOptions.h"
#include "include/core/SkTypeface.h"
#if defined(__APPLE__)
#include "include/ports/SkFontMgr_mac_ct.h"
#else
#include "include/ports/SkFontMgr_fontconfig.h"
#include "include/ports/SkFontScanner_FreeType.h"
#endif

#include <algorithm>
#include <cmath>
#include <ctime>
#include <sstream>

namespace refract {

namespace {

SkFontMgr* fontMgr() {
    static sk_sp<SkFontMgr> mgr =
#if defined(__APPLE__)
        SkFontMgr_New_CoreText(nullptr);
#else
        SkFontMgr_New_FontConfig(nullptr, SkFontScanner_Make_FreeType());
#endif
    return mgr.get();
}

// The system UI face, resolved once per weight. matchFamilyStyle(nullptr, …) gives the
// platform default, which is what the rest of the desktop uses for chrome.
sk_sp<SkTypeface> uiTypeface(bool bold) {
    static sk_sp<SkTypeface> regular =
        fontMgr() ? fontMgr()->matchFamilyStyle(nullptr, SkFontStyle()) : nullptr;
    static sk_sp<SkTypeface> heavy =
        fontMgr() ? fontMgr()->matchFamilyStyle(nullptr, SkFontStyle::Bold()) : nullptr;
    return bold ? heavy : regular;
}

// A monospaced face. Tried by name because there is no "give me the mono default" in the
// font manager; the first that resolves wins, and a deck editor on a machine with none of
// them falls back to the UI face rather than to nothing.
sk_sp<SkTypeface> monoTypeface(bool bold) {
    static const char* kFamilies[] = {"Menlo", "SF Mono", "Monaco", "DejaVu Sans Mono",
                                      "Liberation Mono", "Consolas", "monospace"};
    auto resolve = [](const SkFontStyle& style) -> sk_sp<SkTypeface> {
        if (!fontMgr()) return nullptr;
        for (const char* family : kFamilies) {
            if (auto face = fontMgr()->matchFamilyStyle(family, style)) return face;
        }
        return nullptr;
    };
    static sk_sp<SkTypeface> regular = resolve(SkFontStyle());
    static sk_sp<SkTypeface> heavy = resolve(SkFontStyle::Bold());
    sk_sp<SkTypeface> face = bold ? heavy : regular;
    return face ? face : uiTypeface(bold);
}

}  // namespace

SkFont uiMonoFont(float size, bool bold) {
    SkFont f(monoTypeface(bold), size);
    f.setEdging(SkFont::Edging::kAntiAlias);
    f.setSubpixel(true);
    return f;
}

SkFont uiFont(float size, bool bold) {
    SkFont f(uiTypeface(bold), size);
    f.setEdging(SkFont::Edging::kAntiAlias);
    f.setSubpixel(true);
    return f;
}

SkColor withAlpha(SkColor color, unsigned alpha) {
    return SkColorSetARGB(alpha, SkColorGetR(color), SkColorGetG(color), SkColorGetB(color));
}

float textWidth(const SkFont& font, const std::string& text) {
    return font.measureText(text.c_str(), text.size(), SkTextEncoding::kUTF8);
}

float drawText(SkCanvas* canvas, const std::string& text, float x, float y,
               const SkFont& font, SkColor color) {
    if (text.empty()) return 0.0f;
    SkPaint paint;
    paint.setColor(color);
    paint.setAntiAlias(true);
    canvas->drawSimpleText(text.c_str(), text.size(), SkTextEncoding::kUTF8, x, y, font, paint);
    return textWidth(font, text);
}

float drawTextRight(SkCanvas* canvas, const std::string& text, float x, float y,
                    const SkFont& font, SkColor color) {
    float w = textWidth(font, text);
    drawText(canvas, text, x - w, y, font, color);
    return w;
}

float drawTextCentred(SkCanvas* canvas, const std::string& text, const SkRect& box,
                      const SkFont& font, SkColor color) {
    // Centred on the cap height rather than the baseline: a label sitting on the box's
    // middle line reads as low, because the glyphs hang above it.
    SkFontMetrics metrics;
    font.getMetrics(&metrics);
    const float y = box.centerY() - (metrics.fAscent + metrics.fDescent) * 0.5f;
    return drawText(canvas, text, box.centerX() - textWidth(font, text) * 0.5f, y, font, color);
}

std::vector<std::string> wrapText(const std::string& text, const SkFont& font, float maxWidth) {
    std::vector<std::string> lines;
    std::stringstream in(text);
    std::string paragraph;
    while (std::getline(in, paragraph)) {
        if (!paragraph.empty() && paragraph.back() == '\r') paragraph.pop_back();
        if (paragraph.empty()) { lines.push_back(""); continue; }
        std::stringstream words(paragraph);
        std::string word, line;
        while (words >> word) {
            std::string candidate = line.empty() ? word : line + " " + word;
            if (!line.empty() && textWidth(font, candidate) > maxWidth) {
                lines.push_back(line);
                line = word;
            } else {
                line = candidate;
            }
        }
        lines.push_back(line);
    }
    return lines;
}

std::string ellipsize(const std::string& text, const SkFont& font, float maxWidth) {
    if (textWidth(font, text) <= maxWidth) return text;
    // "..." rather than an ellipsis character: the chrome draws through one typeface with
    // no font fallback, so a glyph the UI font happens not to carry comes out as tofu.
    std::string s = text;
    while (!s.empty() && textWidth(font, s + "...") > maxWidth) {
        // Step back over a whole UTF-8 code point so we never cut one in half.
        do { s.pop_back(); } while (!s.empty() && (s.back() & 0xC0) == 0x80);
    }
    return s + "...";
}

void fillRect(SkCanvas* canvas, const SkRect& r, SkColor color) {
    SkPaint p;
    p.setColor(color);
    p.setAntiAlias(true);
    canvas->drawRect(r, p);
}

void fillRoundRect(SkCanvas* canvas, const SkRect& r, float radius, SkColor color) {
    SkPaint p;
    p.setColor(color);
    p.setAntiAlias(true);
    canvas->drawRRect(SkRRect::MakeRectXY(r, radius, radius), p);
}

void strokeRoundRect(SkCanvas* canvas, const SkRect& r, float radius, SkColor color,
                     float width) {
    SkPaint p;
    p.setColor(color);
    p.setAntiAlias(true);
    p.setStyle(SkPaint::kStroke_Style);
    p.setStrokeWidth(width);
    canvas->drawRRect(SkRRect::MakeRectXY(r, radius, radius), p);
}

SkRect drawImageFit(SkCanvas* canvas, const sk_sp<SkImage>& img, const SkRect& box) {
    if (!img || img->width() <= 0 || img->height() <= 0) {
        fillRoundRect(canvas, box, 4, ui::kPanel);
        strokeRoundRect(canvas, box, 4, ui::kLine);
        return box;
    }
    float s = std::min(box.width() / img->width(), box.height() / img->height());
    float w = img->width() * s, h = img->height() * s;
    SkRect dst = SkRect::MakeXYWH(box.centerX() - w * 0.5f, box.centerY() - h * 0.5f, w, h);
    SkSamplingOptions sampling(SkFilterMode::kLinear, SkMipmapMode::kLinear);
    canvas->drawImageRect(img, dst, sampling);
    return dst;
}

std::string formatDuration(double seconds) {
    bool negative = seconds < 0;
    long total = std::lround(std::fabs(seconds));
    long h = total / 3600, m = (total % 3600) / 60, s = total % 60;
    char buf[32];
    if (h > 0) std::snprintf(buf, sizeof(buf), "%s%ld:%02ld:%02ld", negative ? "-" : "", h, m, s);
    else       std::snprintf(buf, sizeof(buf), "%s%ld:%02ld", negative ? "-" : "", m, s);
    return buf;
}

std::string wallClock() {
    std::time_t t = std::time(nullptr);
    std::tm local{};
    localtime_r(&t, &local);
    char buf[16];
    std::strftime(buf, sizeof(buf), "%H:%M", &local);
    return buf;
}

}  // namespace refract
