"""
YouFeelings — Step 5: Quota-efficient channel scraper
=====================================================
Expands the comment pool from 12 channels to the full 300-channel universe.

WHY THIS IS CHEAP
-----------------
The obvious approach uses search.list to find each channel's videos:
    search.list = 100 quota units  x 300 channels = 30,000 units = 3 days

This uses the uploads-playlist route instead:
    channels.list      1 unit   -> uploads playlist ID + metadata
    playlistItems.list 1 unit   -> up to 50 recent videos
    commentThreads.list 1 unit  -> up to 100 comments per page

    300 channels x (1 + 1 + VIDEOS_PER_CHANNEL x PAGES) ~= 3,000-6,000 units.
    Comfortably inside one day's 10,000-unit quota.

Channel IDs come free from the Takeout export (channel_lookup.csv produced by
01_ingest_watch_histories.py), so no name->ID resolution is needed at all.

BONUS: channels.list also returns subscriberCount / viewCount / videoCount,
which is exactly the metadata the SRS says content-based filtering should use
(category, subscriber count, average views, upload frequency). Written to
channel_metadata.csv so CBF can finally match the spec.

RESUMABLE
---------
State is checkpointed after every channel. If you hit the quota ceiling or
the process dies, just re-run tomorrow -- it skips what it already has.

Usage:
    export YOUTUBE_API_KEY=...
    python 04_scrape_channels.py --lookup channel_lookup.csv --max-channels 300

    # see the cost before spending any quota:
    python 04_scrape_channels.py --lookup channel_lookup.csv --estimate-only
"""

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime, timezone

import pandas as pd

try:
    import requests
except ImportError:
    sys.exit("pip install requests")

API = "https://www.googleapis.com/youtube/v3"

# Quota costs (YouTube Data API v3 published costs)
COST = {"channels.list": 1, "playlistItems.list": 1, "commentThreads.list": 1,
        "videos.list": 1, "search.list": 100}

URL_RE = re.compile(r"https?://\S+")
NONLATIN_RE = re.compile(r"[^\x00-\x7F]")


# ----------------------------------------------------------------------
# Quota tracking
# ----------------------------------------------------------------------
class QuotaTracker:
    def __init__(self, daily=10000, safety=500):
        self.daily, self.safety = daily, safety
        self.used = 0
        self.calls = {}
        self.errors = []

    def can_spend(self, endpoint, n=1):
        return self.used + COST[endpoint] * n <= self.daily - self.safety

    def spend(self, endpoint, n=1):
        self.used += COST[endpoint] * n
        self.calls[endpoint] = self.calls.get(endpoint, 0) + n

    @property
    def remaining(self):
        return self.daily - self.safety - self.used

    def summary(self):
        return {"quota_used": self.used, "quota_remaining": self.remaining,
                "api_calls": self.calls, "errors": self.errors[-50:]}


# ----------------------------------------------------------------------
# API helpers
# ----------------------------------------------------------------------
def api_get(endpoint, params, key, quota, retries=3):
    params = dict(params, key=key)
    url = f"{API}/{endpoint.split('.')[0]}"
    for attempt in range(retries):
        try:
            r = requests.get(url, params=params, timeout=30)
        except requests.RequestException as e:
            if attempt == retries - 1:
                quota.errors.append({"endpoint": endpoint, "error": str(e)})
                return None
            time.sleep(2 ** attempt)
            continue

        quota.spend(endpoint)

        if r.status_code == 200:
            return r.json()

        # 403 can mean quotaExceeded OR commentsDisabled -- very different things
        body = r.text[:300]
        if r.status_code == 403 and "quotaExceeded" in body:
            raise RuntimeError("QUOTA_EXCEEDED")
        if r.status_code in (403, 404):
            quota.errors.append({"endpoint": endpoint, "status": r.status_code,
                                 "detail": body[:120],
                                 "time": datetime.now(timezone.utc).isoformat()})
            return None
        if r.status_code == 429 or r.status_code >= 500:
            time.sleep(2 ** attempt)
            continue
        quota.errors.append({"endpoint": endpoint, "status": r.status_code,
                             "detail": body[:120]})
        return None
    return None


def get_channel_info(channel_ids, key, quota):
    """channels.list accepts up to 50 IDs per call -- batch them (1 unit each call)."""
    out = {}
    for i in range(0, len(channel_ids), 50):
        batch = channel_ids[i:i + 50]
        if not quota.can_spend("channels.list"):
            break
        data = api_get("channels.list",
                       {"part": "snippet,statistics,contentDetails",
                        "id": ",".join(batch), "maxResults": 50}, key, quota)
        if not data:
            continue
        for item in data.get("items", []):
            stats = item.get("statistics", {})
            content = item.get("contentDetails", {})
            snip = item.get("snippet", {})
            out[item["id"]] = {
                "channel_id": item["id"],
                "channel_title": snip.get("title", ""),
                "description": (snip.get("description", "") or "")[:500],
                "published_at": snip.get("publishedAt"),
                "country": snip.get("country"),
                "subscriber_count": int(stats.get("subscriberCount", 0) or 0),
                "view_count": int(stats.get("viewCount", 0) or 0),
                "video_count": int(stats.get("videoCount", 0) or 0),
                "uploads_playlist": content.get("relatedPlaylists", {}).get("uploads"),
            }
    return out


