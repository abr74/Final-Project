"""
YouFeelings — Step 9: Build serving artifacts for the Lambda
============================================================
Replaces generate_lookup_tables.py, which targeted the old 12-channel files
and the old user IDs (sam / ashab / tai).

THE COLD-START PROBLEM THIS SOLVES
----------------------------------
A brand-new visitor uploads their Takeout. They have no NCF row -- the model
has never seen them. The serving layer must still produce personalized,
explained recommendations from:

    1. the channels in their upload            (known at request time)
    2. per-channel aspect vectors              (bert_scores.json)
    3. channel-to-channel content similarity   (channel_similar.json)
    4. aspect reliability weights              (aspect_reliability.json)

That is exactly the BERT + content path in 03_fusion.py, with NCF's 35%
redistributed. Returning users who exist in ncf_scores.json get the full
three-signal fusion.

OUTPUTS (upload all to s3://netfeeling/models/)
-----------------------------------------------
    bert_scores.json        {channel: {aspect: score, bert_overall: score}}
    channel_similar.json    {channel: [[neighbour, similarity], ...]}  top-N
    channel_meta.json       {channel: {title, subs, avg_views, uploads_pm}}
    channel_videos.json     {channel: {video_id, title, url}}
    ncf_scores.json         {user_id: {channel: score}}  REAL users only
    aspect_reliability.json {aspect: weight}
    serving_manifest.json   sizes, counts, build timestamp

Usage:
    python 08_build_serving_artifacts.py
"""

import argparse
import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

ASPECTS = ["content", "entertainment", "creator", "production", "informativeness"]


def build_bert_scores(scored, min_comments=3):
    """Per-channel aspect vectors, with the same confidence shrink as fusion."""
    out = {}
    for ch, sub in scored.groupby("channel_title"):
        vec = {}
        for aspect in ASPECTS:
            col = f"{aspect}_sentiment"
            if col not in sub.columns:
                vec[aspect] = 0.5
                continue
            pos = int((sub[col] == "positive").sum())
            neg = int((sub[col] == "negative").sum())
            total = pos + neg
            if total == 0:
                vec[aspect] = 0.5
            else:
                raw = ((pos - neg) / total + 1) / 2
                shrink = total / (total + min_comments)
                vec[aspect] = round(0.5 + (raw - 0.5) * shrink, 4)
        vec["bert_overall"] = round(sum(vec[a] for a in ASPECTS) / len(ASPECTS), 4)
        vec["n_comments"] = int(len(sub))
        out[str(ch)] = vec
    return out


