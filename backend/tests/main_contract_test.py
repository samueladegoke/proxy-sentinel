from pathlib import Path
import sys
import asyncio
import time
import tempfile

from fastapi import HTTPException

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as main_module
from main import (
    CheckRequest,
    TARGET_POOL_MAX_CONCURRENT,
    TargetPoolStartRequest,
    TargetPoolKeeper,
    TrackRequest,
    _annotate_requested_state,
    _apply_iproyal_pool_option,
    _build_iproyal_scan_diagnostics,
    _build_target_pool_tracking_metadata,
    _ensure_iproyal_high_end_pool_proxy,
    _register_proxy_secret,
    _is_target_pool_viable_result,
    _target_pool_drop_reason,
    _resolve_check_targets,
    _resolve_proxy_secret,
    _resolve_proxy_secret_by_session,
    _resolve_tracking_target,
    _sanitize_proxy_payload,
    _validated_check_request_from_payload,
)
from tracking_store import TrackingLogStore


FULL_PROXY = "geo.iproyal.com:12321:user:secret_country-ng_state-kano_session-contract_lifetime-24h_streaming-1"
STANDARD_POOL_PROXY = "geo.iproyal.com:12321:user:secret_country-ng_state-kano_session-standard_lifetime-24h"


def assert_raises_http(fn, status_code):
    try:
        fn()
    except HTTPException as exc:
        assert exc.status_code == status_code
        return exc
    raise AssertionError(f"Expected HTTPException {status_code}")


def test_proxy_payloads_are_redacted_and_resolvable_by_opaque_handle():
    sanitized = _sanitize_proxy_payload({
        "session": "contract",
        "input_proxy": FULL_PROXY,
        "nested": [{"proxy": FULL_PROXY}],
    })

    assert "secret_country" not in str(sanitized)
    assert sanitized["input_proxy"] == "geo.iproyal.com:12321:user:****"
    assert sanitized["proxy_id"]
    assert _resolve_proxy_secret(sanitized["proxy_id"]) == FULL_PROXY
    assert sanitized["nested"][0]["proxy"] == "geo.iproyal.com:12321:user:****"


def test_check_targets_accept_raw_proxies_and_proxy_handles():
    meta = _register_proxy_secret(FULL_PROXY)

    raw_request = _validated_check_request_from_payload(
        {"proxies": [FULL_PROXY], "protocol": "http"},
        require_explicit_proxies=True,
    )
    handle_request = CheckRequest(proxy_ids=[meta["proxy_id"]], protocol="http")

    assert _resolve_check_targets(raw_request, require_explicit_proxies=True) == [FULL_PROXY]
    assert _resolve_check_targets(handle_request, require_explicit_proxies=True) == [FULL_PROXY]


def test_registered_scan_proxy_can_be_tracked_by_session_fallback():
    _register_proxy_secret(FULL_PROXY)

    assert _resolve_proxy_secret_by_session("contract") == FULL_PROXY
    assert _resolve_tracking_target(TrackRequest(session="contract")) == FULL_PROXY


def test_iproyal_generated_proxy_is_forced_to_high_end_pool():
    normalized = _ensure_iproyal_high_end_pool_proxy(STANDARD_POOL_PROXY)

    assert normalized == f"{STANDARD_POOL_PROXY}_streaming-1"
    assert _ensure_iproyal_high_end_pool_proxy(normalized) == normalized
    assert _ensure_iproyal_high_end_pool_proxy(
        STANDARD_POOL_PROXY + "_streaming-0"
    ) == f"{STANDARD_POOL_PROXY}_streaming-1"
    assert _ensure_iproyal_high_end_pool_proxy(
        STANDARD_POOL_PROXY + "_streaming-10"
    ) == f"{STANDARD_POOL_PROXY}_streaming-1"


def test_iproyal_pool_option_can_remove_high_end_pool_suffix():
    high_end_proxy = f"{STANDARD_POOL_PROXY}_streaming-1"

    assert _apply_iproyal_pool_option(STANDARD_POOL_PROXY, high_end_pool=True) == high_end_proxy
    assert _apply_iproyal_pool_option(high_end_proxy, high_end_pool=True) == high_end_proxy
    assert _apply_iproyal_pool_option(high_end_proxy, high_end_pool=False) == STANDARD_POOL_PROXY
    assert _apply_iproyal_pool_option(
        "socks5://" + high_end_proxy,
        high_end_pool=False,
    ) == "socks5://" + STANDARD_POOL_PROXY


def test_explicit_websocket_scans_do_not_fall_back_to_default_proxies():
    exc = assert_raises_http(
        lambda: _validated_check_request_from_payload({}, require_explicit_proxies=True),
        400,
    )
    assert "No proxies provided" in exc.detail


def test_state_filter_uses_online_geo_sources_not_mmdb_last_resort():
    mmdb_result = {
        "status": "success",
        "local_region": "Kano State",
        "local_city": "Kano",
        "geo_source": "db-ip-mmdb",
        "geo_confirmation_pending": True,
    }
    online_result = {
        "status": "success",
        "local_region": "Kano State",
        "local_city": "Kano",
        "geo_source": "browserleaks-db-ip",
        "geo_confirmation_pending": False,
    }

    assert _annotate_requested_state(mmdb_result, "_country-ng_state-kano") is False
    assert mmdb_result["state_match_source"] == "unconfirmed-geo"
    assert _annotate_requested_state(online_result, "_country-ng_state-kano") is True
    assert online_result["state_match_source"] == "browserleaks-db-ip"


