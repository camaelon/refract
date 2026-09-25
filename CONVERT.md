# Refract Deck Conversion Guide (PPTX / PDF to Refract)

This document details the practical techniques, architectural patterns, coordinate transformations, and layout tricks discovered while converting PowerPoint (`.pptx`) decks (specifically the Google Android Design System template, `ADS-Template.pptx`) to **Refract**.

---

## 1. Coordinate Systems & Scaling Ratios

Standard PowerPoint decks typically define a canvas size in points or EMUs (English Metric Units):
- **PPTX Canvas**: $720 \times 405\text{ pt}$ (16:9 aspect ratio)
- **Rendered Reference Images (e.g. PDF / pdftoppm)**: $1440 \times 810\text{ px}$ (2x supersampled)
- **Refract Target Canvas**: $1600 \times 900\text{ px}$ (16:9 native canvas)

### Exact Conversion Ratios
| Source Coordinate Space | Target: Refract Canvas ($1600 \times 900$) | Scaling Factor |
| :--- | :--- | :--- |
| **PPTX Points** ($720 \times 405$) | Multiply by $1600 / 720 = 20 / 9$ | **$\approx 2.222222$** |
| **PDF / Rendered Page PNG** ($1440 \times 810$) | Multiply by $1600 / 1440 = 10 / 9$ | **$\approx 1.111111$** |
| **PPTX EMUs** ($9,144,000 \times 5,143,500$) | $x \times 1600 / 9,144,000$, $y \times 900 / 5,143,500$ | Exact EMU scale |

> **Pro Tip**: When picking pixel coordinates from an exported reference PNG ($1440 \times 810$), multiply by $10 / 9$ (or $1.1111$) to get the exact Refract canvas coordinate.

---

## 2. Background Documents (`bg_doc`) & Canvas Primitives

Complex visual backgrounds, accent shapes, stadium pills, and decorative dividers that do not participate in text flow should be implemented as lightweight RemoteCompose JSON canvas documents loaded via `bg_doc=...`.

### The Canvas JSON Structure
A background JSON document lives in `includes/` (e.g., `examples/ads/includes/bg_slide_020.json`):
```json
{
  "header": { "width": 1600, "height": 900 },
  "root": {
    "type": "box",
    "modifiers": ["fillMaxSize", { "background": "#FFFFFFFF" }],
    "children": [
      {
        "type": "canvas",
        "modifiers": ["fillMaxSize"],
        "commands": [
          ...
        ]
      }
    ]
  }
}
```

### Drawing Geometry Tricks

#### Half-Pills & Anchored Stadium Shapes
A stadium shape anchored to the edge of the slide (e.g., Slide 19 green left pill, Slide 20 top-anchored rounded card) can be cleanly drawn using `drawroundrect` by placing the opposite rounded corners outside the canvas:
- **Left-anchored stadium pill** ($r = 176$):
  ```json
  {
    "type": "drawroundrect",
    "left": -176.0,
    "top": 92.0,
    "right": 598.0,
    "bottom": 444.0,
    "rx": 176.0,
    "ry": 176.0
  }
  ```
- **Top-anchored card** ($r = 270$):
  ```json
  {
    "type": "drawroundrect",
    "left": 787.8,
    "top": -270.0,
    "right": 1327.8,
    "bottom": 785.6,
    "rx": 270.0,
    "ry": 270.0
  }
  ```

#### Horizontal Dividers
Draw continuous or segmented lines across columns using `drawline`:
```json
{
  "type": "paint",
  "ops": [
    { "color": "#FFBDC1C6" },
    { "style": "stroke" },
    { "strokeWidth": 1.0 }
  ]
},
{
  "type": "drawline",
  "x1": 44.0,
  "y1": 335.33,
  "x2": 1556.0,
  "y2": 335.33
}
```

