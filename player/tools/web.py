#!/usr/bin/env python3
"""Build a self-contained web player for a recorded deck.

Run by `refractplayer --web <dir>`. Copies the slides, the narration and the caption
timings into one directory alongside the RemoteCompose TypeScript player bundle, and writes
an index.html that plays the deck the way refractplayer does: slides advance when their
narration ends, captions light word by word, and a slide with no audio holds for the time
the rehearsal recorded.

The slides are the real `.rc` documents rendered by the TypeScript player — the same
documents the desktop player shows, animations and all — not pictures of them.

    python3 player/tools/web.py <deck-out-dir> <output-dir> [--bundle path/to/bundle.js]

The bundle is built once from the players/cpp sibling checkout:

    (cd players/typescript && npm install && npm run bundle)
"""

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys

MEDIA_EXTS = {".mp4", ".mov", ".m4v", ".webp", ".gif", ".apng"}
SLIDE_EXTS = {".rc", ".rcd"} | MEDIA_EXTS

HERE = os.path.dirname(os.path.abspath(__file__))


def find_bundle(explicit: str | None) -> str | None:
    """The TypeScript player bundle. Looked for beside a sibling checkout of the
    RemoteCompose players, the same way the C++ build finds its own tree."""
    if explicit:
        return explicit if os.path.isfile(explicit) else None
    repo = os.path.abspath(os.path.join(HERE, "..", ".."))
    for rel in ("../remotecompose-experiments/players/typescript/web-player/bundle.js",
                "../rcX/../typescript/web-player/bundle.js"):
        cand = os.path.abspath(os.path.join(repo, rel))
        if os.path.isfile(cand):
            return cand
    return None


def voice_dir_for(out_dir: str) -> str | None:
    """Where the narration lives, matching what the player records: `<deck>/voice` when it
    exists, else `<out>/voice`."""
    deck = os.path.dirname(os.path.abspath(out_dir))
    for cand in (os.path.join(deck, "voice"), os.path.join(out_dir, "voice")):
        if os.path.isdir(cand):
            return cand
    return None


def slide_number(filename: str) -> str:
    """The leading digits a slide's narration is keyed by — "07_a_graph.rc" -> "07"."""
    stem = os.path.basename(filename)
    digits = ""
    for c in stem:
        if c.isdigit():
            digits += c
        else:
            break
    return digits


