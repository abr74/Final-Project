"""
YouFeelings — Step 8: NCF (NeuMF) retrain + leave-one-out evaluation
====================================================================
Replaces YouFeelings_NCF.ipynb and netfeelings_ncf_pipeline.ipynb.

WHAT WAS MISSING
----------------
The old notebook trained on 100% of the data and produced scores with NO
evaluation at all -- no held-out split, no HR@K, no NDCG@K. SRS R3.3.2.5 and
the Spring deck both promise leave-one-out evaluation on held-out real users.
That number did not exist.

WHAT THIS DOES
--------------
1. Trains NeuMF (GMF + MLP branches) on the combined real+synthetic matrix.

2. LEAVE-ONE-OUT PROTOCOL (He et al. 2017): for each user, hold out one
   watched channel. At test time, rank that held-out channel against 99
   sampled unwatched channels and check whether it lands in the top K.
       HR@K   = fraction of users whose held-out item made the top K
       NDCG@K = position-discounted version of the same

3. TWO SEPARATE EVALUATIONS, never mixed:
       real users      -- the number that matters, but n is small
       synthetic users -- larger n, but only measures whether NCF can
                          recover the copula's structure. NOT evidence of
                          real-world recommendation quality.

4. POPULARITY BASELINE. A recommender that beats nothing is not a result.
   The baseline ranks purely by how many users watched each channel.

HONEST WARNING
--------------
With ~7 real users, real-user HR@K is computed over 7 data points. Treat it
as directional only; the confidence interval is enormous. The script prints
this warning itself when the real-user count is small.

Usage:
    python 07_ncf_train.py --matrix combined_matrix.csv --epochs 30
"""

import argparse
import json
import os

import numpy as np
import pandas as pd


# ----------------------------------------------------------------------
# Evaluation
# ----------------------------------------------------------------------
def hit_ratio(rank, k):
    return 1.0 if rank < k else 0.0


def ndcg(rank, k):
    return (1.0 / np.log2(rank + 2)) if rank < k else 0.0


def evaluate(score_fn, test_cases, n_channels, k_values, rng):
    """score_fn(user_idx, [channel_idx]) -> np.array of scores.

    Each test case carries its OWN pre-sampled negatives, chosen once and
    excluded from training. Re-sampling negatives here from the full
    unwatched pool would mostly draw items the model was explicitly trained
    to score ~0, so the unseen held-out item wins by default and every
    metric pins at 1.0. Training and evaluation negatives must be disjoint.
    """
    results = {k: {"hr": [], "ndcg": []} for k in k_values}
    for u_idx, pos_idx, _watched, negs in test_cases:
        if len(negs) == 0:
            continue
        candidates = np.concatenate([[pos_idx], np.array(negs)])

        scores = score_fn(u_idx, candidates)
        # rank of the held-out item (index 0) -- higher score = better
        rank = int((scores > scores[0]).sum())

        for k in k_values:
            results[k]["hr"].append(hit_ratio(rank, k))
            results[k]["ndcg"].append(ndcg(rank, k))

    return {k: {"HR": round(float(np.mean(v["hr"])), 4) if v["hr"] else None,
                "NDCG": round(float(np.mean(v["ndcg"])), 4) if v["ndcg"] else None,
                "n": len(v["hr"])}
            for k, v in results.items()}