#### Canvas Typography & Bold Numbers
To draw bold numbers or labels directly in the canvas:
```json
{
  "type": "paint",
  "ops": [
    { "color": "#FF34A853" },
    { "style": "fill" },
    { "textSize": 24.0 },
    {
      "typeface": {
        "font": "sans-serif",
        "weight": 700
      }
    }
  ]
},
{
  "type": "drawtextanchored",
  "text": "01",
  "x": 46.7,
  "y": 271.11,
  "panX": -1.0,
  "panY": 0.0
}
```
- `panX: -1.0` anchors the text to its **left** edge.
- `panX: 0.0` anchors the text to its **center**.
- `panX: 1.0` anchors the text to its **right** edge.

---

## 3. Layout Constructs in Refract

Refract provides high-level primitives in `slides.md` for orchestrating layouts:

### `:: split [ratio]` vs `:: content [cols]`

- **`:: split [left:right]`**:
  - Automatically places the slide `# Title` in the **left pane** and the body content in the **right pane**.
  - Perfect for slides with a strong vertical division, colored sidebar, or hero left title.
  - Ratio examples: `[1:2]`, `[645:819]`, `[1:1]`.

- **`:: content [col1:col2]`**:
  - Places the slide `# Title` **across the top** of the slide, spanning the full content width.
  - Content below the title is distributed into the specified column ratios (separated by `+++`).
  - Ideal for multi-column grids, tables of contents, and card layouts.

### Vertical Panes & Stacked Content (`===`)
- Use `===` to separate vertically stacked sections within a column or content area.
- Useful when a top block must have custom sizing or spacing distinct from the bottom grid.

### Column Delimiters (`+++`)
- In multi-column layouts, use `+++` to separate content into adjacent columns.

---

## 4. Fine-Tuning Spacing, Alignment, and Typography

### Slide Directive Properties
Directives support fine-grained spacing controls:
- `pad_top`: Nudges the entire slide content vertically (positive moves down, negative moves up).
- `pad_bottom`, `pad_left`, `pad_right`: Controls outer container margins.
- `title_pad_top`: Vertically offsets only the `# Title` (e.g. inside a colored background pill).
- `title_gap`: Adjusts the vertical gap between the title and the content below.
- `title_color`: Overrides the title text color (e.g. `title_color=#FFFFFFFF` on dark backgrounds).

### Per-Slide Heading Overrides
Heading properties can be customized on a per-slide basis directly on the layout directive:
```markdown
:: content bg_doc=bg_slide_020.json h6_band_height=108.5 h6_pad_left=79.4 h6_weight=400 h3_gap=38
```
Supported heading overrides:
- `h{lvl}_band_height`: Sets the fixed height of each heading item (aligning text rows with background lines).
- `h{lvl}_pad_left`: Indents headings horizontally (e.g., leaving room for background numbers or icons).
- `h{lvl}_weight`: Changes heading font weight (`400` = normal, `500` = medium, `700` = bold).
- `h{lvl}_gap`: Sets the spacing after a heading before the next block.

---

## 5. Separation of Concerns: Background Documents vs Markdown Content

A critical architectural pattern in Refract is keeping background chrome distinct from editable slide content:

### What Belongs in `bg_slide_XXX.json`:
- Slide base background color/fill.
- Presentation chrome: logos, confidentiality/proprietary notices, slide category badges.
- Abstract decorative vector shapes: background stadium pills, corner geometry, divider lines, decorative card silhouettes.
- **Rule of Thumb**: Anything a presenter would expect to change when adapting a presentation (photos, names, roles, descriptions) must **never** be hardcoded or baked into the background document.

### What Belongs in `slides.md`:
- Media includes: `<image.png | width=W height=H>` (such as speaker headshots, screenshots, diagrams).
- Typography & text hierarchy: `# Title`, `### Subheading`, body paragraphs.
- Layout orchestration: `:: split [ratio]` or `:: content [cols]`.

### Case Study: Speaker / Headshot Slide (e.g. Slide 35)
When a speaker headshot sits on top of a colored background pill with adjacent metadata:
1. **Background JSON** (`bg_slide_035.json`):
   Draws only the blue stadium capsule:
   ```json
   {
     "type": "drawroundrect",
     "left": 363.34, "top": 156.51, "right": 755.36, "bottom": 743.49,
     "rx": 196.01, "ry": 196.01
   }
   ```
