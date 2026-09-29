#!/usr/bin/env python3
"""Turn a deck's recorded narration into per-word caption timings.

Run by `refractplayer --transcribe`, which passes the voice directory it records into. It
also stands alone:

    python3 player/tools/captions.py <voice-dir> [--model base] [--language en]

This is a step on a *recording*, not on a deck source, which is why it lives with the player
rather than with refract.py — nothing here has anything to say about turning markdown into
slides.

Two steps, each with its own optional dependency:

    transcribe   wav              -> text     (openai-whisper, or faster-whisper)
    align        wav + text       -> per-word start/end  (whisperx)

Neither is a small install (they bring torch with them), and a machine that has them in one
Python rarely has them in the one `python3` happens to mean. So this script keeps its own:

    python3 player/tools/captions.py --install

makes a virtual environment under the user's cache directory and puts them in it, and every
run after that re-executes itself there when the Python it was started with has nothing —
which is what makes `--transcribe` work on a machine where nothing was set up by hand.
``REFRACT_CAPTIONS_VENV`` puts that environment somewhere else; a Python that already has
the packages is used as it is, and no environment is made.

For every ``NN.wav`` in the deck's voice directory this writes:

    NN.txt          the transcript, as plain text
    NN.words.json   {"words": [{"w": …, "start": …, "end": …}, …]}

The transcript is written out rather than kept in memory so it can be *corrected*: fix a
misheard word in ``NN.txt``, re-run, and only the alignment is redone against the text you
supplied. That is also why alignment is a separate step from transcription — forced
alignment against a known transcript is far more accurate than trusting whisper's own word
timings, which is the same split Echo's ``align_words.py`` makes.

Both models are loaded once and reused across the deck; loading dominates the cost for the
short files a slide's narration produces.
"""

from __future__ import annotations   # this script must import under the python3 a machine
                                    # happens to have, which on macOS is still 3.9

import importlib.util
import json
import os
import shutil
import subprocess
import sys


# ── Where the packages live ──────────────────────────────────────────────────

def venv_dir(env: dict | None = None) -> str:
    """The environment `--install` fills, and the one a run falls back to. Under the user's
    cache directory, because it is a cache: deleting it costs one re-install and nothing
    else, and a deck never refers to it."""
    env = os.environ if env is None else env
    named = env.get("REFRACT_CAPTIONS_VENV")
    if named:
        return os.path.expanduser(named)
    home = env.get("HOME") or os.path.expanduser("~")
    if sys.platform == "darwin":
        base = os.path.join(home, "Library", "Caches", "refract")
    else:
        base = env.get("XDG_CACHE_HOME") or os.path.join(home, ".cache")
        base = os.path.join(base, "refract")
    return os.path.join(base, "captions-venv")


def venv_python(venv: str) -> str:
    """The interpreter inside an environment, whichever platform made it."""
    if sys.platform == "win32":
        return os.path.join(venv, "Scripts", "python.exe")
    return os.path.join(venv, "bin", "python3")


def missing(finder=None) -> list[str]:
    """Which of the two steps this interpreter cannot do, by name. Asked with `find_spec`
    rather than an import: importing whisperx pulls torch in, which takes seconds, and the
    answer here is only whether the packages are installed at all."""
    find = finder or importlib.util.find_spec

    def has(name: str) -> bool:
        try:
            return find(name) is not None
        except (ImportError, ValueError):
            return False

    out = []
    if not has("whisper") and not has("faster_whisper"):
        out.append("a transcriber (openai-whisper or faster-whisper)")
    if not has("whisperx"):
        out.append("whisperx (the aligner)")
    return out


def installer_python(which=None) -> str | None:
    """The interpreter to build the environment with. This one when it is new enough, else
    the newest `python3.N` on the PATH: Apple's 3.9 is what `python3` means on a Mac nobody
    has set up, and the packages have no wheels for it. None when there is nothing suitable."""
    look = which or shutil.which
    if sys.version_info >= (3, 10):
        return sys.executable
    for name in ("python3.13", "python3.12", "python3.11", "python3.10"):
        found = look(name)
        if found:
            return found
    return None