def build(out_dir: str, web_dir: str, bundle: str, keep_wav: bool = False) -> int:
    slides = sorted(f for f in os.listdir(out_dir)
                    if os.path.splitext(f)[1].lower() in SLIDE_EXTS
                    and os.path.isfile(os.path.join(out_dir, f)))
    if not slides:
        print(f"web: no slides in {out_dir}", file=sys.stderr)
        return 1

    os.makedirs(web_dir, exist_ok=True)
    shutil.copyfile(bundle, os.path.join(web_dir, "bundle.js"))

    # Media slides are files the page points at; .rc slides are embedded instead — see
    # below.
    for name in slides:
        if os.path.splitext(name)[1].lower() in MEDIA_EXTS:
            shutil.copyfile(os.path.join(out_dir, name), os.path.join(web_dir, name))
    media_src = os.path.join(out_dir, "media")
    if os.path.isdir(media_src):
        shutil.copytree(media_src, os.path.join(web_dir, "media"), dirs_exist_ok=True)

    # Titles and sections, when the deck was built with a manifest.
    titles, sections = {}, {}
    manifest_path = os.path.join(out_dir, "deck.json")
    if os.path.isfile(manifest_path):
        with open(manifest_path) as f:
            manifest = json.load(f)
        for rec in manifest.get("slides", []):
            if rec.get("file"):
                titles[rec["file"]] = rec.get("title", "")
                if rec.get("section"):
                    sections[rec["file"]] = rec["section"]

    # How long the rehearsal spent on each slide, for slides with no narration to time them.
    durations = {}
    timing_path = os.path.join(out_dir, "timing.json")
    if os.path.isfile(timing_path):
        with open(timing_path) as f:
            for rec in json.load(f).get("slides", []):
                if rec.get("file") and rec.get("duration"):
                    durations.setdefault(rec["file"], rec["duration"])

    # Narration and captions, copied under the slide's own name so the page needs no
    # knowledge of the numbering rule.
    voice_dir = voice_dir_for(out_dir)
    audio_dir = os.path.join(web_dir, "audio")
    entries = []
    have_audio = 0
    # Narration is recorded as uncompressed wav, which is right for editing and wrong for
    # something to be downloaded: a talk's worth runs to hundreds of megabytes. Compressed
    # on the way out when ffmpeg is around, which every browser plays.
    # mp3 rather than the better-compressing aac/m4a: `python3 -m http.server` — which is
    # how a deck like this actually gets served — maps .m4a to audio/mp4a-latm, which is not
    # what an .m4a is, and the browser then refuses to decode it. .mp3 is audio/mpeg
    # everywhere and plays in everything.
    encode = shutil.which("ffmpeg") is not None and not keep_wav
    audio_ext = ".mp3" if encode else ".wav"
    for name in slides:
        entry = {"file": name,
                 "title": titles.get(name, ""),
                 "section": sections.get(name, 0),
                 "duration": durations.get(name, 0)}

        # The .rc bytes travel inside the page rather than beside it. The player loads a
        # document by URL with fetch(), and a browser refuses to fetch a local file — so a
        # page opened straight off the disk would show the controls and play the audio (a
        # media element is not a fetch) and never draw a slide. Embedding removes the fetch,
        # and the deck opens by double-clicking index.html.
        if os.path.splitext(name)[1].lower() not in MEDIA_EXTS:
            with open(os.path.join(out_dir, name), "rb") as f:
                entry["data"] = base64.b64encode(f.read()).decode("ascii")
        number = slide_number(name)
        if voice_dir and number:
            wav = os.path.join(voice_dir, number + ".wav")
            if os.path.isfile(wav):
                os.makedirs(audio_dir, exist_ok=True)
                dest = os.path.join(audio_dir, number + audio_ext)
                if encode:
                    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", wav,
                                    "-c:a", "libmp3lame", "-b:a", "96k", dest], check=False)
                if not encode or not os.path.isfile(dest):
                    dest = os.path.join(audio_dir, number + ".wav")
                    shutil.copyfile(wav, dest)
                entry["audio"] = "audio/" + os.path.basename(dest)
                have_audio += 1
            words = os.path.join(voice_dir, number + ".words.json")
            if os.path.isfile(words):
                with open(words) as f:
                    payload = json.load(f)
                entry["words"] = [{"w": w["w"], "s": w["start"], "e": w["end"]}
                                  for w in payload.get("words", [])]
        entries.append(entry)

    deck = {"slides": entries}
    with open(os.path.join(web_dir, "deck.js"), "w") as f:
        # A .js rather than a .json so the page opens from the filesystem too: a fetch of
        # a local file is blocked by the browser, a script tag is not.
        f.write("window.DECK = " + json.dumps(deck, indent=1) + ";\n")

    with open(os.path.join(web_dir, "index.html"), "w") as f:
        f.write(PAGE)

    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(web_dir) for f in fs)
    print(f"web: {len(entries)} slides, {have_audio} with narration, "
          f"{size / 1e6:.0f} MB -> {web_dir}")
    print("     opens straight off the disk (double-click index.html), or serve it:")
    print(f"     (cd {web_dir} && python3 -m http.server 8000)")
    return 0


