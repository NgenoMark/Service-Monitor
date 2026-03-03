import os
import random
import time
from datetime import datetime, timezone

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


def get_service_id(cur):
    cur.execute(
        """
        SELECT id
        FROM monitoring.services
        WHERE service_key = 'service-monitor-backend'
        LIMIT 1
        """
    )
    row = cur.fetchone()
    return row[0] if row else None


def insert_availability_event(cur, service_id: int):
    status = "DOWN" if random.random() < 0.12 else "UP"
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
            '{"origin":"python-populator"}',
        ),
    )
    return status


def maybe_insert_http_error(cur, service_id: int):
    if random.random() > 0.55:
        return

    status_code = random.choice([500, 502, 503, 504, 429])
    error_count = random.randint(1, 8)
    endpoint = random.choice(["/sim/error", "/actuator/health", "/api/orders", "/api/payments"])
    method = random.choice(["GET", "POST"])

    cur.execute(
        """
        INSERT INTO monitoring.http_error_events
            (service_id, source, endpoint, method, status_code, error_count, window_seconds, observed_at, details)
        VALUES
            (%s, 'SIMULATION', %s, %s, %s, %s, 60, %s, %s::jsonb)
        """,
        (
            service_id,
            endpoint,
            method,
            status_code,
            error_count,
            datetime.now(timezone.utc),
            '{"origin":"python-populator"}',
        ),
    )


def maybe_insert_alert(cur, service_id: int, last_status: str):
    if random.random() > 0.45:
        return

    if last_status == "DOWN":
        alert_name = "BackendDown"
        severity = "critical"
    else:
        alert_name = "High5xxRate"
        severity = "warning"

    status = random.choice(["FIRING", "RESOLVED"])
    message = (
        "Synthetic alert generated for dashboard population."
        if status == "FIRING"
        else "Synthetic alert resolved."
    )

    cur.execute(
        """
        INSERT INTO monitoring.alert_events
            (service_id, alert_source, alert_name, severity, status, message, labels, starts_at, ends_at)
        VALUES
            (%s, 'PROMETHEUS', %s, %s, %s, %s, %s::jsonb, %s, %s)
        """,
        (
            service_id,
            alert_name,
            severity,
            status,
            message,
            '{"service":"service-monitor-backend","env":"local"}',
            datetime.now(timezone.utc),
            datetime.now(timezone.utc) if status == "RESOLVED" else None,
        ),
    )


def main():
    interval = int(env("POPULATOR_INTERVAL_SECONDS", "15"))
    while True:
        try:
            with get_connection() as conn:
                with conn.cursor() as cur:
                    service_id = get_service_id(cur)
                    if service_id is None:
                        time.sleep(interval)
                        continue
                    last_status = insert_availability_event(cur, service_id)
                    maybe_insert_http_error(cur, service_id)
                    maybe_insert_alert(cur, service_id, last_status)
                conn.commit()
        except Exception as exc:
            # Keep writer alive; print root cause for troubleshooting.
            print(f"[populator] write cycle failed: {exc}", flush=True)

        time.sleep(interval)


if __name__ == "__main__":
    main()
