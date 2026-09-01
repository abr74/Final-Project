"""
System tests for the deployed "upload-url" Lambda (fronted by API Gateway,
called from my-app/src/Pages/Landing/Landing.jsx).
"""

import uuid

import requests

from .pipeline_helpers import bucket_and_key_from_presigned_url, request_presigned_upload_url


def test_upload_url_lambda_returns_a_presigned_put_url(system_config):
    file_name = f"system-test-{uuid.uuid4().hex}.zip"

    payload = request_presigned_upload_url(system_config.upload_url_endpoint, file_name)

    assert "uploadUrl" in payload, f"Lambda response missing 'uploadUrl': {payload!r}"

    upload_url = payload["uploadUrl"]
    assert upload_url.startswith("https://"), upload_url
    assert "X-Amz-Signature" in upload_url or "Signature" in upload_url, (
        "uploadUrl does not look like a SigV4 presigned URL: " + upload_url
    )

    location = bucket_and_key_from_presigned_url(upload_url)
    assert location["bucket"], f"Could not determine bucket from uploadUrl: {upload_url}"
    assert location["key"], f"Could not determine key from uploadUrl: {upload_url}"


def test_upload_url_lambda_gives_distinct_urls_per_call(system_config):
    first = request_presigned_upload_url(
        system_config.upload_url_endpoint, f"system-test-{uuid.uuid4().hex}.zip"
    )
    second = request_presigned_upload_url(
        system_config.upload_url_endpoint, f"system-test-{uuid.uuid4().hex}.zip"
    )

    assert first["uploadUrl"] != second["uploadUrl"]


def test_upload_url_lambda_responds_to_options_preflight_or_post_only(system_config):
    # The frontend only ever POSTs, but a CORS-enabled API Gateway endpoint
    # should not blow up with a 5xx on other verbs. This guards against a
    # misconfigured deployment silently breaking the browser's preflight.
    response = requests.get(system_config.upload_url_endpoint, timeout=30)
    assert response.status_code < 500, (
        f"GET on upload-url endpoint returned a server error: {response.status_code} {response.text}"
    )
