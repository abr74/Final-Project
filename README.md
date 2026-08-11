# YouFeelings — Complete System

An aspect-based, explainable YouTube recommender. Instead of ranking by watch
time, it reads what viewers actually say about a channel across five aspects —
**content, entertainment, creator, production, informativeness** — builds a
per-user preference profile from those aspects, and explains every
recommendation in terms of the specific quality that user favours.

Samyak Dubey · Ashab Rahman · Drexel University senior project · August 2026

---

## Contents

```
01_ml_pipeline/        offline: data -> models -> serving artifacts
02_backend_lambdas/    AWS pipeline: upload -> parse -> recommend
03_frontend/           upload flow + results page
04_documentation/      SRS, stakeholder deck, spring review, test template
05_backups/            original 12-channel artifacts (recovered)
```

---

## How the system works

```
  Google Takeout .zip
        |  presigned S3 upload
        v
  uploads-v2/{uuid}/          --S3 event-->  yf-v2-takeout-parser
        |
        v
  parsed-v2/{uuid}/central_output.json  --S3 event-->  yf-v2-fusion-recommender
        |                                                      |
        |                              reads models-v2/ artifacts
        v                                                      v
  recommendations-v2/{uuid}.json  <--GET--  yf-v2-get-recommendations  -->  UI
```

Three signals are fused per user:

| signal | weight | what it contributes |
|---|---|---|
| aspect sentiment (BERT) | 40% | which qualities this user actually values |
| collaborative (NeuMF) | 35% | what similar viewers watch |
| content (TF-IDF) | 25% | channels resembling their history |

Scores are min-max normalised **before** weighting, so 40/35/25 are the real
weights. When a signal is unavailable — a first-time visitor has no
collaborative history — its weight is redistributed rather than scored as zero.

---

## 01 — ML pipeline

Run in order. Each script has `--help`.

```bash
pip install beautifulsoup4 lxml sdv transformers torch scikit-learn

python3 01_ingest_watch_histories.py --input-dir ./takeouts --top-channels 300
python3 02_synthesize_users.py  --matrix ncf_interaction_matrix.csv --n 600
python3 00_bert_absa_train.py   --data comments_labeled_synthetic.csv --epochs 5

export YOUTUBE_API_KEY=...
python3 04_scrape_channels.py   --lookup channel_lookup.csv --max-channels 300
python3 05_score_comments.py    --model-dir ./bert_absa_out --comments comments_raw_expanded.csv
python3 07_ncf_train.py         --matrix combined_matrix.csv --epochs 10

python3 03_fusion.py --matrix ncf_interaction_matrix.csv \
                     --scored comments_scored_expanded.csv \
                     --ncf ncf_scores.csv --metadata channel_metadata.csv \
                     --reliability aspect_reliability.json

python3 08_build_serving_artifacts.py
aws s3 cp serving/ s3://netfeeling/models-v2/ --recursive --exclude '*' --include '*.json'
```

`06_content_features.py` is imported by `03_fusion.py` and `08_…`; it does not
need to be run directly, though running it prints nearest-neighbour channels as
a sanity check on the content feature space.

Participant watch histories are pseudonymised at ingest (`user_001`…). The
identity map is written to `pii_user_map.csv`, **outside** the training data —
keep it out of any repo or S3 prefix that holds model inputs.

---

## 02 — Backend

Deploys as a **second pipeline alongside the existing one**, on its own S3
prefixes, so the original stack is never at risk.

```bash
# CloudShell
bash deploy_v2.sh        # creates the four yf-v2-* functions
bash patch_parser.sh     # shrinks central_output.json ~80%
```

Then add two S3 event notifications (console):

| prefix | suffix | destination |
|---|---|---|
| `uploads-v2/` | `.zip` | `yf-v2-takeout-parser` |
| `parsed-v2/` | `central_output.json` | `yf-v2-fusion-recommender` |

`DEPLOY_V2.md` has the full runbook, env vars, and rollback.

---

## 03 — Frontend

`results_preview.html` opens in a browser with no build step and renders the
live response shape. `Landing.jsx` handles upload and polls for results.

The results page leads with the **taste fingerprint** — the one thing YouTube
cannot show you — and the recommendation list follows from it.

---

## Current state

**Working end to end.** Upload through to explained recommendations, verified
on a real 124 MB Takeout: 109 recognised channels, a differentiated aspect
profile (informativeness 0.37, creator 0.26, entertainment 0.24, production
0.07, content 0.06), and ten recommendations with per-signal attribution.

Scale, versus the spring build:

| | spring | now |
|---|---|---|
| real participants | 3 | 7 |
| channel universe | 12 | 300 (261 with aspect scores) |
| analysed comments | 6,532 | 28,550 |
| synthetic mid-frequency fidelity | 0.29 | 0.94 |

---

## What we are not claiming

These are data limitations, stated deliberately. None is a defect in the code.

**Training labels are the ceiling.** Labels came from a rule-based generator,
not human annotation. It produced zero `neutral` examples and only 33 for the
`production` aspect, so the model cannot learn those categories regardless of
training time. At inference the `creator` head fires on 84% of comments and
`informativeness` never predicts negative. Per-aspect F1 tracks label count
almost exactly (informativeness 0.79, creator 0.66, entertainment 0.29).
Model quality now depends on annotation, not engineering.

**Held-out evaluation is directional.** Leave-one-out on 7 real users is 7 data
points. Report K=5 with that caveat, never as a headline accuracy figure.

**The evaluation regime is favourable.** A popularity-only baseline also scores
highly (HR@20 = 1.0 on real users), which indicates the test is easy given how
densely participants' viewing overlaps. Popularity-stratified negatives would
make it harder and more defensible.

**Sentiment scores are not validated.** Scores across 261 channels come from a
model trained on 12. Usable for ranking; not presented as validated sentiment.

**Match percentages saturate.** Min-max normalisation stretches the top of the
range once watched channels are excluded, so the leader often shows ~99%.
Consider capping the displayed figure before a live demo.

---

## Known next steps

1. **Human annotation** — a stratified sample of ~300–500 comments labelled
   independently by two annotators, with a shared subset for inter-annotator
   agreement. This is the binding constraint on quality.
2. **API Gateway routes** for `yf-v2-upload-url` and `yf-v2-get-recommendations`,
   then point `Landing.jsx` at them.
3. **`channel_cats.json` still covers 12 channels**, so category labels render
   as "unknown". Rebuild it from the 300-channel set.
4. **Retire the OAuth path or relabel it.** `activities?mine=true` returns the
   user's own channel activity, and `youtube.readonly` does not grant watch
   history — so that button cannot feed the recommender as written.
5. **Document reconciliation** — the SRS still cites some superseded figures.

---

## A note on the most consequential fix

The fusion layer previously scored every channel with `bert_overall`, a
per-channel average identical for every user. Forty per cent of every
recommendation was a constant, and the aspect-based personalisation — the
product's entire premise — was not implemented. It now builds a genuine
per-user profile from aspect deviations, weighted by how reliably the model
detects each aspect. Verified on contrasting profiles: an education-heavy
viewer and an entertainment-heavy viewer receive different channels and
different explanations, where previously both were recommended the same thing.
