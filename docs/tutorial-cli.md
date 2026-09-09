# Tutorial: a deck from the command line

Fifteen minutes, one file, and a talk you can present. Everything here runs against
[`examples/tutorial/`](../examples/tutorial), which is the deck this page builds — read along,
or type it out and compare.

If you have not run refract before, start with
[Getting started](../README.md#getting-started) and `python3 refract.py --check`.

## 1. A deck is a folder with a slides.md in it

```sh
mkdir coffee && cd coffee
```

That is the whole ceremony. No project file, no config — a `settings.toml` is optional and
comes later.

## 2. Write two slides

Put this in `slides.md`. Slides are separated by `---` on a line of its own:

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

Two things to notice. The `::` line sets what kind of slide this is — `title` is centred and
large; leave it out and you get `content`, which is what the second slide is. And the first
`# heading` is the slide's title, with an `*italic*` line under it becoming a subtitle.

## 3. Build it

```sh
python3 ../refract.py .
```

refract reads `slides.md`, lays each slide out with the RemoteCompose engine, and writes one
`.rc` file per slide into `out/`:

```
out/01_making_coffee.rc
out/02_what_to_buy.rc
out/deck.json            ← the outline: titles, sections, where each slide came from
```

Building again only rewrites what changed. There is a cache keyed on the *generated document*,
so editing one slide rebuilds one slide.

## 4. Look at it

```sh
../prebuilt/refractplayer .
```

Arrow keys move, `H` shows the key card, `Q` quits. The player takes the deck folder and finds
`out/` underneath — and builds it first if it is not there, so step 3 is optional once you are
used to it.

## 5. Add the pieces a talk actually needs

### Sections

A `:: section` slide is a divider, and it numbers itself:

```markdown
---

:: section duration=3m
# Part One: The Beans
```

`duration=` is how long that part should take — `3m`, `90s`, `1h30m`, or a bare number for
minutes. Add them up and you have the talk's planned length, which the player counts down
against and paces you with. It is optional; without it you get no plan and no ghost marker.

### An image

Anything in `includes/` can be dropped on a slide by name, in angle brackets:

```sh
mkdir includes && cp ~/Pictures/beans.jpg includes/
```

```markdown
# The ratio
*One part coffee to sixteen parts water*

<beans.jpg>
```

The extension can be left off — `<beans>` finds it. The same syntax embeds a video
(`<clip.mp4>`), a web page (`<https://example.com>`) or a prebuilt RemoteCompose document
(`<card.json>`), which is drawn live by the engine rather than pasted in as a picture.

### Speaker notes

Everything after a `???` line is yours, not the audience's:

```markdown
# The ratio

???
The ratio is the only number worth remembering. Everything else is taste.
```

They show in the presenter window, and in `out/notes.md`.

### Code

Fenced blocks are syntax-highlighted:

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

## 6. Work with it running

```sh
python3 ../refract.py . --watch
```

Rebuilds whenever `slides.md`, `settings.toml` or `includes/` changes. Leave it running in one
window and the player in another, and the deck reloads under you.

## 7. Give it a look

A `settings.toml` beside `slides.md` sets the theme — colours, fonts, the slide size,
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

There is a lot of it; [the settings reference](../README.md#settingstoml) has the whole list.
Nothing is required, and a deck with no `settings.toml` uses the defaults you have been
looking at.

## 8. Hand it to someone

```sh
python3 ../refract.py . --pdf coffee.pdf       # one page per slide
python3 ../refract.py . --images shots/        # one PNG per slide
../prebuilt/refractplayer . --web site/        # a web player: slides, narration, captions
```

## Where to go next

- **[Authoring in the player](refractplayer.md)** — the same deck, edited and presented in
  refractplayer's own windows, without going back to a terminal.
- **[The markdown grammar](../README.md#markdown-grammar)** — every block type, in one table.
- **[Transitions and magic move](../README.md#transitions--magic-move)** — how slides move,
  and how to make an element travel between them.

## The commands used here

| | |
|---|---|
| `refract.py .` | build the deck in this folder |
| `refract.py . --watch` | rebuild whenever anything changes |
| `refract.py . --force` | rebuild every slide, ignoring the cache |
| `refract.py . --json-only` | stop at the component JSON (no JVM needed) |
| `refract.py --check` | what this machine has, and what it is missing |
| `refractplayer .` | play it |