def test_iproyal_scan_diagnostics_explain_locations_and_rejections_without_proxy_leaks():
    raw_proxy = "geo.iproyal.com:12321:user:secret_country-ng_session-a_lifetime-24h_streaming-1"
    results = [
        {
            "status": "success",
            "input_proxy": raw_proxy,
            "local_region": "Lagos",
            "local_city": "Ikoyi",
            "geo_source": "browserleaks-db-ip",
            "risk_level": "CLEAN",
            "mobile": True,
            "state_match": True,
        },
        {
            "status": "success",
            "input_proxy": raw_proxy,
            "local_region": "Rivers State",
            "local_city": "Port Harcourt",
            "geo_source": "db-ip-api",
            "risk_level": "CLEAN",
            "mobile": False,
            "state_match": True,
        },
        {
            "status": "success",
            "input_proxy": raw_proxy,
            "local_region": "Ogun State",
            "local_city": "Ado-Odo",
            "geo_source": "db-ip-api",
            "risk_level": "RISK",
            "mobile": True,
            "state_match": True,
        },
        {
            "status": "error",
            "input_proxy": raw_proxy,
            "error": "timeout",
        },
    ]

    diagnostics = _build_iproyal_scan_diagnostics(
        results,
        location="_country-ng",
        generated_count=4,
    )

    assert diagnostics["generated_count"] == 4
    assert diagnostics["checked_count"] == 4
    assert diagnostics["successful_count"] == 3
    assert diagnostics["accepted_count"] == 1
    assert diagnostics["state_filter_enabled"] is False

    locations = {item["label"]: item for item in diagnostics["successful_locations"]}
    assert locations["Lagos / Ikoyi"]["count"] == 1
    assert locations["Lagos / Ikoyi"]["accepted_count"] == 1
    assert locations["Rivers State / Port Harcourt"]["rejection_reasons"][0]["reason"] == "not_mobile"
    assert locations["Ogun State / Ado-Odo"]["rejection_reasons"][0]["reason"] == "risk_RISK"

    reasons = {item["reason"]: item["count"] for item in diagnostics["rejection_reasons"]}
    assert reasons == {"not_mobile": 1, "risk_RISK": 1, "failed": 1}
    assert "secret_country" not in str(diagnostics)
    assert "geo.iproyal.com:12321:user" not in str(diagnostics)


def test_target_pool_acceptance_requires_clean_mobile_prefix_and_online_state_match():
    prefixes = {"197.211.52."}
    result = {
        "status": "success",
        "query": "197.211.52.187",
        "local_region": "Ogun State",
        "local_city": "Odeda",
        "geo_source": "browserleaks-db-ip",
        "geo_confirmation_pending": False,
        "risk_level": "CLEAN",
        "mobile": True,
    }

    assert _is_target_pool_viable_result(result, "_country-ng_state-ogun", prefixes) is True
    assert result["state_match"] is True
    assert result["target_ip_prefix_match"] is True

    wrong_prefix = {**result, "query": "197.211.53.187"}
    assert _is_target_pool_viable_result(wrong_prefix, "_country-ng_state-ogun", prefixes) is False
    assert wrong_prefix["target_ip_prefix_match"] is False

    mmdb_only = {**result, "geo_source": "db-ip-mmdb", "geo_confirmation_pending": True}
    assert _is_target_pool_viable_result(mmdb_only, "_country-ng_state-ogun", prefixes) is False
    assert mmdb_only["state_match_source"] == "unconfirmed-geo"


def test_target_pool_drop_requires_confirmed_negative_evidence():
    prefixes = {"197.211.52."}

    assert _target_pool_drop_reason({"status": "error", "error": "timeout"}, "_country-ng_state-ogun", prefixes) is None
    assert _target_pool_drop_reason({"status": "success"}, "_country-ng_state-ogun", prefixes) is None

    pending_geo = {
        "status": "success",
        "query": "197.211.52.187",
        "local_region": "Lagos",
        "local_city": "Ikoyi",
        "geo_source": "db-ip-mmdb",
        "geo_confirmation_pending": True,
        "risk_level": "CLEAN",
        "mobile": True,
    }
    assert _target_pool_drop_reason(pending_geo, "_country-ng_state-ogun", prefixes) is None

    wrong_prefix = {
        "status": "success",
        "query": "197.211.53.187",
        "risk_level": "CLEAN",
        "mobile": True,
    }
    assert _target_pool_drop_reason(wrong_prefix, "_country-ng_state-ogun", prefixes) == "outside_target_prefix"


