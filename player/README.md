# refractplayer

A presenter's player for refract decks.

```sh
player/build.sh                                   # build (once); binary -> prebuilt/refractplayer
prebuilt/refractplayer examples/deck/out --presenter
```

Playback is not reimplemented here. It comes from **`rcplayer`**, the library in the
RemoteCompose `players/cpp` tree that also powers `rcviewer` — same engine, same
Metal/Skia path, same video, web-page and sub-document embeds, same touch handling. This
project is the part a viewer has no reason to have: a second window for the person
talking, a way to get somewhere else in the deck, and a clock.

```
players/cpp/lib/rcplayer   playback runtime  ──┬── players/cpp/apps/viewer   rcviewer
                                               └── refract/player            refractplayer
```

Pulling the upstream tree gets you every engine fix; nothing is vendored or forked.

## What it adds

**A presenter window** (`--presenter`, or `P`). Wall clock, talk timer, the slide you are
on, the one coming next, the speaker notes, how long you have been on this slide, and a
progress bar with a tick per section. The "now" pane is the real frame the projector is
showing, sampled a few times a second — mid-animation, mid-video, whatever is actually up
there. Blank the room's screen and the presenter keeps showing the slide, with a marker
saying the audience cannot see it.

The "next" still is a full render of that slide, which is not cheap: a slide's opening
transition animates *from* the previous one, so the document has to be stepped through real
frames before it shows the right slide. That work is spread across frames on a small
per-frame budget, and held off until the slide you just put up has finished animating in —
so it never lands on a transition. A still that is not finished yet shows "rendering…"
instead of stalling the deck to wait for it.

Embedded content previews too: `rc:` sub-documents render for real and `video:` embeds show
a poster frame. An embedded **web page** cannot be drawn off-screen at all — it is a native
`WKWebView` over the window — so it previews as a dashed frame labelled with where the page
comes from (the host, or the folder for a local one). The real page is live once the slide
is up.

**A navigator** (`Tab` or `G`). The whole deck as a list, sections called out, with a
preview and the notes of whatever row you are on. Enter jumps. It draws on the presenter
window whenever there is one — a navigator projected onto the wall defeats the point.

**A talk timer**. Starts itself when you leave the title slide. With `--duration 25m` it
becomes a **countdown** — the big number is the time left, with the elapsed time small
underneath — and it turns amber in the last fifth, red once you are over, where it keeps
running negative (`-2:30`) to show by how much. Without a duration it counts up.

**Jumping**. Type a slide number and press Enter. `Shift`+`←`/`→` steps by section.
`Home`/`End` go to the ends.

**Blanking** (`B` black, `W` white) and **fullscreen** (`F`, or `--fullscreen`).

## Keys

| Key | |
|---|---|
| `→` `Space` `PgDn` `↓` | next slide |
| `←` `PgUp` `↑` `Backspace` | previous slide |
| `Shift`+`←` / `→` | previous / next section |
| `Home` `End` | first / last slide |
| digits then `Enter` | jump to a slide number |
| `Tab` `G` | navigator |
| `P` | presenter window |
| `T` / `Shift`+`T` | start-pause the timer / reset it |
| `B` `W` | blank the screen to black / white |
| `F` | fullscreen |
| `A` | pause the slide's animation (and its video) |
| `R` | reload the slide |
| `D` | debug overlay |
| `S` | screenshot to `/tmp/refractplayer.png` |
| `H` | key card |
| `Esc` | back out of whatever is on top — never quits |
| `Q` | quit |

`Esc` deliberately does not quit: it closes the help card, then a pending jump, then
un-blanks, then leaves fullscreen. Losing the deck to a stray `Esc` mid-talk is not worth
the convenience.

## Options

```
refractplayer [options] <deck-out-dir | slide.rc | deck.zip> [width height]

  --presenter        open the presenter window
  --fullscreen, -f   start fullscreen
  --display <n>      monitor for the slides (0-based); the presenter window
                     opens on the next one
  --duration <t>     planned talk length: 25m, 45 (minutes), 1h30m, 90s
  --cpu | --metal    rendering backend (default: Metal on macOS)
  --auto <sec>       advance every N seconds
  --auto-voice       advance when a slide's voice-over finishes

  --pdf <out.pdf>    write the deck to a PDF and exit
  --pdf-delay <sec>  how long each slide animates before capture (default 2)
```

## Exporting a PDF

```sh
prebuilt/refractplayer mytalk/out --pdf mytalk.pdf
```

One page per slide, no window opened. `.rc` slides go through Skia's PDF backend, so text
and shapes stay vector and selectable rather than being rasterised. Videos contribute a
first frame, embedded `rc:` documents render in full, and an embedded web page becomes the
same labelled frame the presenter preview shows. Slides with speaker notes get a taller
page with the notes in a panel underneath.

`--pdf-delay` is how far into its animation each slide is taken before capture — the
default of 2 seconds is enough that a slide which animates in is not caught mid-entrance.

The exporter is `rcplayer`'s, so this produces the same PDF as `rcviewer --pdf`.

The two-screen setup:

```sh
prebuilt/refractplayer mytalk/out --display 0 --fullscreen --presenter --duration 30m
```

## Where the deck outline comes from

`refract.py` writes **`out/deck.json`** beside the slides — titles, slide types, section
numbers, which slides have notes. That is what fills the navigator and the presenter's
labels. Speaker notes come from the per-slide `out/<slide>.rc.notes` sidecars.

Neither is required. Without a manifest the player falls back to the filenames
(`07_a_graph.rc` still reads as "A graph") and treats every slide as its own jump target;
you lose section grouping, not playback. A deck built before `deck.json` existed just
needs a re-run of `refract.py`.

Zip decks work the same way, as long as `deck.json` and the `.notes` files are in the
archive.

## Building

`build.sh` finds the RemoteCompose tree at `../remotecompose-experiments/players/cpp`
(the two repos checked out side by side). Otherwise:

```sh
RCX_DIR=/path/to/players/cpp player/build.sh
# or
cmake -B player/build -S player -DRCX_DIR=/path/to/players/cpp
cmake --build player/build -j
```

Skia is a large fetch. When the rcX tree has already been built once, `build.sh` reuses
the archives it downloaded rather than pulling a second copy.

## Layout

| File | |
|---|---|
| `src/main.cpp` | command line, window, event loop, key bindings |
| `src/Deck.{h,cpp}` | the deck: manifest, titles, sections, notes |
| `src/Presenter.{h,cpp}` | the second window |
| `src/Navigator.{h,cpp}` | the navigator, help card, pending-jump chip |
| `src/Thumbs.{h,cpp}` | off-screen slide stills, cached |
| `src/Ui.{h,cpp}` | text, boxes and images for the chrome |
| `src/App.h` | presenter state: talk clock, blanking, overlay state |
