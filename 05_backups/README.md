# Original model artifacts (pre-Aug 2026 rebuild)

Recovered from the code zip. These are the 12-channel artifacts the team
built in April-June 2026, before the 300-channel rebuild overwrote
s3://netfeeling/models/.

| file | contents |
|---|---|
| `bert_scores.json` | 12 channels, aspect scores + `bert_overall` |
| `channel_cats.json` | 12 channels -> category |
| `channel_videos.json` | 12 channels -> representative video |
| `ncf_scores.json` | 103 synthetic users (Faker names) x 12 channels |
| `scrape_report.json` | April scrape stats: 19,231 raw -> 6,532 cleaned |

Note `ncf_scores.json` keys are Faker-generated names ("Aaron Marshall"),
i.e. synthetic users. The three real users were `sam`, `ashab`, `tai`.

Restore to a SEPARATE prefix -- not `models/`, which now holds the
300-channel versions:

    aws s3 cp . s3://netfeeling/backups/models-original/ --recursive
