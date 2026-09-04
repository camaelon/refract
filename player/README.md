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
| `C` | caption window |
| `E` | correct the transcript (in the caption window) |
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

The presenter window has a **play/pause button** beside the clock, doing the same thing as
`T` — which is also what starts an armed recording, so a rehearsal can be driven without the
keyboard.

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
  --auto-voice       advance when a slide's voice-over finishes (plays the wavs
                     a --record-audio run captured)
  --no-sound         never play a slide's voice-over, even where one exists
  --captions         open the close-caption window

  --transcribe       transcribe + align the recorded narration, then exit
  --web <dir>        write a self-contained web player into <dir>, then exit
  --caption-model N  whisper model for transcription (default: base)
  --caption-lang L   language of the narration (default: en)

  --record           time the run into timing.json beside the slides
  --record-audio     also record narration, one wav per slide (implies --record)

  --pdf <out.pdf>    write the deck to a PDF and exit
  --images <dir>     write one PNG per slide into <dir> and exit
  --export-delay <s> how long each slide animates before capture (default 2)
```

## Rehearsing

```sh
prebuilt/refractplayer mytalk/out --record                    # time a run
prebuilt/refractplayer mytalk/out --record-audio --presenter  # time it and record narration
prebuilt/refractplayer mytalk/out --presenter                 # later: run against that trace
```

Recording is **armed** at launch and starts when the talk does — when you press `T` or
click the presenter's play button, or when you advance off the opening slide. Nothing is
written and the microphone stays idle until then, so a trace does not include the minutes
spent getting the projector working. Starting with `T` while the opening slide is up puts
that slide in the trace; starting by advancing past it does not.

`--record` writes **`timing.json`** beside the slides: when each slide came up, measured
from the first one, and how long it held. Slides are keyed by filename rather than position,
so a trace still matches after slides are inserted and renumbered around it. It is written
after every slide change and refreshed every few seconds, so a rehearsal that ends by being
killed still leaves a usable trace.

A recorded run is timed from its **first** slide, not from the first advance — the opening
slide is part of the talk.

Once a trace exists, every later run reads it and the presenter window shows the pace:

- **under the timer** — `2:15 behind`, `0:40 ahead`, or `on pace`, amber when behind and red
  when badly behind. The rehearsal's own time on the current slide is credited, so holding
  its pace holds the number steady; it grows only once you have been on a slide longer than
  the rehearsal was. "On pace" covers 2% of the talk (at least 10s, at most 30s) — a talk is
  not run to the second.
- **on the progress bar** — a second marker for where the rehearsal had got to by now. The
  gap between it and your position *is* how far off you are, which reads faster than a
  number.

### Narration

`--record-audio` also captures the microphone, writing one wav per slide straight into the
deck's voice directory (`<deck>/voice/NN.wav`), which is exactly where voice-over playback
looks.

Capture is **continuous**: the microphone is opened once and only the destination file
changes at a slide boundary. Stopping and restarting a recorder per slide — the obvious
implementation — tears the input device down and back up each time and drops the audio either
side, leaving a hole at every slide change that nothing at playback can put back. Recorded
wavs come out matching their slide's recorded duration to within a few milliseconds. While it records, the presenter window shows the input level as a scrolling waveform
along the bottom, green until it clips and red when it does. A flat line is the failure worth
catching: a talk recorded with the microphone muted looks exactly like one that worked, right
up until you play it back.

Pausing the talk pauses the capture, so a break does not land in the middle of a slide's wav.

A recorded talk plays itself back:

```sh
prebuilt/refractplayer mytalk/out --auto-voice
```

Playback is seamless in the same way. The next slide's audio is opened and readied while the
current one is still being talked over, and the handover happens a moment *before* the
outgoing file ends, with its last few milliseconds allowed to play out underneath — so a
narration recorded across a slide boundary crosses it without a seam. (The player's own
voice-over path spawns `afplay` per slide; process spawn plus device setup is long enough to
hear, so refractplayer plays voice-over itself.)

Each slide plays its narration and advances when it ends. A slide with no wav falls back to
the time the trace recorded for it, and one with neither holds for five seconds (or `--auto`'s
interval, if given) — a recording always has gaps, and `--auto-voice` should not stop dead on
the first one.

`--no-sound` suppresses voice-over playback entirely, wavs present or not. With
`--auto-voice` that gives a silent run at the recorded pace, which is a useful way to watch
the shape of a talk without listening to yourself give it:

```sh
prebuilt/refractplayer mytalk/out --auto-voice --no-sound --presenter
```

It does not affect the audio of a video embedded in a slide — that plays through the
document, not the voice-over path.

Voice-over playback is switched off while recording — otherwise the previous take plays out
of the speakers and straight into the new one.

**Microphone permission.** A command-line tool has no bundle, so macOS attributes the
request to whatever launched it (usually your terminal) and remembers the answer against
that. The prompt appears on the first `--record-audio` run and capture starts as soon as it
is granted — which means the opening slide of that first run is usually missed. Run it once
to grant, then record for real. If access was refused, the player says so and carries on
recording timings without audio.

## Captions

A recorded narration can be transcribed and aligned into per-word timings, and then read
back as a close-caption window with each word lit as it is spoken:

```sh
prebuilt/refractplayer mytalk/out --record-audio     # record the narration
prebuilt/refractplayer mytalk/out --transcribe       # transcribe + align it
prebuilt/refractplayer mytalk/out --captions         # play it back with captions (or press C)
```

`--transcribe` needs two Python packages, one per step:

```sh
pip install openai-whisper     # transcription (or: pip install faster-whisper)
pip install whisperx           # forced alignment
```

The work is Python's, so the player runs [`tools/captions.py`](tools/captions.py) — passing
it the voice directory, the one thing the script cannot work out for itself. That script also
stands alone (`python3 tools/captions.py <voice-dir>`), and `REFRACT_CAPTIONS_SCRIPT` points
the player at it if the binary has been moved away from the repo.

It writes two files beside each wav:

| File | |
|---|---|
| `NN.txt` | the transcript, as plain text |
| `NN.words.json` | `{"words": [{"w": …, "start": …, "end": …}, …]}` |

The transcript is written out rather than kept in memory so it can be **corrected**: fix a
misheard word in `NN.txt`, re-run `--transcribe`, and only the alignment is redone against the
text you supplied. That is also why alignment is a step of its own — forced alignment against
a known transcript is far more accurate than trusting a transcriber's own word timings.

The window highlights from the **audio clock**, not the frame clock, so the lit word is the
one actually coming out of the speakers. Words already spoken stay bright, the current one is
lit, and what is still to come is dim; a long narration scrolls to keep the spoken line in
view. With no audio playing it shows the slide's transcript unlit, which makes it a
serviceable teleprompter for a talk being delivered live.

A slide with no narration, or narration that has not been processed, simply says so —
captions are an addition to a deck, never a requirement of one.

### Correcting what it heard

A transcriber mishears words, and the place you notice is here, watching them go past. So
they can be fixed here: click **Edit** (or press `E`), click the wrong word, type the right
one.

| | |
|---|---|
| click a word | start retyping it |
| shift-click another | take in the span between them |
| `Shift`+`←` / `→` | grow or shrink the span |
| `Enter` / `Tab` | keep the change and move on to the next word |
| `←` / `→` | keep the change and step between words |
| `Esc` | drop the change; again to leave edit mode |
| **Done** | keep everything, leave edit mode |

A **span** can be replaced by any number of words, which is what a join or a split needs —
one word heard as two, or two heard as one. Type as many words as you mean; emptying the
field deletes the span, for when something was heard that was never said.

Timings survive the edit. Correcting a single word needs **no re-alignment at all**: the audio
has not changed, so the word still occupies exactly the time it did — only its label was
wrong. Replacing a span divides the time it covered among the new words in proportion to
their length, which is a guess, but the only one available without going back to Python. It
keeps the highlight on the right word; running `--transcribe` again replaces the guess with a
real alignment against the corrected text.

Leaving edit mode writes both `NN.words.json` and `NN.txt`, and starts the narration again a
second and a half before your **first** correction — the point of replaying is to hear the
change against the audio it was made for, and a long narration should not have to be sat
through to reach it. Change nothing and it starts from the top instead. Keeping the transcript
in step matters too: a later `--transcribe` then aligns against the corrected words instead of
hearing the same mistake again.

**The player stands still while you edit.** Its keys are off in *every* window, and the deck
cannot change slides — not by key, not from the navigator, not by auto-advance. Two reasons:
typing `b` into a word must not blank the projector, and the words on screen belong to the
slide on screen, so moving off it would either throw the edit away or land it on the wrong
slide. GLFW delivers keys to whichever window has focus, so the block has to be global rather
than local to the caption window; a key that would have done something says why it didn't.

An edit still in progress is saved if you quit — leaving mid-word should not be the one way
to lose one.

## A web player

The whole thing — slides, narration, captions — as a page:

```sh
prebuilt/refractplayer mytalk/out --web mytalk/web
(cd mytalk/web && python3 -m http.server 8000)
```

The slides are the **real `.rc` documents**, rendered by the RemoteCompose TypeScript
player: animations, shaders, the same documents the desktop player shows — not pictures of
them. On top of that it plays the recorded narration, lights the captions word by word off
the audio clock, and advances when a slide's narration ends. A slide with no audio holds for
the time the rehearsal recorded, so a partly-recorded deck still plays end to end.

**It opens off the disk.** Double-clicking `index.html` works — the slide bytes travel inside
the page rather than beside it, because a browser refuses to `fetch()` a local file and the
player loads documents by URL. Without that a `file://` deck shows its controls and plays its
audio (a media element is not a fetch) and never draws a slide.

