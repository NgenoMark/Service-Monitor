# Service Monitor

Spring Boot monitoring stack with:

- Backend app (Spring Boot + Actuator + Prometheus metrics)
- Prometheus (scraping backend metrics)
- Grafana (dashboards + alerts + email notifications)
- PostgreSQL (additional Grafana datasource for SQL dashboards)

## 1. Prerequisites

- Docker Desktop running
- Java 8 (for local backend runs outside Docker)
- Ports available: `8081`, `9090`, `3000`, `5432`

## 2. Current Project Configuration

### 2.1 Backend metrics exposure (`src/main/resources/application.properties`)

```properties
spring.application.name=Service_Monitor
server.port=8081

management.endpoints.web.exposure.include=health,prometheus,metrics,info
management.endpoint.prometheus.enabled=true
management.endpoint.health.show-details=always
```

### 2.2 Prometheus scrape config (`monitoring/prometheus/prometheus.yml`)

```yaml
global:
  scrape_interval: 15s

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
- `grafana`
- `postgres`

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

Grafana:
- `http://localhost:3000`
- Login and verify Prometheus datasource `Save & test`

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

## 6. PostgreSQL Schema and Tables

Initialized by:
- `monitoring/postgres/init/001_init_schema.sql`

Created schema:
- `monitoring`

Created tables:
- `monitoring.services`
- `monitoring.service_availability_events`
- `monitoring.http_error_events`
- `monitoring.alert_events`

Important:
- Init scripts run only on first DB initialization (empty `postgres-data` volume).

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

## 8. Suggested Grafana Panels

### 8.1 Prometheus dashboard

- `up{job="service_monitor_backend"}`
- `rate(http_server_requests_seconds_count[1m])`
- `sum(rate(http_server_requests_seconds_count{status=~"5.."}[1m]))`
- `jvm_memory_used_bytes`
- `jvm_threads_live_threads`

### 8.2 PostgreSQL dashboard (starter)

Panel 1:

```sql
SELECT now() AS ts, count(*) AS services_count
FROM monitoring.services;
```

Panel 2:

```sql
SELECT observed_at AS time, count(*) AS error_events
FROM monitoring.http_error_events
WHERE observed_at >= now() - interval '24 hours'
GROUP BY observed_at
ORDER BY observed_at;
```

Panel 3:

```sql
SELECT received_at AS time, status, count(*) AS alert_count
FROM monitoring.alert_events
WHERE received_at >= now() - interval '24 hours'
GROUP BY received_at, status
ORDER BY received_at;
```

## 9. Alerting

### 9.1 Grafana alerts

Rule examples:

1. Backend down:
- Query: `up{job="service_monitor_backend"}`
- Condition: below `1` for `2m`

2. High 5xx:
- Query: `sum(rate(http_server_requests_seconds_count{job="service_monitor_backend",status=~"5.."}[1m]))`
- Condition: above threshold (tune for your traffic)

Labels example:
- `service=service-monitor-backend`
- `severity=critical` or `warning`
- `env=local`

### 9.2 Email notifications

SMTP and alert email routing are configured via environment variables loaded from `.env`.

Used by:
- Grafana SMTP settings
- Alertmanager SMTP settings

Required keys:
- `SMTP_HOST`
- `SMTP_FROM`
- `SMTP_USER`
- `SMTP_PASSWORD`
- `ALERT_EMAIL_TO`

Alertmanager config flow:
- Tracked template: `monitoring/alertmanager/alertmanager.yml.tpl`
- Generated local runtime file (ignored): `monitoring/alertmanager/alertmanager.local.yml`
- Generator script: `monitoring/alertmanager/render-config.ps1`

## 10. Common Pitfalls

1. `/actuator/prometheus` gives 404:
- Usually wrong `management.*` property keys/typos.

2. Prometheus target down:
- Check target host format is `service-monitor-backend:8081` (colon, not dot).

3. Grafana data disappears:
- Ensure `grafana-data:/var/lib/grafana` is present.
- Do not run `docker compose down -v` unless you intend to wipe data.

4. PostgreSQL schema not visible:
- Confirm DB is `service_monitor`.
- Check schema filter includes `monitoring`.

5. SQL command fails in PowerShell:
- SQL must run in Grafana query editor or `psql`, not raw PowerShell.

6. Alertmanager env vars not applied:
- Ensure `monitoring/alertmanager/alertmanager.local.yml` is regenerated after `.env` changes:
  `powershell -ExecutionPolicy Bypass -File monitoring\alertmanager\render-config.ps1`

## 11. What Is Already Done

- Spring Boot 2.7.18 + Java 1.8 alignment
- Prometheus metrics pipeline working
- Grafana dashboards from Prometheus working
- Downtime/error simulation endpoints implemented
- Grafana alerting with email working
- PostgreSQL container + schema/tables initialized
- PostgreSQL datasource connectivity validated
- Prometheus + Alertmanager dual-email alerting configured

## 12. Next Planned Additions

1. Optional provisioning-as-code for Grafana datasources/dashboards/alerts
2. Further PostgreSQL dashboard expansion
3. Ongoing synthetic/real data feed refinement

## 13. PostgreSQL Auto-Population (Step 9)

Python option is active and recommended. Shell option is preserved in the repo but disabled in `docker-compose.yml` to avoid collisions.

### 13.1 Option A: Python writer (recommended)

Service: `postgres-populator-python`  
Profile: `populate-python`

Start with:

```powershell
docker compose --profile populate-python up -d --build postgres-populator-python
```

Stop:

```powershell
docker compose stop postgres-populator-python
```

Implementation files:
- `monitoring/postgres/populator/python/Dockerfile`
- `monitoring/postgres/populator/python/requirements.txt`
- `monitoring/postgres/populator/python/populate.py`

### 13.2 Option B: Shell + psql writer

Status: disabled in Compose (commented out intentionally).  
Implementation file kept for reference:
- `monitoring/postgres/populator/shell/populate.sh`

### 13.3 Behavior

Both writers periodically insert synthetic data into:

- `monitoring.service_availability_events`
- `monitoring.http_error_events`
- `monitoring.alert_events`

Default write interval:
- `20s` (override via `POPULATOR_INTERVAL_SECONDS` env var).

### 13.4 Important

Only the Python populator should run. Shell populator is intentionally not callable from Compose to prevent duplicate inserts.
