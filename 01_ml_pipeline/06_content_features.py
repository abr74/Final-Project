"""
YouFeelings — Content-Based Filtering (TF-IDF over channel metadata)
====================================================================
Replaces the category-share stand-in inside 03_fusion.py.

WHY
---
The old content score was:

    share of the user's watched channels that fall in this channel's category

That needed a `category` column, which only existed for the original 12
channels (comments_pool_12.csv). For the other 249 scraped channels the
category is unknown, so every one of them scored 0 -- the content signal
would silently contribute nothing across 83% of the catalog.

It also did not match the SRS, which specifies (R3.3.3.1/R3.3.3.2):
    "channel metadata (category, subscriber count, average view count,
     upload frequency) ... ranked by TF-IDF cosine similarity"

WHAT THIS DOES
--------------
Builds a feature vector per channel from channel_metadata.csv:

  text features   : TF-IDF over the channel description + title
  numeric features: log10(subscribers), log10(avg views/video),
                    uploads/month, log10(video count)
                    -- log-scaled because these span many orders of
                       magnitude, then min-max normalized so no single
                       feature dominates the cosine

A user profile is the mean vector of the channels they watch. Content score
for a candidate = cosine similarity between the user vector and the channel
vector. Cold start (no watch history) returns zeros so the fusion layer can
redistribute the weight instead of inventing a preference.

Usage (standalone, writes a reusable matrix):
    python 06_content_features.py --metadata channel_metadata.csv

Imported by 03_fusion.py automatically when channel_metadata.csv is present.
"""

import argparse

import numpy as np
import pandas as pd


def build_channel_features(metadata_path, max_text_features=300, text_weight=0.75):
    """Return (DataFrame indexed by channel_title, feature matrix ndarray)."""
    from sklearn.feature_extraction.text import TfidfVectorizer

    meta = pd.read_csv(metadata_path)
    meta = meta.dropna(subset=["channel_title"]).drop_duplicates("channel_title")
    meta = meta.set_index("channel_title")

    # ---- text: description + title ----
    text = (meta.get("channel_title", pd.Series(index=meta.index, dtype=str)).fillna("").astype(str)
            + " "
            + meta.get("description", pd.Series(index=meta.index, dtype=str)).fillna("").astype(str))
    vec = TfidfVectorizer(max_features=max_text_features, stop_words="english",
                          ngram_range=(1, 2), min_df=1)
    try:
        text_mat = vec.fit_transform(text).toarray()
    except ValueError:
        # every description empty / vocabulary too small
        text_mat = np.zeros((len(meta), 1))

    # ---- numeric: log-scaled, min-max normalized ----
    def logcol(name):
        v = pd.to_numeric(meta.get(name, 0), errors="coerce").fillna(0).clip(lower=0)
        return np.log10(v + 1)

    numeric = np.column_stack([
        logcol("subscriber_count"),
        logcol("avg_views_per_video"),
        pd.to_numeric(meta.get("uploads_per_month", 0), errors="coerce").fillna(0).clip(0, 100),
        logcol("video_count"),
    ])
    lo, hi = numeric.min(axis=0), numeric.max(axis=0)
    span = np.where(hi - lo < 1e-9, 1.0, hi - lo)
    numeric = (numeric - lo) / span

    # Normalize the two blocks SEPARATELY before combining.
    # Without this the 4 dense numeric columns dominate a sparse TF-IDF block
    # and cosine similarity ends up measuring "similar subscriber count"
    # rather than "similar topic" -- e.g. 3Blue1Brown matching Rick Astley.
    def l2(block):
        n = np.linalg.norm(block, axis=1, keepdims=True)
        return block / np.where(n < 1e-9, 1.0, n)

    features = np.hstack([l2(text_mat) * text_weight,
                          l2(numeric) * (1.0 - text_weight)])
    # L2-normalize rows so cosine is a plain dot product
    norms = np.linalg.norm(features, axis=1, keepdims=True)
    features = features / np.where(norms < 1e-9, 1.0, norms)

    return meta, features


def content_scores_tfidf(watched, channels, meta_index, features):
    """Cosine similarity between the user's mean watched vector and each channel."""
    pos = {ch: i for i, ch in enumerate(meta_index)}
    idxs = [pos[c] for c in watched if c in pos]
    if not idxs:
        return {c: 0.0 for c in channels}

    user_vec = features[idxs].mean(axis=0)
    n = np.linalg.norm(user_vec)
    if n < 1e-9:
        return {c: 0.0 for c in channels}
    user_vec = user_vec / n

    sims = features @ user_vec                      # rows already L2-normalized
    sims = np.clip(sims, 0, None)                   # negatives are not "less similar"
    return {c: float(sims[pos[c]]) if c in pos else 0.0 for c in channels}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--metadata", default="channel_metadata.csv")
    ap.add_argument("--out", default="channel_features.npz")
    ap.add_argument("--text-weight", type=float, default=0.75,
                    help="Share of the vector from description text vs popularity stats")
    args = ap.parse_args()

    meta, feats = build_channel_features(args.metadata, text_weight=args.text_weight)
    np.savez_compressed(args.out, features=feats,
                        channels=np.array(meta.index, dtype=object))
    print(f"Channels: {len(meta)}  |  feature dims: {feats.shape[1]}")
    print(f"  (text TF-IDF: {feats.shape[1] - 4}, numeric: 4)")

    # sanity: show nearest neighbours for a few channels
    pos = {ch: i for i, ch in enumerate(meta.index)}
    print("\nNearest neighbours (sanity check):")
    for ch in list(meta.index)[:5]:
        sims = feats @ feats[pos[ch]]
        order = np.argsort(-sims)[1:4]
        print(f"  {ch[:28]:28s} -> " +
              ", ".join(f"{meta.index[i][:22]} ({sims[i]:.2f})" for i in order))
    print(f"\nWrote {args.out}")


if __name__ == "__main__":
    main()
