import tempfile
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracking_store import TrackingLogStore


def make_store():
    db_file = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
    db_file.close()
    return TrackingLogStore(db_file.name)


def test_active_runs_can_be_restored_and_stopped_runs_remain_historical():
    store = make_store()
    session_data = {
        "run_id": "lagos-run-1",
        "session": "lagos-session",
        "proxy": "geo.iproyal.com:12321:user:pass_country-ng_state-lagos_session-lagos-session_lifetime-24h",
        "expected_location": "country-ng_state-lagos",
        "expected_state": "Lagos",
        "expected_state_slug": "lagos",
        "expected_lifetime_hours": 24,
        "started_at": 1000.0,
        "expected_expires_at": 87400.0,
    }

    store.start_run(session_data)
    active_runs = store.active_runs()

    assert len(active_runs) == 1
    assert active_runs[0]["run_id"] == "lagos-run-1"
    assert active_runs[0]["proxy"] == session_data["proxy"]

    store.end_run("lagos-run-1")

    assert store.active_runs() == []
    runs = store.runs(limit=10)
    assert runs[0]["run_id"] == "lagos-run-1"
    assert runs[0]["ended_at"] is not None


def test_run_details_include_location_change_timeline():
    store = make_store()
    session_data = {
        "run_id": "kano-run-1",
        "session": "kano-session",
        "proxy": "geo.iproyal.com:12321:user:pass_country-ng_state-kano_session-kano-session_lifetime-48h",
        "expected_state": "Kano",
        "expected_state_slug": "kano",
        "expected_lifetime_hours": 48,
        "started_at": 1000.0,
    }

    store.start_run(session_data)
    first = {"status": "success", "query": "41.1.1.1", "local_region": "Kano", "local_city": "Kano", "isp": "SP 101", "mobile": True, "risk_level": "CLEAN", "geo_source": "db-ip-api"}
    second = {"status": "success", "query": "41.1.1.2", "local_region": "Lagos", "local_city": "Ikeja", "isp": "SP 101", "mobile": True, "risk_level": "CLEAN", "geo_source": "db-ip-api"}

    store.log_observation(session_data, first, {})
    previous = {**session_data, "last_ip": "41.1.1.1", "last_result": first}
    store.log_observation(session_data, second, previous)

    details = store.run_details("kano-run-1")

    assert details["run"]["run_id"] == "kano-run-1"
    assert details["run"]["change_count"] == 1
    assert details["run"]["latest_country"] is None
    assert details["run"]["latest_geo_source"] == "db-ip-api"
    assert details["run"]["latest_isp"] == "SP 101"
    assert details["run"]["latest_mobile"] == 1
    assert details["run"]["latest_risk_level"] == "CLEAN"
    assert len(details["observations"]) == 2
    assert details["observations"][1]["changed_ip"] == 1
    assert details["observations"][1]["old_ip"] == "41.1.1.1"
    assert details["observations"][1]["ip"] == "41.1.1.2"


def test_stopped_run_can_be_deleted_with_its_observations():
    store = make_store()
    session_data = {
        "run_id": "noise-run-1",
        "session": "noise-session",
        "proxy": "127.0.0.1:9:user:pass_session-noise",
        "started_at": 1000.0,
    }

    store.start_run(session_data)
    store.log_observation(
        session_data,
        {"status": "fail", "error": "test noise"},
        {},
    )
    store.end_run("noise-run-1")

    deleted = store.delete_run("noise-run-1")

    assert deleted is True
    assert store.run_details("noise-run-1")["run"] is None
    assert store.recent_observations(session="noise-session") == []


def test_active_run_delete_is_blocked_by_default():
    store = make_store()
    session_data = {
        "run_id": "active-run-1",
        "session": "active-session",
        "proxy": "127.0.0.1:9:user:pass_session-active",
        "started_at": 1000.0,
    }

    store.start_run(session_data)

    deleted = store.delete_run("active-run-1")

    assert deleted is False
    assert store.run_details("active-run-1")["run"] is not None


