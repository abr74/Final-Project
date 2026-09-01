"""
Black-box end-to-end system test: drives the real pipeline exactly the way
the frontend does (upload-url Lambda -> presigned S3 PUT -> S3 event
triggers the parser Lambda -> S3 event triggers the fusion-recommender
Lambda -> GET /recommendations?userId={uploadId}) and confirms the uploaded
data actually shows up out the other end. Requires no AWS credentials since
every step is a plain HTTPS call, same as the browser makes.
"""

import uuid

import requests

from .conftest import poll_until
from .pipeline_helpers import request_presigned_upload_url, upload_bytes_to_presigned_url
from .takeout_fixture import build_synthetic_takeout_zip


def test_uploaded_takeout_data_flows_through_to_recommendations(system_config):
    marker = uuid.uuid4().hex[:10]
    zip_bytes, channel_title = build_synthetic_takeout_zip(marker)
    file_name = f"system-test-{marker}.zip"

    upload_payload = request_presigned_upload_url(system_config.upload_url_endpoint, file_name)
    assert "uploadUrl" in upload_payload, upload_payload
    assert "uploadId" in upload_payload, (
        f"upload-url response missing 'uploadId' (v2 contract): {upload_payload!r}"
    )
    user_id = upload_payload["uploadId"]

    put_response = upload_bytes_to_presigned_url(upload_payload["uploadUrl"], zip_bytes)
    assert put_response.status_code in (200, 204), (
        f"S3 upload failed: {put_response.status_code} {put_response.text}"
    )

    def recommendations_are_ready():
        response = requests.get(
            system_config.recommendations_endpoint,
            params={"userId": user_id},
            timeout=30,
        )
        if response.status_code == 404:
            return None  # still processing
        if response.status_code != 200:
            return None
        return response.json()

    result = poll_until(
        recommendations_are_ready,
        timeout_seconds=system_config.poll_timeout_seconds,
        interval_seconds=system_config.poll_interval_seconds,
        description=(
            f"recommendations to become available for uploadId '{user_id}' "
            f"via {system_config.recommendations_endpoint}"
        ),
    )

    assert result is not None
    assert result.get("user_id") == user_id
    assert marker in (result.get("source_key") or ""), (
        f"source_key doesn't reference this upload's marker '{marker}': {result!r}"
    )
    assert channel_title in (result.get("watched_channels") or []), (
        f"Uploaded channel '{channel_title}' not found in watched_channels: {result!r}"
    )