def get_playlist_videos(playlist_id, key, quota, max_videos=5):
    if not playlist_id or not quota.can_spend("playlistItems.list"):
        return []
    data = api_get("playlistItems.list",
                   {"part": "snippet,contentDetails", "playlistId": playlist_id,
                    "maxResults": min(50, max(max_videos, 5))}, key, quota)
    if not data:
        return []
    vids = []
    for item in data.get("items", []):
        vid = item.get("contentDetails", {}).get("videoId")
        if vid:
            vids.append({"video_id": vid,
                         "video_title": item.get("snippet", {}).get("title", ""),
                         "published_at": item.get("contentDetails", {}).get("videoPublishedAt")})
    return vids[:max_videos]


def get_comments(video_id, key, quota, max_comments=100):
    """commentThreads.list, 1 unit per page of up to 100."""
    out, token, fetched = [], None, 0
    while fetched < max_comments:
        if not quota.can_spend("commentThreads.list"):
            break
        params = {"part": "snippet", "videoId": video_id,
                  "maxResults": min(100, max_comments - fetched),
                  "textFormat": "plainText", "order": "relevance"}
        if token:
            params["pageToken"] = token
        data = api_get("commentThreads.list", params, key, quota)
        if not data:
            break  # comments disabled / video gone -- skip, don't halt the batch
        for item in data.get("items", []):
            s = item["snippet"]["topLevelComment"]["snippet"]
            out.append({
                "comment_id": item["id"],
                "author": s.get("authorDisplayName", ""),
                "text": s.get("textDisplay", ""),
                "like_count": int(s.get("likeCount", 0) or 0),
                "published_at": s.get("publishedAt"),
            })
        fetched = len(out)
        token = data.get("nextPageToken")
        if not token:
            break
    return out