def test_same_ip_geo_source_transition_is_not_counted_as_proxy_change():
    store = make_store()
    session_data = {
        "run_id": "stable-source-transition",
        "session": "stable-session",
        "proxy": "geo.iproyal.com:12321:user:pass_session-stable_lifetime-24h",
        "started_at": 1000.0,
    }

    store.start_run(session_data)
    old_result = {
        "status": "success",
        "query": "197.211.53.88",
        "local_region": "Kwara State",
        "local_city": "Ilorin",
        "geo_source": "db-ip-mmdb",
    }
    new_result = {
        "status": "success",
        "query": "197.211.53.88",
        "local_region": "Lagos",
        "local_city": "Lagos",
        "geo_source": "db-ip-api",
    }

    store.log_observation(session_data, old_result, {})
    event = store.log_observation(
        session_data,
        new_result,
        {**session_data, "last_ip": "197.211.53.88", "last_result": old_result},
    )
    details = store.run_details("stable-source-transition")

    assert event["changed_ip"] is False
    assert event["changed_location"] is False
    assert event["stable"] is True
    assert details["run"]["change_count"] == 0


def test_startup_repair_backfills_latest_ip_from_last_successful_observation():
    store = make_store()
    session_data = {
        "run_id": "repair-run",
        "session": "repair-session",
        "proxy": "geo.iproyal.com:12321:user:pass_session-repair_lifetime-24h",
        "started_at": 1000.0,
    }

    store.start_run(session_data)
    success = {
        "status": "success",
        "query": "197.211.52.222",
        "local_region": "Ogun State",
        "local_city": "Odeda",
        "geo_source": "browserleaks-db-ip",
    }
    store.log_observation(session_data, success, {})

    with store._connect() as conn:
        conn.execute(
            "UPDATE tracking_runs SET latest_ip = NULL, latest_region = NULL, latest_city = NULL WHERE run_id = ?",
            ("repair-run",),
        )

    repaired_store = TrackingLogStore(store.db_path)
    details = repaired_store.run_details("repair-run")

    assert details["run"]["latest_ip"] == "197.211.52.222"
    assert details["run"]["latest_region"] == "Ogun State"
    assert details["run"]["latest_city"] == "Odeda"


def test_same_ip_same_source_location_change_is_tracked_without_ip_change():
    store = make_store()
    session_data = {
        "run_id": "same-source-location",
        "session": "same-source-session",
        "proxy": "geo.iproyal.com:12321:user:pass_session-source_lifetime-24h",
        "started_at": 1000.0,
    }

    store.start_run(session_data)
    old_result = {
        "status": "success",
        "query": "197.211.53.88",
        "local_region": "Kwara State",
        "local_city": "Ilorin",
        "geo_source": "db-ip-api",
    }
    new_result = {
        "status": "success",
        "query": "197.211.53.88",
        "local_region": "Lagos",
        "local_city": "Lagos",
        "geo_source": "db-ip-api",
    }

    store.log_observation(session_data, old_result, {})
    event = store.log_observation(
        session_data,
        new_result,
        {**session_data, "last_ip": "197.211.53.88", "last_result": old_result},
    )

    assert event["changed_ip"] is False
    assert event["changed_location"] is True
    assert event["stable"] is False


def test_analytics_preserve_country_wide_location_scope():
    store = make_store()
    session_data = {
        "run_id": "country-wide-run",
        "session": "country-wide-session",
        "proxy": "geo.iproyal.com:12321:user:pass_country-ng_session-country_lifetime-24h",
        "expected_location": "country-ng",
        "expected_lifetime_hours": 24,
        "started_at": 1000.0,
    }

    store.start_run(session_data)
    store.log_observation(
        session_data,
        {
            "status": "success",
            "query": "197.211.63.59",
            "local_region": "FCT",
            "local_city": "Abaji",
            "geo_source": "db-ip-api",
        },
        {},
    )

    groups = store.analytics()["groups"]

    assert groups[0]["expected_location"] == "country-ng"
    assert groups[0]["expected_state"] is None
    assert groups[0]["expected_lifetime_hours"] == 24


if __name__ == "__main__":
    test_active_runs_can_be_restored_and_stopped_runs_remain_historical()
    test_run_details_include_location_change_timeline()
    test_stopped_run_can_be_deleted_with_its_observations()
    test_active_run_delete_is_blocked_by_default()
    test_same_ip_geo_source_transition_is_not_counted_as_proxy_change()
    test_startup_repair_backfills_latest_ip_from_last_successful_observation()
    test_same_ip_same_source_location_change_is_tracked_without_ip_change()
    test_analytics_preserve_country_wide_location_scope()
    print("tracking store persistence tests passed")
