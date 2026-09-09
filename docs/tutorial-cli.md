# Tutorial: a deck from the command line

One file, fifteen minutes, a talk you can give. Every command here runs against
[`examples/tutorial/`](../examples/tutorial), the deck this page builds — read along, or type
it out and compare.

New to refract? Start at [Getting started](../README.md#getting-started), then run
`python3 refract.py --check`.

## 1. A deck is a folder with a slides.md in it

```sh
mkdir coffee && cd coffee
```

That is all of it. No project file, no config. A `settings.toml` can come later, or never.

## 2. Write two slides

Put this in `slides.md`. A `---` line of its own ends one slide and starts the next:

```markdown
:: title
# Making Coffee
*A very short talk*

---

# What to buy
- Whole beans, not ground
- Roasted **within the last month**
- Something you can buy again
```

Two things to notice. The `::` line says what kind of slide this is: `title` centres the text
and makes it large. Leave the line out and you get `content`, like the second slide. And the
first `# heading` is the slide's title; an `*italic*` line under it becomes the subtitle.

## 3. Build it

```sh
python3 ../refract.py .
```

refract reads `slides.md`, hands each slide to the RemoteCompose engine to lay out, and writes
one `.rc` file per slide into `out/`:

```
out/01_making_coffee.rc
out/02_what_to_buy.rc
out/deck.json            ← the outline: titles, sections, where each slide came from
```

Build again and it rewrites only what changed. The cache keys on the document refract
generates, not on the markdown, so editing one slide rebuilds one slide.

## 4. Look at it

```sh
../prebuilt/refractplayer .
```

Arrow keys move, `H` shows the key card, `Q` quits. Hand the player a deck folder and it finds
`out/` underneath — and builds it first if it finds nothing there. Once you know that, you can
skip step 3.

## 5. Add the pieces a talk needs

### Sections

A `:: section` slide is a divider, and it numbers itself:

```markdown
---

:: section duration=3m
# Part One: The Beans
```

`duration=` says how long that part should take: `3m`, `90s`, `1h30m`, or a plain number for
minutes. The player adds them up, counts the talk down against the total, and tells you whether
you are ahead or behind. Leave it out and you get no plan.

### An image

Drop anything in `includes/` on a slide by name, in angle brackets:

```sh
mkdir includes && cp ~/Pictures/beans.jpg includes/
```

```markdown
# The ratio
*One part coffee to sixteen parts water*

<beans.jpg>
```

Leave the extension off and `<beans>` still finds it. The same brackets take a video
(`<clip.mp4>`), a web page (`<https://example.com>`) and a RemoteCompose document
(`<card.json>`) — and the engine draws that document live on the slide, rather than pasting a
picture of it.

### Speaker notes

Everything after a `???` line is yours, not the audience's:

```markdown
# The ratio

???
The ratio is the only number worth remembering. Everything else is taste.
```

The presenter window shows them, and so does `out/notes.md`.

### Code

refract colours fenced code by language:

````markdown
```python
def brew(beans_g, water_g=None):
    return f"{beans_g}g beans, {water_g or beans_g * 16}g water"
```
````

### Two columns

`+++` splits a slide into panes; `:: split` lays them out side by side:

```markdown
:: split
# Two things to notice
- Sweetness arrives first
- Bitterness is a timing problem

+++

- Sour means under-extracted
- Grind finer, or wait longer
```

## 6. Leave it building

```sh
python3 ../refract.py . --watch
```

It rebuilds whenever `slides.md`, `settings.toml` or `includes/` changes. Keep it in one
window and the player in another, and the deck reloads under you as you type.

## 7. Change how it looks

A `settings.toml` beside `slides.md` sets the colours, the fonts, the slide size and the
transitions:

```toml
[theme]
preset     = "dark"        # dark | light | midnight | warm | mono
background = "#FF141A2E"
accent     = "#FF4FC3F7"

[transition]
style = "push"             # push | push-up | slide | slide-left | slide-up | none

[font]
heading = 76
body    = 44
```

There is a lot of it — [the settings reference](../README.md#settingstoml) lists all of it.
You need none of it. A deck with no `settings.toml` uses the defaults you have been looking
at.

## 8. Hand it to someone

```sh
python3 ../refract.py . --pdf coffee.pdf       # one page per slide
python3 ../refract.py . --images shots/        # one PNG per slide
../prebuilt/refractplayer . --web site/        # a web player: slides, narration, captions
```

## Where to go next

- **[Writing a talk in the player](refractplayer.md)** — the same deck, written, reordered and
  given in refractplayer's own windows, without a terminal.
- **[The markdown grammar](../README.md#markdown-grammar)** — every block type, in one table.
- **[Transitions and magic move](../README.md#transitions--magic-move)** — how slides move, and
  how to send an element travelling from one to the next.

## The commands used here

| | |
|---|---|
| `refract.py .` | build the deck in this folder |
| `refract.py . --watch` | rebuild whenever anything changes |
| `refract.py . --force` | rebuild every slide, ignoring the cache |
| `refract.py . --json-only` | stop at the component JSON; skips the Java step |
| `refract.py --check` | what this machine has, and what it lacks |
| `refractplayer .` | play it |
