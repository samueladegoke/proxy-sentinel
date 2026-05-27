import gzip
from pathlib import Path

import pytest

import decompress_db
import proxy_checker


def test_decompress_gz_preserves_existing_output_on_failure(tmp_path):
    bad_archive = tmp_path / "db.mmdb.gz"
    output = tmp_path / "db.mmdb"
    output.write_bytes(b"existing database")
    bad_archive.write_bytes(b"not a gzip archive")

    with pytest.raises(RuntimeError):
        decompress_db.decompress_gz(bad_archive, output)

    assert output.read_bytes() == b"existing database"


def test_decompress_gz_replaces_output_after_successful_copy(tmp_path):
    archive = tmp_path / "db.mmdb.gz"
    output = tmp_path / "db.mmdb"
    output.write_bytes(b"old database")

    with gzip.open(archive, "wb") as handle:
        handle.write(b"new database")

    decompress_db.decompress_gz(archive, output)

    assert output.read_bytes() == b"new database"


def test_proxy_checker_loads_proxies_from_ignored_file(tmp_path, monkeypatch):
    proxy_file = tmp_path / "proxy_checker.proxies.txt"
    proxy_file.write_text("proxy-one\n\nproxy-two, proxy-three", encoding="utf-8")
    monkeypatch.delenv("PROXY_CHECKER_PROXIES", raising=False)

    assert proxy_checker.load_proxies(proxy_file) == ["proxy-one", "proxy-two", "proxy-three"]


def test_proxy_checker_source_does_not_commit_provider_credentials():
    source = Path(proxy_checker.__file__).read_text(encoding="utf-8")

    assert "PROXIES = [" not in source
    assert "geo.iproyal.com:" not in source


def test_check_proxy_closes_session_when_validator_raises(monkeypatch):
    class DummySession:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            self.close()

        def close(self):
            self.closed = True

    class FailingValidator:
        def validate(self, proxy_urls, session, timeout):
            raise RuntimeError("validator failed")

    session = DummySession()
    monkeypatch.setattr(proxy_checker.requests, "Session", lambda: session)

    result = proxy_checker.check_proxy(
        "example.test:1234:user:password_session-abc_lifetime-1h",
        FailingValidator(),
    )

    assert result["status"] == "fail"
    assert result["session"] == "abc"
    assert session.closed is True