def test_tracking_failed_observation_does_not_overwrite_latest_successful_ip():
    db_path = Path(tempfile.gettempdir()) / f"proxy_check_tracking_{time.time_ns()}.sqlite3"
    try:
        store = TrackingLogStore(str(db_path))
        session_data = {
            "run_id": "run-1",
            "session": "sess-1",
            "proxy": FULL_PROXY,
            "started_at": time.time(),
        }
        store.start_run(session_data)

        success = {
            "status": "success",
            "query": "197.211.52.187",
            "local_region": "Ogun State",
            "local_city": "Odeda",
            "geo_source": "browserleaks-db-ip",
        }
        store.log_observation(session_data, success, {"last_ip": None, "last_result": {}})
        store.log_observation(
            session_data,
            {"status": "error", "error": "timeout"},
            {"last_ip": "197.211.52.187", "last_result": success},
        )
        details = store.run_details("run-1")
    finally:
        for path in (db_path, db_path.with_name(db_path.name + "-wal"), db_path.with_name(db_path.name + "-shm")):
            try:
                path.unlink(missing_ok=True)
            except PermissionError:
                pass

    assert details["run"]["latest_ip"] == "197.211.52.187"
    assert details["run"]["latest_region"] == "Ogun State"
    assert details["run"]["observation_count"] == 2


def test_target_pool_metadata_marks_automated_runs_for_persistent_tracking():
    request = TargetPoolStartRequest(
        proxy_count=10,
        location="_country-ng_state-ogun",
        lifetime="24h",
        target_ip_prefixes=["197.211.52.XXX"],
        min_active=3,
    )
    result = {
        "session": "pool1",
        "input_proxy": "geo.iproyal.com:12321:user:secret_country-ng_state-ogun_session-pool1_lifetime-24h_streaming-1",
    }

    metadata = _build_target_pool_tracking_metadata(result, request, {"197.211.52."})

    assert metadata["target_pool_managed"] is True
    assert metadata["target_pool_min_active"] == 3
    assert metadata["target_pool_prefixes"] == ["197.211.52."]
    assert metadata["expected_state"] == "Ogun"
    assert metadata["expected_lifetime_hours"] == 24


def test_target_pool_hunt_has_no_default_inter_attempt_cooldown():
    request = TargetPoolStartRequest(target_ip_prefixes=["197.211.52.XXX"])

    assert request.replacement_cooldown_seconds == 0


def test_target_pool_uses_higher_concurrency_for_ip_only_scouting():
    assert TARGET_POOL_MAX_CONCURRENT >= 150


def test_target_pool_prefetches_next_generation_while_current_batch_scans():
    async def run_case():
        generation_started = []
        scan_finished = []
        original_generate = main_module.generate_iproyal_proxy_list
        original_stream = main_module.check_proxies_stream

        async def fake_generate(request):
            generation_started.append(time.perf_counter())
            await asyncio.sleep(0.01)
            return [
                f"geo.iproyal.com:12321:user:secret_country-ng_session-gen{len(generation_started)}_lifetime-24h"
            ]

        async def fake_stream(*args, **kwargs):
            assert kwargs["ip_only"] is True
            assert kwargs["max_concurrent"] == TARGET_POOL_MAX_CONCURRENT
            await asyncio.sleep(0.05)
            yield {
                "status": "success",
                "query": "198.51.100.10",
                "session": "miss",
            }
            scan_finished.append(time.perf_counter())

        keeper = TargetPoolKeeper()
        keeper._config = TargetPoolStartRequest(
            proxy_count=1,
            location="_country-ng",
            target_ip_prefixes=["203.0.113.XXX"],
            max_attempts=2,
            min_active=1,
        )
        keeper._active = True

        try:
            main_module.generate_iproyal_proxy_list = fake_generate
            main_module.check_proxies_stream = fake_stream
            await keeper._replace_deficit_locked(1)
        finally:
            main_module.generate_iproyal_proxy_list = original_generate
            main_module.check_proxies_stream = original_stream

        assert len(generation_started) == 2
        assert scan_finished
        assert generation_started[1] < scan_finished[0]

    asyncio.run(run_case())


if __name__ == "__main__":
    test_proxy_payloads_are_redacted_and_resolvable_by_opaque_handle()
    test_check_targets_accept_raw_proxies_and_proxy_handles()
    test_registered_scan_proxy_can_be_tracked_by_session_fallback()
    test_iproyal_generated_proxy_is_forced_to_high_end_pool()
    test_iproyal_pool_option_can_remove_high_end_pool_suffix()
    test_explicit_websocket_scans_do_not_fall_back_to_default_proxies()
    test_state_filter_uses_online_geo_sources_not_mmdb_last_resort()
    test_iproyal_scan_diagnostics_explain_locations_and_rejections_without_proxy_leaks()
    test_target_pool_acceptance_requires_clean_mobile_prefix_and_online_state_match()
    test_target_pool_drop_requires_confirmed_negative_evidence()
    test_tracking_failed_observation_does_not_overwrite_latest_successful_ip()
    test_target_pool_metadata_marks_automated_runs_for_persistent_tracking()
    test_target_pool_hunt_has_no_default_inter_attempt_cooldown()
    test_target_pool_uses_higher_concurrency_for_ip_only_scouting()
    test_target_pool_prefetches_next_generation_while_current_batch_scans()
    print("main API contract tests passed")
