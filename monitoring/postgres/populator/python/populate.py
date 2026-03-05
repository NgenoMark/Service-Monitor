import json
import os
import socket
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

import psycopg2


def env(name: str, default: str) -> str:
    return os.getenv(name, default)


def get_connection():
    return psycopg2.connect(
        host=env("DB_HOST", "postgres"),
        port=env("DB_PORT", "5432"),
        dbname=env("DB_NAME", "service_monitor"),
        user=env("DB_USER", "service_monitor_user"),
        password=env("DB_PASSWORD", "service_monitor_pass"),
    )


def fetch_active_services(cur):
    cur.execute(
        """
        SELECT id, service_key, display_name, base_url
        FROM monitoring.services
        WHERE is_active = TRUE
        ORDER BY id
        """
    )
    return cur.fetchall()


def get_last_status(cur, service_id: int):
    cur.execute(
        """
        SELECT current_status
        FROM monitoring.service_state
        WHERE service_id = %s
        LIMIT 1
        """,
        (service_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def check_http(url: str, timeout_seconds: int):
    req = Request(url, method="GET")
    req.add_header("User-Agent", "service-monitor-populator/1.0")
    started = time.monotonic()

    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            code = int(response.getcode())
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if 200 <= code < 400:
                status = "UP"
            elif code >= 500:
                status = "DOWN"
            else:
                status = "DEGRADED"
            return status, code, None, elapsed_ms
    except HTTPError as http_err:
        code = int(http_err.code)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if code >= 500:
            status = "DOWN"
        else:
            status = "DEGRADED"
        return status, code, str(http_err), elapsed_ms
    except (URLError, TimeoutError, OSError) as conn_err:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return "DOWN", None, str(conn_err), elapsed_ms


def check_tcp(host: str, port: int, timeout_seconds: int):
    started = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            elapsed_ms = int((time.monotonic() - started) * 1000)
            return "UP", None, elapsed_ms
    except OSError as exc:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        return "DOWN", str(exc), elapsed_ms


def probe_service(base_url: str, timeout_seconds: int):
    observed_at = datetime.now(timezone.utc).isoformat()

    if not base_url:
        return "UNKNOWN", {
            "probe": "none",
            "error": "base_url is empty",
            "observed_at": observed_at,
            "response_time_ms": None,
            "http_status": None,
            "target": None,
        }

    raw = base_url.strip()

    if raw.startswith("http://") or raw.startswith("https://"):
        status, http_code, error_text, response_time_ms = check_http(raw, timeout_seconds)
        return status, {
            "probe": "http",
            "request_url": raw,
            "target": raw,
            "http_status": http_code,
            "error": error_text,
            "response_time_ms": response_time_ms,
            "observed_at": observed_at,
        }

    if ":" in raw and "/" not in raw:
        host, port_text = raw.rsplit(":", 1)
        try:
            port = int(port_text)
        except ValueError:
            return "UNKNOWN", {
                "probe": "tcp",
                "target": raw,
                "error": f"invalid port: {port_text}",
                "observed_at": observed_at,
                "response_time_ms": None,
                "http_status": None,
            }

        status, error_text, response_time_ms = check_tcp(host, port, timeout_seconds)
        return status, {
            "probe": "tcp",
            "target": raw,
            "error": error_text,
            "observed_at": observed_at,
            "response_time_ms": response_time_ms,
            "http_status": None,
        }

    fallback_url = f"http://{raw}"
    status, http_code, error_text, response_time_ms = check_http(fallback_url, timeout_seconds)
    return status, {
        "probe": "http",
        "request_url": fallback_url,
        "target": fallback_url,
        "http_status": http_code,
        "error": error_text,
        "response_time_ms": response_time_ms,
        "observed_at": observed_at,
    }


def insert_service_check(cur, service_id: int, status: str, details: dict, observed_at: datetime):
    probe = (details.get("probe") or "none").upper()
    if probe not in {"HTTP", "TCP", "NONE"}:
        probe = "NONE"

    cur.execute(
        """
        INSERT INTO monitoring.service_checks
            (service_id, probe_type, check_target, status, http_status_code, response_time_ms, error_message, observed_at, details)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
        """,
        (
            service_id,
            probe,
            details.get("target"),
            status,
            details.get("http_status"),
            details.get("response_time_ms"),
            details.get("error"),
            observed_at,
            json.dumps(details),
        ),
    )


def insert_availability_event(cur, service_id: int, status: str, details: dict, observed_at: datetime):
    cur.execute(
        """
        INSERT INTO monitoring.service_availability_events
            (service_id, source, status, observed_at, details)
        VALUES
            (%s, 'MANUAL', %s, %s, %s::jsonb)
        """,
        (service_id, status, observed_at, json.dumps(details)),
    )


def insert_http_error_event(cur, service_id: int, base_url: str, details: dict, interval_seconds: int, observed_at: datetime):
    http_status = details.get("http_status")
    if http_status is None or int(http_status) < 400:
        return

    request_url = details.get("request_url", base_url or "")
    parsed = urlparse(request_url)
    endpoint = parsed.path or "/"

    cur.execute(
        """
        INSERT INTO monitoring.http_error_events
            (service_id, source, endpoint, method, status_code, error_count, window_seconds, observed_at, details)
        VALUES
            (%s, 'MANUAL', %s, 'GET', %s, 1, %s, %s, %s::jsonb)
        """,
        (service_id, endpoint, int(http_status), interval_seconds, observed_at, json.dumps(details)),
    )


def upsert_service_state(cur, service_id: int, previous_status: str, current_status: str, details: dict, observed_at: datetime):
    changed = previous_status is None or previous_status != current_status

    if current_status == "DOWN":
        if previous_status == "DOWN":
            cur.execute(
                """
                SELECT COALESCE(consecutive_failures, 0)
                FROM monitoring.service_state
                WHERE service_id = %s
                """,
                (service_id,),
            )
            row = cur.fetchone()
            consecutive_failures = (row[0] if row else 0) + 1
        else:
            consecutive_failures = 1
    else:
        consecutive_failures = 0

    cur.execute(
        """
        INSERT INTO monitoring.service_state
            (service_id, current_status, previous_status, last_check_at, last_change_at, consecutive_failures,
             last_http_status_code, last_error_message, details, updated_at)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb, NOW())
        ON CONFLICT (service_id) DO UPDATE SET
            current_status = EXCLUDED.current_status,
            previous_status = EXCLUDED.previous_status,
            last_check_at = EXCLUDED.last_check_at,
            last_change_at = CASE
                WHEN monitoring.service_state.current_status IS DISTINCT FROM EXCLUDED.current_status THEN EXCLUDED.last_check_at
                ELSE monitoring.service_state.last_change_at
            END,
            consecutive_failures = EXCLUDED.consecutive_failures,
            last_http_status_code = EXCLUDED.last_http_status_code,
            last_error_message = EXCLUDED.last_error_message,
            details = EXCLUDED.details,
            updated_at = NOW()
        """,
        (
            service_id,
            current_status,
            previous_status,
            observed_at,
            observed_at if changed else None,
            consecutive_failures,
            details.get("http_status"),
            details.get("error"),
            json.dumps(details),
        ),
    )


def sync_incident_transition(cur, service_id: int, service_key: str, previous_status: str, current_status: str, details: dict, observed_at: datetime):
    if previous_status == current_status:
        return

    if current_status == "DOWN":
        cur.execute(
            """
            INSERT INTO monitoring.service_incidents
                (service_id, severity, opened_at, is_open, open_reason, open_details, created_at, updated_at)
            VALUES
                (%s, 'critical', %s, TRUE, %s, %s::jsonb, NOW(), NOW())
            ON CONFLICT DO NOTHING
            """,
            (
                service_id,
                observed_at,
                f"{service_key} became unavailable",
                json.dumps(details),
            ),
        )
        return

    if previous_status == "DOWN" and current_status in {"UP", "DEGRADED"}:
        cur.execute(
            """
            UPDATE monitoring.service_incidents
            SET
                resolved_at = %s,
                is_open = FALSE,
                close_reason = %s,
                close_details = %s::jsonb,
                updated_at = NOW()
            WHERE service_id = %s
              AND is_open = TRUE
            """,
            (
                observed_at,
                f"{service_key} recovered with status {current_status}",
                json.dumps(details),
                service_id,
            ),
        )


def insert_alert_transition(cur, service_id: int, service_key: str, previous_status: str, current_status: str, details: dict, observed_at: datetime):
    if previous_status == current_status:
        return

    ends_at = None
    if current_status == "DOWN":
        alert_status = "FIRING"
        severity = "critical"
        message = f"{service_key} became unavailable (status transition: {previous_status} -> {current_status})."
    elif previous_status == "DOWN" and current_status in {"UP", "DEGRADED"}:
        alert_status = "RESOLVED"
        severity = "critical"
        message = f"{service_key} recovered (status transition: {previous_status} -> {current_status})."
        ends_at = observed_at
    else:
        return

    labels = {
        "service": service_key,
        "env": env("ENVIRONMENT", "local"),
        "probe": details.get("probe", "unknown"),
    }

    cur.execute(
        """
        INSERT INTO monitoring.alert_events
            (service_id, alert_source, alert_name, severity, status, message, labels, starts_at, ends_at)
        VALUES
            (%s, 'PROMETHEUS', 'BackendDown', %s, %s, %s, %s::jsonb, %s, %s)
        """,
        (service_id, severity, alert_status, message, json.dumps(labels), observed_at, ends_at),
    )


def main():
    interval_seconds = int(env("POPULATOR_INTERVAL_SECONDS", "15"))
    timeout_seconds = int(env("POPULATOR_TIMEOUT_SECONDS", "5"))

    while True:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    services = fetch_active_services(cur)
                    for service_id, service_key, _display_name, base_url in services:
                        observed_at = datetime.now(timezone.utc)
                        previous_status = get_last_status(cur, service_id)
                        current_status, details = probe_service(base_url, timeout_seconds)

                        insert_service_check(cur, service_id, current_status, details, observed_at)
                        insert_availability_event(cur, service_id, current_status, details, observed_at)
                        insert_http_error_event(cur, service_id, base_url, details, interval_seconds, observed_at)
                        upsert_service_state(cur, service_id, previous_status, current_status, details, observed_at)
                        sync_incident_transition(
                            cur,
                            service_id,
                            service_key,
                            previous_status,
                            current_status,
                            details,
                            observed_at,
                        )
                        insert_alert_transition(
                            cur,
                            service_id,
                            service_key,
                            previous_status,
                            current_status,
                            details,
                            observed_at,
                        )
                conn.commit()
        except Exception as exc:
            print(f"[populator] write cycle failed: {exc}", flush=True)

        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
