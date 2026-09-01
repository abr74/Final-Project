"""
System tests for the deployed "recommendations" Lambda (fronted by API
Gateway, called from my-app/src/Pages/Recommendation/Recommendation.jsx).

v2 contract: requires a ?userId= query parameter (the uploadId returned by
the upload-url Lambda). Missing userId -> 400. Unknown/not-yet-processed
userId -> 404 with {"status": "processing"}. The "returns real
recommendation data" case is covered by test_end_to_end_pipeline.py, since
it requires an actual processed upload to exist.
"""

import uuid

import requests


def test_recommendations_lambda_requires_userid(system_config):
    response = requests.get(system_config.recommendations_endpoint, timeout=30)

    assert response.status_code == 400, (
        f"Expected 400 when userId is missing, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert "userId" in body.get("message", "")


def test_recommendations_lambda_reports_processing_for_unknown_userid(system_config):
    bogus_user_id = f"system-test-unknown-{uuid.uuid4().hex}"

    response = requests.get(
        system_config.recommendations_endpoint,
        params={"userId": bogus_user_id},
        timeout=30,
    )

    assert response.status_code == 404, (
        f"Expected 404 for an unknown userId, got {response.status_code}: {response.text}"
    )
    body = response.json()
    assert body.get("status") == "processing"
    assert body.get("user_id") == bogus_user_id