2. **Slide Markdown** (`slides.md`):
   Positions the photo and text in side-by-side columns:
   ```markdown
   :: split [392:491] bg_doc=bg_slide_035.json pad_left=319.34 pad_right=231.26 pad_top=93.73 pane_gap=78 h1_pad_top=173.4 h1_size=44 h1_weight=700 h1_gap=5 h3_size=31.1 h3_weight=500 h3_color=#FF5F6368 h3_gap=47 body_size=24.4 body_color=#FF3C4043
   <image23_speaker_masked.png | width=392 height=569>

   +++

   # First and last name

   ### Position, Company

   Lorem ipsum dolor sit amet, consectetur<br>adipiscing elit, sed do eiusmod tempor.
   ```
- `pane_gap=78`: Precisely bridges the gap between the pill's right edge ($755.36$) and the text column's left edge ($833.34$).
- `h1_pad_top=173.4`: Offsets the text vertically to align with the visual baseline of the headshot.
- Base padding compensation: Since the theme's default `split` padding is `[44, 80, 44, 44]`, the delta `pad_left` is $363.34 - 44 = 319.34$, and `pad_top` is $173.73 - 80 = 93.73$.

---

## 6. Slide Ordering & Numbering Best Practices

- **Slide Numbering Consistency**:
  Ensure slide filenames in `out/` use consistent zero-padding (`001_...`, `018_...`, `123_...`) so alphabetical directory listings match presentation order.
- **1-to-1 Mapping with Original PPTX**:
  Always verify that Slide $N$ in `slides.md` corresponds directly to Slide $N$ in the source PPTX. Avoid grouping or skipping slides; misplaced section dividers or appendix slides will cascade numbering errors down the entire deck.

---

## 7. Fast Verification Workflow

To rapidly iterate without rebuilding the entire deck:
1. **Incremental Deck Compile**:
   ```bash
   python3 refract.py examples/ads
   ```
   (Reuses unchanged slides from cache, typically completes in $< 1.5\text{s}$).

2. **Single-Slide Render to Image**:
   ```bash
   ./prebuilt/rc2image examples/ads/out/020_agenda.rc /tmp/ads_verify/020_agenda.png 1600 900
   ```
   (Headless Skia render in $\approx 50\text{ms}$).

3. **Pixel Inspection & Baseline Comparison**:
   Compare `/tmp/ads_verify/020_agenda.png` side-by-side with `/tmp/ads_pages/page_020.png` using an image viewer or programmatic pixel difference scripts.

---

## 8. Theme Presets and the `as` Slide Type

When converting large presentation decks, many slides share identical visual treatments, layouts, typography overrides, or background assets (e.g., full-bleed section title cards, offset title slides, speaker cards, centered section intros).

Instead of repeating lengthy override parameter strings on every slide directive:
```markdown
:: section bg=#202124 bg_doc=bg_slide_011.json title_size=207 title_weight=600 pad_top=-44
```

Refract provides the `as` slide type:
```markdown
:: as: <theme_name> [optional_slide_overrides...]
```

### Theme TOML Configuration
Theme preset files live in `<deck_dir>/theme/<theme_name>.toml` (or `<deck_dir>/themes/`).

Example: `examples/ads/theme/section_dark.toml`
```toml
type = "section"
bg = "#202124"
bg_doc = "bg_section_dark.json"
title_size = 207
title_weight = 600
pad_top = -44
```

In `slides.md`, the directive simplifies to:
```markdown
:: as: section_dark
# Title<br>slides
```

### Supported Layouts and Overrides in Theme TOML
A theme preset can define:
- `type`: Target slide layout (e.g., `"content"`, `"split"`, `"section"`, `"title"`)
- `ratio`: Column split ratio (e.g., `ratio = [392, 491]` or `ratio = "1:2"`)
- `bg`, `bg_doc`: Canvas background fill color and JSON background document
- `pad_left`, `pad_top`, `pad_right`, `pad_bottom`: Slide content padding deltas
- `title_size`, `title_weight`, `title_color`, `title_gap`: Slide header styling
- `body_size`, `body_weight`, `body_color`: Slide body text typography
- `h1_...` through `h6_...`: Heading-specific sizes, weights, colors, gaps, padding, and band heights
- Structured tables: `[theme]`, `[layout]`, `[font]`, `[heading.N]`, `[section]`, `[background]`

