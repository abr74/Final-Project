"""
youfeelings-fusion-recommender  (v3)
====================================
FIXES vs v2
-----------
1. PERSONALIZATION. v2 scored every channel with `bert_overall`, a per-channel
   average identical for all users -- so 40% of every score was a constant and
   nothing was actually personalized. v3 builds a per-user aspect preference
   profile from the channels they watched and scores the match. This mirrors
   03_fusion.py exactly.

2. 300-CHANNEL UNIVERSE. v2 read channel_cats.json (12 channels). v3 reads
   bert_scores.json + channel_similar.json produced by
   08_build_serving_artifacts.py, covering every scored channel.

3. ASPECT RELIABILITY. Aspects the BERT model never learned (production had
   33 training labels; entertainment F1 0.14) no longer steer a user's taste
   profile as strongly as informativeness (F1 0.79).

4. USER ID. v2 read parts[1] of "parsed/Uploads/{stem}/..." which is the
   literal string "Uploads" for every user, so everyone overwrote the same
   output file. v3 uses the upload UUID.

5. SCORE NORMALIZATION before weighting (SRS R3.3.4.1) and weight
   redistribution when a signal is missing (R3.3.4.4).

Output keeps every field the frontend already consumes:
  title, author, author_url, category, video_url, match_percent, match_score

Env: BUCKET_NAME, MODELS_PREFIX, OUTPUT_PREFIX
Dependency-free: stdlib + boto3 only.
"""

import json
import math
import os
from urllib.parse import unquote_plus

import boto3

s3 = boto3.client("s3")

BUCKET = os.environ.get("BUCKET_NAME", "netfeeling")
MODELS_PREFIX = os.environ.get("MODELS_PREFIX", "models-v2/")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "recommendations-v2/")
PARSED_PREFIX = os.environ.get("PARSED_PREFIX", "parsed-v2/")

ASPECTS = ["content", "entertainment", "creator", "production", "informativeness"]
W_BERT, W_NCF, W_CONTENT = 0.40, 0.35, 0.25
TEMPERATURE = 2.0

_CACHE = {}


# ----------------------------------------------------------------------
# S3 helpers
# ----------------------------------------------------------------------
def _load_json(key, default=None):
    if key in _CACHE:
        return _CACHE[key]
    try:
        obj = s3.get_object(Bucket=BUCKET, Key=key)
        data = json.loads(obj["Body"].read().decode("utf-8"))
    except Exception as e:
        if default is None:
            raise
        print(f"WARN: could not load {key}: {e}")
        data = default
    _CACHE[key] = data
    return data


def _write_json(key, payload):
    s3.put_object(Bucket=BUCKET, Key=key,
                  Body=json.dumps(payload, indent=2).encode("utf-8"),
                  ContentType="application/json")


def _load_models():
    return {
        "bert": _load_json(f"{MODELS_PREFIX}bert_scores.json"),
        "similar": _load_json(f"{MODELS_PREFIX}channel_similar.json", {}),
        "videos": _load_json(f"{MODELS_PREFIX}channel_videos.json", {}),
        "ncf": _load_json(f"{MODELS_PREFIX}ncf_scores.json", {}),
        "reliability": _load_json(f"{MODELS_PREFIX}aspect_reliability.json",
                                  {a: 1.0 for a in ASPECTS}),
        "cats": _load_json(f"{MODELS_PREFIX}channel_cats.json", {}),
    }


# ----------------------------------------------------------------------
# Scoring (mirrors 03_fusion.py)
# ----------------------------------------------------------------------
def watched_channels(central, known_channels):
    """Channel titles from the parsed Takeout that we have models for."""
    known = set(known_channels)
    found = set()
    for rec in central.get("all_records", []):
        if rec.get("record_type") == "watch_event":
            ct = rec.get("channel_title")
            if ct in known:
                found.add(ct)
    return sorted(found)


def user_aspect_profile(watched, bert, reliability):
    """Aspect weights from deviation vs the global average, reliability-scaled."""
    known = [c for c in watched if c in bert]
    if not known:
        return {a: 1.0 / len(ASPECTS) for a in ASPECTS}, []

    n = len(bert)
    global_mean = {a: sum(v.get(a, 0.5) for v in bert.values()) / n for a in ASPECTS}
    user_mean = {a: sum(bert[c].get(a, 0.5) for c in known) / len(known) for a in ASPECTS}

    devs = [(user_mean[a] - global_mean[a]) * float(reliability.get(a, 1.0))
            for a in ASPECTS]
    peak = max(abs(d) for d in devs) or 1e-9
    scaled = [d / peak * TEMPERATURE for d in devs]
    hi = max(scaled)
    exp = [math.exp(s - hi) for s in scaled]
    total = sum(exp) or 1.0
    return {a: e / total for a, e in zip(ASPECTS, exp)}, known


def minmax(d):
    if not d:
        return {}
    lo, hi = min(d.values()), max(d.values())
    if hi - lo < 1e-9:
        return {k: 0.5 for k in d}
    return {k: (v - lo) / (hi - lo) for k, v in d.items()}


