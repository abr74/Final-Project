"""
Configuration for system tests that exercise the real, deployed AWS
Lambda/API Gateway/S3 pipeline (not local mocks).

Everything is driven by environment variables so no secrets or account
specific identifiers live in source control. Only SYSTEM_TEST_UPLOAD_URL_ENDPOINT
and SYSTEM_TEST_RECOMMENDATIONS_ENDPOINT have defaults, taken from the URLs
already hard-coded in my-app/src/Pages/Landing/Landing.jsx and
my-app/src/Pages/Recommendation/Recommendation.jsx.

Required to run anything in this directory:
    RUN_SYSTEM_TESTS=1

Optional, unlock the deeper boto3-based verification tests:
    SYSTEM_TEST_PARSED_BUCKET          S3 bucket the parser Lambda writes parsed output to
    SYSTEM_TEST_RAW_BUCKET             S3 bucket the presigned upload URL points at (usually derivable from the URL itself)
    SYSTEM_TEST_PARSER_LAMBDA_NAME     Lambda function name, for CloudWatch Logs verification
    SYSTEM_TEST_RECOMMENDATION_LAMBDA_NAME
    AWS_REGION / AWS_DEFAULT_REGION    defaults to us-east-1
    AWS credentials via the normal boto3 mechanisms (env vars, ~/.aws/credentials, SSO, etc.)
"""

import os
from dataclasses import dataclass, field
from typing import Optional


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return int(value)


@dataclass(frozen=True)
class SystemTestConfig:
    upload_url_endpoint: str = field(
        default_factory=lambda: os.environ.get(
            "SYSTEM_TEST_UPLOAD_URL_ENDPOINT",
            "https://hkv39v0ul7.execute-api.us-east-1.amazonaws.com/prod/upload-url",
        )
    )
    recommendations_endpoint: str = field(
        default_factory=lambda: os.environ.get(
            "SYSTEM_TEST_RECOMMENDATIONS_ENDPOINT",
            "https://hkv39v0ul7.execute-api.us-east-1.amazonaws.com/prod/recommendations",
        )
    )
    aws_region: str = field(
        default_factory=lambda: os.environ.get(
            "AWS_REGION", os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
        )
    )
    parsed_bucket: Optional[str] = field(
        default_factory=lambda: os.environ.get("SYSTEM_TEST_PARSED_BUCKET") or None
    )
    raw_bucket: Optional[str] = field(
        default_factory=lambda: os.environ.get("SYSTEM_TEST_RAW_BUCKET") or None
    )
    parser_lambda_name: Optional[str] = field(
        default_factory=lambda: os.environ.get("SYSTEM_TEST_PARSER_LAMBDA_NAME") or None
    )
    recommendation_lambda_name: Optional[str] = field(
        default_factory=lambda: os.environ.get("SYSTEM_TEST_RECOMMENDATION_LAMBDA_NAME") or None
    )
    poll_timeout_seconds: int = field(
        default_factory=lambda: _env_int("SYSTEM_TEST_POLL_TIMEOUT_SECONDS", 120)
    )
    poll_interval_seconds: int = field(
        default_factory=lambda: _env_int("SYSTEM_TEST_POLL_INTERVAL_SECONDS", 5)
    )

    @property
    def has_parsed_bucket(self) -> bool:
        return bool(self.parsed_bucket)

    @property
    def has_parser_lambda_name(self) -> bool:
        return bool(self.parser_lambda_name)

    @property
    def has_recommendation_lambda_name(self) -> bool:
        return bool(self.recommendation_lambda_name)
