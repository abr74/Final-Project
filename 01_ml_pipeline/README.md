# YouFeelings — Fixed Pipeline (Steps 1–3)

Drop these into your SageMaker `~/shared/` folder. Each replaces a notebook.

## Run order

```bash
pip install beautifulsoup4 lxml sdv transformers torch scikit-learn

# 1. Ingest all 10 participants (pseudonymized). Put their files in ./takeouts/
python 01_ingest_watch_histories.py --input-dir ./takeouts --top-channels 150

# 2. Synthetic users (synth_* namespace, re-binarized)
python 02_synthesize_users.py --matrix ncf_interaction_matrix.csv --n 600

# 3. BERT ABSA (the DataLoader bug is fixed; 256 tokens)
python 00_bert_absa_train.py --data comments_labeled_synthetic.csv --epochs 5

# 4. Personalized fusion
python 03_fusion.py --matrix ncf_interaction_matrix.csv \
                    --scored comments_scored.csv \
                    --pool comments_pool_12.csv \
                    --ncf ncf_scores.csv
```

## What changed vs. the notebooks

| File | Replaces | Key fix |
|---|---|---|
| `00_bert_absa_train.py` | `bert_pipeline.ipynb` | DataLoaders were inside a `'''...'''` string → training crashed. Also MAX_LENGTH 128→256, early stopping now breaks, reports F1 excluding the dominant "none" class. |
| `01_ingest_watch_histories.py` | `DataSynthesis.ipynb` (parse block) | Hardcoded 3 paths → folder loop for N users; pseudonymizes to `user_001…`; PII map written separately; reports co-watch overlap. |
| `02_synthesize_users.py` | `DataSynthesis.ipynb` (copula block) | Faker real names → `synth_00001…`; re-binarizes copula output; nan-safe validation. |
| `03_fusion.py` | `YouFeelings_Fusion.ipynb` | **BERT term is now per-user**, not a channel constant. Adds min-max normalization before weighting, weight redistribution when a signal is missing, and truthful explanations. |

## Still to do (steps 4–6)
4. Port leave-one-out HR@K / NDCG@K eval into the PyTorch NCF (real users only in test).
5. Expand the channel universe beyond the current 12 (needs a scraper pass on new channels).
6. Wrap as a SageMaker training job for `ml.g4dn.xlarge`.

## Privacy
`pii_user_map.csv` maps pseudonyms to source filenames. Keep it out of the
training set and off S3 alongside the model artifacts.

---

## Step 5 — Channel scraper (NEW)