# ----------------------------------------------------------------------
# Cleaning (mirrors the existing preprocessing rules)
# ----------------------------------------------------------------------
def clean_comments(rows, min_len=20, max_len=1000):
    kept, stats = [], {"total": len(rows), "too_short": 0, "too_long": 0,
                       "not_english": 0, "spam": 0, "passed": 0}
    for r in rows:
        t = (r.get("text") or "").strip()
        if len(t) < min_len:
            stats["too_short"] += 1
            continue
        if len(t) > max_len:
            stats["too_long"] += 1
            continue
        # crude English heuristic: mostly-ASCII
        if len(NONLATIN_RE.findall(t)) > len(t) * 0.3:
            stats["not_english"] += 1
            continue
        # spam: link-heavy, or long runs of one character
        if len(URL_RE.findall(t)) >= 2 or re.search(r"(.)\1{7,}", t):
            stats["spam"] += 1
            continue
        kept.append({**r, "text": t})
        stats["passed"] += 1
    return kept, stats


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lookup", default="channel_lookup.csv",
                    help="From 01_ingest (channel_name, channel_id, in_universe)")
    ap.add_argument("--out-comments", default="comments_raw_expanded.csv")
    ap.add_argument("--out-metadata", default="channel_metadata.csv")
    ap.add_argument("--state", default="scrape_state.json")
    ap.add_argument("--report", default="scrape_report_expanded.json")
    ap.add_argument("--max-channels", type=int, default=300)
    ap.add_argument("--videos-per-channel", type=int, default=3)
    ap.add_argument("--comments-per-video", type=int, default=100)
    ap.add_argument("--daily-quota", type=int, default=10000)
    ap.add_argument("--safety-margin", type=int, default=500)
    ap.add_argument("--estimate-only", action="store_true",
                    help="Print projected quota cost and exit without calling the API")
    args = ap.parse_args()

    lookup = pd.read_csv(args.lookup)
    if "in_universe" in lookup.columns:
        lookup = lookup[lookup["in_universe"] == 1]
    lookup = lookup.dropna(subset=["channel_id"]).head(args.max_channels)
    n = len(lookup)

    pages_per_video = max(1, args.comments_per_video // 100)
    projected = (
        (n / 50) * COST["channels.list"]
        + n * COST["playlistItems.list"]
        + n * args.videos_per_channel * pages_per_video * COST["commentThreads.list"]
    )
    print(f"Channels to scrape           : {n}")
    print(f"Videos per channel           : {args.videos_per_channel}")
    print(f"Comments per video           : {args.comments_per_video}")
    print(f"Projected quota cost         : ~{projected:,.0f} units "
          f"of {args.daily_quota:,}")
    print(f"  (search.list route would be ~{n * 100:,} units)")
    if args.estimate_only:
        return
    if projected > args.daily_quota - args.safety_margin:
        print("\nWARNING: projected cost exceeds today's quota. The run will stop\n"
              "         cleanly at the ceiling and resume where it left off tomorrow.")

    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        sys.exit("Set YOUTUBE_API_KEY environment variable.")

    # ---- resume ----
    state = {"done_channels": [], "quota_used_today": 0, "date": str(datetime.now().date())}
    if os.path.exists(args.state):
        state = json.load(open(args.state))
        if state.get("date") != str(datetime.now().date()):
            state = {"done_channels": state.get("done_channels", []),
                     "quota_used_today": 0, "date": str(datetime.now().date())}
        print(f"\nResuming: {len(state['done_channels'])} channel(s) already scraped")

    done = set(state["done_channels"])
    todo = lookup[~lookup["channel_id"].isin(done)]
    print(f"Remaining this run           : {len(todo)}\n")

    quota = QuotaTracker(args.daily_quota, args.safety_margin)

    # existing outputs (append mode across days)
    all_comments = []
    if os.path.exists(args.out_comments):
        all_comments = pd.read_csv(args.out_comments).to_dict("records")
    all_meta = []
    if os.path.exists(args.out_metadata):
        all_meta = pd.read_csv(args.out_metadata).to_dict("records")

    # ---- 1. channel metadata (batched, 1 unit per 50) ----
    ids = todo["channel_id"].tolist()
    print("Fetching channel metadata ...")
    try:
        info = get_channel_info(ids, key, quota)
    except RuntimeError:
        print("Quota exceeded during metadata fetch. Re-run tomorrow.")
        info = {}
    print(f"  got metadata for {len(info)} channel(s)  (quota used {quota.used})\n")

    name_by_id = dict(zip(lookup["channel_id"], lookup["channel_name"]))
    clean_stats_total = {"total": 0, "too_short": 0, "too_long": 0,
                         "not_english": 0, "spam": 0, "passed": 0}
    stopped_early = False

    # ---- 2. per channel: videos -> comments ----
    for i, (cid, meta) in enumerate(info.items(), start=1):
        if not quota.can_spend("commentThreads.list"):
            print("\nQuota ceiling reached — stopping cleanly.")
            stopped_early = True
            break

        title = meta["channel_title"] or name_by_id.get(cid, cid)
        try:
            vids = get_playlist_videos(meta["uploads_playlist"], key, quota,
                                       args.videos_per_channel)
            got = 0
            for v in vids:
                raw = get_comments(v["video_id"], key, quota, args.comments_per_video)
                cleaned, st = clean_comments(raw)
                for k in clean_stats_total:
                    clean_stats_total[k] += st[k]
                for c in cleaned:
                    all_comments.append({
                        "channel_id": cid,
                        "channel_title": title,
                        "video_id": v["video_id"],
                        "video_title": v["video_title"],
                        **c,
                    })
                got += len(cleaned)
        except RuntimeError:
            print("\nQuota exceeded mid-channel — stopping cleanly.")
            stopped_early = True
            break

        # derive upload frequency for CBF
        meta_row = dict(meta)
        try:
            started = datetime.fromisoformat(
                (meta.get("published_at") or "").replace("Z", "+00:00"))
            months = max((datetime.now(timezone.utc) - started).days / 30.44, 1)
            meta_row["uploads_per_month"] = round(meta["video_count"] / months, 3)
        except Exception:
            meta_row["uploads_per_month"] = None
        meta_row["avg_views_per_video"] = (
            round(meta["view_count"] / meta["video_count"], 1)
            if meta["video_count"] else 0
        )
        all_meta.append(meta_row)

        done.add(cid)
        state["done_channels"] = sorted(done)
        state["quota_used_today"] = quota.used
        with open(args.state, "w") as f:
            json.dump(state, f)

        print(f"  [{i}/{len(info)}] {title[:38]:38s} +{got:4d} comments  "
              f"(quota {quota.used}/{args.daily_quota})")

    # ---- 3. write ----
    if all_comments:
        pd.DataFrame(all_comments).drop_duplicates("comment_id").to_csv(
            args.out_comments, index=False)
    if all_meta:
        pd.DataFrame(all_meta).drop_duplicates("channel_id").to_csv(
            args.out_metadata, index=False)

    report = {
        "run_timestamp": datetime.now(timezone.utc).isoformat(),
        "channels_completed_total": len(done),
        "channels_this_run": len(info) if not stopped_early else i,
        "comments_total": len(all_comments),
        "cleaning": clean_stats_total,
        "pass_rate": (f"{clean_stats_total['passed'] / clean_stats_total['total']:.1%}"
                      if clean_stats_total["total"] else "n/a"),
        "quota": quota.summary(),
        "stopped_early": stopped_early,
    }
    with open(args.report, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\nComments total : {len(all_comments):,}")
    print(f"Channels done  : {len(done)}/{n}")
    print(f"Quota used     : {quota.used:,}")
    if stopped_early:
        print("\nRe-run tomorrow to continue — progress is saved in "
              f"{args.state}.")
    print(f"\nWrote {args.out_comments}, {args.out_metadata}, {args.report}")


if __name__ == "__main__":
    main()