### Per-Slide Override Precedence
Any parameters specified directly on the slide directive take precedence over the theme TOML defaults:
```markdown
:: as: section_center bg_doc=bg_slide_024.json pad_top=201 title_gap=42
```
Here, `as: section_center` provides `type = "content"`, `align = "center"`, `title_size = 100`, `title_weight = 700`, `body_size = 31.1`, and `body_weight = 500`. The slide directive overrides `pad_top` and `title_gap`, and provides the slide-specific background document.

### Theme Asset Directory Resolution
Assets (background documents and images) can be isolated within `<deck_dir>/theme/include/` (or `<deck_dir>/theme/includes/`) rather than polluting the deck-level `includes/` directory:
- Shared section background `theme/include/bg_section_dark.json`
- Navigation icons `theme/include/btn_back_to_navigation.png`
- Deck branding logos `theme/include/image9.png`

Refract's asset resolution automatically checks `theme/include/` alongside `includes/`.

---

## 9. Tracing a Deck in Absolute Coordinates

Refract is a flow-layout engine: you describe a column of blocks and it stacks
them. A PowerPoint deck is the opposite — every shape carries an absolute
`(x, y, w, h)`. The trick that makes a 1:1 port tractable is to **neutralise the
engine's own margins** so that the numbers you write are the numbers in the
source.

In `settings.toml`, zero every layout's padding:

```toml
[layout.content]
h_align = "start"
v_align = "top"
padding = [0, 0, 0, 0]
# ... and the same for title / section / split / max
```

> [!IMPORTANT]
> `pad_left=` / `pad_top=` / … on a slide or section are **deltas added to the
> slide type's base padding**, not absolute values. Zeroing the base is what
> turns them into absolute PPTX coordinates.

With that in place, a shape at EMU `(x, y)` on a 36 576 000 × 20 574 000 canvas
becomes `pad_left = x/36576000*1600`, `pad_top = y/20574000*900`, and a font at
`N` points becomes `N * 12700 / 36576000 * 1600` pixels.

PowerPoint also adds an internal text inset (`lIns`/`tIns`, 16 px at this scale
by default). A text box whose frame is at `[15.2, 14.36]` puts its first glyph
at `(31.2, 30.36)` — always add the inset before writing the number down.

### Line spacing

PowerPoint's `lnSpc` percentage is not a plain multiple of the font size. The
empirical conversion, verified across three slides, is:

```
pixel pitch ≈ lnSpc/100 * 1.2047 * font_px
```

Feed that back in as a fraction of the font size via `line_height`:

```toml
[heading.1]
line_height = 0.94   # lnSpc 78% at 188.89 px -> 177.5 px pitch
```

`line_height` pins the pitch of a **multi-line** heading by wrapping each line
in a fixed-height, vertically-centred box. Without it each line is as tall as
the font asks to be, which is right for a hand-written deck and wrong for a
traced one.

### Rounded rectangles

A PPTX `roundRect` corner radius is `adj/100000 * min(w, h)`. The common
`adj = 14741` therefore means `0.14741 * min(w, h)`.

---

## 10. Fixed-Height Bands: the `===` Section System

A traced slide is really a stack of horizontal bands at known y offsets. Give
each `===` section an explicit `height=` and the band becomes a fixed-height
strip instead of a weighted one; the y offset of band *n* is just the sum of the
heights above it.

```markdown
:: as: bento height=138.34
# SFT bento-box

===

:: content height=235.18 pad_left=41.66 pad_right=43.6 pane_gap=1.05 [20644:20974:...]
<shot_1.png | width=206.44 height=208>
+++
<shot_2.png | width=209.74 height=209.5>

===

:: content height=120.75 pad_left=33.15 pane_gap=31.75 align=center [123770:29740]
#### E2E UX
+++
##### Waterlock
```

