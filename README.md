# refract

Turn simple markdown into [RemoteCompose](https://developer.android.com/jetpack/androidx/releases/compose-remote)
slides you can play in the C++ desktop player or the TypeScript player.

```
markdown  ──►  refract.py  ──►  component JSON  ──►  json2rc  ──►  .rc
```

refract emits the **androidx component JSON** format and lets the **real
`remote-core` library** do the serialization. Python never touches the wire
format; layout is done by the RemoteCompose engine via components
(Column / Text), not pixel math.

## Layout

- `refract.py` — markdown → RemoteCompose component JSON (pure Python, stdlib only)
- `json2rc/` — a tiny Gradle/Java CLI that converts JSON → binary `.rc` using
  `RemoteComposeJsonParser`. It compiles the androidx `remote-core` and
  `remote-creation-core` sources straight from a local checkout. When the
  upstream json2rc tool lands, this can be swapped for it.
- `examples/deck.md` — sample input

## Setup

Build the converter once (needs JDK 21 and a RemoteCompose checkout):

```sh
cd json2rc
./gradlew installDist
```

By default it mirrors `~/androidx/frameworks/support/compose/remote`. Point it
elsewhere with `-PandroidxRemote=/path/to/compose/remote`.

## Use

```sh
python3 refract.py examples/deck.md -o out
```

This writes `out/NN_title.json` and `out/NN_title.rc`, one pair per slide.
Open the `.rc` files in `RemoteComposeDesktop` or the TypeScript player.

Options:

- `--width` / `--height` — slide size (default 1600×900)
- `--json-only` — stop at JSON (skip json2rc)
- `--json2rc PATH` — explicit path to the json2rc launcher

## Markdown grammar (v1)

Deliberately tiny:

```markdown
:: title
# RemoteCompose, from Markdown
A clean pipeline

---

:: section
# Part One

---

:: content
# A normal slide
Content text for this slide.
More content.
```

- `---` on its own line separates slides (one `.rc` each)
- an optional `:: <type> : <parameters>` line, right after the separator and
  before the title, sets the slide **metadata**. Everything after `::` is
  read as `<type of slide> : <parameters>`.
- the first `# heading` in a slide is the title
- everything else is content, rendered as a single multi-line Text

### Slide types

Selected by the metadata `<type>` (default `content`):

| Type      | Layout                                             |
|-----------|----------------------------------------------------|
| `title`   | cover slide — large title centered on the slide    |
| `section` | section divider — title centered                   |
| `content` | default — title at top, content below, left-aligned |

The parsed metadata is also carried through into each `.json` under a `_meta`
key for reference (the converter ignores it).

Bullets, colors, images, animations, and transitions are intentionally out of
scope for v1 and can be layered on later.
