#!/usr/bin/env bash
set -euo pipefail

DB_HOST="${DB_HOST:-postgres}"
DB_PORT="${DB_PORT:-5432}"
DB_NAME="${DB_NAME:-service_monitor}"
DB_USER="${DB_USER:-service_monitor_user}"
DB_PASSWORD="${DB_PASSWORD:-service_monitor_pass}"
POPULATOR_INTERVAL_SECONDS="${POPULATOR_INTERVAL_SECONDS:-20}"

export PGPASSWORD="${DB_PASSWORD}"

while true; do
  psql \
    -h "${DB_HOST}" \
    -p "${DB_PORT}" \
    -U "${DB_USER}" \
    -d "${DB_NAME}" \
    -v ON_ERROR_STOP=1 <<'SQL'
DO $$
DECLARE
  svc_id BIGINT;
  availability_status TEXT;
  event_roll NUMERIC;
  status_code INT;
  alert_status TEXT;
BEGIN
  SELECT id INTO svc_id
  FROM monitoring.services
  WHERE service_key = 'service-monitor-backend'
  LIMIT 1;

  IF svc_id IS NULL THEN
    RETURN;
  END IF;

  IF random() < 0.12 THEN
    availability_status := 'DOWN';
  ELSE
    availability_status := 'UP';
  END IF;

  INSERT INTO monitoring.service_availability_events
      (service_id, source, status, observed_at, details)
  VALUES
      (svc_id, 'SIMULATION', availability_status, now(), '{"origin":"shell-populator"}'::jsonb);

  event_roll := random();
  IF event_roll < 0.55 THEN
    status_code := (ARRAY[500, 502, 503, 504, 429])[1 + floor(random() * 5)];
    INSERT INTO monitoring.http_error_events
        (service_id, source, endpoint, method, status_code, error_count, window_seconds, observed_at, details)
    VALUES
        (
          svc_id,
          'SIMULATION',
          (ARRAY['/sim/error','/actuator/health','/api/orders','/api/payments'])[1 + floor(random() * 4)],
          (ARRAY['GET','POST'])[1 + floor(random() * 2)],
          status_code,
          1 + floor(random() * 8),
          60,
          now(),
          '{"origin":"shell-populator"}'::jsonb
        );
  END IF;

  IF random() < 0.45 THEN
    IF availability_status = 'DOWN' THEN
      alert_status := 'FIRING';
    ELSE
      alert_status := (ARRAY['FIRING','RESOLVED'])[1 + floor(random() * 2)];
    END IF;

    INSERT INTO monitoring.alert_events
        (service_id, alert_source, alert_name, severity, status, message, labels, starts_at, ends_at)
    VALUES
        (
          svc_id,
          'PROMETHEUS',
          CASE WHEN availability_status = 'DOWN' THEN 'BackendDown' ELSE 'High5xxRate' END,
          CASE WHEN availability_status = 'DOWN' THEN 'critical' ELSE 'warning' END,
          alert_status,
          CASE WHEN alert_status = 'FIRING' THEN 'Synthetic shell alert fired.' ELSE 'Synthetic shell alert resolved.' END,
          '{"service":"service-monitor-backend","env":"local"}'::jsonb,
          now(),
          CASE WHEN alert_status = 'RESOLVED' THEN now() ELSE NULL END
        );
  END IF;
END $$;
SQL

  sleep "${POPULATOR_INTERVAL_SECONDS}"
done
