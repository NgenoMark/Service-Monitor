-- Step 1 monitoring model extension: raw checks, current state, incidents, sampled metrics

CREATE TABLE IF NOT EXISTS monitoring.service_checks (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT NOT NULL REFERENCES monitoring.services(id),
    probe_type VARCHAR(20) NOT NULL,
    check_target VARCHAR(255),
    status VARCHAR(20) NOT NULL,
    http_status_code INTEGER,
    response_time_ms INTEGER,
    error_message TEXT,
    observed_at TIMESTAMPTZ NOT NULL,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_service_checks_probe_type
        CHECK (probe_type IN ('HTTP', 'TCP', 'NONE')),
    CONSTRAINT chk_service_checks_status
        CHECK (status IN ('UP', 'DOWN', 'DEGRADED', 'UNKNOWN'))
);

CREATE INDEX IF NOT EXISTS idx_service_checks_service_time
    ON monitoring.service_checks (service_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_service_checks_status_time
    ON monitoring.service_checks (status, observed_at DESC);

CREATE TABLE IF NOT EXISTS monitoring.service_state (
    service_id BIGINT PRIMARY KEY REFERENCES monitoring.services(id),
    current_status VARCHAR(20) NOT NULL,
    previous_status VARCHAR(20),
    last_check_at TIMESTAMPTZ NOT NULL,
    last_change_at TIMESTAMPTZ,
    consecutive_failures INTEGER NOT NULL DEFAULT 0,
    last_http_status_code INTEGER,
    last_error_message TEXT,
    details JSONB,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_service_state_current_status
        CHECK (current_status IN ('UP', 'DOWN', 'DEGRADED', 'UNKNOWN')),
    CONSTRAINT chk_service_state_previous_status
        CHECK (previous_status IS NULL OR previous_status IN ('UP', 'DOWN', 'DEGRADED', 'UNKNOWN'))
);

CREATE INDEX IF NOT EXISTS idx_service_state_status
    ON monitoring.service_state (current_status);

CREATE TABLE IF NOT EXISTS monitoring.service_incidents (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT NOT NULL REFERENCES monitoring.services(id),
    severity VARCHAR(20) NOT NULL,
    opened_at TIMESTAMPTZ NOT NULL,
    resolved_at TIMESTAMPTZ,
    is_open BOOLEAN NOT NULL DEFAULT TRUE,
    open_reason TEXT,
    close_reason TEXT,
    open_details JSONB,
    close_details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_service_incidents_severity
        CHECK (severity IN ('critical', 'warning', 'info'))
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_service_incidents_one_open_per_service
    ON monitoring.service_incidents (service_id)
    WHERE is_open = TRUE;

CREATE INDEX IF NOT EXISTS idx_service_incidents_service_opened
    ON monitoring.service_incidents (service_id, opened_at DESC);

CREATE INDEX IF NOT EXISTS idx_service_incidents_is_open
    ON monitoring.service_incidents (is_open);

CREATE TABLE IF NOT EXISTS monitoring.metric_samples (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT REFERENCES monitoring.services(id),
    metric_name VARCHAR(150) NOT NULL,
    metric_value DOUBLE PRECISION NOT NULL,
    labels JSONB,
    sampled_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_metric_samples_name_time
    ON monitoring.metric_samples (metric_name, sampled_at DESC);

CREATE INDEX IF NOT EXISTS idx_metric_samples_service_time
    ON monitoring.metric_samples (service_id, sampled_at DESC);

-- Seed service_state for existing datasets if availability events already exist.
INSERT INTO monitoring.service_state (
    service_id,
    current_status,
    previous_status,
    last_check_at,
    last_change_at,
    consecutive_failures,
    details,
    updated_at
)
SELECT
    latest.service_id,
    latest.status,
    NULL,
    latest.observed_at,
    latest.observed_at,
    CASE WHEN latest.status = 'DOWN' THEN 1 ELSE 0 END,
    latest.details,
    NOW()
FROM (
    SELECT DISTINCT ON (e.service_id)
        e.service_id,
        e.status,
        e.observed_at,
        e.details
    FROM monitoring.service_availability_events e
    ORDER BY e.service_id, e.observed_at DESC, e.id DESC
) latest
ON CONFLICT (service_id) DO NOTHING;