Per-section keys that matter for tracing: `height`, `pad_left`, `pad_right`,
`pad_top`, `pane_gap`, `align`.

### Exact pane widths

When `pane_gap` is present the available width is computed as
`width - pad_left - pad_right - gap*(n-1)` and the gaps are emitted as explicit
spacer boxes, so pane widths come out exactly as the ratio asks. Ratios are
parsed with `int()`, so **use scaled integers**: `[20644:20974]`, not
`[206.44:209.74]`.

### Empty panes are the escape hatch for uneven gutters

Two consecutive `+++` with nothing between them render as a fixed-width column
with no children. That is how you express a row whose columns are *not* evenly
spaced — model each gutter as its own pane:

```markdown
:: content pane_gap=0 [27774:7341:48630:5270:28548]
<premium.png | width=277.74 height=283>
+++
+++
<hr.png | width=486.3 height=285.5>
+++
+++
<splits.png | width=285.48 height=287.5>
```

### Per-image vertical offsets

Images inside a row all start at the band's top. When the source staggers them
vertically, **bake a transparent top margin into the asset itself** rather than
reaching for a layout feature that does not exist.

> [!WARNING]
> **A slide's `::` line *is* the first `===` section's `::` line.** Any `pad_*`
> you put on it is applied twice — once as slide padding, once as section
> padding. This silently shrank one slide's column pitch from 357.88 to 334.3.
> If the first band needs its own padding, make the slide line theme-only
> (`:: as: name`) and start the real content in the next band; an empty leading
> section parses fine and contributes zero height.

---

## 11. Splitting Decoration from Content

The rule of thumb, and the one the deck owner asked for explicitly: **if it is
not words, it is decoration.** A card, a pill, a gradient ring, a search-box
chrome, a plate of rounded rectangles — all of it belongs in the background
document. Only the text that a reader would retype belongs in `slides.md`.

Worked examples from the ADS26 port:

| Slide | Background document holds | `slides.md` holds |
|---|---|---|
| "Learn more" | the pill, its gradient ring, black fill and magnifier glyph | the URL typed into it |
| "SFT bento-box" | the pale-blue fill, six rounded gradient cards, the E2E pill | the screenshots and their captions |
| Every dark slide | the gradient plate and the baked `#AndroidDevSummit` footer | nothing |

This keeps the markdown readable and lets slides that look alike share one
theme preset. Nine of the ten ported slides reuse one of eight presets.

### Where the indent lives matters

A theme's `[layout] pad_left` indents the **whole slide column**, which squeezes
every band's absolute geometry. To indent only the title, put the pad on the
heading:

```toml
[heading.1]
pad_left = 31.2
pad_top = 30.36
```

---

## 12. Fonts

This is the single most likely thing to make a numerically-good port look
wrong, because **nothing warns you when it goes wrong**.

Refract resolves a font family through the *system* font list. Name a family
that is not installed and the text silently renders in the deck's default face:
the geometry is correct, the metrics are close enough that the pixel diff
barely moves, and the letterforms are simply a different typeface. On the
ADS26 port this hid behind a respectable mean diff of 3.55 until the crops were
actually looked at.

First step on any new deck: list the typefaces the source asks for, and check
each one against `/Library/Fonts` and `~/Library/Fonts`.

```sh
python3 -c "
import re
x = open('/tmp/<deck>_x/ppt/slides/slide9.xml').read()
print(sorted(set(re.findall(r'typeface=\"([^\"]+)\"', x))))
"
```

For fonts that *are* freely available, `scripts/install_deck_fonts.sh` pulls
them straight from the `google/fonts` repository into `~/Library/Fonts`. Extend
it rather than installing by hand, so the next checkout renders identically.

### Families with no bold face are not synthetically emboldened

PowerPoint's `b="1"` is a request, and PowerPoint (and the PDF exporter) will
fake a bold by smearing the outline when the family has no bold face. Refract
will not. Instrument Serif ships Regular and Italic only, so the ADS26 card
captions render regular where the source shows faux-bold.

