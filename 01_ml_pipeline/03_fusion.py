"""
YouFeelings — Step 3: Personalized aspect profiler + normalized fusion
=====================================================================
Replaces YouFeelings_Fusion.ipynb.

WHAT WAS WRONG
--------------
The old fusion used:

    b = bert_df.loc[ch, "bert_overall"]        # per-channel average
    final = 0.40*b + 0.35*n + 0.25*c

`bert_overall` is identical for every user, so 40% of every score was a
constant. The aspect-based personalization -- the whole point of the
product -- was not actually personalizing anything. Explanations like
"matches your taste on content" were true of every user equally.

WHAT THIS DOES INSTEAD
----------------------
1. USER ASPECT PROFILE
   Build a per-user preference vector over the 5 aspects from the channels
   they actually watch, expressed as a DEVIATION from the global average.
   If everyone's channels score high on "content", that carries no
   information about you; what identifies you is which aspects your
   channels over-index on relative to everyone else's.

2. PERSONALIZED BERT SCORE
   bert_score(user, channel) = sum_a  w_user[a] * channel_aspect[channel][a]
   Now the 40% term differs per user, and the explanation is truthful.

3. NORMALIZATION BEFORE WEIGHTING  (SRS R3.3.4.1)
   The three signals live on different scales (BERT ~0.5-1.0, NCF is a
   saturated sigmoid, content is mostly 0). Weighting raw values means
   40/35/25 are not the real weights. Each signal is min-max normalized
   across the candidate set per user before fusion.

4. GRACEFUL DEGRADATION  (SRS R3.3.4.4)
   If a signal is missing (new user with no NCF history), its weight is
   redistributed across the available signals instead of scoring 0.

Usage:
    python 03_fusion.py --matrix ncf_interaction_matrix.csv \
                        --scored comments_scored.csv \
                        --pool comments_pool_12.csv \
                        --ncf ncf_scores.csv
"""

import argparse
import json
import os

import numpy as np
import pandas as pd

ASPECTS = ["content", "entertainment", "creator", "production", "informativeness"]
W_BERT, W_NCF, W_CONTENT = 0.40, 0.35, 0.25


# ----------------------------------------------------------------------
# 1. Channel aspect vectors (from BERT output)
# ----------------------------------------------------------------------
def build_channel_aspect_vectors(scored, channels, min_comments=3):
    """Per-channel aspect sentiment in [0,1].

    Adds a confidence shrink the original lacked: a channel with 2 comments
    should not get the same extreme score as one with 200. We shrink toward
    0.5 based on sample size so thin evidence can't dominate the ranking.
    """
    out = {}
    for ch in channels:
        sub = scored[scored["channel_title"] == ch]
        vec = {}
        for aspect in ASPECTS:
            col = f"{aspect}_sentiment"
            if col not in sub.columns or len(sub) == 0:
                vec[aspect] = 0.5
                continue
            vals = sub[col]
            pos = int((vals == "positive").sum())
            neg = int((vals == "negative").sum())
            total = pos + neg
            if total == 0:
                vec[aspect] = 0.5
            else:
                raw = ((pos - neg) / total + 1) / 2          # -> [0,1]
                shrink = total / (total + min_comments)       # 0..1
                vec[aspect] = 0.5 + (raw - 0.5) * shrink
        vec["n_comments"] = int(len(sub))
        out[ch] = vec
    return pd.DataFrame(out).T


# ----------------------------------------------------------------------
# 2. User aspect profile  (THE CORE FIX)
# ----------------------------------------------------------------------
def build_user_aspect_profile(watched_channels, aspect_df, temperature=2.0,
                              reliability=None):
    """Preference weights over aspects for one user.

    Returns (weights dict summing to 1, raw deviation dict).

    A user who watches 3Blue1Brown and TED over-indexes on
    informativeness/content; someone on MrBeast over-indexes on
    entertainment. Deviation-from-global is what separates them.

    `reliability` down-weights aspects the BERT model never actually learned
    (see aspect_reliability.json from 05_score_comments.py). Without it,
    production -- which had 33 training labels and F1 on 4 test examples --
    would steer a user's profile as strongly as informativeness, which had
    571 labels and F1 0.79. That is noise driving personalization.
    """
    global_mean = aspect_df[ASPECTS].mean()

    watched = [c for c in watched_channels if c in aspect_df.index]
    if not watched:
        # Cold start: no watch history -> flat profile, no false personalization
        flat = {a: 1.0 / len(ASPECTS) for a in ASPECTS}
        return flat, {a: 0.0 for a in ASPECTS}

    user_mean = aspect_df.loc[watched, ASPECTS].mean()
    deviation = (user_mean - global_mean).to_dict()

    # scale each aspect's deviation by how much we trust that aspect
    if reliability:
        devs = np.array([deviation[a] * reliability.get(a, 1.0) for a in ASPECTS],
                        dtype=float)
    else:
        devs = np.array([deviation[a] for a in ASPECTS], dtype=float)

    # softmax over deviations -> positive weights that sum to 1
    if np.allclose(devs, 0):
        weights = np.full(len(ASPECTS), 1.0 / len(ASPECTS))
    else:
        scaled = devs / (np.abs(devs).max() + 1e-9) * temperature
        e = np.exp(scaled - scaled.max())
        weights = e / e.sum()

    return ({a: float(w) for a, w in zip(ASPECTS, weights)},
            {a: float(round(deviation[a], 4)) for a in ASPECTS})


