# Service Monitor

Spring Boot monitoring stack with:

- Backend app (Spring Boot + Actuator + Prometheus metrics)
- Prometheus (scrapes backend metrics and evaluates rules)
- Alertmanager (native Prometheus email alerts)
- Grafana (dashboards + Grafana-managed alerts + email)
- PostgreSQL (additional Grafana datasource for SQL dashboards)
- Python populator (writes live probe results into PostgreSQL)

## 1. Prerequisites

- Docker Desktop running
- Java 8 (for local backend runs outside Docker)
- Ports available: `8081`, `9090`, `9093`, `3000`, `5432`

## 2. Current Project Configuration

### 2.1 Backend metrics exposure (`src/main/resources/application.properties`)

```properties
spring.application.name=Service_Monitor
server.port=8081

management.endpoints.web.exposure.include=health,prometheus,metrics,info
management.endpoint.prometheus.enabled=true
management.endpoint.health.show-details=always
```

### 2.2 Prometheus scrape + alerting (`monitoring/prometheus/prometheus.yml`)

```yaml
global:
  scrape_interval: 15s

rule_files:
  - /etc/prometheus/alert.rules.yml

alerting:
  alertmanagers:
    - static_configs:
        - targets: ['alertmanager:9093']

scrape_configs:
  - job_name: 'service_monitor_backend'
    metrics_path: /actuator/prometheus
    static_configs:
      - targets: ['service-monitor-backend:8081']
```

### 2.3 Docker services (`docker-compose.yml`)

Services:
- `service-monitor-backend`
- `prometheus`
- `alertmanager`
- `grafana`
- `postgres`
- `postgres-populator-python`

Persisted volumes:
- `grafana-data` (Grafana dashboards/datasources)
- `postgres-data` (PostgreSQL data)

PostgreSQL init scripts:
- Mounted from `monitoring/postgres/init` to `/docker-entrypoint-initdb.d`

## 3. Start / Stop Commands

Before first run:

```powershell
Copy-Item .env.example .env
```

Then set real SMTP and DB values in `.env`.

Generate Alertmanager runtime config from template:

```powershell
powershell -ExecutionPolicy Bypass -File monitoring\alertmanager\render-config.ps1
```

Start all:

```powershell
docker compose up -d --build
```

Stop all (keep data):

```powershell
docker compose down
```

Stop all and delete all volumes (destructive):

```powershell
docker compose down -v
```

Check running containers:

```powershell
docker compose ps
```

## 4. Verification Checklist

Backend:
- `http://localhost:8081/actuator/health`
- `http://localhost:8081/actuator/prometheus`

Prometheus:
- `http://localhost:9090/targets`
- job `service_monitor_backend` should be `UP`

Alertmanager:
- `http://localhost:9093`

Grafana:
- `http://localhost:3000`
- verify Prometheus datasource `Save & test`

PostgreSQL quick check:

```powershell
docker compose exec -T postgres psql -U service_monitor_user -d service_monitor -c "SELECT now() AS ts, count(*) AS services_count FROM monitoring.services;"
```

## 5. Grafana Datasource Setup

### 5.1 Prometheus datasource

- URL: `http://prometheus:9090`

### 5.2 PostgreSQL datasource

Use these values in Grafana (container-to-container):

- Host: `postgres:5432`
- Database: `service_monitor`
- User: `service_monitor_user`
- Password: `service_monitor_pass`
- SSL mode: `disable`

Note:
- `localhost` is wrong inside Grafana container for PostgreSQL datasource.

### 5.3 Local IDE / pgAdmin connection

For host machine tools (IntelliJ, pgAdmin), use the mapped host port from `docker-compose.yml`.

- Host: `localhost` (or `127.0.0.1`)
- Port: `55432` (if your compose mapping is `55432:5432`)
- Database: `service_monitor`
- User: `service_monitor_user`
- Password: `service_monitor_pass`

Important:
- `postgres:5432` is for container-to-container traffic only.
- `localhost:55432` is for host machine tools only.

## 6. PostgreSQL Schema and Tables

Initialized by:
- `monitoring/postgres/init/001_init_schema.sql`
- `monitoring/postgres/init/002_monitoring_model.sql`
- `monitoring/postgres/init/003_service_probe_config.sql`
- `monitoring/postgres/init/004_populator_source_constraints.sql`

Created schema:
- `monitoring`

Created tables:
- `monitoring.services`
- `monitoring.service_availability_events`
- `monitoring.http_error_events`
- `monitoring.alert_events`
- `monitoring.service_checks`
- `monitoring.service_state`
- `monitoring.service_incidents`
- `monitoring.metric_samples`

