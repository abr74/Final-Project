"""
YouFeelings — Step 6: Score scraped comments with the trained BERT model
========================================================================
The missing link between 04_scrape_channels.py and 03_fusion.py.

    04_scrape_channels.py  ->  comments_raw_expanded.csv   (28,550 comments,
                                                            NO sentiment yet)
    THIS SCRIPT           ->  comments_scored_expanded.csv (adds
                                {aspect}_sentiment / {aspect}_confidence)
    03_fusion.py          ->  recommendations over all 300 channels

ALSO EMITS aspect_reliability.json
----------------------------------
Training showed F1 tracks label count almost exactly:

    informativeness  571 labels -> F1 0.79    trustworthy
    creator        1,102 labels -> F1 0.66    trustworthy
    content          178 labels -> F1 0.38    weak
    entertainment    217 labels -> F1 0.29    poor
    production        33 labels -> F1 0.44    meaningless (support=4)

Treating all five equally in the fusion layer lets noise carry the same
weight as signal. This script reads the per-aspect test metrics out of the
training config and writes reliability weights that 03_fusion.py uses to
down-weight the aspects the model hasn't actually learned.

Usage:
    python 05_score_comments.py --model-dir ./bert_absa_out \
                                --comments comments_raw_expanded.csv
"""

import argparse
import json
import os

import numpy as np
import pandas as pd

ASPECTS = ["content", "entertainment", "creator", "production", "informativeness"]
SENTIMENT_LABELS = ["none", "positive", "negative", "neutral"]


