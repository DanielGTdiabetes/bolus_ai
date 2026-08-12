from __future__ import annotations

import importlib.util
from pathlib import Path


MODULE_PATH = Path(__file__).parents[1] / "mfp_sync_trigger.py"
SPEC = importlib.util.spec_from_file_location("mfp_sync_trigger", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
mfp_sync_trigger = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mfp_sync_trigger)


def build(output: str, returncode: int = 0):
    return mfp_sync_trigger.build_sync_response(
        sync_id="sync-test-123",
        output=output,
        returncode=returncode,
        duration_ms=321,
    )


def test_success_contract_reports_ingested_meal():
    response, http_status = build(
        "2026-08-12 INFO mfp request status=200 "
        "url=https://api.myfitnesspal.com/v2/users/123?fields=profile\n"
        "sync complete posted=1 queued=0\n"
    )

    assert http_status == 200
    assert response == {
        "sync_id": "sync-test-123",
        "success": 1,
        "status": "success",
        "metadata_status": "success",
        "ingest_status": "success",
        "notification_status": "unknown",
        "posted_count": 1,
        "queued_count": 0,
        "returncode": 0,
        "duration_ms": 321,
        "output_tail": (
            "2026-08-12 INFO mfp request status=200 "
            "url=https://api.myfitnesspal.com/v2/users/123?fields=profile\n"
            "sync complete posted=1 queued=0\n"
        ),
    }


def test_metadata_500_is_recovered_warning_when_ingest_succeeds():
    response, http_status = build(
        "2026-08-12 INFO mfp request status=500 "
        "url=https://api.myfitnesspal.com/v2/users/123?fields=diary_preferences\n"
        "2026-08-12 INFO diary fallback selected\n"
        "sync complete posted=1 queued=0\n"
    )

    assert http_status == 200
    assert response["status"] == "success_with_warning"
    assert response["metadata_status"] == "fallback_recovered"
    assert response["ingest_status"] == "success"
    assert response["posted_count"] == 1


def test_no_changes_is_distinct_from_failure():
    response, http_status = build("sync complete posted=0 queued=0\n")

    assert http_status == 200
    assert response["success"] == 1
    assert response["status"] == "no_changes"
    assert response["ingest_status"] == "no_changes"


def test_queued_meal_reports_retry_scheduled():
    response, http_status = build("sync complete posted=0 queued=2\n")

    assert http_status == 202
    assert response["success"] == 1
    assert response["status"] == "retry_scheduled"
    assert response["ingest_status"] == "retry_scheduled"
    assert response["queued_count"] == 2


def test_nonzero_exit_without_queue_is_failed():
    response, http_status = build("fatal: authentication failed\n", returncode=3)

    assert http_status == 500
    assert response["success"] == 0
    assert response["status"] == "failed"
    assert response["ingest_status"] == "failed"


def test_structured_child_summary_is_supported():
    response, http_status = build(
        '{"metadata_status":"success","ingest_status":"success",'
        '"posted_count":2,"queued_count":0}\n'
    )

    assert http_status == 200
    assert response["status"] == "success"
    assert response["posted_count"] == 2
    assert response["queued_count"] == 0


def test_complete_output_is_parsed_before_output_tail_is_truncated():
    output = "sync complete posted=3 queued=0\n" + ("diagnostic filler\n" * 400)

    response, http_status = build(output)

    assert http_status == 200
    assert response["status"] == "success"
    assert response["posted_count"] == 3
    assert len(response["output_tail"]) == mfp_sync_trigger.OUTPUT_TAIL_LIMIT
    assert "sync complete" not in response["output_tail"]


def test_timeout_returns_structured_gateway_timeout():
    response, http_status = mfp_sync_trigger.build_sync_response(
        sync_id="sync-timeout",
        output="partial output",
        returncode=None,
        duration_ms=120_000,
        timed_out=True,
        message="sync timed out after 120s",
    )

    assert http_status == 504
    assert response["success"] == 0
    assert response["status"] == "failed"
    assert response["ingest_status"] == "failed"
    assert response["message"] == "sync timed out after 120s"


def test_not_started_response_keeps_the_same_contract_shape():
    response = mfp_sync_trigger.build_not_started_response(
        "sync-busy",
        "retry_scheduled",
        "sync already running",
    )

    assert response["sync_id"] == "sync-busy"
    assert response["success"] == 0
    assert response["status"] == "retry_scheduled"
    assert response["metadata_status"] == "not_attempted"
    assert response["ingest_status"] == "retry_scheduled"
    assert response["output_tail"] == ""


def test_successful_ingest_with_pending_notification_is_a_warning():
    response, http_status = build(
        '{"metadata_status":"success","ingest_status":"success",'
        '"notification_status":"retry_scheduled","posted_count":1,"queued_count":0}\n'
    )

    assert http_status == 200
    assert response["status"] == "success_with_warning"
    assert response["ingest_status"] == "success"
    assert response["notification_status"] == "retry_scheduled"