def build_channel_similarity(metadata_path, channels, top_n=25):
    """Top-N most similar channels per channel, from the TF-IDF feature space.

    Shipping a top-N neighbour list instead of the full NxN matrix keeps the
    artifact small enough for a Lambda cold start (261x261 floats would be
    ~550KB of JSON; top-25 is ~10x smaller and is all the serving layer needs).
    """
    import importlib.util
    here = os.path.dirname(os.path.abspath(__file__))
    spec = importlib.util.spec_from_file_location(
        "cf", os.path.join(here, "06_content_features.py"))
    cf = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cf)

    meta, feats = cf.build_channel_features(metadata_path)
    names = list(meta.index)
    keep = [i for i, n in enumerate(names) if n in channels]
    if not keep:
        return {}, meta

    sims = feats[keep] @ feats[keep].T
    kept_names = [names[i] for i in keep]
    out = {}
    for i, name in enumerate(kept_names):
        row = sims[i].copy()
        row[i] = -1
        order = np.argsort(-row)[:top_n]
        out[str(name)] = [[str(kept_names[j]), round(float(row[j]), 4)]
                          for j in order if row[j] > 0]
    return out, meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scored", default="comments_scored_expanded.csv")
    ap.add_argument("--metadata", default="channel_metadata.csv")
    ap.add_argument("--raw-comments", default="comments_raw_expanded.csv")
    ap.add_argument("--ncf", default="ncf_scores.csv")
    ap.add_argument("--matrix", default="combined_matrix.csv")
    ap.add_argument("--reliability", default="aspect_reliability.json")
    ap.add_argument("--out-dir", default="serving")
    ap.add_argument("--top-n-similar", type=int, default=25)
    args = ap.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    manifest = {"built_at": datetime.now(timezone.utc).isoformat()}

    # ---- 1. BERT aspect scores ----
    scored = pd.read_csv(args.scored)
    bert_scores = build_bert_scores(scored)
    channels = set(bert_scores)
    print(f"bert_scores      : {len(bert_scores)} channels")

    # ---- 2. content similarity ----
    similar, meta = ({}, None)
    if os.path.exists(args.metadata):
        similar, meta = build_channel_similarity(args.metadata, channels,
                                                 args.top_n_similar)
        print(f"channel_similar  : {len(similar)} channels "
              f"(top {args.top_n_similar} each)")
    else:
        print("channel_similar  : SKIPPED (no channel_metadata.csv)")

    # ---- 3. channel metadata for display ----
    channel_meta = {}
    if meta is not None:
        for ch in channels:
            if ch in meta.index:
                r = meta.loc[ch]
                channel_meta[str(ch)] = {
                    "subscriber_count": int(r.get("subscriber_count", 0) or 0),
                    "avg_views_per_video": float(r.get("avg_views_per_video", 0) or 0),
                    "uploads_per_month": float(r.get("uploads_per_month", 0) or 0),
                }
    print(f"channel_meta     : {len(channel_meta)} channels")

    # ---- 4. representative video per channel ----
    channel_videos = {}
    if os.path.exists(args.raw_comments):
        raw = pd.read_csv(args.raw_comments)
        for ch, sub in raw.groupby("channel_title"):
            if ch not in channels or sub.empty:
                continue
            top_vid = sub["video_id"].value_counts().idxmax()
            row = sub[sub["video_id"] == top_vid].iloc[0]
            channel_videos[str(ch)] = {
                "video_id": str(top_vid),
                "video_title": str(row.get("video_title", "")),
                "url": f"https://www.youtube.com/watch?v={top_vid}",
            }
    print(f"channel_videos   : {len(channel_videos)} channels")

    # ---- 5. NCF scores, REAL users only ----
    ncf_nested = {}
    if os.path.exists(args.ncf):
        ncf = pd.read_csv(args.ncf)
        real_ids = None
        if os.path.exists(args.matrix):
            m = pd.read_csv(args.matrix)
            if "is_synthetic" in m.columns:
                real_ids = set(m.loc[m["is_synthetic"] == 0, "user_id"])
        if real_ids is not None:
            ncf = ncf[ncf["user_id"].isin(real_ids)]
        for uid, g in ncf.groupby("user_id"):
            ncf_nested[str(uid)] = {
                str(r["channel"]): round(float(r["ncf_score"]), 4)
                for _, r in g.iterrows() if r["channel"] in channels
            }
    print(f"ncf_scores       : {len(ncf_nested)} users "
          f"(synthetic excluded from serving)")
    # Guard against a stale ncf_scores.csv built on a different channel
    # universe -- the Lambda would silently serve BERT+content only.
    if ncf_nested:
        covered = sum(1 for v in ncf_nested.values() if v)
        if covered == 0:
            print("  WARNING: no NCF entry overlaps the scored channel set.\n"
                  "           ncf_scores.csv is stale — retrain NCF on the "
                  "current matrix,\n           or the Lambda will serve "
                  "BERT+content only for every user.")
        elif covered < len(ncf_nested):
            print(f"  NOTE: {len(ncf_nested) - covered} user(s) have no "
                  f"overlapping channels.")

    # ---- 6. aspect reliability ----
    reliability = {a: 1.0 for a in ASPECTS}
    if os.path.exists(args.reliability):
        reliability = json.load(open(args.reliability)).get("reliability", reliability)
    print(f"reliability      : {reliability}")

    # ---- write ----
    artifacts = {
        "bert_scores.json": bert_scores,
        "channel_similar.json": similar,
        "channel_meta.json": channel_meta,
        "channel_videos.json": channel_videos,
        "ncf_scores.json": ncf_nested,
        "aspect_reliability.json": reliability,
    }
    print()
    for name, obj in artifacts.items():
        path = os.path.join(args.out_dir, name)
        with open(path, "w") as f:
            json.dump(obj, f, separators=(",", ":"))
        kb = os.path.getsize(path) / 1024
        manifest[name] = {"entries": len(obj), "kb": round(kb, 1)}
        print(f"  {name:26s} {len(obj):>5} entries  {kb:>8.1f} KB")

    total_kb = sum(v["kb"] for k, v in manifest.items() if isinstance(v, dict))
    manifest["total_kb"] = round(total_kb, 1)
    with open(os.path.join(args.out_dir, "serving_manifest.json"), "w") as f:
        json.dump(manifest, f, indent=2)

    print(f"\nTotal serving payload: {total_kb:.1f} KB")
    if total_kb > 5000:
        print("  WARNING: >5MB. Consider trimming --top-n-similar or the "
              "channel universe for Lambda cold-start time.")

    print(f"\nUpload:\n  aws s3 cp {args.out_dir}/ s3://netfeeling/models/ "
          f"--recursive --exclude '*' --include '*.json'")


if __name__ == "__main__":
    main()
