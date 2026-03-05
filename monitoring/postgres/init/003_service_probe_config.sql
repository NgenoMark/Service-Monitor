-- Step 2: make probing data-driven per service.

ALTER TABLE monitoring.services
    ADD COLUMN IF NOT EXISTS probe_type VARCHAR(10) NOT NULL DEFAULT 'HTTP',
    ADD COLUMN IF NOT EXISTS probe_path VARCHAR(255),
    ADD COLUMN IF NOT EXISTS expected_status_codes VARCHAR(255) NOT NULL DEFAULT '200-399',
    ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER NOT NULL DEFAULT 5,
    ADD COLUMN IF NOT EXISTS check_interval_seconds INTEGER NOT NULL DEFAULT 15;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_services_probe_type'
          AND conrelid = 'monitoring.services'::regclass
    ) THEN
        ALTER TABLE monitoring.services
            ADD CONSTRAINT chk_services_probe_type
                CHECK (probe_type IN ('HTTP', 'TCP'));
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_services_timeout_seconds'
          AND conrelid = 'monitoring.services'::regclass
    ) THEN
        ALTER TABLE monitoring.services
            ADD CONSTRAINT chk_services_timeout_seconds CHECK (timeout_seconds > 0);
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'chk_services_check_interval_seconds'
          AND conrelid = 'monitoring.services'::regclass
    ) THEN
        ALTER TABLE monitoring.services
            ADD CONSTRAINT chk_services_check_interval_seconds CHECK (check_interval_seconds > 0);
    END IF;
END $$;

-- Auto-detect obvious TCP endpoints (host:port without URL path).
UPDATE monitoring.services
SET probe_type = 'TCP'
WHERE base_url IS NOT NULL
  AND base_url ~ '^[a-zA-Z0-9._-]+:[0-9]+$';

-- Ensure known HTTP services remain HTTP.
UPDATE monitoring.services
SET probe_type = 'HTTP'
WHERE service_key IN ('service-monitor-backend', 'service-monitor-backend-actuator', 'prometheus', 'grafana', 'alertmanager');

-- Prefer health endpoint for backend root service.
UPDATE monitoring.services
SET probe_path = '/actuator/health'
WHERE service_key = 'service-monitor-backend'
  AND (probe_path IS NULL OR probe_path = '');
