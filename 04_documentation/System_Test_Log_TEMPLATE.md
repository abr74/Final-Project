# YouFeelings — Manual System Test Log

**Tester:** Samyak Dubey **Date:** ______
**Commit tested:** `git rev-parse --short HEAD` → ______
**Environment:** AWS (v2 parallel stack) — `uploads-v2/` → `parsed-v2/` → `recommendations-v2/`

> Per Ashab: pull latest commits first (`git pull`), use his system test list, and
> skip the Google OAuth cases if the latest commit removed that portion.
> Every executed case needs a screenshot.

---

## How to run each case

1. Note the test ID from Ashab's list
2. Perform the steps exactly as written
3. **Screenshot the result** — name it `TC-<id>.png`
4. Fill in the row below
5. If it fails, capture the error text/log too (`aws logs tail /aws/lambda/<fn> --since 5m`)

---

## Results

| ID | Test case | Steps | Expected | Actual | Pass/Fail | Screenshot |
|---|---|---|---|---|---|---|
| TC-01 | | | | | | `TC-01.png` |
| TC-02 | | | | | | `TC-02.png` |
| TC-03 | | | | | | |
| TC-04 | | | | | | |
| TC-05 | | | | | | |

---

## AWS-specific cases worth covering

These map to the pipeline as deployed; fold them into Ashab's IDs where they fit.

| Area | What to verify | How |
|---|---|---|
| Upload URL | Presigned URL returned, 15-min TTL | POST to the upload-url endpoint; check `expiresIn: 900` |
| Upload | Large `.zip` (>100 MB) uploads without expiry | Upload a real Takeout; confirm 200 from S3 |
| Trigger 1 | `.zip` in `uploads-v2/` fires the parser | `aws s3 ls s3://netfeeling/parsed-v2/ --recursive` |
| Session isolation | Each upload gets its own folder | Output path is `parsed-v2/{uuid}/…`, **not** `parsed-v2/Uploads/…` |
| Trigger 2 | `central_output.json` fires the recommender | `aws s3 ls s3://netfeeling/recommendations-v2/` |
| Personalization | Two different histories → different results | Compare `aspect_profile` across two uploads; weights must differ |
| Cold start | New user with no collaborative history still gets results | Response `mode` = `cold_start`, recommendations non-empty |
| Results API | `?userId=` returns that user's file | GET with a known id |
| Results API | Unknown/incomplete id returns 404 "processing" | GET with a bogus id |
| Error handling | Non-zip upload rejected | Upload a `.txt`; expect a clear message, no crash |
| Isolation | Ashab's stack unaffected | `aws s3 ls s3://netfeeling/recommendations/` unchanged |

---

## Defects found

| # | Severity | Description | Steps to reproduce | Screenshot |
|---|---|---|---|---|
| 1 | | | | |

---

## Summary

- Cases executed: ___ / ___
- Passed: ___  Failed: ___  Blocked: ___
- Not applicable (Google OAuth removed): ___

**Notes for Ashab:**
-
