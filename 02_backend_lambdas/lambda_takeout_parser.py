"""
takeout-parser  (v2)
====================
FIX: v1 derived the user id as

    user_id = input_key.split("/")[0]        # key = "Uploads/{uuid}/file.zip"

which is the literal string "Uploads" for every upload. The {uuid} -- the only
thing that identifies the session -- was discarded, so every user wrote to
parsed/Uploads/... and overwrote each other. Concurrent demo users would
clobber one another's results.

v2 uses the UUID. It also fails loudly if the key shape is unexpected rather
than silently bucketing everyone together.
"""

import json
import os
import tempfile
from pathlib import Path
from urllib.parse import unquote_plus

import boto3

from parser import YouTubeTakeoutParser

s3 = boto3.client("s3")
OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET")
PARSED_PREFIX = os.environ.get("PARSED_PREFIX", "parsed-v2/")


def extract_upload_id(key):
    """<prefix>/{uuid}/file.zip -> uuid

    Works for any single-segment upload prefix (Uploads/, uploads-v2/, ...).
    The folder immediately containing the zip is the session id.
    """
    parts = [p for p in key.split("/") if p]
    if len(parts) >= 3:
        return parts[-2]
    if len(parts) >= 2:
        return parts[-2]
    return "unknown_user"


def lambda_handler(event, context):
    try:
        record = event["Records"][0]
        input_bucket = record["s3"]["bucket"]["name"]
        input_key = unquote_plus(record["s3"]["object"]["key"])

        if not input_key.lower().endswith(".zip"):
            return {"statusCode": 400,
                    "body": json.dumps({"message": "Uploaded file must be a .zip "
                                                   "Google Takeout file."})}

        output_bucket = OUTPUT_BUCKET or input_bucket
        user_id = extract_upload_id(input_key)          # <-- the fix
        print(f"input_key={input_key}  ->  user_id={user_id}")

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            takeout_dir = tmp_path / "Takeout Collection"
            output_dir = tmp_path / "parsed_output"
            takeout_dir.mkdir(parents=True, exist_ok=True)

            local_zip_path = takeout_dir / Path(input_key).name
            s3.download_file(input_bucket, input_key, str(local_zip_path))

            parser = YouTubeTakeoutParser(takeout_collection_dir=takeout_dir,
                                          output_dir=output_dir)
            result = parser.parse(local_zip_path.name)
            parser.write_output(result, output_dir)

            base_output_key = f"{PARSED_PREFIX}{user_id}/{local_zip_path.stem}"
            for file_path in output_dir.rglob("*"):
                if file_path.is_file():
                    s3.upload_file(str(file_path), output_bucket,
                                   f"{base_output_key}/{file_path.name}")

            return {"statusCode": 200,
                    "body": json.dumps({"message": "Takeout parsed successfully.",
                                        "user_id": user_id,
                                        "input_key": input_key,
                                        "output_prefix": base_output_key,
                                        "counts": result.get("counts", {})})}

    except Exception as e:
        print("ERROR:", str(e))
        return {"statusCode": 500,
                "body": json.dumps({"message": "Parser failed.", "error": str(e)})}