PAGE = r"""<!doctype html>
<meta charset="utf-8">
<title>refract</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: #000; overflow: hidden;
               font: 14px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif; }
  /* A column: the slide takes what is left after the caption band, rather than the band
     being laid over the slide. The slide then letterboxes into whatever that leaves, so a
     window shorter than the deck's aspect ratio gives up slide height to the captions
     instead of covering the content with them. */
  #app { position: fixed; inset: 0; display: flex; flex-direction: column; }
  #stage { flex: 1 1 auto; min-height: 0; position: relative; display: grid;
           place-items: center; }
  #slide { position: relative; }
  #slide canvas { display: block; }

  /* Captions sit over the slide, so they are kept to a band: two lines at a time on a dark
     strip, scrolled so the words being spoken are the ones showing. The whole transcript
     laid out over a full-bleed slide covers the content it is describing. */
  #captions { flex: 0 0 auto; text-align: center; pointer-events: none;
              font-size: clamp(15px, 1.55vw, 23px); line-height: 1.45;
              /* Two lines exactly. box-sizing is border-box, so the padding has to be in
                 the height or the second line is clipped. */
              height: calc(2.9em + 1.1em); overflow: hidden;
              padding: .55em 5vw; background: #07090d; color: #fff; }
  #captions.hidden { display: none; }
  #capsInner { transition: transform .18s ease-out; }
  #captions .w { color: rgba(255,255,255,.42); transition: color .12s linear; }
  #captions .w.said { color: rgba(255,255,255,.92); }
  #captions .w.now { color: #8fc0ff; }

  /* Over the slide, not over the captions — those have their own space now. */
  #bar { position: absolute; left: 0; right: 0; bottom: 0; padding: 12px 18px 14px;
         display: flex; align-items: center; gap: 14px;
         background: linear-gradient(transparent, rgba(0,0,0,.82) 42%);
         opacity: 0; transition: opacity .25s; }
  #bar.show { opacity: 1; }
  button { appearance: none; border: 0; background: rgba(255,255,255,.10); color: #e8eaf0;
           width: 34px; height: 34px; border-radius: 8px; cursor: pointer; font-size: 15px;
           display: grid; place-items: center; }
  button:hover { background: rgba(255,255,255,.2); }
  button.wide { width: auto; padding: 0 12px; font-size: 12px; letter-spacing: .04em; }
  #track { flex: 1; height: 5px; border-radius: 3px; background: rgba(255,255,255,.16);
           position: relative; cursor: pointer; }
  #fill { position: absolute; inset: 0 auto 0 0; border-radius: 3px; background: #6ea8ff; }
  #tick { position: absolute; top: -3px; width: 2px; height: 11px; background: rgba(255,255,255,.34); }
  #count { color: #99a0ad; font-variant-numeric: tabular-nums; font-size: 12px; min-width: 62px;
           text-align: right; }
  #title { position: fixed; top: 16px; left: 20px; color: rgba(255,255,255,.5); font-size: 12px;
           opacity: 0; transition: opacity .25s; }
  #title.show { opacity: 1; }

  /* Browsers refuse to play sound until the page has been interacted with, so the deck
     opens behind a start screen rather than silently failing to begin. */
  #start { position: fixed; inset: 0; display: grid; place-items: center; cursor: pointer;
           background: rgba(0,0,0,.72); backdrop-filter: blur(3px); z-index: 5; }
  #start.gone { display: none; }
  #start div { text-align: center; color: #e8eaf0; }
  #start .play { font-size: 46px; opacity: .92; }
  #start .hint { margin-top: 10px; color: #99a0ad; font-size: 13px; }
</style>

<div id="app">
  <div id="stage">
    <div id="slide"></div>
    <div id="bar">
  <button id="prev" title="Previous slide (&larr;)">&#9664;</button>
  <button id="play" title="Play / pause (space)">&#9654;</button>
  <button id="next" title="Next slide (&rarr;)">&#9654;&#9654;</button>
  <div id="track"><div id="fill"></div></div>
  <button id="cc" class="wide" title="Captions (c)">CC</button>
  <button id="full" title="Fullscreen (f)">&#9974;</button>
  <div id="count"></div>
    </div>
  </div>
  <div id="captions"></div>
</div>
<div id="title"></div>

<div id="start"><div>
  <div class="play">&#9654;</div>
  <div class="hint">click to start &mdash; space, arrows, C for captions, F for fullscreen</div>
</div></div>

<script src="bundle.js"></script>
<script src="deck.js"></script>
<script>
(function () {
  const slides = (window.DECK && window.DECK.slides) || [];
  const stage = document.getElementById('slide');
  const capsEl = document.getElementById('captions');
  const bar = document.getElementById('bar');
  const titleEl = document.getElementById('title');
  const fill = document.getElementById('fill');
  const count = document.getElementById('count');
  const startEl = document.getElementById('start');
  const playBtn = document.getElementById('play');

  // A slide with no narration and no recorded duration still has to end sometime.
  const DEFAULT_HOLD = 5;

  let index = 0, playing = false, showCaptions = true;
  let handle = null, docW = 1600, docH = 900, capsInner = null;
  let holdTimer = null, wordSpans = [], lastWord = -1;

  const audio = new Audio();      // the slide being heard
  const ahead = new Audio();      // the next one, opened early so the join has no gap in it
  audio.preload = ahead.preload = 'auto';

  const isMedia = f => /\.(mp4|mov|m4v|webp|gif|apng)$/i.test(f);

  // Slides are authored at a fixed design size, and that is the size they are laid out at
  // — the canvas keeps the document's own dimensions and the browser scales the result to
  // the window. Resizing the canvas to the window instead makes the engine re-measure the
  // document at that size, which leaves everything absolute in it (padding, font sizes,
  // pane widths) at authored scale in a corner of a bigger box. This is what the desktop
  // player does too: lay out at the design size, scale to fit, letterbox the remainder.
  function fit() {
    if (!handle || !handle.canvas) return;
    // The stage, not the window: the caption band has already taken its share, and the
    // slide letterboxes into what is left.
    const box = document.getElementById('stage');
    const scale = Math.min(box.clientWidth / docW, box.clientHeight / docH);
    handle.canvas.style.width = Math.round(docW * scale) + 'px';
    handle.canvas.style.height = Math.round(docH * scale) + 'px';
  }

  async function showSlide(i, opts) {
    opts = opts || {};
    index = Math.max(0, Math.min(i, slides.length - 1));
    const slide = slides[index];

    clearTimeout(holdTimer);
    titleEl.textContent = slide.title || slide.file;
    count.textContent = (index + 1) + ' / ' + slides.length;
    fill.style.width = ((index + 1) / slides.length * 100) + '%';

    // Audio first: continuity across a slide boundary matters more than the picture, and
    // the narration was recorded straight through it.
    startAudio(slide, opts.at || 0);

    if (isMedia(slide.file)) {
      stage.innerHTML = '<video src="' + slide.file + '" autoplay muted playsinline ' +
                        'style="max-width:100%;max-height:100%"></video>';
      handle = null;
    } else {
      if (!handle || !stage.querySelector('canvas')) {
        stage.innerHTML = '';
        handle = RC.createPlayer(stage, { theme: 'dark', background: '#000' });
      }
      // From the embedded bytes, not by URL: fetch() is refused for a local file, and this
      // page is meant to open off the disk as readily as off a server.
      const doc = slide.data ? await handle.loadFromBase64(slide.data)
                             : await handle.loadFromUrl(slide.file);
      if (doc && doc.width && doc.height) { docW = doc.width; docH = doc.height; }
      // The canvas is the document's own size, and nothing else. The player sizes the
      // document to whatever the canvas is — "the content fills the context space
      // natively" — which is right for a document authored to reflow and wrong for a slide
      // authored at a fixed size: told it is 3200 wide, the deck's chrome moves out to the
      // new edges while the title, bullets and figures keep their authored sizes and end up
      // huddled in one corner. Laying out at the design size and letting the browser scale
      // the result is the same thing the desktop player does.
      handle.resize(docW, docH);
      fit();
    }

    buildCaptions(slide);
    preloadNext();
  }

  function startAudio(slide, at) {
    audio.pause();
    if (!slide.audio) {
      audio.removeAttribute('src');
      if (playing) holdFor(slide.duration || DEFAULT_HOLD);
      return;
    }
    // Reuse the file opened for this slide, if it is the one that was prepared.
    if (ahead.src && ahead.src.endsWith(slide.audio)) {
      audio.src = ahead.src;
    } else {
      audio.src = slide.audio;
    }
    audio.currentTime = at || 0;
    if (playing) audio.play().catch(() => {});
  }

  function preloadNext() {
    const next = slides[index + 1];
    if (next && next.audio) { ahead.src = next.audio; ahead.load(); }
  }

  // Slides with no narration are held for as long as the rehearsal spent on them, so a deck
  // that is only partly recorded still plays end to end at something like the right pace.
  function holdFor(seconds) {
    clearTimeout(holdTimer);
    holdTimer = setTimeout(() => { if (playing) advance(); }, Math.max(0.4, seconds) * 1000);
  }

  function advance() {
    if (index + 1 < slides.length) showSlide(index + 1);
    else setPlaying(false);
  }

  audio.addEventListener('ended', () => { if (playing) advance(); });

  function buildCaptions(slide) {
    capsEl.innerHTML = '<div id="capsInner"></div>';
    capsInner = document.getElementById('capsInner');
    capsInner.style.transform = 'translateY(0)';
    wordSpans = [];
    lastWord = -1;
    const words = slide.words || [];
    words.forEach(word => {
      const span = document.createElement('span');
      span.className = 'w';
      span.textContent = word.w + ' ';
      span.dataset.s = word.s;
      capsInner.appendChild(span);
      wordSpans.push(span);
    });
    capsEl.classList.toggle('hidden', !showCaptions || words.length === 0);
    fit();   // the band appearing or going away resizes the slide
  }

  // Keep the line being spoken in the band — the spoken line sits on the lower of the two
  // showing, so the one coming next is already readable above it.
  function scrollCaptions(current) {
    if (!capsInner || current < 0) return;
    const line = wordSpans[current].offsetTop;
    const lineHeight = parseFloat(getComputedStyle(capsEl).lineHeight) || 24;
    capsInner.style.transform = 'translateY(' + (-Math.max(0, line - lineHeight)) + 'px)';
  }

  // Driven off the audio clock, not a timer: the lit word has to be the one being heard.
  function tick() {
    // Repaint every frame while a slide is up. The player only schedules another frame
    // while the document asks for one (needsRepaint), and a refract slide is a *transition*
    // — it animates in from the slide before it — which leaves it stopped part-way through
    // the moment it stops asking. The desktop player sidesteps this by repainting
    // unconditionally; so does this. It also keeps animated backgrounds moving.
    if (handle && handle.player && !isMedia(slides[index].file)) {
      try { handle.player.repaint(); } catch (e) { /* mid-load */ }
    }

    if (wordSpans.length && !audio.paused) {
      const t = audio.currentTime;
      let current = -1;
      for (let i = 0; i < wordSpans.length; i++) {
        if (t >= +wordSpans[i].dataset.s) current = i; else break;
      }
      if (current !== lastWord) {
        for (let i = 0; i < wordSpans.length; i++) {
          wordSpans[i].classList.toggle('said', i < current);
          wordSpans[i].classList.toggle('now', i === current);
        }
        scrollCaptions(current);
        lastWord = current;
      }
    }
    requestAnimationFrame(tick);
  }
  requestAnimationFrame(tick);

  function setPlaying(on) {
    playing = on;
    playBtn.innerHTML = on ? '&#10073;&#10073;' : '&#9654;';
    if (on) {
      if (audio.src) audio.play().catch(() => {});
      else holdFor(slides[index].duration || DEFAULT_HOLD);
    } else {
      audio.pause();
      clearTimeout(holdTimer);
    }
  }

  // ── Controls ──────────────────────────────────────────────────────
  document.getElementById('prev').onclick = () => showSlide(index - 1);
  document.getElementById('next').onclick = () => advance();
  playBtn.onclick = () => setPlaying(!playing);
  document.getElementById('cc').onclick = () => {
    showCaptions = !showCaptions;
    capsEl.classList.toggle('hidden', !showCaptions || !wordSpans.length);
    fit();
  };
  document.getElementById('full').onclick = () => {
    if (document.fullscreenElement) document.exitFullscreen();
    else document.documentElement.requestFullscreen();
  };
  document.getElementById('track').onclick = e => {
    const r = e.currentTarget.getBoundingClientRect();
    showSlide(Math.floor((e.clientX - r.left) / r.width * slides.length));
  };

  addEventListener('keydown', e => {
    switch (e.key) {
      case ' ': case 'ArrowRight': case 'PageDown': e.preventDefault(); advance(); break;
      case 'ArrowLeft': case 'PageUp': showSlide(index - 1); break;
      case 'Home': showSlide(0); break;
      case 'End': showSlide(slides.length - 1); break;
      case 'c': case 'C': document.getElementById('cc').click(); break;
      case 'f': case 'F': document.getElementById('full').click(); break;
      case 'p': case 'P': setPlaying(!playing); break;
    }
  });

  // The controls stay out of the way until the pointer moves.
  let hideTimer = null;
  function wake() {
    bar.classList.add('show');
    titleEl.classList.add('show');
    clearTimeout(hideTimer);
    hideTimer = setTimeout(() => {
      bar.classList.remove('show');
      titleEl.classList.remove('show');
    }, 2600);
  }
  addEventListener('mousemove', wake);
  addEventListener('touchstart', wake);
  addEventListener('resize', fit);

  startEl.onclick = () => {
    startEl.classList.add('gone');
    setPlaying(true);
    wake();
  };

  // Section marks along the progress bar, so the shape of the talk is visible.
  const track = document.getElementById('track');
  slides.forEach((s, i) => {
    if (!s.section) return;
    const tick = document.createElement('div');
    tick.id = 'tick';
    tick.style.left = (i / slides.length * 100) + '%';
    track.appendChild(tick);
  });

  showSlide(0);
})();
</script>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("out_dir", help="the deck's out/ directory")
    ap.add_argument("web_dir", help="where to write the site")
    ap.add_argument("--bundle", default=None,
                    help="path to the TypeScript player's bundle.js")
    ap.add_argument("--keep-wav", action="store_true",
                    help="ship the narration as recorded instead of compressing it")
    args = ap.parse_args()

    bundle = find_bundle(args.bundle)
    if not bundle:
        print("web: the RemoteCompose TypeScript player bundle was not found. Build it with:\n"
              "    (cd ../remotecompose-experiments/players/typescript && npm install && "
              "npm run bundle)\n"
              "or pass --bundle <path to bundle.js>", file=sys.stderr)
        return 2
    return build(os.path.abspath(args.out_dir), os.path.abspath(args.web_dir), bundle,
                 args.keep_wav)


if __name__ == "__main__":
    sys.exit(main())
