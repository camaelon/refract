#!/usr/bin/env python3
"""Read a refractplayer --perf record and say which slides are slow, and how.

    refractplayer out/ 1920 1080 --perf perf.json [--perf-dwell 3]
    python3 player/tools/perf_report.py perf.json [--top 15] [--transition 1.2] [--json]

For every slide it looks at two windows: the transition (the first --transition seconds after
the slide change — the push, the content reveal) and the rest of the dwell. In each it reports
the longest gap between frames, how many frames missed the display (a gap longer than 1.5 ×
the refresh interval, which the eye reads as a stutter), and the CPU time the player spent per
frame (render + present). The slide change itself — loading the next slide, before its first
frame — is reported on its own: a long one is the hitch you see as you press the key.

The refresh interval is estimated from the record (the median gap of the steady frames), so
the same thresholds work on a 60 Hz and a 120 Hz display.
"""
import argparse
import json
import statistics
import sys


def pct(values, p):
    if not values:
        return 0.0
    v = sorted(values)
    return v[min(len(v) - 1, int(round(p / 100.0 * (len(v) - 1))))]


def analyse(rec, transition):
    frames = rec["frames"]
    titles = {s["index"]: s.get("title", "") for s in rec["slides"]}
    switch = {}
    for s in rec["slides"]:
        switch[s["index"]] = max(switch.get(s["index"], 0.0), s["switch_ms"])
    steady = [f[2] for f in frames if f[1] > transition]
    refresh = statistics.median(steady) if steady else 16.7
    miss = refresh * 1.5
    by = {}
    prev_cpu = 0.0
    for f in frames:
        idx, since, interval, cpu = f[0], f[1], f[2], f[3]
        poll = f[4] if len(f) > 4 else 0.0
        swap = f[5] if len(f) > 5 else 0.0
        # where a gap went: the previous frame's render, its swap, the event pump, the rest of the loop
        other = max(0.0, interval - prev_cpu - swap - poll)
        by.setdefault(idx, []).append((since, interval, cpu, prev_cpu, swap, poll, other))
        prev_cpu = cpu
    rows = []
    first_slide = frames[0][0] if frames else None
    for idx in sorted(by):
        fs = by[idx]
        # the first frame's gap includes the slide change itself; it is reported as "first"
        first = fs[0][1] if fs else 0.0
        tr = [f for f in fs[1:] if f[0] <= transition]
        st = [f for f in fs if f[0] > transition]
        def summary(win):
            gaps = [f[1] for f in win]
            cpus = [f[2] for f in win]
            return {
                "frames": len(win),
                "max_gap_ms": round(max(gaps), 1) if gaps else 0.0,
                "missed": sum(1 for g in gaps if g > miss),
                "cpu_p95_ms": round(pct(cpus, 95), 1),
                "cpu_max_ms": round(max(cpus), 1) if cpus else 0.0,
            }
        t, s = summary(tr), summary(st)
        w = max(fs, key=lambda f: f[1]) if fs else None
        worst_frame = ({"at_s": round(w[0], 2), "gap_ms": round(w[1], 1), "prev_render_ms": round(w[3], 1),
                        "swap_ms": round(w[4], 1), "events_ms": round(w[5], 1), "other_ms": round(w[6], 1)}
                       if w else None)
        rows.append({"slide": idx + 1, "title": titles.get(idx, ""), "switch_ms": round(switch.get(idx, 0.0), 1),
                     "first_frame_ms": round(first, 1), "transition": t, "steady": s,
                     "worst_frame": worst_frame,
                     # the run's first slide opens with the window: its first frame is startup
                     "run_start": idx == first_slide,
                     # one number to rank by: the worst stall the audience sees around the change
                     "worst_ms": round(max(0.0 if idx == first_slide else first, t["max_gap_ms"]), 1)})
    return {"refresh_ms": round(refresh, 2), "miss_ms": round(miss, 2), "transition_s": transition,
            "slides": rows}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("record")
    ap.add_argument("--top", type=int, default=15, help="how many of the slowest slides to list")
    ap.add_argument("--transition", type=float, default=1.2,
                    help="seconds after a change that count as its transition (default 1.2)")
    ap.add_argument("--json", action="store_true", help="the whole analysis as JSON")
    a = ap.parse_args(argv)
    rec = json.load(open(a.record))
    res = analyse(rec, a.transition)
    if a.json:
        json.dump(res, sys.stdout, indent=1)
        print()
        return 0
    rows = res["slides"]
    hz = 1000.0 / res["refresh_ms"] if res["refresh_ms"] else 0
    print(f"{len(rows)} slides, refresh {res['refresh_ms']} ms (~{hz:.0f} Hz); a frame counts as missed past {res['miss_ms']} ms\n")
    worst = sorted(rows, key=lambda r: -r["worst_ms"])[:a.top]
    print(f"{'slide':>5}  {'worst':>7}  {'switch':>7}  {'first':>7}  {'tr gap':>7}  {'tr miss':>7}  {'tr cpu95':>8}  {'st miss':>7}  {'st cpu95':>8}  title")
    for r in worst:
        t, s = r["transition"], r["steady"]
        print(f"{r['slide']:>5}  {r['worst_ms']:>7.1f}  {r['switch_ms']:>7.1f}  {r['first_frame_ms']:>7.1f}  "
              f"{t['max_gap_ms']:>7.1f}  {t['missed']:>7}  {t['cpu_p95_ms']:>8.1f}  {s['missed']:>7}  {s['cpu_p95_ms']:>8.1f}  {r['title'][:48]}"
              + ("  (run start: its first frame is the window opening)" if r["run_start"] else ""))
    print("\nwhere the worst frame of each went (ms): gap = previous render + swap + events + other loop work")
    for r in worst:
        w = r["worst_frame"]
        if not w:
            continue
        print(f"  slide {r['slide']:>3} at {w['at_s']:>5.2f}s  gap {w['gap_ms']:>6.1f} = render {w['prev_render_ms']:>5.1f}"
              f" + swap {w['swap_ms']:>5.1f} + events {w['events_ms']:>5.1f} + other {w['other_ms']:>5.1f}")
    tot_tr = sum(r["transition"]["missed"] for r in rows)
    tot_st = sum(r["steady"]["missed"] for r in rows)
    print(f"\nmissed frames: {tot_tr} in transitions, {tot_st} while holding")
    return 0


if __name__ == "__main__":
    sys.exit(main())
