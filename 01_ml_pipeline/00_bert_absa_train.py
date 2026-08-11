"""
YouFeelings — BERT ABSA training (fixed + SageMaker-ready)
==========================================================
Replaces bert_pipeline.ipynb.

FIXES APPLIED
-------------
1. BLOCKING BUG: in the notebook, the DataLoader block was wrapped in a
   '''...''' string, so train_loader / val_loader / test_loader were never
   defined and Cell 8 crashed on `len(train_loader)`. They are real code here.

2. MAX_LENGTH was 128 in code but 256 in the SRS and the Spring deck.
   Now a CLI flag, default 256, so code and documents agree.

3. Stratification fallback: train_test_split(stratify=category) throws when
   any category has a single member. Falls back to unstratified with a
   warning instead of dying mid-run.

4. Early stopping actually breaks out of the loop (the notebook tracked a
   patience counter but the break was cut off).

5. Reports per-aspect F1 EXCLUDING the dominant "none" class as well as
   including it. With ~89% of labels being "none", macro-F1-with-none
   flatters the model; the excluding-none number is the honest one.

6. Runs on CPU or GPU, and reads SageMaker's channel env vars when present
   so the same file works locally and as a training-job entry point.

Usage (local):
    python 00_bert_absa_train.py --data comments_labeled_synthetic.csv --epochs 5

Usage (SageMaker training job entry point):
    estimator = PyTorch(entry_point="00_bert_absa_train.py",
                        instance_type="ml.g4dn.xlarge", ...)
"""

import argparse
import json
import os
import random

import numpy as np
import pandas as pd

ASPECTS = ["content", "entertainment", "creator", "production", "informativeness"]
SENTIMENT_LABELS = ["none", "positive", "negative", "neutral"]  # index 0..3


# ----------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------
def load_data(filepath):
    """Long (comment, aspect, sentiment) rows -> one row per comment."""
    df = pd.read_csv(filepath)
    print(f"Raw labeled rows: {len(df):,}")
    print(f"Unique comments:  {df['comment_id'].nunique():,}")
    print("\nAspect distribution:")
    print(df["aspect"].value_counts().to_string())
    print("\nSentiment distribution:")
    print(df["sentiment"].value_counts().to_string())

    records = []
    for comment_id, group in df.groupby("comment_id"):
        first = group.iloc[0]
        row = {
            "comment_id": comment_id,
            "text": first["text"],
            "category": first.get("category", "unknown"),
        }
        for aspect in ASPECTS:
            row[f"label_{aspect}"] = 0  # default "none"
        for _, r in group.iterrows():
            if r["aspect"] in ASPECTS and r["sentiment"] in SENTIMENT_LABELS:
                row[f"label_{r['aspect']}"] = SENTIMENT_LABELS.index(r["sentiment"])
        records.append(row)

    result = pd.DataFrame(records)
    print(f"\nPivoted: {len(result):,} comments")
    print("\nLabel distribution per aspect:")
    for aspect in ASPECTS:
        counts = result[f"label_{aspect}"].value_counts()
        line = ", ".join(f"{SENTIMENT_LABELS[i]}={counts.get(i, 0)}"
                         for i in range(len(SENTIMENT_LABELS)))
        print(f"  {aspect:16s}: {line}")

    # Honest warning about what the labeler can/can't teach
    neutral_total = sum(int((result[f"label_{a}"] == 3).sum()) for a in ASPECTS)
    if neutral_total == 0:
        print("\n  NOTE: zero 'neutral' labels in this dataset. The model cannot\n"
              "        learn to predict neutral. Expected if labels came from the\n"
              "        rule-based synthetic labeler (it has no neutral rules).")
    return result


def safe_split(df, test_size, seed, stratify_col="category"):
    from sklearn.model_selection import train_test_split
    strat = df[stratify_col] if stratify_col in df.columns else None
    if strat is not None and strat.value_counts().min() < 2:
        print(f"  (stratify disabled: a '{stratify_col}' value has <2 members)")
        strat = None
    return train_test_split(df, test_size=test_size, random_state=seed, stratify=strat)


