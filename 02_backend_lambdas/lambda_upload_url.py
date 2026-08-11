"""
upload-url-lambda  (v3)
=======================
FIX: ExpiresIn was 120 seconds. A 171 MB Takeout on typical wifi takes longer
than two minutes to upload, and the PUT fails mid-transfer with an expired
signature -- which looks exactly like the old SignatureDoesNotMatch bug and
is very confusing to debug. Raised to 900s (15 min), matching the SRS
requirement that presigned URLs be short-lived but usable (R4.3.5).

Also returns uploadId so the frontend can poll for results without having to
parse it back out of the object key.
"""

import json
import os
import uuid

import boto3
from botocore.config import Config

# SigV4 + pinned region: under SigV4 Content-Type is unsigned, so the browser's
# automatic "application/x-zip-compressed" cannot break the signature.
s3 = boto3.client(
    "s3",
    region_name=os.environ.get("BUCKET_REGION", "us-east-1"),
    config=Config(signature_version="s3v4"),
)

BUCKET_NAME = os.environ.get("BUCKET_NAME", "netfeeling")
UPLOAD_PREFIX = os.environ.get("UPLOAD_PREFIX", "uploads-v2/")
EXPIRES_IN = int(os.environ.get("UPLOAD_URL_TTL", "900"))

HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Allow-Methods": "POST,OPTIONS",
}


def lambda_handler(event, context):
    try:
        if event.get("httpMethod") == "OPTIONS":
            return {"statusCode": 200, "headers": HEADERS, "body": ""}

        body = json.loads(event.get("body") or "{}")
        file_name = body.get("fileName") or "upload.zip"
        upload_id = str(uuid.uuid4())
        object_key = f"{UPLOAD_PREFIX}{upload_id}/{file_name}"

        # ContentType stays OUT of Params so it remains unsigned.
        upload_url = s3.generate_presigned_url(
            ClientMethod="put_object",
            Params={"Bucket": BUCKET_NAME, "Key": object_key},
            ExpiresIn=EXPIRES_IN,
        )

        return {"statusCode": 200, "headers": HEADERS,
                "body": json.dumps({"uploadUrl": upload_url,
                                    "objectKey": object_key,
                                    "uploadId": upload_id,
                                    "expiresIn": EXPIRES_IN})}

    except Exception as e:
        return {"statusCode": 500, "headers": HEADERS,
                "body": json.dumps({"error": str(e)})}
