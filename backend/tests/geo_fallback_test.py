from pathlib import Path
import sys
import asyncio
import ssl
import time
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import proxy_lib_async
from proxy_lib_async import (
    _apply_browserleaks_location,
    _apply_dbip_api_location,
    _parse_browserleaks_lookup,
    _process_response,
    lookup_browserleaks_html,
)


def test_browserleaks_supplies_location_when_dbip_api_is_unavailable():
    result = {"query": "197.211.53.88"}

    applied = _apply_browserleaks_location(
        result,
        {
            "city": "Ilorin",
            "stateProv": "Kwara State",
            "countryName": "Nigeria",
            "countryCode": "NG",
        },
    )

    assert applied is True
    assert result["local_city"] == "Ilorin"
    assert result["local_region"] == "Kwara State"
    assert result["local_country"] == "Nigeria"
    assert result["geo_source"] == "browserleaks-db-ip"
    assert result["dbip_source"] == "browserleaks"


def test_browserleaks_does_not_override_primary_dbip_api_location():
    result = {"query": "197.211.53.88"}
    _apply_dbip_api_location(
        result,
        {
            "city": "Lagos",
            "stateProv": "Lagos",
            "countryName": "Nigeria",
            "countryCode": "NG",
        },
    )

    applied = _apply_browserleaks_location(
        result,
        {
            "city": "Ilorin",
            "stateProv": "Kwara State",
            "countryName": "Nigeria",
            "countryCode": "NG",
        },
    )

    assert applied is False
    assert result["local_city"] == "Lagos"
    assert result["local_region"] == "Lagos"
    assert result["geo_source"] == "db-ip-api"
    assert result["dbip_source"] == "api"


def test_browserleaks_only_fills_missing_primary_fields():
    result = {"query": "197.211.53.88"}
    _apply_dbip_api_location(
        result,
        {
            "stateProv": "Lagos",
            "countryName": "Nigeria",
            "countryCode": "NG",
        },
    )

    applied = _apply_browserleaks_location(
        result,
        {
            "city": "Ikeja",
            "stateProv": "Kwara State",
            "countryName": "Nigeria",
            "countryCode": "NG",
        },
    )

    assert applied is True
    assert result["local_city"] == "Ikeja"
    assert result["local_region"] == "Lagos"
    assert result["geo_source"] == "db-ip-api"
    assert result["geo_fallback_source"] == "browserleaks-db-ip"


def test_browserleaks_replaces_provisional_mmdb_location():
    result = {
        "query": "197.211.53.84",
        "local_city": "Ilorin",
        "local_region": "Kwara State",
        "local_country": "Nigeria",
        "geo_source": "db-ip-mmdb",
        "dbip_source": "mmdb",
        "geo_quality": "provisional-mmdb",
        "geo_confirmation_pending": True,
    }

    applied = _apply_browserleaks_location(
        result,
        {
            "city": "Ipetumodu",
            "stateProv": "Osun State",
            "countryName": "Nigeria",
            "countryCode": "NG",
            "latitude": "7.5215",
            "longitude": "4.4448",
        },
    )

    assert applied is True
    assert result["local_city"] == "Ipetumodu"
    assert result["local_region"] == "Osun State"
    assert result["geo_source"] == "browserleaks-db-ip"
    assert result["dbip_source"] == "browserleaks"


def test_browserleaks_parser_reads_only_ip_location_table():
    html = """
        <table>
          <tr><td>IP Address</td><td id="lookup-ip">197.211.53.84</td></tr>
          <tr class="thead"><td colspan="2"><h3>IP Address Location</h3></td></tr>
          <tr><td>Country</td><td><span title="Nigeria (NG)">Nigeria <span>(NG)</span></span></td></tr>
          <tr><td>State/Region</td><td>Osun State</td></tr>
          <tr><td>City</td><td>Ipetumodu</td></tr>
          <tr><td>ISP</td><td>GLO</td></tr>
          <tr><td>Network</td><td><a>AS37148</a> Globacom Limited</td></tr>
          <tr><td>Usage Type</td><td>Cellular</td></tr>
          <tr><td>Timezone</td><td>Africa/Lagos <span>(WAT)</span></td></tr>
          <tr><td>Coordinates</td><td id="coords-data" data-lat="7.5215" data-lon="4.4448">7.5215,4.4448</td></tr>
        </table>
        <table id="whois-ip">
          <tr><td>City</td><td>Wrong Whois City</td></tr>
          <tr><td>State/Region</td><td>Wrong Whois Region</td></tr>
        </table>
    """

    parsed = _parse_browserleaks_lookup(html, "197.211.53.84")

    assert parsed["city"] == "Ipetumodu"
    assert parsed["stateProv"] == "Osun State"
    assert parsed["countryName"] == "Nigeria"
    assert parsed["isp"] == "GLO"
    assert parsed["usageType"] == "Cellular"
    assert parsed["latitude"] == "7.5215"
    assert parsed["longitude"] == "4.4448"


