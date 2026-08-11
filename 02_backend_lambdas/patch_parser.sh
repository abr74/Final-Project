#!/usr/bin/env bash
#
# Patch parser.py inside yf-v2-takeout-parser
# ===========================================
# central_output.json is currently 254 MB for a 300k-event history, which
# forced the fusion lambda to 3 GB of memory. Three causes, all in parser.py:
#
#   1. raw={"html_text": str(cell)} stores the full HTML of EVERY watch and
#      search event. This is the bulk of the file. Nothing downstream reads
#      it -- the fusion lambda only uses record_type and channel_title.
#
#   2. soup.find_all(["div","li"]) matches nested ancestors, so one watch
#      event is emitted 2-4 times. Inflates the file AND skews watch counts.
#
#   3. write_output() writes central_output.json + all_records.jsonl + one
#      .jsonl per record type -- three copies of the same data, all uploaded
#      to S3 and all competing for Lambda's 512 MB /tmp.
#
# Only Ashab's v2 copy is touched. His takeout-parser is untouched.
#
# Usage (CloudShell):   bash patch_parser.sh

set -euo pipefail

FN="yf-v2-takeout-parser"
WORK="${HOME}/parser-patch"

echo "Patching ${FN}"
rm -rf "$WORK" && mkdir -p "$WORK" && cd "$WORK"

url=$(aws lambda get-function --function-name "$FN" --query 'Code.Location' --output text)
curl -s -o current.zip "$url"
mkdir -p pkg && cd pkg && unzip -oq ../current.zip && cd ..

if [ ! -f pkg/parser.py ]; then
  echo "ERROR: parser.py not found in the package. Contents:"
  ls -la pkg
  exit 1
fi

BEFORE=$(wc -c < pkg/parser.py)
cp pkg/parser.py "${WORK}/parser.py.bak"

python3 - <<'PYEOF'
import re, sys

path = "pkg/parser.py"
src = open(path, encoding="utf-8").read()
orig = src
changes = []

# ---- 1. stop storing raw HTML per record -------------------------------
n = src.count('raw={"html_text": str(cell)},')
if n:
    src = src.replace('raw={"html_text": str(cell)},', 'raw={},')
    changes.append(f"dropped stored raw HTML from {n} record site(s)")

# ---- 2. only iterate the real outer cells ------------------------------
old_cells = '        cells = soup.find_all(["div", "li"])'
new_cells = ('        # Takeout nests divs several levels deep; matching every div/li\n'
             '        # emits the same event 2-4 times (once per ancestor).\n'
             '        cells = soup.find_all("div", class_="outer-cell")\n'
             '        if not cells:                      # older export formats\n'
             '            cells = soup.find_all(["div", "li"])')
n = src.count(old_cells)
if n:
    src = src.replace(old_cells, new_cells)
    changes.append(f"scoped cell iteration to div.outer-cell in {n} parser(s)")

# ---- 3. write only what downstream consumes ----------------------------
old_extra = '''        all_records_path = out_dir / "all_records.jsonl"
        with all_records_path.open("w", encoding="utf-8") as f:
            for record in result.get("all_records", []):
                f.write(json.dumps(record, ensure_ascii=False) + "\\n")'''
new_extra = '''        # all_records.jsonl and the per-type .jsonl files duplicate
        # central_output.json three times over. Only central_output.json is
        # consumed downstream, and Lambda's /tmp is 512 MB. Set
        # WRITE_JSONL=1 to restore them for local debugging.
        write_jsonl = os.environ.get("WRITE_JSONL") == "1"

        if write_jsonl:
            all_records_path = out_dir / "all_records.jsonl"
            with all_records_path.open("w", encoding="utf-8") as f:
                for record in result.get("all_records", []):
                    f.write(json.dumps(record, ensure_ascii=False) + "\\n")'''
if old_extra in src:
    src = src.replace(old_extra, new_extra)
    changes.append("made all_records.jsonl optional (WRITE_JSONL=1)")

# guard the per-record-type jsonl loop the same way
old_loop = '''        for record_type, records in grouped.items():
            file_path = out_dir / f"{record_type}.jsonl"
            with file_path.open("w", encoding="utf-8") as f:
                for record in records:
                    f.write(json.dumps(record, ensure_ascii=False) + "\\n")'''
new_loop = '''        if write_jsonl:
            for record_type, records in grouped.items():
                file_path = out_dir / f"{record_type}.jsonl"
                with file_path.open("w", encoding="utf-8") as f:
                    for record in records:
                        f.write(json.dumps(record, ensure_ascii=False) + "\\n")'''
if old_loop in src:
    src = src.replace(old_loop, new_loop)
    changes.append("made per-type .jsonl optional")

# manifest lists files that may no longer exist
src = src.replace(
    '''            "files_written": ["central_output.json", "all_records.jsonl"]
            + [f"{record_type}.jsonl" for record_type in sorted(grouped.keys())],''',
    '''            "files_written": ["central_output.json"] + (
                ["all_records.jsonl"]
                + [f"{record_type}.jsonl" for record_type in sorted(grouped.keys())]
                if write_jsonl else []),''')

# parser.py must import os for the env flag
if "\nimport os\n" not in src:
    src = src.replace("import json\n", "import json\nimport os\n", 1)
    changes.append("added missing 'import os'")

if src == orig:
    print("NOTHING CHANGED -- the file may already be patched.")
    sys.exit(2)

open(path, "w", encoding="utf-8").write(src)
print("Applied:")
for c in changes:
    print("  -", c)
PYEOF

python3 -m py_compile pkg/parser.py && echo "parser.py compiles"

AFTER=$(wc -c < pkg/parser.py)
echo "parser.py ${BEFORE} -> ${AFTER} bytes"

cd pkg && rm -f ../patched.zip && zip -qr ../patched.zip . && cd ..
echo "repackaged ($(du -h patched.zip | cut -f1))"

aws lambda update-function-code --function-name "$FN" \
    --zip-file "fileb://${WORK}/patched.zip" >/dev/null
aws lambda wait function-updated --function-name "$FN"
echo "deployed"

echo
echo "Now re-run a large file and compare central_output.json size:"
echo "  aws s3 cp s3://netfeeling/uploads-v2/run3/t.zip s3://netfeeling/uploads-v2/run5/t.zip"
echo "  sleep 90"
echo "  aws s3 ls s3://netfeeling/parsed-v2/run5/ --recursive --human-readable"
echo
echo "Backup of the original parser.py: ${WORK}/parser.py.bak"
