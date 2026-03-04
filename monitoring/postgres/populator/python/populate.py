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
        SELECT status
        FROM monitoring.service_availability_events
        WHERE service_id = %s
        ORDER BY observed_at DESC, id DESC
        LIMIT 1
        """,
        (service_id,),
    )
    row = cur.fetchone()
    return row[0] if row else None


def check_http(url: str, timeout_seconds: int):
    req = Request(url, method="GET")
    req.add_header("User-Agent", "service-monitor-populator/1.0")

    try:
        with urlopen(req, timeout=timeout_seconds) as response:
            code = int(response.getcode())
            if 200 <= code < 400:
                status = "UP"
            elif code >= 500:
                status = "DOWN"
            else:
                status = "DEGRADED"
            return status, code, None
    except HTTPError as http_err:
        code = int(http_err.code)
        if code >= 500:
            status = "DOWN"
        else:
            status = "DEGRADED"
        return status, code, str(http_err)
    except (URLError, TimeoutError, OSError) as conn_err:
        return "DOWN", None, str(conn_err)


def check_tcp(host: str, port: int, timeout_seconds: int):
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return "UP", None
    except OSError as exc:
        return "DOWN", str(exc)


def probe_service(base_url: str, timeout_seconds: int):
    observed_at = datetime.now(timezone.utc).isoformat()

    if not base_url:
        return "UNKNOWN", {
            "probe": "none",
            "error": "base_url is empty",
            "observed_at": observed_at,
        }

    raw = base_url.strip()

    if raw.startswith("http://") or raw.startswith("https://"):
        status, http_code, error_text = check_http(raw, timeout_seconds)
        return status, {
            "probe": "http",
            "request_url": raw,
            "http_status": http_code,
            "error": error_text,
            "observed_at": observed_at,
        }

    # Accept host:port targets such as postgres:5432 and use TCP probing.
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
            }

        status, error_text = check_tcp(host, port, timeout_seconds)
        return status, {
            "probe": "tcp",
            "target": raw,
            "error": error_text,
            "observed_at": observed_at,
        }

    # Fallback: treat anything else as HTTP target.
    fallback_url = f"http://{raw}"
    status, http_code, error_text = check_http(fallback_url, timeout_seconds)
    return status, {
        "probe": "http",
        "request_url": fallback_url,
        "http_status": http_code,
        "error": error_text,
        "observed_at": observed_at,
    }


def insert_availability_event(cur, service_id: int, status: str, details: dict):
    cur.execute(
        """
        INSERT INTO monitoring.service_availability_events
            (service_id, source, status, observed_at, details)
        VALUES
            (%s, 'MANUAL', %s, %s, %s::jsonb)
        """,
        (
            service_id,
            status,
            datetime.now(timezone.utc),
            json.dumps(details),
        ),
    )


def insert_http_error_event(cur, service_id: int, base_url: str, details: dict, interval_seconds: int):
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
        (
            service_id,
            endpoint,
            int(http_status),
            interval_seconds,
            datetime.now(timezone.utc),
            json.dumps(details),
        ),
    )


def insert_alert_transition(cur, service_id: int, service_key: str, previous_status: str, current_status: str, details: dict):
    if previous_status == current_status:
        return

    starts_at = datetime.now(timezone.utc)
    ends_at = None

    if current_status == "DOWN":
        alert_status = "FIRING"
        severity = "critical"
        message = f"{service_key} became unavailable (status transition: {previous_status} -> {current_status})."
    elif previous_status == "DOWN" and current_status in {"UP", "DEGRADED"}:
        alert_status = "RESOLVED"
        severity = "critical"
        message = f"{service_key} recovered (status transition: {previous_status} -> {current_status})."
        ends_at = starts_at
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
        (
            service_id,
            severity,
            alert_status,
            message,
            json.dumps(labels),
            starts_at,
            ends_at,
        ),
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
                        previous_status = get_last_status(cur, service_id)
                        current_status, details = probe_service(base_url, timeout_seconds)

                        insert_availability_event(cur, service_id, current_status, details)
                        insert_http_error_event(cur, service_id, base_url, details, interval_seconds)
                        insert_alert_transition(
                            cur,
                            service_id,
                            service_key,
                            previous_status,
                            current_status,
                            details,
                        )
                conn.commit()
        except Exception as exc:
            # Keep writer alive; print root cause for troubleshooting.
            print(f"[populator] write cycle failed: {exc}", flush=True)

        time.sleep(interval_seconds)


if __name__ == "__main__":
    main()