def test_process_response_uses_browserleaks_before_mmdb():
    class FakeResponse:
        status = 200
        headers = {"Content-Type": "application/json"}

        async def text(self):
            return """
            {
              "status": "success",
              "query": "197.211.53.84",
              "country": "Nigeria",
              "countryCode": "NG",
              "regionName": "Kwara State",
              "city": "Ilorin",
              "isp": "GLO",
              "mobile": true,
              "proxy": false,
              "hosting": false
            }
            """

    async def run_case():
        original_lookup_dbip = proxy_lib_async.lookup_dbip_api
        original_lookup_browserleaks = proxy_lib_async.lookup_browserleaks_html
        original_apply_mmdb = proxy_lib_async._apply_mmdb_location

        async def fake_lookup_dbip(*args, **kwargs):
            return None

        async def fake_lookup_browserleaks(*args, **kwargs):
            return {
                "city": "Ipetumodu",
                "stateProv": "Osun State",
                "countryName": "Nigeria",
                "countryCode": "NG",
            }

        def fail_if_mmdb_is_used(*args, **kwargs):
            raise AssertionError("MMDB should not run when BrowserLeaks returns a location")

        try:
            proxy_lib_async.lookup_dbip_api = fake_lookup_dbip
            proxy_lib_async.lookup_browserleaks_html = fake_lookup_browserleaks
            proxy_lib_async._apply_mmdb_location = fail_if_mmdb_is_used
            result = await _process_response(
                FakeResponse(),
                "session-1",
                "http",
                dbip_session=None,
                browserleaks_wait=False,
            )
        finally:
            proxy_lib_async.lookup_dbip_api = original_lookup_dbip
            proxy_lib_async.lookup_browserleaks_html = original_lookup_browserleaks
            proxy_lib_async._apply_mmdb_location = original_apply_mmdb

        assert result["geo_source"] == "browserleaks-db-ip"
        assert result["dbip_source"] == "browserleaks"
        assert result["local_city"] == "Ipetumodu"
        assert result["local_region"] == "Osun State"
        assert result["geo_quality"] == "online-confirmed"
        assert result["geo_confirmation_pending"] is False

    asyncio.run(run_case())


def test_browserleaks_can_wait_instead_of_skipping_to_mmdb():
    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def text(self):
            return """
                <table>
                  <tr><td>City</td><td>Ipetumodu</td></tr>
                  <tr><td>State/Region</td><td>Osun State</td></tr>
                  <tr><td>Country</td><td>Nigeria NG</td></tr>
                </table>
            """

    class FakeSession:
        def __init__(self):
            self.requests = []

        def get(self, url, **kwargs):
            self.requests.append((url, kwargs))
            return FakeResponse()

    async def run_case():
        fake_session = FakeSession()
        sleeps = []
        original_sleep = proxy_lib_async.asyncio.sleep
        original_last_request_at = proxy_lib_async._browserleaks_last_request_at
        original_cache_loaded = proxy_lib_async._browserleaks_cache_loaded
        proxy_lib_async._browserleaks_cache.clear()
        proxy_lib_async._browserleaks_cache_loaded = True
        proxy_lib_async._browserleaks_last_request_at = time.monotonic()

        async def fake_sleep(delay):
            sleeps.append(delay)

        try:
            proxy_lib_async.asyncio.sleep = fake_sleep
            result = await lookup_browserleaks_html(
                fake_session,
                "197.211.53.84",
                respect_crawl_delay=True,
                wait_for_crawl_delay=True,
            )
        finally:
            proxy_lib_async.asyncio.sleep = original_sleep
            proxy_lib_async._browserleaks_last_request_at = original_last_request_at
            proxy_lib_async._browserleaks_cache_loaded = original_cache_loaded
            proxy_lib_async._browserleaks_cache.clear()

        assert sleeps and sleeps[0] > 0
        assert fake_session.requests
        assert result["city"] == "Ipetumodu"
        assert result["stateProv"] == "Osun State"

    asyncio.run(run_case())


