"""
Shared helpers for driving the real, deployed upload pipeline:
  POST {upload_url_endpoint} -> presigned S3 PUT url
  PUT the takeout zip bytes to that url
"""

import json
from urllib.parse import urlparse
from typing import Any, Dict

import requests


def request_presigned_upload_url(endpoint: str, file_name: str, timeout: int = 30) -> Dict[str, Any]:
    response = requests.post(
        endpoint,
        headers={"Content-Type": "application/json"},
        json={"fileName": file_name},
        timeout=timeout,
    )
    response.raise_for_status()

    payload = response.json()

    # API Gateway Lambda-proxy integrations sometimes come back double
    # encoded (the Lambda's own {"statusCode": ..., "body": "..."} envelope
    # leaking through) -- the frontend already defends against this in
    # Landing.jsx, so mirror that here.
    if isinstance(payload, dict) and isinstance(payload.get("body"), str):
        payload = json.loads(payload["body"])

    return payload


def upload_bytes_to_presigned_url(upload_url: str, data: bytes, timeout: int = 60) -> requests.Response:
    response = requests.put(upload_url, data=data, timeout=timeout)
    return response


def bucket_and_key_from_presigned_url(upload_url: str) -> Dict[str, str]:
    """
    Best-effort extraction of the S3 bucket/key from a presigned URL, to
    avoid requiring the bucket name as a separate configured value. Supports
    both virtual-hosted-style (bucket.s3.region.amazonaws.com/key) and
    path-style (s3.region.amazonaws.com/bucket/key) URLs.
    """
    parsed = urlparse(upload_url)
    host_parts = parsed.netloc.split(".")
    path = parsed.path.lstrip("/")

    if host_parts[0] not in ("s3", "s3-accelerate") and ".s3" in parsed.netloc:
        bucket = host_parts[0]
        key = path
    else:
        segments = path.split("/", 1)
        bucket = segments[0]
        key = segments[1] if len(segments) > 1 else ""

    return {"bucket": bucket, "key": key}
