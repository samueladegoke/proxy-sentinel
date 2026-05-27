import os
import sqlite3
import threading
import time
import re
from typing import Any, Dict, List, Optional


TRACKING_LOG_DB = os.getenv(
    "TRACKING_LOG_DB",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "tracking_logs.sqlite3")
)


class TrackingLogStore:
    """Durable tracking log for proxy stability analysis."""

    def __init__(self, db_path: str = TRACKING_LOG_DB):
        self.db_path = db_path
        self._lock = threading.Lock()
        self.initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    @staticmethod
    def _ensure_columns(conn: sqlite3.Connection, table: str, columns: Dict[str, str]):
        existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        for name, column_type in columns.items():
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {column_type}")

    def initialize(self):
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with self._lock, self._connect() as conn:
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tracking_runs (
                    run_id TEXT PRIMARY KEY,
                    session TEXT NOT NULL,
                    proxy TEXT NOT NULL,
                    expected_location TEXT,
                    expected_state TEXT,
                    expected_state_slug TEXT,
                    expected_lifetime_hours REAL,
                    started_at REAL NOT NULL,
                    expected_expires_at REAL,
                    ended_at REAL,
                    first_ip TEXT,
                    first_region TEXT,
                    first_city TEXT,
                    latest_ip TEXT,
                    latest_region TEXT,
                    latest_city TEXT,
                    latest_country TEXT,
                    latest_geo_source TEXT,
                    latest_geo_provider TEXT,
                    latest_isp TEXT,
                    latest_mobile INTEGER,
                    latest_risk_level TEXT,
                    first_change_at REAL,
                    first_change_elapsed_seconds REAL,
                    observation_count INTEGER NOT NULL DEFAULT 0,
                    change_count INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS tracking_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    session TEXT NOT NULL,
                    proxy TEXT NOT NULL,
                    checked_at REAL NOT NULL,
                    elapsed_seconds REAL NOT NULL,
                    expected_lifetime_hours REAL,
                    lifetime_progress REAL,
                    status TEXT,
                    ip TEXT,
                    region TEXT,
                    city TEXT,
                    country TEXT,
                    isp TEXT,
                    mobile INTEGER,
                    risk_level TEXT,
                    geo_source TEXT,
                    old_ip TEXT,
                    old_region TEXT,
                    old_city TEXT,
                    changed_ip INTEGER NOT NULL,
                    changed_location INTEGER NOT NULL,
                    stable INTEGER NOT NULL,
                    error TEXT,
                    FOREIGN KEY(run_id) REFERENCES tracking_runs(run_id)
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracking_obs_run_time ON tracking_observations(run_id, checked_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_tracking_obs_session_time ON tracking_observations(session, checked_at)"
            )
            self._ensure_columns(conn, "tracking_runs", {
                "latest_country": "TEXT",
                "latest_geo_source": "TEXT",
                "latest_geo_provider": "TEXT",
                "latest_isp": "TEXT",
                "latest_mobile": "INTEGER",
                "latest_risk_level": "TEXT",
            })
            self._repair_latest_successful_observations(conn)

    def _repair_latest_successful_observations(self, conn: sqlite3.Connection):
        """Backfill historical runs whose latest signal was overwritten by an inconclusive check."""
        rows = conn.execute(
            """
            SELECT run_id FROM tracking_runs
            WHERE latest_ip IS NULL
              AND EXISTS (
                SELECT 1 FROM tracking_observations
                WHERE tracking_observations.run_id = tracking_runs.run_id
                  AND ip IS NOT NULL
              )
            """
        ).fetchall()
        for row in rows:
            observation = conn.execute(
                """
                SELECT ip, region, city, country, geo_source, isp, mobile, risk_level
                FROM tracking_observations
                WHERE run_id = ? AND ip IS NOT NULL
                ORDER BY checked_at DESC
                LIMIT 1
                """,
                (row["run_id"],),
            ).fetchone()
            if not observation:
                continue
            conn.execute(
                """
                UPDATE tracking_runs
                SET latest_ip = ?,
                    latest_region = ?,
                    latest_city = ?,
                    latest_country = ?,
                    latest_geo_source = ?,
                    latest_isp = ?,
                    latest_mobile = ?,
                    latest_risk_level = ?
                WHERE run_id = ?
                """,
                (
                    observation["ip"],
                    observation["region"],
                    observation["city"],
                    observation["country"],
                    observation["geo_source"],
                    observation["isp"],
                    observation["mobile"],
                    observation["risk_level"],
                    row["run_id"],
                ),
            )

    def start_run(self, session_data: Dict[str, Any]):
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT OR IGNORE INTO tracking_runs (
                    run_id, session, proxy, expected_location, expected_state,
                    expected_state_slug, expected_lifetime_hours, started_at,
                    expected_expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_data["run_id"],
                    session_data["session"],
                    session_data["proxy"],
                    session_data.get("expected_location"),
                    session_data.get("expected_state"),
                    session_data.get("expected_state_slug"),
                    session_data.get("expected_lifetime_hours"),
                    session_data["started_at"],
                    session_data.get("expected_expires_at"),
                ),
            )

    def end_run(self, run_id: str):
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE tracking_runs SET ended_at = COALESCE(ended_at, ?) WHERE run_id = ?",
                (time.time(), run_id),
            )

    def active_runs(self) -> List[Dict[str, Any]]:
        """Return runs that should be restored into active tracking after restart."""
        with self._lock, self._connect() as conn:
            return [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT * FROM tracking_runs
                    WHERE ended_at IS NULL
                    ORDER BY started_at ASC
                    """
                ).fetchall()
            ]

    @staticmethod
    def _normalize_location_value(value: Any) -> str:
        if not value:
            return ""
        return re.sub(r"[^a-z0-9]+", " ", str(value).lower()).strip()

    def log_observation(self, session_data: Dict[str, Any], result: Dict[str, Any], previous: Dict[str, Any]):
        now = time.time()
        started_at = session_data.get("started_at") or now
        elapsed_seconds = max(0.0, now - started_at)
        expected_lifetime_hours = session_data.get("expected_lifetime_hours")
        lifetime_progress = None
        if expected_lifetime_hours:
            lifetime_progress = elapsed_seconds / (float(expected_lifetime_hours) * 3600)

        ip = result.get("query")
        region = result.get("local_region") or result.get("regionName") or result.get("region")
        city = result.get("local_city") or result.get("city")
        country = result.get("local_country") or result.get("country")

        old_result = previous.get("last_result") or {}
        old_ip = previous.get("last_ip")
        old_region = old_result.get("local_region") or old_result.get("regionName") or old_result.get("region")
        old_city = old_result.get("local_city") or old_result.get("city")
        old_geo_source = old_result.get("geo_source")
        new_geo_source = result.get("geo_source")

        changed_ip = bool(old_ip and ip and old_ip != ip)
        old_location = (
            self._normalize_location_value(old_region),
            self._normalize_location_value(old_city),
        )
        new_location = (
            self._normalize_location_value(region),
            self._normalize_location_value(city),
        )
        changed_location = bool(
            old_ip
            and old_location != new_location
            and (changed_ip or old_geo_source == new_geo_source)
        )
        stable = not changed_ip and not changed_location

        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO tracking_observations (
                    run_id, session, proxy, checked_at, elapsed_seconds,
                    expected_lifetime_hours, lifetime_progress, status, ip,
                    region, city, country, isp, mobile, risk_level, geo_source,
                    old_ip, old_region, old_city, changed_ip, changed_location,
                    stable, error
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    session_data["run_id"],
                    session_data["session"],
                    session_data["proxy"],
                    now,
                    elapsed_seconds,
                    expected_lifetime_hours,
                    lifetime_progress,
                    result.get("status"),
                    ip,
                    region,
                    city,
                    country,
                    result.get("isp"),
                    1 if result.get("mobile") else 0,
                    result.get("risk_level"),
                    result.get("geo_source"),
                    old_ip,
                    old_region,
                    old_city,
                    1 if changed_ip else 0,
                    1 if changed_location else 0,
                    1 if stable else 0,
                    result.get("error"),
                ),
            )

            row = conn.execute(
                "SELECT first_ip, first_change_at FROM tracking_runs WHERE run_id = ?",
                (session_data["run_id"],),
            ).fetchone()
            has_ip = 1 if ip else 0
            should_set_first_ip = 1 if row and not row["first_ip"] and ip else 0
            should_set_first_change = 1 if (changed_ip or changed_location) and row and not row["first_change_at"] else 0
            latest_mobile = None if result.get("mobile") is None else 1 if result.get("mobile") else 0
            conn.execute(
                """
                UPDATE tracking_runs
                SET
                    latest_ip = CASE WHEN ? THEN ? ELSE latest_ip END,
                    latest_region = CASE WHEN ? THEN ? ELSE latest_region END,
                    latest_city = CASE WHEN ? THEN ? ELSE latest_city END,
                    latest_country = CASE WHEN ? THEN ? ELSE latest_country END,
                    latest_geo_source = CASE WHEN ? THEN ? ELSE latest_geo_source END,
                    latest_geo_provider = CASE WHEN ? THEN ? ELSE latest_geo_provider END,
                    latest_isp = CASE WHEN ? THEN ? ELSE latest_isp END,
                    latest_mobile = CASE WHEN ? THEN ? ELSE latest_mobile END,
                    latest_risk_level = CASE WHEN ? THEN ? ELSE latest_risk_level END,
                    first_ip = CASE WHEN ? THEN ? ELSE first_ip END,
                    first_region = CASE WHEN ? THEN ? ELSE first_region END,
                    first_city = CASE WHEN ? THEN ? ELSE first_city END,
                    first_change_at = CASE WHEN ? THEN ? ELSE first_change_at END,
                    first_change_elapsed_seconds = CASE WHEN ? THEN ? ELSE first_change_elapsed_seconds END,
                    observation_count = observation_count + 1,
                    change_count = change_count + ?
                WHERE run_id = ?
                """,
                (
                    has_ip, ip,
                    has_ip, region,
                    has_ip, city,
                    has_ip, country,
                    has_ip, result.get("geo_source"),
                    has_ip, result.get("geo_provider"),
                    has_ip, result.get("isp"),
                    has_ip, latest_mobile,
                    has_ip, result.get("risk_level"),
                    should_set_first_ip, ip,
                    should_set_first_ip, region,
                    should_set_first_ip, city,
                    should_set_first_change, now,
                    should_set_first_change, elapsed_seconds,
                    1 if (changed_ip or changed_location) else 0,
                    session_data["run_id"],
                ),
            )

        return {
            "checked_at": now,
            "elapsed_seconds": elapsed_seconds,
            "expected_lifetime_hours": expected_lifetime_hours,
            "lifetime_progress": lifetime_progress,
            "changed_ip": changed_ip,
            "changed_location": changed_location,
            "stable": stable,
            "old_ip": old_ip,
            "old_region": old_region,
            "old_city": old_city,
            "new_ip": ip,
            "new_region": region,
            "new_city": city,
        }

    def recent_observations(self, limit: int = 100, session: Optional[str] = None) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        sql = "SELECT * FROM tracking_observations"
        params: List[Any] = []
        if session:
            sql += " WHERE session = ?"
            params.append(session)
        sql += " ORDER BY checked_at DESC LIMIT ?"
        params.append(limit)

        with self._lock, self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, params).fetchall()]

    def runs(self, limit: int = 100, status: Optional[str] = None) -> List[Dict[str, Any]]:
        limit = max(1, min(limit, 1000))

        with self._lock, self._connect() as conn:
            if status == "active":
                rows = conn.execute(
                    "SELECT * FROM tracking_runs WHERE ended_at IS NULL ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            elif status == "stopped":
                rows = conn.execute(
                    "SELECT * FROM tracking_runs WHERE ended_at IS NOT NULL ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tracking_runs ORDER BY started_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [
                dict(row)
                for row in rows
            ]

    def run_details(self, run_id: str, observation_limit: int = 500) -> Dict[str, Any]:
        observation_limit = max(1, min(observation_limit, 2000))
        with self._lock, self._connect() as conn:
            run = conn.execute(
                "SELECT * FROM tracking_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            observations = conn.execute(
                """
                SELECT * FROM tracking_observations
                WHERE run_id = ?
                ORDER BY checked_at ASC
                LIMIT ?
                """,
                (run_id, observation_limit),
            ).fetchall()

        return {
            "run": dict(run) if run else None,
            "observations": [dict(row) for row in observations],
        }

    def delete_run(self, run_id: str, include_active: bool = False) -> bool:
        """Delete a historical run and its observations. Active runs are protected by default."""
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT ended_at FROM tracking_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if not row:
                return False
            if row["ended_at"] is None and not include_active:
                return False

            conn.execute("DELETE FROM tracking_observations WHERE run_id = ?", (run_id,))
            conn.execute("DELETE FROM tracking_runs WHERE run_id = ?", (run_id,))
            return True

    def analytics(self) -> Dict[str, Any]:
        with self._lock, self._connect() as conn:
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT
                        expected_location,
                        expected_state,
                        expected_state_slug,
                        expected_lifetime_hours,
                        COUNT(*) AS runs,
                        SUM(observation_count) AS observations,
                        SUM(change_count) AS changes,
                        AVG(first_change_elapsed_seconds) AS avg_first_change_seconds,
                        MAX(COALESCE(first_change_elapsed_seconds, ended_at - started_at, ? - started_at)) AS max_stable_seconds
                    FROM tracking_runs
                    GROUP BY expected_location, expected_state_slug, expected_lifetime_hours
                    ORDER BY max_stable_seconds DESC
                    """,
                    (time.time(),),
                ).fetchall()
            ]

            totals = dict(
                conn.execute(
                    """
                    SELECT
                        COUNT(*) AS runs,
                        SUM(observation_count) AS observations,
                        SUM(change_count) AS changes
                    FROM tracking_runs
                    """
                ).fetchone()
            )

        for row in rows:
            observations = row.get("observations") or 0
            changes = row.get("changes") or 0
            row["change_rate"] = changes / observations if observations else 0
            if row.get("avg_first_change_seconds") is not None:
                row["avg_first_change_hours"] = row["avg_first_change_seconds"] / 3600
            row["max_stable_hours"] = (row.get("max_stable_seconds") or 0) / 3600

        return {
            "database": self.db_path,
            "totals": totals,
            "groups": rows,
        }
