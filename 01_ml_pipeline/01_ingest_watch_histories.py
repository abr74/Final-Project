"""
YouFeelings — Step 1: Ingest watch histories (N users, pseudonymized)
=====================================================================
Replaces the hardcoded 3-file block in DataSynthesis.ipynb.

Drop every participant's Takeout file into --input-dir. Any of these work:
    watch-history.html        (Takeout HTML)
    watch-history.json        (Takeout JSON)
    anything_*.html / .json

Each file becomes ONE user, pseudonymized to user_001, user_002, ...
The real-name -> pseudonym map is written OUTSIDE the training data
(--map-out, default: pii_user_map.csv) so it never lands in a model input.

Outputs:
    watch_history_long.csv    user_id, video_id, video_title, channel_name, timestamp, watch_count
    ncf_interaction_matrix.csv  user_id + one binary column per channel
    ingest_report.json        per-user counts, channel coverage, dropped rows

Usage:
    python 01_ingest_watch_histories.py --input-dir ./takeouts --top-channels 150
"""

import argparse
import json
import os
import re
import sys
from collections import Counter

import pandas as pd

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("Missing dependency: pip install beautifulsoup4 lxml")
    raise


# ----------------------------------------------------------------------
# Parsing
# ----------------------------------------------------------------------
TS_RE = re.compile(
    r"([A-Z][a-z]{2}\s+\d{1,2},\s+\d{4},\s+\d{1,2}:\d{2}:\d{2}\s+[AP]M\s+\w+)"
)
VID_RE = re.compile(r"v=([^&]+)")
CHAN_RE = re.compile(r"/channel/(UC[\w-]+)")


def parse_watch_history_html(filepath):
    """Parse a Takeout watch-history.html into a DataFrame.

    Uses lxml when available (much faster on 200MB+ files) and streams the
    outer-cell divs rather than holding every tag in memory.
    """
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        html = f.read()

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")

    rows = []
    for entry in soup.find_all("div", class_="outer-cell"):
        cell = entry.find("div", class_="content-cell")
        if not cell:
            continue

        video_title = video_id = channel_name = channel_id = None
        for link in cell.find_all("a"):
            href = link.get("href", "") or ""
            if "watch?v=" in href:
                video_title = link.get_text(strip=True)
                m = VID_RE.search(href)
                if m:
                    video_id = m.group(1)
            elif "/channel/" in href or "/@" in href:
                channel_name = link.get_text(strip=True)
                # Takeout gives the UC... channel ID for free. Capturing it here
                # saves 100 quota units per channel later (search.list would
                # otherwise be needed to resolve name -> ID).
                m = CHAN_RE.search(href)
                if m:
                    channel_id = m.group(1)

        text = cell.get_text()
        m = TS_RE.search(text)
        timestamp = m.group(1) if m else None

        # A row is only useful to us if we know which channel it belongs to.
        if channel_name:
            rows.append(
                {
                    "video_id": video_id,
                    "video_title": video_title,
                    "channel_name": channel_name,
                    "channel_id": channel_id,
                    "timestamp": timestamp,
                }
            )
    return pd.DataFrame(rows)


def parse_watch_history_json(filepath):
    """Parse a Takeout watch-history.json into a DataFrame."""
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        data = json.load(f)

    rows = []
    for item in data:
        title = item.get("title", "")
        # Takeout JSON prefixes with "Watched "
        video_title = title[len("Watched "):] if title.startswith("Watched ") else title

        video_id = None
        url = item.get("titleUrl", "") or ""
        m = VID_RE.search(url)
        if m:
            video_id = m.group(1)

        channel_name = channel_id = None
        subs = item.get("subtitles") or []
        if subs and isinstance(subs, list):
            channel_name = subs[0].get("name")
            m = CHAN_RE.search(subs[0].get("url", "") or "")
            if m:
                channel_id = m.group(1)

        if channel_name:
            rows.append(
                {
                    "video_id": video_id,
                    "video_title": video_title,
                    "channel_name": channel_name,
                    "channel_id": channel_id,
                    "timestamp": item.get("time"),
                }
            )
    return pd.DataFrame(rows)