Important:
- Init scripts run only on first DB initialization (empty `postgres-data` volume).
- `001_init_schema.sql` now seeds all core services by default on fresh volume creation.

If your DB volume already exists, apply step-1 model migration manually:

```powershell
docker compose exec -T postgres psql -U service_monitor_user -d service_monitor -f /docker-entrypoint-initdb.d/002_monitoring_model.sql
```

Apply step-2 probe configuration migration manually:

```powershell
docker compose exec -T postgres psql -U service_monitor_user -d service_monitor -f /docker-entrypoint-initdb.d/003_service_probe_config.sql
```

Apply step-3 deterministic writer hardening migration manually:

```powershell
docker compose exec -T postgres psql -U service_monitor_user -d service_monitor -f /docker-entrypoint-initdb.d/004_populator_source_constraints.sql
```

## 7. Simulation Endpoints

Implemented in `src/main/java/com/example/service_monitor/SimulationController.java`:

- `GET /sim/error` -> always returns `500`
- `GET /sim/flaky` -> randomly returns `200` or `500`

Generate error load:

```powershell
1..300 | % { Invoke-WebRequest "http://localhost:8081/sim/error" -UseBasicParsing -ErrorAction SilentlyContinue | Out-Null; Start-Sleep -Milliseconds 150 }
```

Downtime simulation:

```powershell
docker compose stop service-monitor-backend
docker compose start service-monitor-backend
```

## 8. Prometheus Dashboard (Recommended Panels)

### 8.1 Backend Status (Stat)

```promql
up{job="service_monitor_backend",instance="service-monitor-backend:8081"}
```

Settings:
- Calculation: `Last (not null)`
- Text mode: `Value and name`
- Value mappings: `0 -> DOWN`, `1 -> UP`
- Thresholds: `0 red`, `1 green`

### 8.2 Request Rate (Time series)

```promql
sum(rate(http_server_requests_seconds_count{job="service_monitor_backend"}[1m]))
```

Settings:
- Unit: `reqps`
- Min: `Auto` (recommended for visibility of small changes)

### 8.3 5xx Error Rate (Time series)

```promql
sum(rate(http_server_requests_seconds_count{job="service_monitor_backend",status=~"5.."}[1m]))
```

Settings:
- Unit: `reqps`
- Min: `0` (important zero baseline)
- Suggested thresholds: yellow `0.2`, red `1`

### 8.4 JVM Heap Used (Time series)

```promql
sum(jvm_memory_used_bytes{job="service_monitor_backend",area="heap"})
```

Settings:
- Unit: `bytes (IEC)`
- Min: `Auto`

### 8.5 JVM Non-Heap Used (Time series)

```promql
sum(jvm_memory_used_bytes{job="service_monitor_backend",area="nonheap"})
```

Settings:
- Unit: `bytes (IEC)`
- Min: `Auto`

### 8.6 Live JVM Threads (Time series)

```promql
jvm_threads_live_threads{job="service_monitor_backend"}
```

Settings:
- Unit: `none`
- Min: `0`

### 8.7 Current RPS (Stat)

```promql
sum(rate(http_server_requests_seconds_count{job="service_monitor_backend"}[1m]))
```

Settings:
- Calculation: `Last (not null)`
- Text mode: `Value and name`

## 9. PostgreSQL Dashboard (Starter Queries)

Service count:

```sql
SELECT now() AS ts, count(*) AS services_count
FROM monitoring.services;
```

Recent availability events:

```sql
SELECT s.service_key, e.status, e.observed_at
FROM monitoring.service_availability_events e
JOIN monitoring.services s ON s.id = e.service_id
ORDER BY e.id DESC
LIMIT 50;
```

Recent HTTP errors:

```sql
SELECT s.service_key, h.status_code, h.endpoint, h.observed_at
FROM monitoring.http_error_events h
JOIN monitoring.services s ON s.id = h.service_id
ORDER BY h.id DESC
LIMIT 50;
```

Recent alerts:

```sql
SELECT s.service_key, a.alert_name, a.status, a.severity, a.received_at
FROM monitoring.alert_events a
LEFT JOIN monitoring.services s ON s.id = a.service_id
ORDER BY a.id DESC
LIMIT 50;
```

## 9.1 Service Registry (monitoring.services)

Current expected service entries:

