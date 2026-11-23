#!/usr/bin/env python3
"""
collect_fr_hooks.py - build a French hook corpus from public YouTube Shorts.

Same method as the original author's test (see README): for each channel,
take its recent Shorts, keep the top N and bottom N by views, and pull the
first 3 seconds of the French auto-captions. That spoken first line is the
hook, as said, not as written. Public data only, no login, small volume.

Needs yt-dlp (pip install yt-dlp) and network access to youtube.com.

Usage
  python3 collect_fr_hooks.py --search "trouver des clients freelance" --search "site internet entrepreneur" --out corpus.tsv
  python3 collect_fr_hooks.py --channel @SomeChannel --channel @Other --per-band 4 --out corpus.tsv

Output: TSV with account, followers (empty), median, views, band, video_id, hook.
It plugs straight into ig-viral/swipe.py and into tests/calibrate_fr.py.
"""

import argparse
import json
import os
import re
import statistics
import subprocess
import sys
import tempfile

YTDLP = [sys.executable, "-m", "yt_dlp", "--quiet", "--no-warnings", "--ignore-errors"]


def ytdlp_json(args, timeout=120):
    try:
        out = subprocess.run(YTDLP + args, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return []
    items = []
    for line in out.stdout.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                items.append(json.loads(line))
            except ValueError:
                pass
    return items


def search_channels(queries, per_query):
    """Find French Shorts channels from search queries. Returns {channel_url: count}."""
    found = {}
    for q in queries:
        for v in ytdlp_json(["--flat-playlist", "-j", f"ytsearch{per_query}:{q} #shorts"]):
            url = v.get("channel_url") or (f"https://www.youtube.com/channel/{v['channel_id']}"
                                           if v.get("channel_id") else None)
            if url:
                found[url] = found.get(url, 0) + 1
    return found


def channel_shorts(channel, limit):
    url = channel if channel.startswith("http") else f"https://www.youtube.com/{channel}"
    url = url.rstrip("/") + "/shorts"
    rows = []
    for v in ytdlp_json(["--flat-playlist", "-j", "--playlist-end", str(limit), url]):
        if v.get("id") and v.get("view_count") is not None:
            rows.append({"id": v["id"], "views": int(v["view_count"]),
                         "channel": v.get("playlist_uploader") or v.get("channel") or channel})
    return rows


def first_seconds(video_id, seconds=3.0):
    """Words of the French auto-captions spoken before `seconds`."""
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(YTDLP + ["--skip-download", "--write-auto-subs", "--write-subs",
                                "--sub-langs", "fr.*,fr", "--sub-format", "json3",
                                "-o", os.path.join(tmp, "s"),
                                f"https://www.youtube.com/watch?v={video_id}"],
                       capture_output=True, text=True, timeout=120)
        files = [f for f in os.listdir(tmp) if f.endswith(".json3")]
        if not files:
            return ""
        data = json.load(open(os.path.join(tmp, sorted(files)[0]), encoding="utf-8"))
    words = []
    for ev in data.get("events", []):
        start = ev.get("tStartMs", 0)
        for seg in ev.get("segs") or []:
            t = (start + seg.get("tOffsetMs", 0)) / 1000
            txt = seg.get("utf8", "").strip()
            if txt and t < seconds:
                words.append(txt)
    return re.sub(r"\s+", " ", " ".join(words)).strip()


def main():
    ap = argparse.ArgumentParser(description="French hook corpus from public Shorts.")
    ap.add_argument("--channel", action="append", default=[], help="@handle or channel URL")
    ap.add_argument("--search", action="append", default=[], help="search query to find channels")
    ap.add_argument("--per-query", type=int, default=30)
    ap.add_argument("--max-channels", type=int, default=6)
    ap.add_argument("--shorts", type=int, default=40, help="recent Shorts per channel")
    ap.add_argument("--per-band", type=int, default=4, help="top N and bottom N per channel")
    ap.add_argument("--out", default="corpus.tsv")
    args = ap.parse_args()

    channels = list(args.channel)
    if args.search:
        found = search_channels(args.search, args.per_query)
        ranked = sorted(found, key=lambda c: -found[c])
        channels += [c for c in ranked if c not in channels]
    if not channels:
        sys.exit("give --channel or --search")

    out_rows, used = [], 0
    for ch in channels:
        if used >= args.max_channels:
            break
        shorts = channel_shorts(ch, args.shorts)
        if len(shorts) < args.per_band * 2 + 2:
            print(f"skip {ch}: {len(shorts)} shorts", file=sys.stderr)
            continue
        med = int(statistics.median(s["views"] for s in shorts))
        ranked = sorted(shorts, key=lambda s: -s["views"])
        picked = [("top", s) for s in ranked[:args.per_band]] + \
                 [("bottom", s) for s in ranked[-args.per_band:]]
        got = 0
        for band, s in picked:
            hook = first_seconds(s["id"])
            if not hook:
                continue
            out_rows.append([s["channel"], "", str(med), str(s["views"]), band, s["id"], hook])
            got += 1
        print(f"{ch}: median {med}, {got} hooks", file=sys.stderr)
        if got:
            used += 1

    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write("account\tfollowers\tmedian\tviews\tband\tvideo_id\thook\n")
        for r in out_rows:
            fh.write("\t".join(c.replace("\t", " ") for c in r) + "\n")
    print(f"wrote {args.out}: {len(out_rows)} hooks from {used} channels", file=sys.stderr)


if __name__ == "__main__":
    main()
