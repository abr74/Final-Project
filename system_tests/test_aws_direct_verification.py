"""
Deep verification tests that reach past the public HTTP surface and use
boto3 (your AWS credentials) to confirm the parser Lambda actually did the
right thing: wrote correctly-structured parsed output to S3, and ran without
logging errors to CloudWatch.

Each test independently skips itself if the AWS resource identifier it
needs was not provided via environment variable (see system_tests/config.py)
-- so this file is safe to collect even if you've only configured some of
the optional identifiers.

There's no DynamoDB-based status tracking here -- this architecture uses S3
key prefixes (uploads-v2/, parsed-v2/, recommendations-v2/) as the only
state, confirmed by `aws dynamodb list-tables` returning empty for this
account. A DynamoDB status check would never be more than permanently
skipped, so it isn't included.
"""

import json
import time
import uuid

import pytest

from .conftest import poll_until
from .pipeline_helpers import (
    bucket_and_key_from_presigned_url,
    request_presigned_upload_url,
    upload_bytes_to_presigned_url,
)
from .takeout_fixture import build_synthetic_takeout_zip


def _upload_synthetic_takeout(system_config):
    marker = uuid.uuid4().hex[:10]
    zip_bytes, channel_title = build_synthetic_takeout_zip(marker)
    file_name = f"system-test-{marker}.zip"

    upload_payload = request_presigned_upload_url(system_config.upload_url_endpoint, file_name)
    upload_started_at = time.time()

    put_response = upload_bytes_to_presigned_url(upload_payload["uploadUrl"], zip_bytes)
    assert put_response.status_code in (200, 204), (
        f"S3 upload failed: {put_response.status_code} {put_response.text}"
    )

    location = bucket_and_key_from_presigned_url(upload_payload["uploadUrl"])

    return {
        "marker": marker,
        "channel_title": channel_title,
        "file_name": file_name,
        "raw_bucket": location["bucket"],
        "raw_key": location["key"],
        "upload_started_at": upload_started_at,
    }


def _require(condition: bool, reason: str):
    if not condition:
        pytest.skip(reason)


def test_parsed_output_is_written_to_s3_with_expected_records(system_config, s3_client):
    _require(
        system_config.has_parsed_bucket,
        "Set SYSTEM_TEST_PARSED_BUCKET to enable this test.",
    )

    upload = _upload_synthetic_takeout(system_config)

    def find_parsed_object():
        response = s3_client.list_objects_v2(Bucket=system_config.parsed_bucket)
        for obj in response.get("Contents", []):
            key = obj["Key"]
            if upload["marker"] in key and key.endswith("central_output.json"):
                return key
        return None

    parsed_key = poll_until(
        find_parsed_object,
        timeout_seconds=system_config.poll_timeout_seconds,
        interval_seconds=system_config.poll_interval_seconds,
        description=(
            f"a central_output.json containing marker '{upload['marker']}' "
            f"in s3://{system_config.parsed_bucket}"
        ),
    )

    obj = s3_client.get_object(Bucket=system_config.parsed_bucket, Key=parsed_key)
    body = json.loads(obj["Body"].read())

    counts = body.get("counts", body)
    assert counts.get("subscription", 0) >= 1 or counts.get("watch_event", 0) >= 1, (
        f"Parsed output for marker '{upload['marker']}' is missing expected record types: {body!r}"
    )


def test_parser_lambda_logs_no_errors_for_the_upload(system_config, logs_client):
    _require(
        system_config.has_parser_lambda_name,
        "Set SYSTEM_TEST_PARSER_LAMBDA_NAME to enable this test.",
    )

    upload = _upload_synthetic_takeout(system_config)
    log_group_name = f"/aws/lambda/{system_config.parser_lambda_name}"
    start_time_ms = int(upload["upload_started_at"] * 1000)

    def find_invocation_events():
        try:
            response = logs_client.filter_log_events(
                logGroupName=log_group_name,
                startTime=start_time_ms,
                filterPattern=upload["marker"],
            )
        except logs_client.exceptions.ResourceNotFoundException:
            pytest.fail(f"Log group not found: {log_group_name}")
        return response.get("events") or None

    events = poll_until(
        find_invocation_events,
        timeout_seconds=system_config.poll_timeout_seconds,
        interval_seconds=system_config.poll_interval_seconds,
        description=(
            f"a CloudWatch Logs entry referencing marker '{upload['marker']}' "
            f"in {log_group_name}"
        ),
    )

    error_events = [
        e for e in events if "ERROR" in e.get("message", "") or "Traceback" in e.get("message", "")
    ]
    assert not error_events, (
        f"Parser Lambda logged errors while processing upload '{upload['file_name']}': "
        + "\n".join(e["message"] for e in error_events)
    )
