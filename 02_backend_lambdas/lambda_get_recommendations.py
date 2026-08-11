"""
recommendation-lambda  (v2)  — GET /recommendations?userId=...
==============================================================
FIX: v1 read a HARDCODED key:

    RECOMMENDATION_KEY = os.environ.get("RECOMMENDATION_KEY",
                                        "recommendations/sam.json")

so every visitor was served Sam's recommendations regardless of what they
uploaded. The upload, parse and fusion all worked -- the UI just showed the
wrong person's results.

v2 takes userId from the query string (the upload UUID the frontend already
receives as `objectKey`), and returns a clear 404 while the pipeline is still
running instead of a confusing 500.
"""

import json
import os

import boto3
from botocore.exceptions import ClientError

s3 = boto3.client("s3")

BUCKET_NAME = os.environ.get("BUCKET_NAME", "netfeeling")
OUTPUT_PREFIX = os.environ.get("OUTPUT_PREFIX", "recommendations-v2/")
FALLBACK_USER = os.environ.get("FALLBACK_USER", "")   # demo only; empty = off

CORS_HEADERS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type",
    "Access-Control-Allow-Methods": "GET,OPTIONS",
}


def lambda_handler(event, context):
    if event.get("httpMethod") == "OPTIONS":
        return {"statusCode": 200, "headers": CORS_HEADERS, "body": ""}

    qs = event.get("queryStringParameters") or {}
    user_id = qs.get("userId") or qs.get("user_id") or FALLBACK_USER

    if not user_id:
        return {"statusCode": 400, "headers": CORS_HEADERS,
                "body": json.dumps({"message": "Missing userId query parameter."})}

    key = f"{OUTPUT_PREFIX}{user_id}.json"

    try:
        response = s3.get_object(Bucket=BUCKET_NAME, Key=key)
        data = json.loads(response["Body"].read().decode("utf-8"))
        return {"statusCode": 200, "headers": CORS_HEADERS,
                "body": json.dumps(data)}

    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("NoSuchKey", "404"):
            # Not an error: the pipeline is still running. The frontend
            # should poll on this.
            return {"statusCode": 404, "headers": CORS_HEADERS,
                    "body": json.dumps({"status": "processing",
                                        "message": "Recommendations are not ready yet.",
                                        "user_id": user_id})}
        return {"statusCode": 500, "headers": CORS_HEADERS,
                "body": json.dumps({"message": "Failed to load recommendations",
                                    "error": str(e)})}
    except Exception as e:
        return {"statusCode": 500, "headers": CORS_HEADERS,
                "body": json.dumps({"message": "Failed to load recommendations",
                                    "error": str(e)})}
