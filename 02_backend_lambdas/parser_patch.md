# `parser.py` — two changes needed before demoing a large Takeout

Both are in `_parse_watch_history` (and the same pattern in
`_parse_search_history`). Neither changes the output schema.

## 1. Duplicate records from nested elements

```python
cells = soup.find_all(["div", "li"])
```

Takeout HTML nests divs several levels deep (`outer-cell > mdl-grid >
content-cell`). Every ancestor that contains a `watch?v=` link produces its own
record, so a single watch event is emitted 2–4 times. That inflates the record
count and skews every downstream watch_count.

**Change to:**

```python
cells = soup.find_all("div", class_="outer-cell")
if not cells:                       # fall back for older export formats
    cells = soup.find_all(["div", "li"])
```

## 2. Memory — the real demo risk

```python
raw={"html_text": str(cell)},
```

This stores the full HTML of every watch event. With ~27,000 entries (your
larger participants) that is a `central_output.json` in the hundreds of MB,
which Lambda will either OOM or time out on, and which the fusion lambda then
has to download and parse again.

**Change to:**

```python
raw={},                             # HTML retained only for debugging
```

Or gate it: `raw={"html_text": str(cell)} if os.environ.get("KEEP_RAW_HTML") else {}`

Nothing downstream reads `raw` for watch events — `youfeelings-fusion-recommender`
only reads `record_type`, `channel_title`.

## Optional: also drop `all_records.jsonl`

`write_output` writes `central_output.json` **and** `all_records.jsonl` **and**
one JSONL per record type — three copies of the same data, all uploaded to S3.
For the demo path only `central_output.json` is consumed.
