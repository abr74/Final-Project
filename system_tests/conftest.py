import os
import time

import pytest

from .config import SystemTestConfig


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_SYSTEM_TESTS") == "1":
        return

    skip_marker = pytest.mark.skip(
        reason=(
            "System tests hit real, deployed AWS infrastructure and are opt-in. "
            "Set RUN_SYSTEM_TESTS=1 to run them (see system_tests/config.py for "
            "the full list of environment variables)."
        )
    )
    for item in items:
        if "system_tests" in str(item.fspath).replace("\\", "/"):
            item.add_marker(skip_marker)


@pytest.fixture(scope="session")
def system_config() -> SystemTestConfig:
    return SystemTestConfig()


@pytest.fixture(scope="session")
def boto3_session(system_config):
    boto3 = pytest.importorskip("boto3")
    return boto3.session.Session(region_name=system_config.aws_region)


@pytest.fixture(scope="session")
def s3_client(boto3_session):
    return boto3_session.client("s3")


@pytest.fixture(scope="session")
def logs_client(boto3_session):
    return boto3_session.client("logs")


def poll_until(predicate, timeout_seconds: int, interval_seconds: int, description: str):
    """
    Calls predicate() every interval_seconds until it returns a truthy value
    or timeout_seconds elapses. Returns the truthy value, or raises
    AssertionError with a message naming what was being waited for.
    """
    deadline = time.monotonic() + timeout_seconds
    last_result = None
    while time.monotonic() < deadline:
        last_result = predicate()
        if last_result:
            return last_result
        time.sleep(interval_seconds)

    raise AssertionError(
        f"Timed out after {timeout_seconds}s waiting for: {description}. "
        f"Last observed value: {last_result!r}"
    )