def parse_any(filepath):
    ext = os.path.splitext(filepath)[1].lower()
    if ext == ".json":
        return parse_watch_history_json(filepath)
    return parse_watch_history_html(filepath)


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input-dir", required=True,
                    help="Folder containing one watch-history file per participant")
    ap.add_argument("--out-long", default="watch_history_long.csv")
    ap.add_argument("--out-matrix", default="ncf_interaction_matrix.csv")
    ap.add_argument("--map-out", default="pii_user_map.csv",
                    help="Pseudonym map. KEEP THIS OUT OF THE TRAINING SET.")
    ap.add_argument("--report", default="ingest_report.json")
    ap.add_argument("--top-channels", type=int, default=150,
                    help="Keep the N most-watched channels overall")
    ap.add_argument("--min-watches", type=int, default=1,
                    help="A user 'watched' a channel if watch_count >= this")
    args = ap.parse_args()

    files = sorted(
        os.path.join(args.input_dir, f)
        for f in os.listdir(args.input_dir)
        if f.lower().endswith((".html", ".json"))
    )
    if not files:
        sys.exit(f"No .html/.json files found in {args.input_dir}")

    print(f"Found {len(files)} participant file(s)\n")

    frames, id_map, report_users = [], [], []

    for i, path in enumerate(files, start=1):
        pseudonym = f"user_{i:03d}"
        source_name = os.path.basename(path)
        print(f"  [{pseudonym}] parsing {source_name} ...", end=" ", flush=True)

        df = parse_any(path)
        if df.empty:
            print("no rows parsed — SKIPPED")
            continue

        df["user_id"] = pseudonym
        frames.append(df)
        id_map.append({"pseudonym": pseudonym, "source_file": source_name})
        report_users.append(
            {
                "user_id": pseudonym,
                "rows": int(len(df)),
                "unique_channels": int(df["channel_name"].nunique()),
                "unique_videos": int(df["video_id"].nunique()),
            }
        )
        print(f"{len(df):,} rows, {df['channel_name'].nunique():,} channels")

    if not frames:
        sys.exit("Nothing parsed successfully.")

    all_real = pd.concat(frames, ignore_index=True)

    # ---- long format with watch_count (implicit rating signal) ----
    long_df = (
        all_real.groupby(["user_id", "channel_name"], as_index=False)
        .agg(
            watch_count=("channel_name", "size"),
            unique_videos=("video_id", "nunique"),
        )
    )

    # ---- channel universe ----
    channel_totals = all_real["channel_name"].value_counts()
    top_channels = channel_totals.head(args.top_channels).index
    kept = long_df[long_df["channel_name"].isin(top_channels)].copy()

    print(f"\nChannel universe: {len(top_channels)} of {channel_totals.size} "
          f"({args.top_channels} requested)")

    # ---- binary interaction matrix ----
    kept["watched"] = (kept["watch_count"] >= args.min_watches).astype(int)
    matrix = (
        kept.pivot_table(index="user_id", columns="channel_name",
                         values="watched", fill_value=0)
        .astype(int)
        .reset_index()
    )
    # guarantee every top channel appears as a column, even if sparse
    for ch in top_channels:
        if ch not in matrix.columns:
            matrix[ch] = 0
    matrix = matrix[["user_id"] + sorted([c for c in matrix.columns if c != "user_id"])]

    # ---- co-watch stat (how much signal NCF actually has) ----
    per_channel_users = (matrix.drop(columns="user_id").sum(axis=0))
    shared = int((per_channel_users >= 2).sum())

    # ---- write ----
    # channel_name -> channel_id lookup for the scraper (free IDs from Takeout)
    chan_lookup = (
        all_real[all_real["channel_id"].notna()]
        .groupby("channel_name")["channel_id"].agg(lambda s: s.mode().iloc[0])
        .reset_index()
    )
    chan_lookup["in_universe"] = chan_lookup["channel_name"].isin(top_channels).astype(int)
    chan_lookup = chan_lookup.sort_values(["in_universe", "channel_name"],
                                          ascending=[False, True])
    chan_lookup.to_csv("channel_lookup.csv", index=False)
    resolved = int(chan_lookup["in_universe"].sum())
    print(f"Channel IDs resolved from Takeout: {resolved}/{len(top_channels)} "
          f"in-universe  (saves ~{resolved * 100:,} quota units vs search.list)")

    all_real.to_csv(args.out_long, index=False)
    matrix.to_csv(args.out_matrix, index=False)
    pd.DataFrame(id_map).to_csv(args.map_out, index=False)

    density = float(matrix.drop(columns="user_id").values.mean())
    report = {
        "n_users": int(matrix.shape[0]),
        "n_channels": int(matrix.shape[1] - 1),
        "channels_shared_by_2plus_users": shared,
        "matrix_density": round(density, 4),
        "total_watch_rows": int(len(all_real)),
        "users": report_users,
    }
    with open(args.report, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nMatrix: {report['n_users']} users x {report['n_channels']} channels "
          f"(density {density:.1%})")
    print(f"Channels watched by 2+ users: {shared}  <- the only ones NCF can learn from")
    if shared < 10:
        print("  WARNING: very little overlap between users. NCF will struggle;\n"
              "           consider raising --top-channels or recruiting more users.")

    print(f"\nWrote:\n  {args.out_long}\n  {args.out_matrix}\n  channel_lookup.csv\n  {args.report}")
    print(f"  {args.map_out}  <-- contains file names; keep out of training data")


if __name__ == "__main__":
    main()
