CREATE SCHEMA IF NOT EXISTS monitoring;

CREATE TABLE IF NOT EXISTS monitoring.services (
    id BIGSERIAL PRIMARY KEY,
    service_key VARCHAR(100) NOT NULL UNIQUE,
    display_name VARCHAR(150) NOT NULL,
    base_url VARCHAR(255),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS monitoring.service_availability_events (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT NOT NULL REFERENCES monitoring.services(id),
    source VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_service_availability_source
        CHECK (source IN ('PROMETHEUS', 'GRAFANA', 'MANUAL')),
    CONSTRAINT chk_service_availability_status
        CHECK (status IN ('UP', 'DOWN', 'DEGRADED', 'UNKNOWN'))
);

CREATE TABLE IF NOT EXISTS monitoring.http_error_events (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT NOT NULL REFERENCES monitoring.services(id),
    source VARCHAR(20) NOT NULL,
    endpoint VARCHAR(255) NOT NULL,
    method VARCHAR(10),
    status_code INTEGER NOT NULL,
    error_count INTEGER NOT NULL DEFAULT 1,
    window_seconds INTEGER,
    observed_at TIMESTAMPTZ NOT NULL,
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_http_error_source
        CHECK (source IN ('PROMETHEUS', 'GRAFANA', 'MANUAL', 'SIMULATION')),
    CONSTRAINT chk_http_error_status_code CHECK (status_code >= 400 AND status_code <= 599)
);

CREATE TABLE IF NOT EXISTS monitoring.alert_events (
    id BIGSERIAL PRIMARY KEY,
    service_id BIGINT REFERENCES monitoring.services(id),
    alert_source VARCHAR(20) NOT NULL,
    alert_name VARCHAR(200) NOT NULL,
    severity VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    message TEXT,
    labels JSONB,
    starts_at TIMESTAMPTZ,
    ends_at TIMESTAMPTZ,
    received_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_alert_source CHECK (alert_source IN ('GRAFANA', 'PROMETHEUS')),
    CONSTRAINT chk_alert_status CHECK (status IN ('FIRING', 'RESOLVED'))
);

CREATE INDEX IF NOT EXISTS idx_availability_events_service_time
    ON monitoring.service_availability_events (service_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_http_error_events_service_time
    ON monitoring.http_error_events (service_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_alert_events_service_time
    ON monitoring.alert_events (service_id, received_at DESC);

CREATE INDEX IF NOT EXISTS idx_alert_events_status_time
    ON monitoring.alert_events (status, received_at DESC);

INSERT INTO monitoring.services (service_key, display_name, base_url, is_active)
VALUES
    ('service-monitor-backend', 'Service Monitor Backend', 'http://service-monitor-backend:8081', TRUE),
    ('postgres-db', 'PostgreSQL Database', 'postgres:5432', TRUE),
    ('prometheus', 'Prometheus', 'http://prometheus:9090/-/healthy', TRUE),
    ('grafana', 'Grafana', 'http://grafana:3000/api/health', TRUE),
    ('alertmanager', 'Alertmanager', 'http://alertmanager:9093/-/healthy', TRUE),
    ('service-monitor-backend-actuator', 'Service Monitor Backend Actuator', 'http://service-monitor-backend:8081/actuator/health', TRUE)
ON CONFLICT (service_key) DO NOTHING;