- `service-monitor-backend` -> `http://service-monitor-backend:8081`
- `postgres-db` -> `postgres:5432`
- `prometheus` -> `http://prometheus:9090/-/healthy`
- `grafana` -> `http://grafana:3000/api/health`
- `alertmanager` -> `http://alertmanager:9093/-/healthy`
- `service-monitor-backend-actuator` -> `http://service-monitor-backend:8081/actuator/health`

Per-service probe config fields (in `monitoring.services`):
- `probe_type` (`HTTP` or `TCP`)
- `probe_path` (HTTP only, optional)
- `expected_status_codes` (example: `200,204,301-304`)
- `timeout_seconds`
- `check_interval_seconds`

Reseed (idempotent):

```sql
INSERT INTO monitoring.services
    (service_key, display_name, base_url, is_active, probe_type, probe_path, expected_status_codes, timeout_seconds, check_interval_seconds)
VALUES
  ('service-monitor-backend', 'Service Monitor Backend', 'http://service-monitor-backend:8081', true, 'HTTP', '/actuator/health', '200-399', 5, 15),
  ('postgres-db', 'PostgreSQL Database', 'postgres:5432', true, 'TCP', NULL, '200-399', 3, 15),
  ('prometheus', 'Prometheus', 'http://prometheus:9090/-/healthy', true, 'HTTP', NULL, '200-399', 5, 15),
  ('grafana', 'Grafana', 'http://grafana:3000/api/health', true, 'HTTP', NULL, '200-399', 5, 15),
  ('alertmanager', 'Alertmanager', 'http://alertmanager:9093/-/healthy', true, 'HTTP', NULL, '200-399', 5, 15),
  ('service-monitor-backend-actuator', 'Service Monitor Backend Actuator', 'http://service-monitor-backend:8081/actuator/health', true, 'HTTP', NULL, '200-399', 5, 15)
ON CONFLICT (service_key) DO UPDATE
SET
  display_name = EXCLUDED.display_name,
  base_url = EXCLUDED.base_url,
  is_active = EXCLUDED.is_active,
  probe_type = EXCLUDED.probe_type,
  probe_path = EXCLUDED.probe_path,
  expected_status_codes = EXCLUDED.expected_status_codes,
  timeout_seconds = EXCLUDED.timeout_seconds,
  check_interval_seconds = EXCLUDED.check_interval_seconds;
```

Run from PowerShell via Docker:

```powershell
docker compose exec -T postgres psql -U service_monitor_user -d service_monitor -c "INSERT INTO monitoring.services (service_key, display_name, base_url, is_active, probe_type, probe_path, expected_status_codes, timeout_seconds, check_interval_seconds) VALUES ('service-monitor-backend', 'Service Monitor Backend', 'http://service-monitor-backend:8081', true, 'HTTP', '/actuator/health', '200-399', 5, 15), ('postgres-db', 'PostgreSQL Database', 'postgres:5432', true, 'TCP', NULL, '200-399', 3, 15), ('prometheus', 'Prometheus', 'http://prometheus:9090/-/healthy', true, 'HTTP', NULL, '200-399', 5, 15), ('grafana', 'Grafana', 'http://grafana:3000/api/health', true, 'HTTP', NULL, '200-399', 5, 15), ('alertmanager', 'Alertmanager', 'http://alertmanager:9093/-/healthy', true, 'HTTP', NULL, '200-399', 5, 15), ('service-monitor-backend-actuator', 'Service Monitor Backend Actuator', 'http://service-monitor-backend:8081/actuator/health', true, 'HTTP', NULL, '200-399', 5, 15) ON CONFLICT (service_key) DO UPDATE SET display_name = EXCLUDED.display_name, base_url = EXCLUDED.base_url, is_active = EXCLUDED.is_active, probe_type = EXCLUDED.probe_type, probe_path = EXCLUDED.probe_path, expected_status_codes = EXCLUDED.expected_status_codes, timeout_seconds = EXCLUDED.timeout_seconds, check_interval_seconds = EXCLUDED.check_interval_seconds;"
```
Quick verify:

```powershell
docker compose exec -T postgres psql -U service_monitor_user -d service_monitor -c "SELECT id, service_key, base_url, probe_type, probe_path, expected_status_codes, timeout_seconds, check_interval_seconds, is_active FROM monitoring.services ORDER BY id;"
```

### 9.2 After Volume Reset

If you run:

```powershell
docker compose down
docker volume rm service_monitor_postgres-data
docker compose up -d
```

Then PostgreSQL recreates everything automatically:
- schema/tables from init scripts `001` to `004`
- default six service rows in `monitoring.services` (from `001`)

