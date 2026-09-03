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

import json
import os
import sys


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
                      device: str = "cpu", force: bool = False) -> int:
    """Transcribe and align every recorded slide in `voice_dir`. Returns an exit code."""
    if not os.path.isdir(voice_dir) or not _wavs(voice_dir):
        print(f"captions: no recorded narration in {voice_dir} — record one with "
              "`refractplayer <deck>/out --record-audio`", file=sys.stderr)
        return 1

    wavs = _wavs(voice_dir)
    print(f"captions: {len(wavs)} recorded slide(s) in {voice_dir}")

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
    transcribe = _load_transcriber(model_name) if needs_transcription else None
    if needs_transcription and transcribe is None:
        print("captions: no transcriber available. Install one with:\n"
              "    pip install openai-whisper      (or: pip install faster-whisper)",
              file=sys.stderr)
        return 2

    align = _load_aligner(language, device)
    if align is None:
        print("captions: whisperx is required for word timings. Install with:\n"
              "    pip install whisperx", file=sys.stderr)
        return 2

    failures = 0
    for stem, wav_path, txt_path, json_path in pending:
        if os.path.exists(txt_path):
            with open(txt_path) as f:
                text = f.read().strip()
            source = "transcript"
        else:
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

    return 1 if failures else 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Transcribe and align a deck's recorded narration into caption timings.")
    ap.add_argument("voice_dir", help="directory of recorded NN.wav files")
    ap.add_argument("--model", default="base",
                    help="whisper model for transcription (default: base)")
    ap.add_argument("--language", default="en",
                    help="language of the narration (default: en)")
    ap.add_argument("--device", default="cpu",
                    help="torch device for alignment (default: cpu — whisperx's alignment "
                         "is flaky on Apple silicon's mps)")
    ap.add_argument("--force", action="store_true",
                    help="redo slides whose captions are already up to date")
    args = ap.parse_args()
    return process_voice_dir(args.voice_dir, args.model, args.language, args.device,
                             args.force)


if __name__ == "__main__":
    sys.exit(main())