def test_browserleaks_skips_without_waiting_during_bulk_mode():
    class FakeSession:
        def get(self, url, **kwargs):
            raise AssertionError("Bulk mode should skip instead of making a BrowserLeaks request")

    async def run_case():
        original_last_request_at = proxy_lib_async._browserleaks_last_request_at
        original_cache_loaded = proxy_lib_async._browserleaks_cache_loaded
        proxy_lib_async._browserleaks_cache.clear()
        proxy_lib_async._browserleaks_cache_loaded = True
        proxy_lib_async._browserleaks_last_request_at = time.monotonic()

        try:
            result = await lookup_browserleaks_html(
                FakeSession(),
                "197.211.53.84",
                respect_crawl_delay=True,
                wait_for_crawl_delay=False,
            )
        finally:
            proxy_lib_async._browserleaks_last_request_at = original_last_request_at
            proxy_lib_async._browserleaks_cache_loaded = original_cache_loaded
            proxy_lib_async._browserleaks_cache.clear()

        assert result is None

    asyncio.run(run_case())


def test_browserleaks_rechecks_cache_inside_crawl_delay_lock():
    class FakeSession:
        def get(self, url, **kwargs):
            raise AssertionError("Cached BrowserLeaks data should be reused inside the lock")

    async def run_case():
        original_last_request_at = proxy_lib_async._browserleaks_last_request_at
        original_cache_loaded = proxy_lib_async._browserleaks_cache_loaded
        proxy_lib_async._browserleaks_cache.clear()
        proxy_lib_async._browserleaks_cache_loaded = True
        proxy_lib_async._browserleaks_last_request_at = time.monotonic()
        proxy_lib_async._browserleaks_cache["197.211.53.84"] = (
            time.monotonic(),
            {"city": "Ipetumodu", "stateProv": "Osun State"},
        )

        try:
            result = await lookup_browserleaks_html(
                FakeSession(),
                "197.211.53.84",
                respect_crawl_delay=True,
                wait_for_crawl_delay=False,
            )
        finally:
            proxy_lib_async._browserleaks_last_request_at = original_last_request_at
            proxy_lib_async._browserleaks_cache_loaded = original_cache_loaded
            proxy_lib_async._browserleaks_cache.clear()

        assert result["city"] == "Ipetumodu"
        assert result["stateProv"] == "Osun State"

    asyncio.run(run_case())


def test_browserleaks_persistent_cache_reuses_saved_result():
    class FakeSession:
        def get(self, url, **kwargs):
            raise AssertionError("Persistent BrowserLeaks cache should avoid network requests")

    async def run_case():
        original_path = proxy_lib_async.BROWSERLEAKS_CACHE_PATH
        original_loaded = proxy_lib_async._browserleaks_cache_loaded
        original_cache = dict(proxy_lib_async._browserleaks_cache)

        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                proxy_lib_async.BROWSERLEAKS_CACHE_PATH = str(Path(tmp_dir) / "browserleaks_cache.json")
                proxy_lib_async._browserleaks_cache_loaded = True
                proxy_lib_async._browserleaks_cache.clear()
                proxy_lib_async._browserleaks_cache["197.211.53.84"] = (
                    time.monotonic(),
                    {"city": "Ipetumodu", "stateProv": "Osun State"},
                )
                proxy_lib_async._save_browserleaks_cache()

                proxy_lib_async._browserleaks_cache.clear()
                proxy_lib_async._browserleaks_cache_loaded = False
                result = await lookup_browserleaks_html(
                    FakeSession(),
                    "197.211.53.84",
                    respect_crawl_delay=True,
                    wait_for_crawl_delay=False,
                )
            finally:
                proxy_lib_async.BROWSERLEAKS_CACHE_PATH = original_path
                proxy_lib_async._browserleaks_cache_loaded = original_loaded
                proxy_lib_async._browserleaks_cache.clear()
                proxy_lib_async._browserleaks_cache.update(original_cache)

        assert result["city"] == "Ipetumodu"
        assert result["stateProv"] == "Osun State"

    asyncio.run(run_case())


def test_dbip_api_rate_limit_enters_backoff_and_skips_followup_calls():
    class FakeResponse:
        status = 200

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

        async def json(self, content_type=None):
            return {
                "errorCode": "OVER_QUERY_LIMIT",
                "error": "maximum number of queries per day exceeded",
            }

    class FakeSession:
        def __init__(self):
            self.requests = []

        def get(self, url, **kwargs):
            self.requests.append((url, kwargs))
            return FakeResponse()

    async def run_case():
        fake_session = FakeSession()
        original_disabled_until = proxy_lib_async._dbip_api_disabled_until
        original_last_error = proxy_lib_async._dbip_api_last_error
        original_cache = dict(proxy_lib_async._dbip_api_cache)

        try:
            proxy_lib_async._dbip_api_disabled_until = 0.0
            proxy_lib_async._dbip_api_last_error = None
            proxy_lib_async._dbip_api_cache.clear()

            first_result = await proxy_lib_async.lookup_dbip_api(fake_session, "8.8.8.8")
            second_result = await proxy_lib_async.lookup_dbip_api(fake_session, "1.1.1.1")
            stats = proxy_lib_async.get_db_stats()
        finally:
            proxy_lib_async._dbip_api_disabled_until = original_disabled_until
            proxy_lib_async._dbip_api_last_error = original_last_error
            proxy_lib_async._dbip_api_cache.clear()
            proxy_lib_async._dbip_api_cache.update(original_cache)

        assert first_result is None
        assert second_result is None
        assert len(fake_session.requests) == 1
        assert stats["dbip_api_rate_limited"] is True
        assert stats["dbip_api_available"] is False
        assert stats["dbip_api_last_error"]["code"] == "OVER_QUERY_LIMIT"

    asyncio.run(run_case())