**Slides are laid out at their design size and scaled to fit**, exactly as the desktop player
does. The web player would otherwise size the document to the canvas — right for a document
authored to reflow, wrong for a slide authored at a fixed size, where it leaves the chrome
stretched to the new edges and the title, bullets and figures huddled in one corner at their
authored sizes.

**Narration is compressed** to mp3 on the way out when `ffmpeg` is available (`--keep-wav`
opts out): wav is the right format to record and edit in and the wrong one to download, at
roughly ten times the size. mp3 rather than the better-compressing m4a because
`python3 -m http.server` — which is how a deck like this actually gets served — labels `.m4a`
as `audio/mp4a-latm`, which is not what an `.m4a` is, and the browser then refuses it.

**Captions sit below the slide, not over it.** The page is a column — a two-line band at the
bottom that scrolls with the narration, and the slide letterboxed into whatever is left. So a
window shorter than the deck's aspect ratio gives up slide height to the captions rather than
covering the content they are describing, and the slide keeps its proportions at any window
shape. `C` hides the band, and the slide grows back into the space.

Controls: space / arrows to move, `C` for captions, `F` for fullscreen, `P` to pause, and a
scrubbable progress bar with a tick per section. Browsers refuse to play sound until the page
has been clicked, so it opens behind a start screen rather than silently failing to begin.

