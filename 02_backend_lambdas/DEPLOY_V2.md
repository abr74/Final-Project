# YouFeelings v2 — parallel deployment (Ashab's stack untouched)

Nothing existing is modified. A second pipeline runs beside it on its own
S3 prefixes, so both can be demoed and compared.

| | existing (untouched) | new |
|---|---|---|
| upload prefix | `Uploads/` | `uploads-v2/` |
| parsed prefix | `parsed/` | `parsed-v2/` |
| results prefix | `recommendations/` | `recommendations-v2/` |
| models prefix | `models/` | `models-v2/` |
| parser | `takeout-parser` | `yf-v2-takeout-parser` |
| fusion | `youfeelings-fusion-recommender` | `yf-v2-fusion-recommender` |
| upload URL | `upload-url-lambda` | `yf-v2-upload-url` |
| results API | `recommendation-lambda` | `yf-v2-get-recommendations` |

**Why separate prefixes are mandatory:** S3 rejects overlapping event
notifications for the same event type + prefix + suffix. Two parsers cannot
both watch `Uploads/*.zip`.

## 1. Put the model artifacts on the v2 prefix

From SageMaker:
```bash
cd ~/run2
aws s3 cp serving/ s3://netfeeling/models-v2/ --recursive --exclude '*' --include '*.json'
```

## 2. Deploy the functions (CloudShell)

Upload the four `.py` files plus `deploy_v2.sh` into `~/yf-v2/`, then:

```bash
mkdir -p ~/yf-v2 && cd ~/yf-v2      # upload files here first
bash deploy_v2.sh
```

The script:
- reads the IAM roles off the existing functions (read-only; does not change them)
- pulls `parser.py` out of the deployed `takeout-parser` so there is only one
  copy of it to maintain
- reuses the shared `beautifulsoup-layer:1`
- creates all four functions with the right timeouts, memory and env vars
- sets `yf-v2-takeout-parser` to 15 min / 3008 MB

Safe to re-run: it updates rather than duplicating.

## 3. Add S3 triggers (console, manual on purpose)

S3 → `netfeeling` → Properties → Event notifications → **Create** (do not edit
the existing ones):

| prefix | suffix | destination |
|---|---|---|
| `uploads-v2/` | `.zip` | `yf-v2-takeout-parser` |
| `parsed-v2/` | `central_output.json` | `yf-v2-fusion-recommender` |

## 4. API Gateway

Add routes for `yf-v2-upload-url` (POST) and `yf-v2-get-recommendations` (GET),
then point `Landing.jsx` at the new invoke URLs (`UPLOAD_URL_API`,
`RECOMMENDATIONS_API`).

## 5. Smoke test

```bash
# copy any Takeout zip into the v2 prefix to fire the chain
aws s3 cp s3://netfeeling/<some-takeout>.zip s3://netfeeling/uploads-v2/testrun/t.zip

sleep 90
aws s3 ls s3://netfeeling/parsed-v2/ --recursive | head
aws s3 ls s3://netfeeling/recommendations-v2/
aws s3 cp s3://netfeeling/recommendations-v2/testrun.json - | python3 -m json.tool | head -40
```

Expect `"mode"`, a populated `"aspect_profile"`, and channels drawn from the
300-channel set. Ashab's `parsed/` and `recommendations/` must be unchanged.

## Rollback
Delete the four `yf-v2-*` functions and the two new S3 notifications. Nothing
else was altered.
