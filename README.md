# refract

Turn a simple markdown deck into [RemoteCompose](https://developer.android.com/jetpack/androidx/releases/compose-remote)
slides you can play in the C++ desktop viewer or the TypeScript player.

```
slides.md  ──►  refract.py  ──►  component JSON  ──►  json2rc  ──►  .rc
```

refract emits the **androidx component JSON** format and lets the **real
`remote-core` library** do the serialization. Python never touches the wire
format; layout is done by the RemoteCompose engine via components, not pixel math.

## Deck layout on disk

```
<deck>/
  slides.md          # the deck
  includes/          # images, sub-decks, .rc / .json resources
  out/               # generated .rc files          (created)
  out/json/          # generated .json documents     (created)
```

## Setup

`prebuilt/` ships ready-to-run tools (checked in because json2rc currently
carries local code):

- `prebuilt/json2rc/bin/json2rc` — JSON → `.rc` converter
- `prebuilt/rcviewer` — interactive C++ viewer
- `prebuilt/rc2image` — headless `.rc` → PNG renderer

To rebuild json2rc from the local androidx checkout (JDK 21):

```sh
cd json2rc && ./gradlew installDist          # -PandroidxRemote=/path to override
```

## Use

```sh
python3 refract.py examples/deck            # writes examples/deck/out/*.rc (+ out/json/*.json)
python3 refract.py examples/deck --debug    # outline every component with a 1px red border
```

Options: `--width/--height` (default 1600×900), `--json-only`, `--json2rc PATH`.

View a deck (directory = slideshow; N/P to step, R to reload):

```sh
prebuilt/rcviewer examples/deck/out 1600 900
```

## Markdown grammar

```markdown
:: title
# refract
Markdown to RemoteCompose

---

:: include : intro          # splice includes/intro/slides.md here

---

:: content
# Content types
- bullet lists
  - with sub-bullets

```kotlin
fun greet(name: String) { println("Hello, $name") }
```

<logo.png>                  # image include
<card.json>                 # RemoteCompose JSON spliced inline
```

- `---` separates slides (one `.rc` each).
- `:: <type> : <parameters>` right after the separator sets the slide metadata.
- The first `# heading` is the title; the rest is content blocks in order.

### Slide types (`<type>`)

| Type      | Layout                                              |
|-----------|-----------------------------------------------------|
| `title`   | large title centered on the slide                   |
| `section` | title centered                                      |
| `content` | default — title at top, content below (left-aligned)|
| `include` | splice another deck from `includes/<param>/slides.md` (placeholder if missing) |

### Content blocks

| Block        | Markdown                                   |
|--------------|--------------------------------------------|
| text         | plain paragraphs                           |
| bullet list  | `- item`, indent two spaces per sub-level  |
| code         | fenced ```` ``` ```` block (monospace)     |
| image        | `<name.png>` — embedded **inline** in the `.rc` at build time |
| json include | `<name.json>` — a RemoteCompose JSON document spliced inline  |
| rc include   | `<name.rc>` — a prebuilt document used as a whole passthrough slide |

## Notes

- **Images** are authored as separate files under `includes/` but embedded inline
  into each `.rc` at conversion time (`json2rc` loads the file, re-encodes to PNG,
  and hoists the bitmap to the head of the document). The androidx JSON format has
  no path→image support yet, so json2rc adds an `image` component for this.
- The embedded `DATA_BITMAP` is hoisted **before** the root layout component
  (op order `HEADER → DATA_BITMAP → LAYOUT_ROOT → …`) so players that load bitmap
  data from the head of the stream find it.
- **Images (temporary canvas approach):** the C++ viewer doesn't paint the
  `LAYOUT_IMAGE` component (its `LayoutImage` is a read-only stub), but it does paint
  canvas bitmap draws. So an image block is emitted as a fixed-size `canvas` that
  `addbitmap`s the file and `drawbitmap`s it into a computed, aspect-preserving
  ("fully contained") rect — a rough equivalent of the image component that renders
  in the C++ viewer today. When `LAYOUT_IMAGE` painting lands in the viewer this can
  revert to a plain `image` component (still supported by json2rc).
- **Debug borders** use a solid 1px red border — the `border` modifier has no dash
  option today.
