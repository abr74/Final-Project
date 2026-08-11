"""
YouFeelings — Step 2: Synthetic user generation (Gaussian Copula / SDV)
======================================================================
Replaces the Faker-name block in DataSynthesis.ipynb.

Two changes that matter:

1. Synthetic users are named  synth_00001, synth_00002, ...
   NOT Faker real-person names. Real users are user_001...
   This makes "synthetic never enters evaluation" mechanically enforceable
   (SRS R3.2.4.3) instead of a naming convention you have to remember.

2. Copula output is re-binarized. GaussianCopula can emit values outside
   {0,1} on binary columns; concatenating those straight into the matrix
   silently poisons NCF's labels.

Outputs:
    synthetic_users.csv          synth_* rows only
    combined_matrix.csv          real + synthetic, with an is_synthetic flag
    synthesis_validation.json    real vs synthetic correlation report

Usage:
    python 02_synthesize_users.py --matrix ncf_interaction_matrix.csv --n 600
"""

import argparse
import json

import numpy as np
import pandas as pd


def validate(real_df, synth_df, top_k=10):
    """Compare real vs synthetic channel-frequency structure."""
    real_num = real_df.drop(columns=["user_id"], errors="ignore").select_dtypes("number")
    synth_num = synth_df.drop(columns=["user_id"], errors="ignore").select_dtypes("number")
    common = [c for c in real_num.columns if c in synth_num.columns]
    real_num, synth_num = real_num[common], synth_num[common]

    real_rate = real_num.mean()
    synth_rate = synth_num.mean()

    order = real_rate.sort_values(ascending=False)
    top = order.head(top_k).index
    mid = order.iloc[top_k: top_k * 3].index

    def safe_corr(a, b):
        """Pearson corr that returns None instead of nan on zero-variance input.

        This is the bug that produced nan correlations in the original
        notebook: constant columns have no variance, so corr is undefined.
        """
        if len(a) < 2 or np.std(a) == 0 or np.std(b) == 0:
            return None
        v = float(np.corrcoef(a, b)[0, 1])
        return None if np.isnan(v) else round(v, 4)

    # marginal watch-rate agreement
    rate_corr_all = safe_corr(real_rate.values, synth_rate.values)
    rate_corr_top = safe_corr(real_rate[top].values, synth_rate[top].values)
    rate_corr_mid = safe_corr(real_rate[mid].values, synth_rate[mid].values) if len(mid) > 1 else None

    # inter-channel co-viewing structure (the thing a copula is FOR)
    real_var = real_num.loc[:, real_num.nunique() > 1]
    synth_var = synth_num.loc[:, synth_num.nunique() > 1]
    shared_var = [c for c in real_var.columns if c in synth_var.columns]

    co_real = co_synth = None
    if len(shared_var) > 1:
        co_real = round(float(real_var[shared_var].corr().values[np.triu_indices(len(shared_var), 1)].mean()), 4)
        co_synth = round(float(synth_var[shared_var].corr().values[np.triu_indices(len(shared_var), 1)].mean()), 4)

    return {
        "n_real_users": int(len(real_df)),
        "n_synthetic_users": int(len(synth_df)),
        "n_channels": len(common),
        "watch_rate_corr_all_channels": rate_corr_all,
        "watch_rate_corr_top_channels": rate_corr_top,
        "watch_rate_corr_mid_channels": rate_corr_mid,
        "mean_inter_channel_corr_real": co_real,
        "mean_inter_channel_corr_synthetic": co_synth,
        "channels_with_variance_real": int(real_var.shape[1]),
        "channels_with_variance_synthetic": int(synth_var.shape[1]),
        "note": "null = undefined (zero variance), not zero correlation",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--matrix", default="ncf_interaction_matrix.csv",
                    help="Real user matrix from step 1")
    ap.add_argument("--n", type=int, default=600, help="How many synthetic users")
    ap.add_argument("--out-synth", default="synthetic_users.csv")
    ap.add_argument("--out-combined", default="combined_matrix.csv")
    ap.add_argument("--report", default="synthesis_validation.json")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    np.random.seed(args.seed)

    from sdv.single_table import GaussianCopulaSynthesizer

    real = pd.read_csv(args.matrix)
    channels = [c for c in real.columns if c != "user_id"]
    print(f"Real matrix: {len(real)} users x {len(channels)} channels")

    if len(real) < 3:
        print("WARNING: fewer than 3 real users — a copula cannot learn "
              "meaningful co-viewing structure from this.")

    # SDV >=1.3 prefers Metadata; SingleTableMetadata is deprecated and will
    # be removed. Try the new API first, fall back for older installs.
    try:
        from sdv.metadata import Metadata
        metadata = Metadata.detect_from_dataframe(real)
        table = list(metadata.tables)[0]
        metadata.update_column(column_name="user_id", sdtype="id", table_name=table)
    except (ImportError, AttributeError, TypeError):
        from sdv.metadata import SingleTableMetadata
        metadata = SingleTableMetadata()
        metadata.detect_from_dataframe(real)
        metadata.update_column(column_name="user_id", sdtype="id")

    print("Fitting Gaussian Copula ...")
    synth = GaussianCopulaSynthesizer(metadata)
    synth.fit(real)

    print(f"Sampling {args.n} synthetic users ...")
    sampled = synth.sample(num_rows=args.n)

    # --- namespace + re-binarize (both fixes) ---
    sampled["user_id"] = [f"synth_{i:05d}" for i in range(1, len(sampled) + 1)]
    for ch in channels:
        if ch in sampled.columns:
            sampled[ch] = (pd.to_numeric(sampled[ch], errors="coerce")
                           .fillna(0) > 0.5).astype(int)
        else:
            sampled[ch] = 0
    sampled = sampled[["user_id"] + channels]

    report = validate(real, sampled)

    real_out = real.copy()
    real_out["is_synthetic"] = 0
    synth_out = sampled.copy()
    synth_out["is_synthetic"] = 1
    combined = pd.concat([real_out, synth_out], ignore_index=True)

    sampled.to_csv(args.out_synth, index=False)
    combined.to_csv(args.out_combined, index=False)
    with open(args.report, "w") as f:
        json.dump(report, f, indent=2)

    print("\n--- validation ---")
    for k, v in report.items():
        if k != "note":
            print(f"  {k:38s} {v}")

    print(f"\nWrote:\n  {args.out_synth}\n  {args.out_combined}\n  {args.report}")
    print("\nReminder: filter is_synthetic == 0 before ANY evaluation split.")


if __name__ == "__main__":
    main()