Keep the `weight = 700` in the theme anyway — it records what the source
actually says, and it will render correctly on a host that does synthesize.
Just do not spend time chasing the residual diff it leaves.

### Variable fonts collapse to their default instance

`Unbounded[wght].ttf` and `RobotoMono[wght].ttf` are variable fonts. They load
and render fine, but the `weight` in the theme has no effect — you get the
default instance whatever you ask for. Setting Roboto Mono to 300 instead of
400 changed the rendered pixels not at all. If you genuinely need a specific
weight, instance the variable font to a static TTF first.

### Substituting a font you cannot ship

Some source fonts are not distributable — ADS26 uses **Google Sans Mono**, which
is internal. Pick the closest public face, and say so in a comment at the point
of use:

```toml
# The source deck sets "Google Sans Mono", which is not publicly distributable.
# Roboto Mono is the closest freely available stand-in; the important property
# is that it is monospaced, since the proportional fallback reads as a
# different design entirely.
[heading.6]
family = "Roboto Mono"
```

Choose the substitute on the property that carries the meaning. Here that is
*monospaced* — a proportional fallback destroyed the "technical label" reading
of the text, while a different mono preserves it.

### Naming a family in a theme

A font family can only be set per heading level; there is no top-level
`title_font` key in a theme TOML.

```toml
[heading.1]
family = "Unbounded"
```

---

## 13. Traps and Hard Limits

> [!CAUTION]
> **Any JSON string value beginning with `#` breaks the `json2rc` converter.**
> It tries to parse it as a hex colour and dies with
> `For input string: "AndroidDevSummit" under radix 16`. Text like
> `#AndroidDevSummit` has to be baked into an image.

- A background JSON document **must include `"profiles": 512`** in its header or
  its text components are rejected outright.
- Box components use `horizontalAlignment` / `verticalAlignment`. There is no
  `contentAlignment` key.
- There is **no letter-spacing support**, and the rendered Google Sans is about
  **1.8 % wider** than the same font in the source PDF. On slides with very
  large type this is the entire remaining pixel difference. Shrinking the font
  to compensate is a worse trade than living with it.
- Markdown here has **no comment syntax**, and the `::` line must be the first
  non-blank line of a slide. A stray `#` line at the top of `slides.md` becomes
  a slide title.
- `rm -rf <deck>/out` forces a full rebuild; otherwise stale `.rc` files are
  reused and your edit appears to have done nothing.
- `--json-only` leaves the intermediate JSON in `<deck>/out/json/` instead of
  cleaning it up. Dumping that tree is by far the fastest way to see what the
  layout engine actually computed — pane widths, band heights, emitted padding.

---

## 14. The Tuning Loop

Three small scripts carried the whole conversion:

1. **A page renderer.** Rasterise the source PDF to exactly the deck's pixel
   size (`pymupdf` at 1600×900) once, into `/tmp/<deck>_pages/page_NNN.png`.
2. **A differ.** Render each `.rc` with `prebuilt/rc2image`, diff it against its
   source page with `PIL.ImageStat`, and print one mean-difference number per
   slide. A single scalar per slide is what lets you tell instantly whether an
   edit helped. For reference, on the ADS26 port: **< 3 is indistinguishable by
   eye, 3–6 is a font-metric difference, > 20 means something is structurally
   wrong** (a 22.9 turned out to be a slide-wide `pad_left` shifting every
   band).
3. **An ink-band profiler.** Print the runs of rows (or columns) that contain
   dark pixels, for the reference and the render side by side. Comparing two
   lists of `(start, end)` pairs localises a mismatch to a specific band in
   seconds, where staring at a side-by-side image does not.

Also keep a **side-by-side PNG** per slide — stack reference above render — and
actually look at it. The differ will happily report a good score for a slide
whose font is wrong.

And once the geometry is settled, do one **zoomed crop pass over the text**:
cut the same text band out of the reference and the render, paste them one
above the other, and blow the result up. A whole-slide side-by-side is too
small to tell Instrument Serif from Google Sans at 26 px, or a proportional
face from a monospaced one in a 14 px label. Both substitutions survived every
other check on this deck and were only caught this way.
