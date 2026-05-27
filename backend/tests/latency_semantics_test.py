import time
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from proxy_lib_async import _with_check_duration, _with_proxy_latency


def test_proxy_latency_and_check_duration_are_separate():
    started_at = time.perf_counter()

    proxy_timed = _with_proxy_latency({"status": "success"}, started_at)

    assert "latency_ms" in proxy_timed
    assert "check_duration_ms" not in proxy_timed
    assert proxy_timed["latency_ms"] >= 0

    time.sleep(0.001)
    full_timed = _with_check_duration(dict(proxy_timed), started_at)

    assert full_timed["latency_ms"] == proxy_timed["latency_ms"]
    assert "check_duration_ms" in full_timed
    assert full_timed["check_duration_ms"] >= full_timed["latency_ms"]


if __name__ == "__main__":
    test_proxy_latency_and_check_duration_are_separate()
    print("latency semantics tests passed")