def recommend(user_id, watched, models, top_k=10):
    bert = models["bert"]
    similar = models["similar"]
    videos = models["videos"]
    cats = models["cats"]
    reliability = models["reliability"]

    weights, known = user_aspect_profile(watched, bert, reliability)
    watched_set = set(watched)
    candidates = [c for c in bert if c not in watched_set]
    if not candidates:
        return [], "no_candidates", weights

    # BERT: personalized aspect match (this is the v2 fix)
    bert_s = {c: sum(weights[a] * bert[c].get(a, 0.5) for a in ASPECTS)
              for c in candidates}

    # Content: similarity to channels they already watch
    content_s = {c: 0.0 for c in candidates}
    for w in known:
        for entry in similar.get(w, []):
            try:
                nb, sim = entry[0], float(entry[1])
            except (IndexError, TypeError, ValueError):
                continue
            if nb in content_s and sim > content_s[nb]:
                content_s[nb] = sim

    # NCF: only for users the model has actually seen
    user_ncf = models["ncf"].get(str(user_id), {})
    has_ncf = bool(user_ncf)
    has_content = any(v > 0 for v in content_s.values())

    w = {"bert": W_BERT,
         "ncf": W_NCF if has_ncf else 0.0,
         "content": W_CONTENT if has_content else 0.0}
    tot = sum(w.values()) or 1.0
    w = {k: v / tot for k, v in w.items()}

    nb_ = minmax(bert_s)
    nn_ = minmax({c: float(user_ncf.get(c, 0.0)) for c in candidates})
    nc_ = minmax(content_s)

    top_aspect = max(weights, key=weights.get)
    recs = []
    for c in candidates:
        final = (w["bert"] * nb_[c] + w["ncf"] * nn_.get(c, 0.0)
                 + w["content"] * nc_.get(c, 0.0))
        vid = videos.get(c, {})

        reasons = [f"you favour {top_aspect} and this channel scores "
                   f"{bert[c].get(top_aspect, 0.5):.2f} there"]
        if w["ncf"] and nn_.get(c, 0) > 0.6:
            reasons.append("viewers with similar history watch it")
        if w["content"] and nc_.get(c, 0) > 0.5:
            reasons.append("it resembles channels you already watch")

        recs.append({
            # fields the frontend consumes
            "title": vid.get("video_title", "") or c,
            "author": c,
            "author_url": vid.get("author_url", ""),
            "category": cats.get(c, "unknown"),
            "video_url": vid.get("url", ""),
            "match_percent": round(final * 100, 1),
            "match_score": round(final, 4),
            # supporting detail
            "channel": c,
            "video_id": vid.get("video_id", ""),
            "top_aspect": top_aspect,
            "explanation": "Recommended because " + "; ".join(reasons) + ".",
            "signals": {"bert": round(nb_[c], 3),
                        "ncf": round(nn_.get(c, 0.0), 3) if has_ncf else None,
                        "content": round(nc_.get(c, 0.0), 3)},
        })

    recs.sort(key=lambda r: r["match_score"], reverse=True)
    mode = "full_fusion" if has_ncf else "cold_start"
    return recs[:top_k], mode, weights


# ----------------------------------------------------------------------
# Handler
# ----------------------------------------------------------------------
def _user_id_from_key(key):
    """parsed/{upload_uuid}/{stem}/central_output.json -> upload_uuid.

    v2 used parts[1] of a key that began with the literal 'Uploads/', so every
    user resolved to "Uploads" and overwrote the same output object.
    """
    parts = [p for p in key.split("/") if p]
    root = PARSED_PREFIX.strip("/")
    if len(parts) >= 2 and parts[0] == root:
        return parts[1]
    return parts[1] if len(parts) > 2 else "unknown_user"


def lambda_handler(event, context):
    try:
        if "Records" in event:
            key = unquote_plus(event["Records"][0]["s3"]["object"]["key"])
            if not key.endswith("central_output.json"):
                return {"statusCode": 204,
                        "body": json.dumps({"message": "ignored non-central_output key"})}
            user_id = _user_id_from_key(key)
        else:
            key = event["central_output_key"]
            user_id = event.get("user_id") or _user_id_from_key(key)

        central = _load_json(key)
        models = _load_models()
        watched = watched_channels(central, models["bert"].keys())
        recs, mode, profile = recommend(user_id, watched, models)

        payload = {
            "user_id": user_id,
            "mode": mode,
            "watched_channels": watched,
            "num_watched_recognized": len(watched),
            "aspect_profile": {a: round(v, 4) for a, v in profile.items()},
            "num_recommendations": len(recs),
            "recommendations": recs,
            "source_key": key,
        }
        _write_json(f"{OUTPUT_PREFIX}{user_id}.json", payload)

        return {"statusCode": 200,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps(payload)}

    except Exception as e:
        print("ERROR:", str(e))
        return {"statusCode": 500,
                "headers": {"Access-Control-Allow-Origin": "*"},
                "body": json.dumps({"message": "Recommendation generation failed.",
                                    "error": str(e)})}
