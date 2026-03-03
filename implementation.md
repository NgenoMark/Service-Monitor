# Service Monitor Implementation Plan

## 1. Project Goal

Build a complete observability pipeline for a Spring Boot backend:

1. Backend exposes metrics via Actuator + Micrometer Prometheus registry.
2. Prometheus scrapes those metrics on a schedule.
3. Grafana visualizes metrics in dashboards.
4. Downtime/error scenarios are simulated and observed.
5. Grafana sends email alerts when service availability degrades.

The implementation must be done in sequence so each layer is validated before moving to the next.

## 1.1 Current Status

Completed:

1. Backend metrics setup (Actuator + Prometheus registry + endpoint exposure).
2. Full runtime verification:
   - `docker compose up --build`
   - Backend health endpoint working
   - Prometheus target is `UP`
   - Grafana datasource `Save & test` successful
3. Initial Grafana dashboard/panels created and saved.

Remaining:

1. Downtime and error simulation validation.
2. Grafana email alerting (SMTP + rules + test delivery).

## 2. Architecture and Responsibilities

- Spring Boot app (inside IDE / backend codebase)
  - Produces operational metrics.
  - Exposes `/actuator/health` and `/actuator/prometheus`.
- Prometheus (outside IDE, separate runtime)
  - Pulls metrics from backend endpoint.
  - Stores time-series data.
- Grafana (outside IDE, separate runtime)
  - Reads from Prometheus datasource.
  - Displays dashboards and evaluates alerts.

## 3. Environment Prerequisites

Complete these before implementation:

1. Java 8 SDK installed and selected for project runtime.
2. Maven wrapper works (`.\mvnw.cmd -v`).
3. Docker Desktop installed and running (recommended path for Prometheus/Grafana).
4. Ports available:
   - Backend: `8081`
   - Prometheus: `9090`
   - Grafana: `3000`

If Docker is not available, Prometheus and Grafana can be installed as native binaries, but Docker is the fastest/cleanest setup.

## 4. Phase 1: Backend Metrics Foundation (IDE / code changes)

### 4.1 Ensure required dependencies are present in `pom.xml`

Required dependencies:

- `spring-boot-starter-actuator`
- `micrometer-registry-prometheus`
- `spring-boot-starter-web` (keeps app running as a web service)

Capability enabled:
- App can publish internal metrics and expose HTTP actuator endpoints.

### 4.2 Configure actuator exposure in `src/main/resources/application.properties`

Use:

```properties
spring.application.name=Service_Monitor
server.port=8081

management.endpoints.web.exposure.include=health,info,metrics,prometheus
management.endpoint.prometheus.enabled=true
management.endpoint.health.show-details=always
```

Capability enabled:
- Health and Prometheus metrics endpoints become externally reachable.

### 4.3 Run and verify backend locally (from IDE or terminal)

Run:

```powershell
.\mvnw.cmd spring-boot:run
```

Verify:

- `http://localhost:8081/actuator/health` returns `UP`.
- `http://localhost:8081/actuator/prometheus` returns text metrics.

Capability enabled:
- Backend is now a valid Prometheus scrape target.

---

## 5. Phase 2: Prometheus Setup (outside IDE)

Prometheus is infrastructure. It does not run inside IntelliJ project execution.

### 5.1 Create Prometheus config file

Create `monitoring/prometheus/prometheus.yml`:

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "service_monitor_backend"
    metrics_path: /actuator/prometheus
    static_configs:
      - targets: ["service-monitor-backend:8081"]
```

Why `service-monitor-backend:8081`:
- Backend is running as a Docker Compose service in the same network.
- Prometheus reaches it using the Compose service name.

### 5.2 Run Prometheus

Option A (recommended): Docker Compose  
Option B: native Prometheus binary

If using Docker Compose, continue to Phase 3 and start both Prometheus + Grafana together.

### 5.3 Verify Prometheus target health

Open:

- `http://localhost:9090/targets`

Expected:
- Job `service_monitor_backend` is `UP`.

Capability enabled:
- Metrics are now being ingested and stored over time.

---

## 6. Phase 3: Grafana Setup (outside IDE)

Grafana is infrastructure and must run separately from the Java app process.

### 6.1 Create `docker-compose.yml` in project root