def build_leave_one_out(matrix, channels, rng, min_watched=2, n_eval_negatives=99):
    """Hold out one watched channel per user, plus a reserved negative set.

    Returns (test_cases, train_pairs, reserved) where
        test_cases = [(user_idx, held_out_idx, remaining_watched, eval_negs)]
        reserved   = {user_idx: set(eval_negs)}  -- must be excluded from
                     training negative sampling, otherwise the model
                     memorizes them and the held-out item ranks first by
                     default (metrics pin at 1.0).
    """
    test_cases, train_pairs, reserved = [], [], {}
    ch_index = {c: i for i, c in enumerate(channels)}
    n_channels = len(channels)

    for u_idx, (_, row) in enumerate(matrix.iterrows()):
        watched = [ch_index[c] for c in channels if row[c] == 1]
        if len(watched) < min_watched:
            train_pairs.extend([(u_idx, c) for c in watched])
            continue
        held = int(rng.choice(watched))
        remaining = [c for c in watched if c != held]

        pool = np.setdiff1d(np.arange(n_channels), np.array(sorted(watched)))
        n_neg = min(n_eval_negatives, len(pool))
        eval_negs = rng.choice(pool, size=n_neg, replace=False) if n_neg else np.array([])

        test_cases.append((u_idx, held, set(remaining), eval_negs))
        reserved[u_idx] = set(int(x) for x in eval_negs)
        train_pairs.extend([(u_idx, c) for c in remaining])

    return test_cases, train_pairs, reserved


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default="combined_matrix.csv",
                    help="From 02_synthesize_users.py (has is_synthetic column)")
    ap.add_argument("--out-scores", default="ncf_scores.csv")
    ap.add_argument("--out-metrics", default="ncf_eval.json")
    ap.add_argument("--embed-dim", type=int, default=16)
    ap.add_argument("--mlp-layers", default="32,16,8")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch-size", type=int, default=256)
    ap.add_argument("--lr", type=float, default=1e-3)
    ap.add_argument("--neg-ratio", type=int, default=4)
    ap.add_argument("--dropout", type=float, default=0.2)
    ap.add_argument("--k-values", default="5,10,20")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    import torch
    import torch.nn as nn
    from torch.utils.data import Dataset, DataLoader

    rng = np.random.default_rng(args.seed)
    torch.manual_seed(args.seed)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    k_values = [int(k) for k in args.k_values.split(",")]
    mlp_layers = [int(x) for x in args.mlp_layers.split(",")]

    # ---------------- data ----------------
    matrix = pd.read_csv(args.matrix)
    is_synth_col = "is_synthetic" in matrix.columns
    if not is_synth_col:
        print("WARNING: no is_synthetic column — treating every user as real.")
        matrix["is_synthetic"] = 0

    channels = [c for c in matrix.columns if c not in ("user_id", "is_synthetic")]
    users = matrix["user_id"].tolist()
    n_users, n_channels = len(users), len(channels)
    real_mask = (matrix["is_synthetic"] == 0).values
    n_real = int(real_mask.sum())

    print(f"Device: {device}")
    print(f"Users: {n_users}  (real {n_real}, synthetic {n_users - n_real})")
    print(f"Channels: {n_channels}")
    print(f"Positive interactions: {int(matrix[channels].values.sum()):,}")

    if n_real < 20:
        print(f"\n  WARNING: only {n_real} real users. Leave-one-out metrics on\n"
              f"  real users will be computed over ~{n_real} data points and carry\n"
              f"  very wide error bars. Report them as directional only.")

    # ---------------- leave-one-out split ----------------
    test_cases, train_pairs, reserved = build_leave_one_out(
        matrix[channels], channels, rng)
    real_tests = [tc for tc in test_cases if real_mask[tc[0]]]
    synth_tests = [tc for tc in test_cases if not real_mask[tc[0]]]
    print(f"\nHeld-out test cases: {len(real_tests)} real, {len(synth_tests)} synthetic")
    print(f"Training pairs (positives): {len(train_pairs):,}")

    watched_by_user = {}
    for u, c in train_pairs:
        watched_by_user.setdefault(u, set()).add(c)

    # ---------------- dataset with negative sampling ----------------
    class NCFData(Dataset):
        def __init__(self):
            self.samples = []
            for u, c in train_pairs:
                self.samples.append((u, c, 1.0))
            for u, watched in watched_by_user.items():
                # exclude BOTH watched items and this user's reserved
                # evaluation negatives from the training negative pool
                blocked = watched | reserved.get(u, set())
                pool = np.setdiff1d(np.arange(n_channels), np.array(sorted(blocked)))
                n_neg = min(len(pool), len(watched) * args.neg_ratio)
                if n_neg > 0:
                    for c in rng.choice(pool, size=n_neg, replace=False):
                        self.samples.append((u, int(c), 0.0))

        def __len__(self):
            return len(self.samples)

        def __getitem__(self, i):
            u, c, y = self.samples[i]
            return (torch.tensor(u), torch.tensor(c), torch.tensor(y, dtype=torch.float))

    ds = NCFData()
    loader = DataLoader(ds, batch_size=args.batch_size, shuffle=True)
    print(f"Training samples (pos+neg): {len(ds):,}")

    # ---------------- model ----------------
    class NeuMF(nn.Module):
        def __init__(self):
            super().__init__()
            self.gmf_u = nn.Embedding(n_users, args.embed_dim)
            self.gmf_i = nn.Embedding(n_channels, args.embed_dim)
            self.mlp_u = nn.Embedding(n_users, args.embed_dim)
            self.mlp_i = nn.Embedding(n_channels, args.embed_dim)
            mods, size = [], args.embed_dim * 2
            for h in mlp_layers:
                mods += [nn.Linear(size, h), nn.ReLU(), nn.Dropout(args.dropout)]
                size = h
            self.mlp = nn.Sequential(*mods)
            self.predict = nn.Linear(args.embed_dim + mlp_layers[-1], 1)
            for emb in (self.gmf_u, self.gmf_i, self.mlp_u, self.mlp_i):
                nn.init.normal_(emb.weight, std=0.01)

        def forward(self, u, i):
            gmf = self.gmf_u(u) * self.gmf_i(i)
            mlp = self.mlp(torch.cat([self.mlp_u(u), self.mlp_i(i)], dim=-1))
            return torch.sigmoid(self.predict(torch.cat([gmf, mlp], dim=-1)).squeeze(-1))

    model = NeuMF().to(device)
    print(f"Parameters: {sum(p.numel() for p in model.parameters()):,}")

    criterion = nn.BCELoss()
    opt = torch.optim.Adam(model.parameters(), lr=args.lr)

    # ---------------- train ----------------
    print(f"\n{'Epoch':>5} | {'Loss':>9}")
    print("-" * 18)
    for epoch in range(1, args.epochs + 1):
        model.train()
        total = 0.0
        for u, c, y in loader:
            u, c, y = u.to(device), c.to(device), y.to(device)
            opt.zero_grad()
            loss = criterion(model(u, c), y)
            loss.backward()
            opt.step()
            total += loss.item()
        if epoch % 5 == 0 or epoch == 1:
            print(f"{epoch:>5} | {total / len(loader):>9.4f}")

    # ---------------- evaluate ----------------
    model.eval()

    def ncf_score(u_idx, cand):
        with torch.no_grad():
            ut = torch.full((len(cand),), u_idx, dtype=torch.long, device=device)
            ct = torch.tensor(cand, dtype=torch.long, device=device)
            return model(ut, ct).cpu().numpy()

    popularity = matrix.loc[real_mask, channels].values.sum(axis=0).astype(float)

    def pop_score(u_idx, cand):
        return popularity[cand]

    print("\n" + "=" * 62)
    print("LEAVE-ONE-OUT EVALUATION")
    print("=" * 62)

    metrics = {}
    for name, cases in (("real_users", real_tests), ("synthetic_users", synth_tests)):
        if not cases:
            continue
        ncf_m = evaluate(ncf_score, cases, n_channels, k_values, rng)
        pop_m = evaluate(pop_score, cases, n_channels, k_values, rng)
        metrics[name] = {"ncf": ncf_m, "popularity_baseline": pop_m,
                         "n_users_evaluated": len(cases)}

        print(f"\n{name.replace('_', ' ').upper()}  (n = {len(cases)})")
        print(f"  {'K':>4} | {'HR@K':>8} {'NDCG@K':>8} | {'HR base':>8} {'NDCG base':>10}")
        print("  " + "-" * 50)
        for k in k_values:
            print(f"  {k:>4} | {ncf_m[k]['HR']:>8.4f} {ncf_m[k]['NDCG']:>8.4f} | "
                  f"{pop_m[k]['HR']:>8.4f} {pop_m[k]['NDCG']:>10.4f}")

    if real_tests and len(real_tests) < 20:
        print(f"\n  NOTE: real-user metrics come from {len(real_tests)} held-out "
              f"interactions.\n  Directional only — not a statistically reliable estimate.")
    if synth_tests:
        print("\n  NOTE: synthetic-user metrics measure whether NCF can recover the\n"
              "  copula's structure. They are NOT evidence of real-world quality.")

    # ---------------- scores for the fusion layer ----------------
    rows = []
    with torch.no_grad():
        all_c = torch.arange(n_channels, dtype=torch.long, device=device)
        for u_idx, uid in enumerate(users):
            ut = torch.full((n_channels,), u_idx, dtype=torch.long, device=device)
            s = model(ut, all_c).cpu().numpy()
            for c_idx, ch in enumerate(channels):
                rows.append({"user_id": uid, "channel": ch,
                             "ncf_score": round(float(s[c_idx]), 4)})
    pd.DataFrame(rows).to_csv(args.out_scores, index=False)

    with open(args.out_metrics, "w") as f:
        json.dump({
            "config": {"embed_dim": args.embed_dim, "mlp_layers": mlp_layers,
                       "epochs": args.epochs, "neg_ratio": args.neg_ratio,
                       "n_users": n_users, "n_real_users": n_real,
                       "n_channels": n_channels},
            "metrics": metrics,
            "caveats": [
                "Real-user metrics computed over a small held-out sample; directional only.",
                "Synthetic-user metrics measure copula-structure recovery, not real quality.",
                "Protocol: leave-one-out, held-out item ranked against 99 negatives that were "
                "reserved from training (disjoint from training negatives).",
            ],
        }, f, indent=2)

    print(f"\nWrote {args.out_scores} ({len(rows):,} rows) and {args.out_metrics}")


if __name__ == "__main__":
    main()