def test_proxy_stream_converts_escaped_ssl_error_to_failed_candidate():
    async def run_case():
        original_check = proxy_lib_async.check_single_proxy_async
        original_initialize = proxy_lib_async._db_manager.initialize

        async def failing_check(*args, **kwargs):
            raise ssl.SSLError(1, "sslv3 alert bad record mac")

        async def fake_initialize(*args, **kwargs):
            return True

        try:
            proxy_lib_async.check_single_proxy_async = failing_check
            proxy_lib_async._db_manager.initialize = fake_initialize
            results = [
                result
                async for result in proxy_lib_async.check_proxies_stream(
                    ["geo.iproyal.com:12321:user:secret_country-ng_session-sslerr_lifetime-24h"],
                    max_concurrent=1,
                )
            ]
        finally:
            proxy_lib_async.check_single_proxy_async = original_check
            proxy_lib_async._db_manager.initialize = original_initialize

        assert len(results) == 1
        assert results[0]["status"] == "fail"
        assert results[0]["session"] == "sslerr"
        assert results[0]["error_type"] == "network_error"
        assert "Network/TLS error" in results[0]["error"]

    asyncio.run(run_case())


def test_ip_only_stream_uses_fast_exit_probe_without_full_geo_check():
    async def run_case():
        calls = {"fast": 0, "full": 0}
        original_fast = proxy_lib_async.check_single_proxy_exit_ip_async
        original_full = proxy_lib_async.check_single_proxy_async
        original_initialize = proxy_lib_async._db_manager.initialize

        async def fake_fast(proxy, *args, **kwargs):
            calls["fast"] += 1
            return {
                "session": "fast1",
                "status": "success",
                "query": "197.211.52.187",
                "ip_probe_only": True,
            }

        async def forbidden_full(*args, **kwargs):
            calls["full"] += 1
            raise AssertionError("full proxy check should not run during IP-only scouting")

        async def fake_initialize(*args, **kwargs):
            return True

        try:
            proxy_lib_async.check_single_proxy_exit_ip_async = fake_fast
            proxy_lib_async.check_single_proxy_async = forbidden_full
            proxy_lib_async._db_manager.initialize = fake_initialize
            results = [
                result
                async for result in proxy_lib_async.check_proxies_stream(
                    ["geo.iproyal.com:12321:user:secret_country-ng_session-fast1_lifetime-24h"],
                    max_concurrent=1,
                    ip_only=True,
                )
            ]
        finally:
            proxy_lib_async.check_single_proxy_exit_ip_async = original_fast
            proxy_lib_async.check_single_proxy_async = original_full
            proxy_lib_async._db_manager.initialize = original_initialize

        assert calls == {"fast": 1, "full": 0}
        assert results[0]["ip_probe_only"] is True
        assert results[0]["query"] == "197.211.52.187"

    asyncio.run(run_case())


if __name__ == "__main__":
    test_browserleaks_supplies_location_when_dbip_api_is_unavailable()
    test_browserleaks_does_not_override_primary_dbip_api_location()
    test_browserleaks_only_fills_missing_primary_fields()
    test_browserleaks_replaces_provisional_mmdb_location()
    test_browserleaks_parser_reads_only_ip_location_table()
    test_process_response_uses_browserleaks_before_mmdb()
    test_browserleaks_can_wait_instead_of_skipping_to_mmdb()
    test_browserleaks_skips_without_waiting_during_bulk_mode()
    test_browserleaks_rechecks_cache_inside_crawl_delay_lock()
    test_browserleaks_persistent_cache_reuses_saved_result()
    test_dbip_api_rate_limit_enters_backoff_and_skips_followup_calls()
    test_proxy_stream_converts_escaped_ssl_error_to_failed_candidate()
    test_ip_only_stream_uses_fast_exit_probe_without_full_geo_check()
    print("geo fallback tests passed")