What is not auto-restored by PostgreSQL reset:
- Grafana dashboards/datasources/alert rules if `grafana-data` is also removed
- any manual UI-only configuration not stored as code
## 10. Alerting

### 10.1 Grafana alerts

Examples:
- Backend down: `up{job="service_monitor_backend"} < 1` for `2m`
- High 5xx: `sum(rate(http_server_requests_seconds_count{job="service_monitor_backend",status=~"5.."}[1m]))` above threshold

### 10.2 Prometheus + Alertmanager alerts

Rule file:
- `monitoring/prometheus/alert.rules.yml`

Alertmanager config flow:
- Tracked template: `monitoring/alertmanager/alertmanager.yml.tpl`
- Generated runtime file (ignored): `monitoring/alertmanager/alertmanager.local.yml`
- Generator script: `monitoring/alertmanager/render-config.ps1`
- Email template: `monitoring/alertmanager/templates/email.tmpl`

Important:
- `email.tmpl` must define both:
  - `service_monitor.subject`
  - `service_monitor.text`

Otherwise emails fail with template errors.

### 10.3 Alertmanager webhook ingestion (Step 4)

Spring Boot endpoint:
- `POST /api/alerts/alertmanager`

Alertmanager is configured to forward alerts to the backend via webhook, and the backend persists alerts into `monitoring.alert_events` with `alert_source='PROMETHEUS'`.

After changing `.env`, regenerate Alertmanager config:

```powershell
powershell -ExecutionPolicy Bypass -File monitoring\alertmanager\render-config.ps1
docker compose restart alertmanager
```

## 11. Python Populator (Active Probing)

Files:
- `monitoring/postgres/populator/python/Dockerfile`
- `monitoring/postgres/populator/python/requirements.txt`
- `monitoring/postgres/populator/python/populate.py`

Current behavior:
- Reads all active services from `monitoring.services`
- Uses per-service probe settings from DB (`probe_type`, `probe_path`, `expected_status_codes`, `timeout_seconds`, `check_interval_seconds`)
- Writes real events (not random):
  - `monitoring.service_checks` (raw probe checks)
  - `monitoring.service_state` (latest per-service state)
  - `monitoring.service_incidents` (open/close lifecycle)
  - `monitoring.service_availability_events` (compatibility history)
  - `monitoring.http_error_events` (4xx/5xx)
  - `monitoring.alert_events` (status transition alerts)
- Writer-tagged records use `source='POPULATOR'` / `alert_source='POPULATOR'` for clear provenance

Useful env vars:
- `PYTHON_POPULATOR_INTERVAL_SECONDS` (already in `.env.example`)
- `POPULATOR_TIMEOUT_SECONDS` (optional, default `5`)

Shell populator status:
- `monitoring/postgres/populator/shell/populate.sh` kept for reference
- shell service remains disabled/commented in compose to avoid duplicate inserts

## 12. Common Pitfalls

1. `/actuator/prometheus` gives 404:
- wrong `management.*` property keys/typos.

2. Prometheus target down:
- use `service-monitor-backend:8081` (colon, not dot).

3. Grafana data disappears:
- ensure `grafana-data:/var/lib/grafana` exists.
- avoid `docker compose down -v` unless wiping intentionally.

4. PostgreSQL schema not visible:
- check DB is `service_monitor`.
- schema filter should include `monitoring`.

5. SQL in PowerShell fails:
- run SQL in Grafana query editor or via `psql`.

6. Alertmanager env vars not applied:
- regenerate config after `.env` edits:
  `powershell -ExecutionPolicy Bypass -File monitoring\alertmanager\render-config.ps1`

7. Alertmanager emails missing:
- check logs for template errors:
  `docker compose logs --tail=100 alertmanager`

## 13. What Is Already Done

- Spring Boot 2.7.18 + Java 1.8 alignment
- Prometheus metrics pipeline working
- Grafana dashboards from Prometheus working
- Downtime/error simulation endpoints implemented
- Grafana alerting with email working
- Prometheus + Alertmanager dual alerting path configured
- PostgreSQL container + schema/tables initialized
- PostgreSQL datasource connectivity validated
- Python populator converted to active real probing for all active services

## 14. Optional Next Improvements

1. Provision Grafana datasources/dashboards/alerts as code
2. Add per-service probe path metadata in DB (for non-root health paths)
3. Add dedup/rate-limiting strategy for DB alert event inserts
4. Move sensitive runtime secret handling to a dedicated secret manager