def install_commands(venv: str, upgrade: bool = False, python: str | None = None) -> list[list[str]]:
    """The commands `--install` runs, in order. whisperx brings faster-whisper and torch with
    it, so one install covers both steps; openai-whisper is an alternative transcriber, not a
    second requirement."""
    py = venv_python(venv)
    return [
        [python or sys.executable, "-m", "venv", venv],
        [py, "-m", "pip", "install", "--upgrade", "pip", "wheel"],
        [py, "-m", "pip", "install"] + (["--upgrade"] if upgrade else []) + ["whisperx"],
    ]


def install(venv: str, upgrade: bool = False, dry_run: bool = False) -> int:
    """Make the environment and put the packages in it. Prints the same `progress:` lines the
    transcription does, so a window watching one can watch this too — it is minutes of
    downloading, and silence would look like a hang."""
    python = installer_python()
    if python is None:
        print("captions: this is Python %d.%d and the packages need 3.10 or newer. Install one\n"
              "    brew install python\n"
              "and run this again." % sys.version_info[:2], file=sys.stderr)
        return 2
    commands = install_commands(venv, upgrade, python)
    what = ["creating the environment", "updating pip", "installing whisperx (this takes a while)"]
    for i, (command, step) in enumerate(zip(commands, what)):
        print(f"progress: {i}/{len(commands)} {step}", file=sys.stderr, flush=True)
        print("  " + " ".join(command))
        if dry_run:
            continue
        # The first command makes the environment; if it is already there, `venv` is a no-op
        # that keeps what is in it.
        result = subprocess.run(command)
        if result.returncode != 0:
            print(f"captions: {step} failed", file=sys.stderr)
            return result.returncode
    print(f"progress: {len(commands)}/{len(commands)} done", file=sys.stderr, flush=True)
    if dry_run:
        return 0
    left = subprocess.run([venv_python(venv), "-c",
                           "import importlib.util as u;"
                           "print('ok' if u.find_spec('whisperx') else 'missing')"],
                          capture_output=True, text=True).stdout.strip()
    if left != "ok":
        print("captions: the packages did not land in " + venv, file=sys.stderr)
        return 2
    print(f"captions: ready — the transcriber lives in {venv}")
    return 0


def reexec_into_venv() -> None:
    """Run again inside the environment `--install` made, when this Python has nothing and
    that one does. The player calls `python3 captions.py`, and this is what makes that work
    on a machine where the packages were never installed into `python3` itself."""
    if os.environ.get("REFRACT_CAPTIONS_INSIDE"):
        return                                  # already there: never loop
    if not missing():
        return                                  # this interpreter can do the work
    python = venv_python(venv_dir())
    if not os.path.exists(python):
        return
    try:
        if os.path.samefile(python, sys.executable):
            return
    except OSError:
        pass
    os.environ["REFRACT_CAPTIONS_INSIDE"] = "1"
    os.execv(python, [python, os.path.abspath(__file__)] + sys.argv[1:])


def _wavs(voice_dir: str) -> list[str]:
    return sorted(f for f in os.listdir(voice_dir) if f.endswith(".wav"))


def _load_transcriber(model_name: str):
    """openai-whisper if present, else faster-whisper, else None. Both are wrapped to the
    same ``transcribe(path, language) -> text`` shape."""
    try:
        import whisper
    except ImportError:
        pass
    else:
        model = whisper.load_model(model_name)
        return lambda path, lang: (model.transcribe(path, language=lang).get("text") or "").strip()

    try:
        from faster_whisper import WhisperModel
    except ImportError:
        return None
    model = WhisperModel(model_name)

    def run(path, lang):
        segments, _ = model.transcribe(path, language=lang)
        return " ".join(s.text for s in segments).strip()
    return run