def compute_class_weights(df, num_classes, device):
    """Inverse-frequency weights per aspect, normalized to max 1."""
    import torch
    weights = []
    for aspect in ASPECTS:
        counts = df[f"label_{aspect}"].value_counts()
        freq = [max(int(counts.get(i, 0)), 1) for i in range(num_classes)]
        total = sum(freq)
        w = [total / (num_classes * f) for f in freq]
        mx = max(w)
        weights.append(torch.tensor([x / mx for x in w],
                                    dtype=torch.float32, device=device))
    return weights


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=os.environ.get(
        "SM_CHANNEL_TRAIN", ".") + "/comments_labeled_synthetic.csv")
    ap.add_argument("--model-name", default="bert-base-uncased")
    ap.add_argument("--out-dir", default=os.environ.get("SM_MODEL_DIR", "./bert_absa_out"))
    ap.add_argument("--max-length", type=int, default=256,
                    help="256 matches the SRS/deck; notebook had 128")
    ap.add_argument("--batch-size", type=int, default=16)
    ap.add_argument("--epochs", type=int, default=5)
    ap.add_argument("--lr", type=float, default=2e-5, help="BERT encoder LR")
    ap.add_argument("--head-lr-mult", type=float, default=5.0, help="heads LR = lr * mult")
    ap.add_argument("--dropout", type=float, default=0.3)
    ap.add_argument("--warmup-ratio", type=float, default=0.1)
    ap.add_argument("--weight-decay", type=float, default=0.01)
    ap.add_argument("--patience", type=int, default=2)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    import torch
    import torch.nn as nn
    from torch.utils.data import Dataset, DataLoader
    from torch.optim import AdamW
    from transformers import BertTokenizer, BertModel, get_linear_schedule_with_warmup
    from sklearn.metrics import classification_report, f1_score

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(args.seed)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")
    if torch.cuda.is_available():
        p = torch.cuda.get_device_properties(0)
        print(f"GPU: {p.name} ({p.total_memory / 1e9:.1f} GB)")
    else:
        print("  (no GPU — this will be slow; fine for a smoke test)")

    NUM_SENT = len(SENTIMENT_LABELS)
    NUM_ASP = len(ASPECTS)

    # ---------------- data ----------------
    df = load_data(args.data)
    train_df, temp_df = safe_split(df, 0.3, args.seed)
    val_df, test_df = safe_split(temp_df, 0.5, args.seed)
    print(f"\nTrain {len(train_df)} | Val {len(val_df)} | Test {len(test_df)}")

    tokenizer = BertTokenizer.from_pretrained(args.model_name)

    class ABSADataset(Dataset):
        def __init__(self, frame):
            self.data = frame.reset_index(drop=True)

        def __len__(self):
            return len(self.data)

        def __getitem__(self, idx):
            row = self.data.iloc[idx]
            enc = tokenizer(str(row["text"]), max_length=args.max_length,
                            padding="max_length", truncation=True,
                            return_tensors="pt")
            return {
                "input_ids": enc["input_ids"].squeeze(0),
                "attention_mask": enc["attention_mask"].squeeze(0),
                "labels": torch.tensor([row[f"label_{a}"] for a in ASPECTS],
                                       dtype=torch.long),
            }

    # ---- THE FIX: these were inside a ''' ''' string in the notebook ----
    train_loader = DataLoader(ABSADataset(train_df), batch_size=args.batch_size,
                              shuffle=True, num_workers=2, pin_memory=True)
    val_loader = DataLoader(ABSADataset(val_df), batch_size=args.batch_size,
                            shuffle=False, num_workers=2, pin_memory=True)
    test_loader = DataLoader(ABSADataset(test_df), batch_size=args.batch_size,
                             shuffle=False, num_workers=2, pin_memory=True)
    print(f"Batches -> train {len(train_loader)}, val {len(val_loader)}, test {len(test_loader)}")

    # ---------------- model ----------------
    class BertABSA(nn.Module):
        def __init__(self):
            super().__init__()
            self.bert = BertModel.from_pretrained(args.model_name)
            hidden = self.bert.config.hidden_size
            self.dropout = nn.Dropout(args.dropout)
            self.shared_dense = nn.Linear(hidden, 256)
            self.activation = nn.ReLU()
            self.aspect_heads = nn.ModuleList(
                [nn.Linear(256, NUM_SENT) for _ in range(NUM_ASP)])

        def forward(self, input_ids, attention_mask):
            out = self.bert(input_ids=input_ids, attention_mask=attention_mask)
            cls = out.last_hidden_state[:, 0, :]
            x = self.dropout(cls)
            x = self.activation(self.shared_dense(x))
            x = self.dropout(x)
            return torch.stack([h(x) for h in self.aspect_heads], dim=1)

    model = BertABSA().to(device)
    print(f"Parameters: {sum(p.numel() for p in model.parameters()):,}")

    class_weights = compute_class_weights(train_df, NUM_SENT, device)
    criteria = [nn.CrossEntropyLoss(weight=w) for w in class_weights]

    optimizer = AdamW([
        {"params": model.bert.parameters(), "lr": args.lr},
        {"params": model.shared_dense.parameters(), "lr": args.lr * args.head_lr_mult},
        {"params": model.aspect_heads.parameters(), "lr": args.lr * args.head_lr_mult},
    ], weight_decay=args.weight_decay)

    total_steps = len(train_loader) * args.epochs
    scheduler = get_linear_schedule_with_warmup(
        optimizer, int(total_steps * args.warmup_ratio), total_steps)

    # ---------------- loops ----------------
    def run(loader, train):
        model.train() if train else model.eval()
        total_loss = 0.0
        preds = {a: [] for a in ASPECTS}
        golds = {a: [] for a in ASPECTS}
        ctx = torch.enable_grad() if train else torch.no_grad()
        with ctx:
            for batch in loader:
                ids = batch["input_ids"].to(device)
                mask = batch["attention_mask"].to(device)
                labels = batch["labels"].to(device)
                if train:
                    optimizer.zero_grad()
                logits = model(ids, mask)
                loss = sum(criteria[i](logits[:, i, :], labels[:, i])
                           for i in range(NUM_ASP))
                if train:
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    optimizer.step()
                    scheduler.step()
                total_loss += loss.item()
                p = logits.argmax(dim=2)
                for i, a in enumerate(ASPECTS):
                    preds[a].extend(p[:, i].cpu().numpy())
                    golds[a].extend(labels[:, i].cpu().numpy())

        f1_all = np.mean([f1_score(golds[a], preds[a], average="macro", zero_division=0)
                          for a in ASPECTS])
        # honest metric: ignore the dominant "none" class (label 0)
        f1_no_none = np.mean([
            f1_score(golds[a], preds[a], average="macro", zero_division=0,
                     labels=[1, 2, 3]) for a in ASPECTS])
        return total_loss / max(len(loader), 1), f1_all, f1_no_none, preds, golds

    best_f1, patience_left, history = -1.0, args.patience, []
    os.makedirs(args.out_dir, exist_ok=True)
    best_path = os.path.join(args.out_dir, "model_best.pt")

    print("\n" + "=" * 78)
    print(f"{'Epoch':>5} | {'TrLoss':>8} | {'TrF1':>6} | {'VaLoss':>8} | "
          f"{'VaF1':>6} | {'VaF1(no none)':>13}")
    print("=" * 78)

    for epoch in range(1, args.epochs + 1):
        tr_loss, tr_f1, tr_f1n, _, _ = run(train_loader, True)
        va_loss, va_f1, va_f1n, _, _ = run(val_loader, False)
        history.append({"epoch": epoch, "train_loss": tr_loss, "train_f1": tr_f1,
                        "val_loss": va_loss, "val_f1": va_f1,
                        "val_f1_excl_none": va_f1n})

        star = ""
        if va_f1 > best_f1:
            best_f1, patience_left, star = va_f1, args.patience, "  *best"
            torch.save(model.state_dict(), best_path)
        else:
            patience_left -= 1

        print(f"{epoch:>5} | {tr_loss:>8.4f} | {tr_f1:>6.4f} | {va_loss:>8.4f} | "
              f"{va_f1:>6.4f} | {va_f1n:>13.4f}{star}")

        if patience_left <= 0:                      # FIX: actually stop
            print(f"Early stopping (no val improvement in {args.patience} epochs)")
            break

    # ---------------- test ----------------
    model.load_state_dict(torch.load(best_path, map_location=device))
    te_loss, te_f1, te_f1n, te_preds, te_golds = run(test_loader, False)
    print("\n" + "=" * 60)
    print("TEST RESULTS")
    print("=" * 60)
    print(f"Loss                 : {te_loss:.4f}")
    print(f"Macro F1 (all)       : {te_f1:.4f}")
    print(f"Macro F1 (excl none) : {te_f1n:.4f}   <- the honest number")

    per_aspect = {}
    for a in ASPECTS:
        print(f"\n--- {a.upper()} ---")
        # labels=... is required: "neutral" may be absent from the data, and
        # sklearn then errors on the 4 target_names it was given.
        print(classification_report(te_golds[a], te_preds[a],
                                    labels=list(range(NUM_SENT)),
                                    target_names=SENTIMENT_LABELS,
                                    zero_division=0))
        per_aspect[a] = {
            "f1_macro": float(f1_score(te_golds[a], te_preds[a],
                                       average="macro", zero_division=0)),
            "f1_macro_excl_none": float(f1_score(te_golds[a], te_preds[a],
                                                 average="macro", zero_division=0,
                                                 labels=[1, 2, 3])),
        }

    tokenizer.save_pretrained(args.out_dir)
    with open(os.path.join(args.out_dir, "config.json"), "w") as f:
        json.dump({
            "model_name": args.model_name,
            "aspects": ASPECTS,
            "sentiment_labels": SENTIMENT_LABELS,
            "max_length": args.max_length,
            "dropout": args.dropout,
            "batch_size": args.batch_size,
            "lr_encoder": args.lr,
            "lr_heads": args.lr * args.head_lr_mult,
            "epochs_run": len(history),
            "training_history": history,
            "test_metrics": {"loss": te_loss, "f1_macro": te_f1,
                             "f1_macro_excl_none": te_f1n,
                             "per_aspect": per_aspect},
        }, f, indent=2)
    print(f"\nSaved model + config to {args.out_dir}/")


if __name__ == "__main__":
    main()
