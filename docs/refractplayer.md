# refractplayer

A deck is markdown, but you need neither a text editor to write it nor a terminal to change
it. Write the talk here, then give it here.

This page has two halves: a **[tutorial](#tutorial-write-a-talk-without-a-terminal)** that
builds a small talk in the player's own windows, and a **[reference](#the-windows)** for each
window. Both use [`examples/tutorial/`](../examples/tutorial), so you can open every screen
you see here.

To build the same deck from a terminal instead, read
**[the command-line tutorial](tutorial-cli.md)**.

---

## Tutorial: write a talk without a terminal

### Start with nothing

```sh
prebuilt/refractplayer
```

<img src="images/start-window.png" width="560" alt="The start window: Open a deck, New deck, and a list of recent decks">

**New deck…** asks where to put it, then writes a starter `slides.md` — a few real slides
rather than an empty file, so you have something to change instead of something to invent.
**Open a deck…** takes any folder with a `slides.md` in it. Underneath sit the decks you opened
before; the player remembers them between runs.

Name a deck on the command line and it goes straight past all this:

```sh
prebuilt/refractplayer examples/tutorial
```

### The deck itself

<img src="images/slide-window.png" width="700" alt="The slide window showing the title slide">

The room sees this window and nothing else. Arrows move, `Space` advances, `H` brings up the
key card, `F` fills the screen, `B` blanks it. Every other part of the player is a second
window, and none of them touch this one.

Point it at a deck folder and it finds `out/` underneath — and **builds it if nothing is
there**, so a deck you have only written is one command away from a talk.

### See the whole talk: `V`

<img src="images/deck-view.png" width="800" alt="The deck view: every slide as a card, with section bars beneath">

Every slide at once. The bars under the rows are **sections**, and the sub-decks an
`:: include` pulled in: click one to fold it away, drag one to move the whole run. Drag a
single card and the player rewrites the markdown behind it and rebuilds the deck. This is not
a preview of a reorder — it is the reorder.

`N` adds a slide, `⌫` twice deletes one, `shift`+`D` duplicates, `J` joins two, `cmd`+`Z` takes
any of it back. A card shows whether that slide has narration, and a `note` mark whether it has
speaker notes.

### Change a slide: `E`

<img src="images/editor.png" width="480" alt="The slide editor showing the title slide's markdown">

The markdown behind whatever is on screen. It follows the deck as you move, so you pick what to
edit by walking to it. `cmd`+`S` saves; the deck then rebuilds and reloads underneath.

The tabs at the top aim it at one **slide**, the whole **slides.md**, or the deck's
**settings.toml**. The theme was the last thing here that needed a terminal.

### It knows the words

Type `::` and pause. It offers what may follow, and says what each word does:

<img src="images/menu-meta.png" width="480" alt="The completion menu after typing a colon-colon, listing slide types with explanations">

That list is not the player's idea of refract's grammar. It comes out of refract itself, so
the menu offers every slide type that exists and no word the build would reject.

Type `<` and pause. Now it offers **the deck's own files**, and shows you the one under the
cursor. The engine that plays the deck draws the preview, so a document or a clip arrives as a
picture of itself:

<img src="images/menu-include.png" width="480" alt="The include menu listing card.json and logo.png, with a rendered preview of the selected document">

Past a `|` it offers what you can tell that embed — and only what would do something to *that*
kind of file:

<img src="images/menu-options.png" width="480" alt="The options menu after a pipe, listing crop, fit, ratio, title and stagger">

### Rebuild it: `M`

<img src="images/build-panel.png" width="260" alt="The build panel: refract's options, a Rebuild button, and a watch switch">

refract's options, a button, and a column that sits against the deck view. **Watch** rebuilds
whenever the markdown changes, so the deck follows the file and you press nothing. Each build
reports what it did: how many slides it rebuilt, and how many it reused.

### See what the deck is made of: `I`

<img src="images/assets.png" width="640" alt="The asset window listing card.json and logo.png with previews and which slides use them">

Everything under `includes/`, with a picture of it and the slides that use it. The window
marks anything nothing uses as unused, and an `includes/` folder gathers plenty of that over the life of a
talk. Removing a file moves it to `out/.trash/`; it deletes nothing.

### Then give the talk: `P`

<img src="images/presenter.png" width="700" alt="The presenter window: clock, timer, the current and next slides, notes, and a progress bar">

The wall clock, the talk timer, the slide that is up, the one coming next, and your notes. The
"now" pane holds the **frame the projector is showing this moment** — part way through an
animation, part way through a video, whatever is there.

The timer reads `10:00` because the deck's three `:: section duration=` lines add up to ten
minutes. That plan also marks the progress bar with where you should be, so you can pace the
talk the first time you give it, with no rehearsal to measure against.

---

## The windows

| | | |
|---|---|---|
| [Presenter](#presenter) | `P` · `cmd`+`1` | clock, timer, notes, what's next, pace |
| [Deck view](#deck-view) | `V` · `cmd`+`2` | every slide; reorder, fold, add, delete |
| [Slide editor](#slide-editor) | `E` · `cmd`+`3` | the markdown, with a completion menu |
| [Build panel](#build-panel) | `M` · `cmd`+`4` | refract's options and a Rebuild button |
| [Captions](#captions) | `C` · `cmd`+`5` | the narration, word by word |
| [Navigator](#navigator) | `Tab` · `cmd`+`6` | the deck as a list, to jump |
| [Assets](#assets) | `I` · `cmd`+`7` | what is in `includes/`, and what uses it |

The **Window** menu lists every panel and ticks the ones that are open. Each panel remembers
where you put it, deck by deck.

### Presenter

<img src="images/presenter.png" width="700" alt="The presenter window">

Clock, talk timer, the live frame, the next slide as a still, notes, and a progress bar with a
tick per section. Blank the room's screen and this window keeps the slide, with a mark saying
the audience cannot see it.

The **ghost marker** on the progress bar says where you should be by now. It follows a
rehearsal if you have one, and the deck's `:: section duration=` plan if you have not. The plan
draws quieter than the rehearsal, because what a talk took and what it should take are two
different claims. Under the timer: `2:15 behind`, `0:40 ahead`, or `on pace`.

The button at the foot records the current slide's narration again, and leaves the rest of the
talk alone.

Full detail: [player/README.md § the presenter window](../player/README.md#the-presenter-window).

### Deck view

<img src="images/deck-view.png" width="800" alt="The deck view">

| | |
|---|---|
| drag a card | move that slide |
| drag a bar | move the whole section or sub-deck |
| click a bar | fold it away · `Z` folds the run at the cursor, `shift`+`Z` the whole deck |
| `Enter`, double-click | put that slide on the projector |
| `N` / `shift`+`N` | add a slide after / before |
| `shift`+`D`, `J`, `⌫` | duplicate, join with the next, delete (twice) |
| `cmd`+`Z` / `shift`+`cmd`+`Z` | undo / redo |
| `/` | find a slide by name |

Every one of those rewrites `slides.md` and rebuilds the deck. The narration index and the
rehearsal trace travel with the slides, in the same write.

### Slide editor

<img src="images/editor.png" width="480" alt="The slide editor">

`cmd`+`S` saves; auto-save waits until you stop typing. `cmd`+`Enter` cuts a slide in two at the
caret. Click again and again to take a word, then the line, then the paragraph; hold `option`
and the selection becomes a **rectangle** instead of a run, which is how you take a column out
of a table or the indent down a list.

The menu completes `::` lines, `<includes>` and their options — see
[the tutorial above](#it-knows-the-words) and
[player/README.md § completing a `::` line](../player/README.md#completing-a--line).

### Build panel

<img src="images/build-panel.png" width="260" alt="The build panel">

A column that sits against the deck view or the presenter. It reads its options from the way
the deck was built rather than from defaults, so it opens telling the truth. **Watch**
rebuilds on every change. Builds run on a worker thread, so the window stays alive while
refract works.

### Assets

<img src="images/assets.png" width="640" alt="The asset window">

Each row carries a picture of what it holds: the player decodes an image itself and hands a
document or a clip to the engine to draw. The pane on the right shows the one you are on,
large, with its path, its size and **every** slide that uses it — which is the question you
want answered before you throw anything away. `⌫` twice moves it to `out/.trash/`.

### Captions

`C`. Your recorded narration, transcribed and lined up with the audio, lighting each word as
you speak it. Where the transcription heard you wrong, correct it here. Run `--transcribe`
first.

### Navigator

`Tab` or `G`. The deck as a list, laid over the slide — or over the presenter window when you
have one open, so it never reaches the projector. `/` filters by name; `Enter` goes.

---

## Presenting

| | |
|---|---|
| `→` `Space` `Page Down` | next |
| `←` `Page Up` | previous |
| `shift`+`→` / `←` | next / previous **section** |
| a number, then `Enter` | jump to that slide |
| `F` | fullscreen |
| `B` | blank the room's screen (`shift`+`B` white) |
| `T` | start / pause the talk timer |
| `H` | the key card |
| `Q` `Esc` | quit |

With two screens, `--display 1` throws the slides on the second monitor and keeps the presenter
window on the first.

## Rehearsing

```sh
prebuilt/refractplayer mytalk --record              # time the run
prebuilt/refractplayer mytalk --record-audio        # ...and record the narration
prebuilt/refractplayer mytalk --transcribe          # turn that into captions
prebuilt/refractplayer mytalk --auto-voice          # play it back, slide by slide
prebuilt/refractplayer mytalk --web site/           # ...or as a web page
```

A recorded run writes `timing.json` beside the slides, and every later run reads it. That file
is where the presenter gets your pace and its ghost marker. The narration goes to one wav per
slide in `<deck>/voice/`, and it **follows the slides through a reorder**: the trace names the
block of markdown a slide came from, not its position and not its filename.

Full detail: [player/README.md § rehearsing](../player/README.md#rehearsing).

## Exporting

```sh
prebuilt/refractplayer mytalk --pdf talk.pdf        # one page per slide
prebuilt/refractplayer mytalk --images shots/       # one PNG per slide
```

`refract.py --pdf` and `--images` run these.

## Everything else

[player/README.md](../player/README.md) holds the full reference: every flag, every key, and
the reasoning behind the parts that are not obvious.
