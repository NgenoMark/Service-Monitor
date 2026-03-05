import json
import os
import socket
import time
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
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
        SELECT
            id,
            service_key,
            display_name,
            base_url,
            probe_type,
            probe_path,
            expected_status_codes,
            timeout_seconds,
            check_interval_seconds
        FROM monitoring.services
        WHERE is_active = TRUE
        ORDER BY id
        """
    )
    return cur.fetchall()


def get_service_state(cur, service_id: int):
    cur.execute(
        """
        SELECT current_status, last_check_at, consecutive_failures
        FROM monitoring.service_state
        WHERE service_id = %s
        LIMIT 1
        """,
        (service_id,),
    )
    row = cur.fetchone()
    if not row:
        return None, None, 0
    return row[0], row[1], row[2] or 0


def parse_expected_status_codes(spec: str):
    tokens = (spec or "200-399").replace(" ", "").split(",")
    exact = set()
    ranges = []

    for token in tokens:
        if not token:
            continue
        if "-" in token:
            start_text, end_text = token.split("-", 1)
            try:
                start = int(start_text)
                end = int(end_text)
            except ValueError:
                continue
            if start > end:
                start, end = end, start
            ranges.append((start, end))
        else:
            try:
                exact.add(int(token))
            except ValueError:
                continue

    if not exact and not ranges:
        ranges.append((200, 399))

    return exact, ranges


def is_expected_http_status(code: int, expected_spec: str) -> bool:
    exact, ranges = parse_expected_status_codes(expected_spec)
    if code in exact:
        return True
    for start, end in ranges:
        if start <= code <= end:
            return True
    return False


def build_http_url(base_url: str, probe_path: str):
    raw = (base_url or "").strip()
    if not raw:
        return None, "base_url is empty"

    if not raw.startswith("http://") and not raw.startswith("https://"):
        raw = f"http://{raw}"

    parsed = urlparse(raw)
    if not parsed.netloc:
        return None, "invalid HTTP target"

    if probe_path and probe_path.strip():
        path = probe_path.strip()
        if not path.startswith("/"):
            path = f"/{path}"
    else:
        path = parsed.path if parsed.path else "/"

    final_url = urlunparse((parsed.scheme or "http", parsed.netloc, path, "", "", ""))
    return final_url, None


def parse_tcp_target(base_url: str):
    raw = (base_url or "").strip()
    if not raw:
        return None, None, "base_url is empty"

    if raw.startswith("http://") or raw.startswith("https://"):
        parsed = urlparse(raw)
        host_port = parsed.netloc
    else:
        host_port = raw.split("/", 1)[0]

    if ":" not in host_port:
        return None, None, "missing host:port"

    host, port_text = host_port.rsplit(":", 1)
    try:
        port = int(port_text)
    except ValueError:
        return None, None, f"invalid port: {port_text}"

    if not host:
        return None, None, "missing host"

    return host, port, None


def check_http(url: str, timeout_seconds: int, expected_status_codes: str):
    req = Request(url, method="GET")
    req.add_header("User-Agent", "service-monitor-populator/1.0")
    started = time.monotonic()

    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            code = int(response.getcode())
            elapsed_ms = int((time.monotonic() - started) * 1000)
            if is_expected_http_status(code, expected_status_codes):
                status = "UP"
            elif code >= 500:
                status = "DOWN"
            else:
                status = "DEGRADED"
            return status, code, None, elapsed_ms
    except HTTPError as http_err:
        code = int(http_err.code)
        elapsed_ms = int((time.monotonic() - started) * 1000)
        if is_expected_http_status(code, expected_status_codes):
            status = "UP"
        elif code >= 500:
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


def should_probe(last_check_at: datetime, interval_seconds: int, now: datetime) -> bool:
    if last_check_at is None:
        return True
    elapsed = (now - last_check_at).total_seconds()
    return elapsed >= interval_seconds


def probe_service(service_row, default_timeout_seconds: int):
    (
        _service_id,
        service_key,
        _display_name,
        base_url,
        probe_type,
        probe_path,
        expected_status_codes,
        timeout_seconds,
        check_interval_seconds,
    ) = service_row

    observed_at = datetime.now(timezone.utc).isoformat()
    timeout = int(timeout_seconds or default_timeout_seconds)
    configured_probe = (probe_type or "HTTP").upper()

    details = {
        "configured_probe_type": configured_probe,
        "configured_probe_path": probe_path,
        "configured_expected_status_codes": expected_status_codes,
        "configured_timeout_seconds": timeout,
        "configured_check_interval_seconds": int(check_interval_seconds or 15),
        "service_key": service_key,
        "observed_at": observed_at,
    }

    if configured_probe == "HTTP":
        request_url, url_err = build_http_url(base_url, probe_path)
        if url_err:
            details.update({"probe": "http", "target": base_url, "error": url_err, "http_status": None, "response_time_ms": None})
            return "UNKNOWN", details

        status, http_code, error_text, response_time_ms = check_http(request_url, timeout, expected_status_codes)
        details.update(
            {
                "probe": "http",
                "request_url": request_url,
                "target": request_url,
                "http_status": http_code,
                "error": error_text,
                "response_time_ms": response_time_ms,
            }
        )
        return status, details

    if configured_probe == "TCP":
        host, port, parse_err = parse_tcp_target(base_url)
        if parse_err:
            details.update({"probe": "tcp", "target": base_url, "error": parse_err, "http_status": None, "response_time_ms": None})
            return "UNKNOWN", details

        status, error_text, response_time_ms = check_tcp(host, port, timeout)
        details.update(
            {
                "probe": "tcp",
                "target": f"{host}:{port}",
                "error": error_text,
                "response_time_ms": response_time_ms,
                "http_status": None,
            }
        )
        return status, details

    details.update({"probe": "none", "target": base_url, "error": f"unsupported probe_type: {configured_probe}", "http_status": None, "response_time_ms": None})
    return "UNKNOWN", details


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


def upsert_service_state(
    cur,
    service_id: int,
    previous_status: str,
    previous_consecutive_failures: int,
    current_status: str,
    details: dict,
    observed_at: datetime,
):
    changed = previous_status is None or previous_status != current_status

    if current_status == "DOWN":
        if previous_status == "DOWN":
            consecutive_failures = int(previous_consecutive_failures or 0) + 1
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
    default_interval_seconds = int(env("POPULATOR_INTERVAL_SECONDS", "15"))
    default_timeout_seconds = int(env("POPULATOR_TIMEOUT_SECONDS", "5"))

    while True:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    services = fetch_active_services(cur)

                    for service in services:
                        (
                            service_id,
                            service_key,
                            _display_name,
                            base_url,
                            _probe_type,
                            _probe_path,
                            _expected_status_codes,
                            _timeout_seconds,
                            check_interval_seconds,
                        ) = service

                        previous_status, last_check_at, previous_failures = get_service_state(cur, service_id)
                        interval = int(check_interval_seconds or default_interval_seconds)
                        now = datetime.now(timezone.utc)

                        if not should_probe(last_check_at, interval, now):
                            continue

                        observed_at = now
                        current_status, details = probe_service(service, default_timeout_seconds)

                        insert_service_check(cur, service_id, current_status, details, observed_at)
                        insert_availability_event(cur, service_id, current_status, details, observed_at)
                        insert_http_error_event(cur, service_id, base_url, details, interval, observed_at)
                        upsert_service_state(
                            cur,
                            service_id,
                            previous_status,
                            previous_failures,
                            current_status,
                            details,
                            observed_at,
                        )
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

        time.sleep(default_interval_seconds)


if __name__ == "__main__":
    main()