```yaml
services:
  prometheus:
    image: prom/prometheus:latest
    container_name: prometheus
    ports:
      - "9090:9090"
    volumes:
      - ./monitoring/prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
    restart: unless-stopped

  grafana:
    image: grafana/grafana:latest
    container_name: grafana
    ports:
      - "3000:3000"
    restart: unless-stopped
    depends_on:
      - prometheus
```

### 6.2 Start infrastructure

From project root:

```powershell
docker compose up -d
```

Verify containers:

```powershell
docker ps
```

### 6.3 Configure Grafana datasource

1. Open `http://localhost:3000`
2. Login (default `admin/admin`, then change password)
3. Add datasource:
   - Type: Prometheus
   - URL: `http://prometheus:9090`
4. Click `Save & test`

Capability enabled:
- Grafana can query Prometheus metrics.

---

## 7. Phase 4: Dashboard Creation

Create a dashboard named `Service Monitor - Backend`.

Suggested initial panels:

1. Service availability
   - Query: `up{job="service_monitor_backend"}`
2. Request throughput
   - Query: `rate(http_server_requests_seconds_count[1m])`
3. JVM memory
   - Query: `jvm_memory_used_bytes`
4. JVM threads
   - Query: `jvm_threads_live_threads`

Capability enabled:
- Real-time service health and runtime trends are visible.

---

## 8. Phase 5: Downtime and Error Simulation

Do this only after dashboard metrics are confirmed.

### 8.1 Downtime simulation

Stop backend process (IDE stop button or terminal interrupt).

Expected observations:
- Prometheus target changes `UP -> DOWN`.
- Grafana `up` panel drops to `0`.

### 8.2 Error simulation

Add a temporary endpoint that returns HTTP 500 and hit it repeatedly (Postman/curl/JMeter).

Expected observations:
- Request counters increase.
- 5xx-related metrics/rates spike.

Capability enabled:
- Monitoring stack proves it can detect outages and bad behavior, not just normal operation.

---

## 9. Phase 6: Email Alerts in Grafana

Do this after downtime/error simulation is visible.

### 9.1 Configure SMTP for Grafana

Set SMTP in Grafana config (or environment variables in `docker-compose.yml`), then restart Grafana.

Typical env vars:

- `GF_SMTP_ENABLED=true`
- `GF_SMTP_HOST=<smtp-host:port>`
- `GF_SMTP_USER=<username>`
- `GF_SMTP_PASSWORD=<password>`
- `GF_SMTP_FROM_ADDRESS=<sender-email>`
- `GF_SMTP_FROM_NAME=Service Monitor Alerts`

### 9.2 Create contact point

Grafana:
- Alerting -> Contact points -> Add email contact.

### 9.3 Create alert rules

Start with:

1. Backend down:
   - Query: `up{job="service_monitor_backend"}`
   - Condition: `IS BELOW 1` for `2m`
2. High server errors:
   - Query based on 5xx request rate
   - Condition threshold based on expected traffic

### 9.4 Test alert delivery

Trigger downtime/error and verify email is sent and resolved.

Capability enabled:
- Automatic proactive notification for service incidents.

---

## 10. Operational Order (Strict Sequence)

Follow exactly:

1. Backend dependency/config setup
2. Backend endpoint verification (`health`, `prometheus`)
3. Prometheus configuration and `UP` target validation
4. Grafana datasource connection test
5. Dashboard creation and live metric validation
6. Downtime/error simulation and graph validation
7. Alerting + email configuration
8. Alert test and incident runbook finalization

Do not configure alerts before metric ingestion is proven stable.

## 11. Definition of Done

Project is complete only when all are true:

1. Backend metrics endpoint returns valid Prometheus format.
2. Prometheus target remains `UP` during normal run.
3. Grafana dashboard shows live backend metrics.
4. Simulated downtime is visible in Prometheus and Grafana.
5. Simulated errors are visible in Grafana metrics.
6. Email alert is sent on downtime and clears on recovery.

## 12. Troubleshooting Quick Notes

1. Grafana cannot reach Prometheus:
   - Ensure datasource URL is `http://prometheus:9090` (inside Docker network), not localhost.
2. Prometheus target `DOWN`:
   - Confirm backend is running on `8081`.
   - Confirm target uses `service-monitor-backend:8081` when backend is in Docker Compose.
3. No `/actuator/prometheus` endpoint:
   - Recheck actuator exposure properties.
4. App starts then exits:
   - Ensure `spring-boot-starter-web` is present.
5. No email alerts:
   - Validate SMTP host/port/auth and check Grafana alerting logs.