def _load_aligner(language: str, device: str):
    """whisperx's wav2vec2 CTC aligner, or None when whisperx is missing."""
    try:
        import whisperx
    except ImportError:
        return None
    model, metadata = whisperx.load_align_model(language_code=language, device=device)

    def run(path, text):
        audio = whisperx.load_audio(path)
        duration = len(audio) / 16000.0
        result = whisperx.align([{"start": 0.0, "end": duration, "text": text}],
                                model, metadata, audio, device,
                                return_char_alignments=False)
        return result.get("word_segments", []), duration
    return run


def process_voice_dir(voice_dir: str, model_name: str = "base", language: str = "en",
                      device: str = "cpu", force: bool = False,
                      only: list[str] | None = None) -> int:
    """Transcribe and align every recorded slide in `voice_dir` — or just the stems in
    `only` (e.g. ["07"]) when the player asks for one slide. Returns an exit code."""
    if not os.path.isdir(voice_dir) or not _wavs(voice_dir):
        print(f"captions: no recorded narration in {voice_dir} — record one with "
              "`refractplayer <deck>/out --record-audio`", file=sys.stderr)
        return 1

    # Both models read the audio through ffmpeg. Said here rather than at the first failure,
    # which happens minutes in, after the models have loaded.
    if shutil.which("ffmpeg") is None:
        print("captions: ffmpeg is needed to read the recordings — brew install ffmpeg", file=sys.stderr)
        return 2

    wavs = _wavs(voice_dir)
    if only:
        wavs = [w for w in wavs if os.path.splitext(w)[0] in only]
        if not wavs:
            print(f"captions: no recording named {', '.join(only)} in {voice_dir}", file=sys.stderr)
            return 1
    print(f"captions: {len(wavs)} recorded slide(s) in {voice_dir}")

    # Progress, one line per step, for whoever is watching — the player reads these off
    # stderr and shows them in the presenter, since a whole deck is minutes of silence
    # otherwise. `done` counts slides finished, `total` the ones being processed.
    def progress(done: int, total: int, phase: str, stem: str = "") -> None:
        print(f"progress: {done}/{total} {phase} {stem}".rstrip(), file=sys.stderr, flush=True)

    # Only pay for a model if something actually needs it.
    pending = []
    for wav in wavs:
        stem = os.path.splitext(wav)[0]
        wav_path = os.path.join(voice_dir, wav)
        txt_path = os.path.join(voice_dir, stem + ".txt")
        json_path = os.path.join(voice_dir, stem + ".words.json")
        fresh = (os.path.exists(json_path)
                 and os.path.getmtime(json_path) >= os.path.getmtime(wav_path)
                 and (not os.path.exists(txt_path)
                      or os.path.getmtime(json_path) >= os.path.getmtime(txt_path)))
        if fresh and not force:
            print(f"  {stem}  up to date")
            continue
        pending.append((stem, wav_path, txt_path, json_path))

    if not pending:
        return 0

    # A transcript the user has already written or corrected is authoritative; whisper is
    # only needed for the slides that have none.
    needs_transcription = any(not os.path.exists(t) for _, _, t, _ in pending)
    if needs_transcription:
        progress(0, len(pending), "loading the transcriber")
    transcribe = _load_transcriber(model_name) if needs_transcription else None
    if needs_transcription and transcribe is None:
        print("captions: nothing to transcribe with — run `refractplayer --install-transcriber` "
              "(or `python3 player/tools/captions.py --install`)", file=sys.stderr)
        return 2

    progress(0, len(pending), "loading the aligner")
    align = _load_aligner(language, device)
    if align is None:
        print("captions: nothing to align with (whisperx) — run `refractplayer --install-transcriber` "
              "(or `python3 player/tools/captions.py --install`)", file=sys.stderr)
        return 2

    failures = 0
    for done, (stem, wav_path, txt_path, json_path) in enumerate(pending):
        if os.path.exists(txt_path):
            with open(txt_path) as f:
                text = f.read().strip()
            source = "transcript"
        else:
            progress(done, len(pending), "transcribing", stem)
            text = transcribe(wav_path, language)
            with open(txt_path, "w") as f:
                f.write(text + "\n")
            source = "transcribed"

        if not text:
            print(f"  {stem}  silent — no captions")
            with open(json_path, "w") as f:
                json.dump({"version": 1, "wav": os.path.basename(wav_path),
                           "text": "", "words": []}, f, indent=2)
            continue

        progress(done, len(pending), "aligning", stem)
        try:
            words, duration = align(wav_path, text)
        except Exception as e:                      # noqa: BLE001 - one bad slide is not fatal
            print(f"  {stem}  alignment failed: {e}", file=sys.stderr)
            failures += 1
            continue

        payload = {
            "version": 1,
            "wav": os.path.basename(wav_path),
            "duration": round(duration, 3),
            "text": text,
            "words": [
                {"w": (w.get("word") or "").strip(),
                 "start": round(w["start"], 3),
                 "end": round(w["end"], 3)}
                for w in words
                if w.get("start") is not None and w.get("end") is not None
            ],
        }
        with open(json_path, "w") as f:
            json.dump(payload, f, indent=2)
        print(f"  {stem}  {source}, {len(payload['words'])} words")

    progress(len(pending), len(pending), "done")
    return 1 if failures else 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Transcribe and align a deck's recorded narration into caption timings.")
    ap.add_argument("voice_dir", nargs="?", help="directory of recorded NN.wav files")
    ap.add_argument("--install", action="store_true",
                    help="put the transcriber and the aligner in this script's own virtual "
                         "environment (under the user's cache directory, or REFRACT_CAPTIONS_VENV)")
    ap.add_argument("--upgrade", action="store_true",
                    help="with --install: update the packages already there")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --install: print what it would run, and run none of it")
    ap.add_argument("--where", action="store_true",
                    help="print where the packages are looked for, and whether they are there")
    ap.add_argument("--model", default="base",
                    help="whisper model for transcription (default: base)")
    ap.add_argument("--language", default="en",
                    help="language of the narration (default: en)")
    ap.add_argument("--device", default="cpu",
                    help="torch device for alignment (default: cpu — whisperx's alignment "
                         "is flaky on Apple silicon's mps)")
    ap.add_argument("--force", action="store_true",
                    help="redo slides whose captions are already up to date")
    ap.add_argument("--only", default=None,
                    help="only these recordings, by stem, comma-separated (e.g. 07,08)")
    args = ap.parse_args()
    venv = venv_dir()
    if args.where:
        print(f"this python:  {sys.executable}")
        print(f"environment:  {venv}" + ("" if os.path.exists(venv_python(venv)) else "  (not made yet)"))
        gaps = missing()
        print("here:         " + ("everything needed" if not gaps else "missing " + ", ".join(gaps)))
        if gaps and os.path.exists(venv_python(venv)):
            inside = subprocess.run([venv_python(venv), os.path.abspath(__file__), "--where"],
                                    capture_output=True, text=True,
                                    env={**os.environ, "REFRACT_CAPTIONS_INSIDE": "1"})
            print("in it:        " + ("everything needed" if "everything needed" in inside.stdout
                                      else "missing something — re-run with --install"))
        print(f"ffmpeg:       {shutil.which('ffmpeg') or 'not on the PATH — brew install ffmpeg'}")
        return 0
    if args.install:
        return install(venv, args.upgrade, args.dry_run)
    if not args.voice_dir:
        ap.error("a voice directory is needed (or --install / --where)")
    only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
    return process_voice_dir(args.voice_dir, args.model, args.language, args.device,
                             args.force, only)


if __name__ == "__main__":
    # Before anything else: if this Python cannot do the work and the environment can, this
    # process becomes one running there.
    if "--install" not in sys.argv:
        reexec_into_venv()
    sys.exit(main())