# ----------------------------------------------------------------------
# Reliability weights from training metrics
# ----------------------------------------------------------------------
def build_reliability(config_path, min_support=30, floor=0.15):
    """Map per-aspect test F1 -> a weight in [floor, 1].

    An aspect the model never learned should not steer a user's taste
    profile. We use macro-F1 excluding the dominant "none" class, since
    that is the honest signal, and floor it so no aspect is fully ignored.
    """
    if not os.path.exists(config_path):
        print(f"  no {config_path} found — using uniform reliability")
        return {a: 1.0 for a in ASPECTS}, {}

    cfg = json.load(open(config_path))
    per = cfg.get("test_metrics", {}).get("per_aspect", {})
    if not per:
        return {a: 1.0 for a in ASPECTS}, {}

    raw = {a: float(per.get(a, {}).get("f1_macro_excl_none", 0.0)) for a in ASPECTS}
    mx = max(raw.values()) or 1.0
    rel = {a: round(floor + (1 - floor) * (v / mx), 4) for a, v in raw.items()}
    return rel, raw


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model-dir", default="./bert_absa_out")
    ap.add_argument("--comments", default="comments_raw_expanded.csv")
    ap.add_argument("--out", default="comments_scored_expanded.csv")
    ap.add_argument("--reliability-out", default="aspect_reliability.json")
    ap.add_argument("--batch-size", type=int, default=64,
                    help="Inference batch; 64 fits comfortably on a T4")
    ap.add_argument("--max-length", type=int, default=None,
                    help="Defaults to the value stored in the model config")
    ap.add_argument("--min-confidence", type=float, default=0.0,
                    help="Below this, a prediction is recorded as 'none'")
    ap.add_argument("--limit", type=int, default=None, help="Score only N rows (smoke test)")
    args = ap.parse_args()

    import torch
    import torch.nn as nn
    from torch.utils.data import Dataset, DataLoader
    from transformers import BertTokenizer, BertModel

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # ---- config ----
    cfg_path = os.path.join(args.model_dir, "config.json")
    cfg = json.load(open(cfg_path)) if os.path.exists(cfg_path) else {}
    max_length = args.max_length or cfg.get("max_length", 256)
    model_name = cfg.get("model_name", "bert-base-uncased")
    dropout = cfg.get("dropout", 0.3)
    print(f"Model: {model_name} | max_length: {max_length}")

    # ---- reliability (before loading the model, so it's written even on failure) ----
    rel, raw_f1 = build_reliability(cfg_path)
    with open(args.reliability_out, "w") as f:
        json.dump({"reliability": rel, "source_f1_macro_excl_none": raw_f1,
                   "note": "weights derived from per-aspect test F1; "
                           "floored so no aspect is fully discarded"}, f, indent=2)
    print("\nAspect reliability (from training metrics):")
    for a in ASPECTS:
        bar = "#" * int(rel[a] * 30)
        print(f"  {a:16s} F1={raw_f1.get(a, 0):.3f}  weight={rel[a]:.3f}  {bar}")

    # ---- data ----
    df = pd.read_csv(args.comments)
    if args.limit:
        df = df.head(args.limit)
    df = df[df["text"].notna()].reset_index(drop=True)
    print(f"\nComments to score: {len(df):,} "
          f"across {df['channel_title'].nunique():,} channels")

    tokenizer = BertTokenizer.from_pretrained(args.model_dir
                                              if os.path.exists(os.path.join(args.model_dir, "vocab.txt"))
                                              else model_name)

    class TextDataset(Dataset):
        def __init__(self, texts):
            self.texts = texts

        def __len__(self):
            return len(self.texts)

        def __getitem__(self, i):
            enc = tokenizer(str(self.texts[i]), max_length=max_length,
                            padding="max_length", truncation=True,
                            return_tensors="pt")
            return {"input_ids": enc["input_ids"].squeeze(0),
                    "attention_mask": enc["attention_mask"].squeeze(0)}

    loader = DataLoader(TextDataset(df["text"].tolist()),
                        batch_size=args.batch_size, shuffle=False,
                        num_workers=2, pin_memory=True)

    # ---- model (architecture must match 00_bert_absa_train.py exactly) ----
    class BertABSA(nn.Module):
        def __init__(self):
            super().__init__()
            self.bert = BertModel.from_pretrained(model_name)
            self.dropout = nn.Dropout(dropout)
            self.shared_dense = nn.Linear(self.bert.config.hidden_size, 256)
            self.activation = nn.ReLU()
            self.aspect_heads = nn.ModuleList(
                [nn.Linear(256, len(SENTIMENT_LABELS)) for _ in ASPECTS])

        def forward(self, input_ids, attention_mask):
            out = self.bert(input_ids=input_ids, attention_mask=attention_mask)
            x = self.dropout(out.last_hidden_state[:, 0, :])
            x = self.activation(self.shared_dense(x))
            x = self.dropout(x)
            return torch.stack([h(x) for h in self.aspect_heads], dim=1)

    weights_path = os.path.join(args.model_dir, "model_best.pt")
    if not os.path.exists(weights_path):
        raise SystemExit(f"No weights at {weights_path} — train the model first.")

    model = BertABSA().to(device)
    model.load_state_dict(torch.load(weights_path, map_location=device))
    model.eval()
    print(f"Loaded weights from {weights_path}")

    # ---- inference ----
    all_labels = {a: [] for a in ASPECTS}
    all_conf = {a: [] for a in ASPECTS}
    done = 0
    with torch.no_grad():
        for batch in loader:
            ids = batch["input_ids"].to(device, non_blocking=True)
            mask = batch["attention_mask"].to(device, non_blocking=True)
            probs = torch.softmax(model(ids, mask), dim=2)   # (B, aspects, 4)
            conf, pred = probs.max(dim=2)
            pred, conf = pred.cpu().numpy(), conf.cpu().numpy()
            for i, a in enumerate(ASPECTS):
                for p, c in zip(pred[:, i], conf[:, i]):
                    label = SENTIMENT_LABELS[p]
                    if c < args.min_confidence:
                        label = "none"
                    all_labels[a].append(label)
                    all_conf[a].append(round(float(c), 4))
            done += ids.size(0)
            if done % (args.batch_size * 20) == 0 or done >= len(df):
                print(f"  scored {done:,}/{len(df):,}", end="\r", flush=True)

    print()
    for a in ASPECTS:
        df[f"{a}_sentiment"] = all_labels[a]
        df[f"{a}_confidence"] = all_conf[a]

    df.to_csv(args.out, index=False)

    # ---- summary ----
    print(f"\nWrote {args.out}")
    print("\nPredicted sentiment distribution per aspect:")
    for a in ASPECTS:
        vc = df[f"{a}_sentiment"].value_counts()
        parts = ", ".join(f"{k}={vc.get(k, 0):,}" for k in SENTIMENT_LABELS)
        print(f"  {a:16s} {parts}")

    # channel coverage — what fusion will actually be able to use
    covered = 0
    for _, g in df.groupby("channel_title"):
        if any((g[f"{a}_sentiment"].isin(["positive", "negative"])).any() for a in ASPECTS):
            covered += 1
    print(f"\nChannels with usable aspect signal: {covered:,}/"
          f"{df['channel_title'].nunique():,}")
    print(f"Reliability weights written to {args.reliability_out}")


if __name__ == "__main__":
    main()