The output directory is self-contained — the slides are inside `deck.js`, alongside `media/`,
`audio/`, `bundle.js` and `index.html` — so it can be opened directly or served from
anywhere. It needs the TypeScript player bundle,
built once from the sibling RemoteCompose checkout:

```sh
(cd ../remotecompose-experiments/players/typescript && npm install && npm run bundle)
```

`--web` finds it there automatically; `tools/web.py --bundle <path>` takes it explicitly.

## Exporting

```sh
prebuilt/refractplayer mytalk/out --pdf mytalk.pdf
prebuilt/refractplayer mytalk/out --images mytalk/png
prebuilt/refractplayer mytalk/out --pdf mytalk.pdf --images mytalk/png   # both in one pass
```

Both are headless — no window opens — and both take `--export-delay`, which is how far into
its animation each slide is taken before capture. The default of 2 seconds is enough that a
slide which animates in is not caught mid-entrance.

**`--pdf`** writes one page per slide. `.rc` slides go through Skia's PDF backend, so text
and shapes stay vector and selectable rather than being rasterised. Videos contribute a
first frame, embedded `rc:` documents render in full, and an embedded web page becomes the
same labelled frame the presenter preview shows. Slides with speaker notes get a taller page
with the notes in a panel underneath.

**`--images`** writes `<dir>/<slide>.png`. Unlike the PDF path, this drives the player
itself — load a slide, let it animate, snapshot the surface — so a slide renders exactly as
it would on screen.

Both exporters live in `rcplayer`, so they produce the same output as `rcviewer --pdf` and
`rcviewer --screenshot-dir`. `refract.py --pdf` / `--images` call this player.

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
| `src/Captions.{h,cpp}`, `CaptionWindow.{h,cpp}` | caption timings and the window that lights them |
| `src/Audio*.{h,mm}` | narration capture and gapless playback |
| `tools/captions.py` | transcription + forced alignment (whisper, whisperx) |
| `tools/web.py` | the web player: assembles the deck, audio and captions into a page |