`01_ingest_watch_histories.py` now also captures **channel IDs** from the
Takeout HTML (they're in the `/channel/UC...` href, free) and writes
`channel_lookup.csv`. This is what makes the scraper cheap.

```bash
# 1. Re-run ingest to produce channel_lookup.csv
python3 01_ingest_watch_histories.py --input-dir ./takeouts --top-channels 300

# 2. Check the quota cost before spending anything
python3 04_scrape_channels.py --lookup channel_lookup.csv --estimate-only

# 3. Scrape (resumable — safe to re-run)
export YOUTUBE_API_KEY=your_key_here
python3 04_scrape_channels.py --lookup channel_lookup.csv --max-channels 300
```

### Why it's ~25x cheaper
| Route | Cost for 300 channels |
|---|---|
| `search.list` per channel | ~30,000 units (3 days) |
| `channels.list` -> uploads playlist -> `playlistItems.list` | **~1,206 units (12% of one day)** |

Channel IDs come free from Takeout, so no name->ID resolution is needed.

### Outputs
- `comments_raw_expanded.csv` — cleaned comments across all 300 channels
- `channel_metadata.csv` — subscriber count, avg views/video, uploads/month,
  category signals. **This is the metadata the SRS says CBF should use**, so it
  unblocks the proper TF-IDF content filter.
- `scrape_state.json` — resume checkpoint (re-run after a quota reset)
- `scrape_report_expanded.json` — cleaning stats + quota usage

Tuning knobs: `--videos-per-channel` (default 3) and `--comments-per-video`
(default 100). Raising either raises quota cost roughly linearly.

---

## Step 6 — Score the scraped comments (NEW)

The missing link between the scraper and the fusion layer.

```bash
# smoke test on 500 comments first
python3 05_score_comments.py --model-dir ./bert_absa_out \
                             --comments comments_raw_expanded.csv --limit 500

# full run (~28,550 comments, a few minutes on the T4)
python3 05_score_comments.py --model-dir ./bert_absa_out \
                             --comments comments_raw_expanded.csv

# fusion now covers all 300 channels, with aspect reliability applied
python3 03_fusion.py --matrix ncf_interaction_matrix.csv \
                     --scored comments_scored_expanded.csv \
                     --pool comments_pool_12.csv \
                     --ncf ncf_scores.csv \
                     --reliability aspect_reliability.json
```

### Aspect reliability weighting
Training showed per-aspect F1 tracks label count almost exactly:

| aspect | labels | F1 (excl none) | weight |
|---|---|---|---|
| creator | 1,102 | 0.30 | 1.00 |
| informativeness | 571 | 0.26 | 0.90 |
| content | 178 | 0.26 | 0.89 |
| production | 33 | 0.15 | 0.57 |
| entertainment | 217 | 0.14 | 0.55 |

`05_score_comments.py` writes these to `aspect_reliability.json`, and
`03_fusion.py` uses them to scale each aspect's contribution to a user's
taste profile. Without this, production -- 33 training labels, F1 measured on
4 test examples -- steers personalization as strongly as informativeness.

Weights are floored at 0.15 so no aspect is discarded entirely. Re-run
step 6 after any retrain to refresh them.

---

## Step 7 — Proper content-based filtering (NEW)

`06_content_features.py` replaces the category-share heuristic with TF-IDF
cosine over channel metadata, which is what SRS R3.3.3.1/R3.3.3.2 specify.

Why it was needed: category-share reads `category` from
`comments_pool_12.csv`, which covers only 12 of 261 channels. Every other
channel scored 0, so the content signal contributed nothing across 95% of
the catalog.

Features per channel:
- **text (75%)**: TF-IDF over description + title, 1-2 grams
- **numeric (25%)**: log10 subscribers, log10 avg views/video,
  uploads/month, log10 video count

The two blocks are L2-normalized *separately* before combining. Skipping that
lets 4 dense numeric columns dominate a sparse TF-IDF block, so cosine ends up
measuring "similar subscriber count" instead of "similar topic".

`03_fusion.py` picks this up automatically when `channel_metadata.csv` exists,
and falls back to category-share when it doesn't.

```bash
# inspect the feature space (prints nearest neighbours as a sanity check)
python3 06_content_features.py --metadata channel_metadata.csv

# full fusion over all scored channels
python3 03_fusion.py --matrix ncf_interaction_matrix.csv \
                     --scored comments_scored_expanded.csv \
                     --pool comments_pool_12.csv \
                     --ncf ncf_scores.csv \
                     --metadata channel_metadata.csv \
                     --reliability aspect_reliability.json
```

Tune with `--text-weight` (default 0.75) if topic vs popularity needs rebalancing.

---

## Step 8 — NCF retrain + leave-one-out evaluation (NEW)

Replaces both `YouFeelings_NCF.ipynb` (PyTorch, no eval) and
`netfeelings_ncf_pipeline.ipynb` (TensorFlow duplicate). Keep the PyTorch
NeuMF architecture; the evaluation utilities are ported in here.

```bash
python3 07_ncf_train.py --matrix combined_matrix.csv --epochs 30

# then re-run fusion WITH the collaborative signal restored
python3 03_fusion.py --matrix ncf_interaction_matrix.csv \
                     --scored comments_scored_expanded.csv \
                     --pool comments_pool_12.csv \
                     --ncf ncf_scores.csv \
                     --metadata channel_metadata.csv \
                     --reliability aspect_reliability.json
```

### Protocol (He et al. 2017)
Hold out one watched channel per user. Rank it against 99 sampled unwatched
channels. HR@K = did it land in the top K; NDCG@K = position-discounted.

### Two separate evaluations — never averaged together
- **real users** — the number that matters, but n is small
- **synthetic users** — larger n, but only shows NCF can recover the copula's
  structure. NOT evidence of real-world quality.

### Popularity baseline
Every run also scores a popularity-only recommender. NCF beating nothing is
not a result; the comparison is what makes HR@K meaningful.

### Train/eval negative disjointness (important)
Each user's 99 evaluation negatives are sampled ONCE and excluded from
training negative sampling.

Without this, training drives the sampled negatives toward 0 and the model
memorizes them (loss ~0.015). At eval, most sampled negatives are ones the
model was trained to score ~0, while the held-out positive is unseen for that
user and gets a middling score -- so it ranks #1 by default and every metric
pins at 1.0000. That is leakage, not performance. If you ever see HR and NDCG
both at exactly 1.0, suspect this first.

### Outputs
- `ncf_scores.csv` — user x channel scores for the fusion layer
- `ncf_eval.json` — metrics, config, and caveats, ready to cite in the report

---

## Steps 9-10 — MVP serving layer (NEW)

`08_build_serving_artifacts.py` replaces `generate_lookup_tables.py`, which
still targeted the 12-channel files and the old user IDs.

```bash
python3 08_build_serving_artifacts.py
aws s3 cp serving/ s3://netfeeling/models/ --recursive --exclude '*' --include '*.json'
```

Produces six artifacts (a few hundred KB total, sized for Lambda cold start):

| file | contents |
|---|---|
| `bert_scores.json` | per-channel aspect vectors |
| `channel_similar.json` | top-25 similar channels each (from TF-IDF space) |
| `channel_meta.json` | subscribers, avg views, uploads/month |
| `channel_videos.json` | representative video per channel |
| `ncf_scores.json` | **real users only** — synthetic never served |
| `aspect_reliability.json` | per-aspect trust weights |

Shipping top-25 neighbour lists instead of the full NxN similarity matrix keeps
the payload ~10x smaller with no loss for serving.

### `09_recommend_lambda.py` — the recommendation handler

Mirrors `03_fusion.py` scoring exactly, so deployed behaviour matches what was
evaluated offline. **If you change scoring in one, change it in both.**

```json
POST { "watched_channels": ["3Blue1Brown","TED"], "user_id": "user_003", "top_k": 10 }
```

**Cold start works.** A first-time visitor has no NCF row, so their aspect
profile is built from the channels in their own upload and NCF's 0.35 is
redistributed across BERT and content (SRS R3.3.4.4). Verified:

- education upload -> informativeness 0.611 -> Vsauce, Fireship
- entertainment upload -> entertainment 0.451 -> different channels entirely
- known user -> all three signals at 0.40 / 0.35 / 0.25

The response includes `signals_used` and `applied_weights` so the UI can show
honestly which signals contributed.