def personalized_bert_score(channel, aspect_df, user_weights):
    """Weighted match between a user's aspect preferences and a channel."""
    if channel not in aspect_df.index:
        return 0.5
    row = aspect_df.loc[channel]
    return float(sum(user_weights[a] * row[a] for a in ASPECTS))


# ----------------------------------------------------------------------
# 3. Content-based score
# ----------------------------------------------------------------------
def content_scores_for_user(watched, channels, chan_cat, cbf=None):
    """Content score per channel.

    If channel_metadata.csv is available, use TF-IDF cosine over channel
    metadata (SRS R3.3.3.2). Otherwise fall back to the category-share
    heuristic, which only works for channels with a known category.
    """
    if cbf is not None:
        meta_index, features, tfidf_fn = cbf
        return tfidf_fn(watched, channels, meta_index, features)
    return _content_scores_category(watched, channels, chan_cat)


def _content_scores_category(watched, channels, chan_cat):
    """Category-affinity score in [0,1] for every candidate channel."""
    cats = [chan_cat.get(c) for c in watched if chan_cat.get(c)]
    if not cats:
        return {c: 0.0 for c in channels}
    share = pd.Series(cats).value_counts(normalize=True).to_dict()
    raw = {c: share.get(chan_cat.get(c), 0.0) for c in channels}
    mx = max(raw.values()) or 1.0
    return {c: v / mx for c, v in raw.items()}


# ----------------------------------------------------------------------
# 4. Normalization + fusion
# ----------------------------------------------------------------------
def minmax(d):
    """Min-max a dict of scores to [0,1]; constant input -> all 0.5."""
    vals = np.array(list(d.values()), dtype=float)
    lo, hi = vals.min(), vals.max()
    if hi - lo < 1e-9:
        return {k: 0.5 for k in d}
    return {k: float((v - lo) / (hi - lo)) for k, v in d.items()}


def fuse(bert_s, ncf_s, content_s, has_ncf=True, has_content=True):
    """Weighted fusion with normalization and weight redistribution."""
    weights = {"bert": W_BERT,
               "ncf": W_NCF if has_ncf else 0.0,
               "content": W_CONTENT if has_content else 0.0}
    total = sum(weights.values())
    weights = {k: v / total for k, v in weights.items()}  # re-normalize

    b, n, c = minmax(bert_s), minmax(ncf_s), minmax(content_s)
    return {
        ch: weights["bert"] * b[ch]
            + weights["ncf"] * n.get(ch, 0.0)
            + weights["content"] * c.get(ch, 0.0)
        for ch in bert_s
    }, weights


# ----------------------------------------------------------------------
# 5. Recommend + explain
# ----------------------------------------------------------------------
def explain(channel, aspect_df, user_weights, parts):
    """Truthful explanation: names the aspect THIS user actually favors."""
    top_aspect = max(user_weights, key=user_weights.get)
    ch_val = aspect_df.loc[channel, top_aspect] if channel in aspect_df.index else 0.5
    bits = [f"you favor {top_aspect} and this channel scores "
            f"{ch_val:.2f} there"]
    if parts.get("ncf", 0) > 0.6:
        bits.append("viewers with similar history watch it")
    if parts.get("content", 0) > 0.6:
        bits.append("it matches categories you already watch")
    return "Recommended because " + "; ".join(bits) + "."


def recommend(user_id, matrix, aspect_df, ncf_lookup, chan_cat, channels, top_k=10,
              reliability=None, cbf=None):
    urow = matrix[matrix["user_id"] == user_id]
    watched = ([c for c in channels if c in urow.columns and urow.iloc[0][c] == 1]
               if len(urow) else [])

    user_weights, deviation = build_user_aspect_profile(watched, aspect_df,
                                                       reliability=reliability)
    user_ncf = ncf_lookup.get(user_id, {})
    has_ncf = len(user_ncf) > 0
    has_content = len(watched) > 0

    bert_s = {ch: personalized_bert_score(ch, aspect_df, user_weights) for ch in channels}
    ncf_s = {ch: float(user_ncf.get(ch, 0.0)) for ch in channels}
    content_s = content_scores_for_user(watched, channels, chan_cat, cbf)

    fused, applied_w = fuse(bert_s, ncf_s, content_s, has_ncf, has_content)

    nb, nn_, nc = minmax(bert_s), minmax(ncf_s), minmax(content_s)
    rows = []
    for ch in channels:
        parts = {"bert": nb[ch], "ncf": nn_[ch], "content": nc[ch]}
        rows.append({
            "user_id": user_id,
            "channel": ch,
            "final_score": round(fused[ch], 4),
            "bert": round(parts["bert"], 4),
            "ncf": round(parts["ncf"], 4),
            "content": round(parts["content"], 4),
            "top_user_aspect": max(user_weights, key=user_weights.get),
            "already_watched": ch in watched,
            "explanation": explain(ch, aspect_df, user_weights, parts),
        })

    recs = (pd.DataFrame(rows)
            .sort_values("final_score", ascending=False)
            .reset_index(drop=True))
    profile = {
        "user_id": user_id,
        "n_watched": len(watched),
        "aspect_weights": {k: round(v, 4) for k, v in user_weights.items()},
        "aspect_deviation": deviation,
        "applied_fusion_weights": {k: round(v, 3) for k, v in applied_w.items()},
    }
    return recs, watched, profile


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default="ncf_interaction_matrix.csv")
    ap.add_argument("--scored", default="comments_scored.csv")
    ap.add_argument("--pool", default="comments_pool_12.csv")
    ap.add_argument("--ncf", default="ncf_scores.csv")
    ap.add_argument("--out", default="final_recommendations.csv")
    ap.add_argument("--profiles-out", default="user_aspect_profiles.json")
    ap.add_argument("--top-k", type=int, default=10)
    ap.add_argument("--metadata", default="channel_metadata.csv",
                    help="Enables TF-IDF content filtering (SRS R3.3.3.2)")
    ap.add_argument("--reliability", default="aspect_reliability.json",
                    help="From 05_score_comments.py; down-weights aspects "
                         "the model never learned. Omit for uniform.")
    args = ap.parse_args()

    matrix = pd.read_csv(args.matrix)
    scored = pd.read_csv(args.scored)
    pool = pd.read_csv(args.pool) if os.path.exists(args.pool) else pd.DataFrame(
        columns=["channel_title", "category"])

    # NCF is optional. If it hasn't been retrained for the current channel
    # universe / user IDs yet, the fusion layer runs on BERT + content and
    # redistributes NCF's 35% weight (SRS R3.3.4.4) rather than failing.
    if os.path.exists(args.ncf):
        ncf = pd.read_csv(args.ncf)
    else:
        print(f"(no {args.ncf} — running without collaborative signal; "
              f"its weight is redistributed)")
        ncf = pd.DataFrame(columns=["user_id", "channel", "ncf_score"])

    channels = sorted(set(ncf["channel"].unique())
                      | set(scored["channel_title"].dropna().unique()))
    if not channels:
        raise SystemExit("No channels found in the scored comments file.")
    aspect_df = build_channel_aspect_vectors(scored, channels)
    chan_cat = (pool.drop_duplicates("channel_title")
                .set_index("channel_title")["category"].to_dict())
    ncf_lookup = ({u: g.set_index("channel")["ncf_score"].to_dict()
                   for u, g in ncf.groupby("user_id")} if len(ncf) else {})

    cbf = None
    _cf_exists = os.path.exists(os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "06_content_features.py"))
    if os.path.exists(args.metadata) and _cf_exists:
        import importlib.util
        # resolve next to THIS script, not the current working directory
        cf_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "06_content_features.py")
        spec = importlib.util.spec_from_file_location("cf", cf_path)
        cf = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cf)
        meta, feats = cf.build_channel_features(args.metadata)
        cbf = (list(meta.index), feats, cf.content_scores_tfidf)
        print(f"Content filter: TF-IDF over {len(meta)} channels "
              f"({feats.shape[1]} features)")
    elif os.path.exists(args.metadata):
        print("(06_content_features.py not found next to this script — "
              "falling back to category-share content filter)")
    else:
        print(f"(no {args.metadata} — falling back to category-share content filter)")

    reliability = None
    if os.path.exists(args.reliability):
        reliability = json.load(open(args.reliability)).get("reliability")
        print("Aspect reliability weights loaded:")
        for a in ASPECTS:
            print(f"  {a:16s} {reliability.get(a, 1.0):.3f}")
    else:
        print(f"(no {args.reliability} — all aspects weighted equally)")

    print(f"Channels: {len(channels)} | Users: {len(matrix)}")

    all_recs, profiles = [], []
    for user in matrix["user_id"]:
        recs, watched, profile = recommend(
            user, matrix, aspect_df, ncf_lookup, chan_cat, channels, args.top_k,
            reliability=reliability, cbf=cbf
        )
        profiles.append(profile)
        fresh = recs[~recs["already_watched"]].head(args.top_k)
        all_recs.append(fresh)

    final = pd.concat(all_recs, ignore_index=True)
    final.to_csv(args.out, index=False)
    with open(args.profiles_out, "w") as f:
        json.dump(profiles, f, indent=2)

    # show that profiles actually differ between users
    print("\n--- user aspect profiles (proof of personalization) ---")
    for p in profiles[:6]:
        top = sorted(p["aspect_weights"].items(), key=lambda x: -x[1])[:2]
        print(f"  {p['user_id']:12s} watched={p['n_watched']:3d}  "
              f"top: {top[0][0]}={top[0][1]:.3f}, {top[1][0]}={top[1][1]:.3f}")

    print(f"\nWrote {args.out} ({len(final)} rows) and {args.profiles_out}")


if __name__ == "__main__":
    main()
