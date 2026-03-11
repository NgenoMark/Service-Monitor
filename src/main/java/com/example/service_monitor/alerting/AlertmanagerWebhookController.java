package com.example.service_monitor.alerting;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.sql.Timestamp;
import java.time.OffsetDateTime;
import java.util.Map;
import java.util.Optional;

@RestController
public class AlertmanagerWebhookController {

    private static final Logger LOGGER = LoggerFactory.getLogger(AlertmanagerWebhookController.class);

    private final JdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;

    public AlertmanagerWebhookController(JdbcTemplate jdbcTemplate, ObjectMapper objectMapper) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
    }

    @PostMapping("/api/alerts/alertmanager")
    public ResponseEntity<Void> receive(@RequestBody String rawPayload) {
        AlertmanagerWebhookPayload payload;
        try {
            payload = objectMapper.readValue(rawPayload, AlertmanagerWebhookPayload.class);
        } catch (Exception ex) {
            LOGGER.warn("Invalid Alertmanager payload: {}", ex.getMessage());
            return ResponseEntity.badRequest().build();
        }

        if (payload == null || payload.getAlerts() == null || payload.getAlerts().isEmpty()) {
            LOGGER.info("Alertmanager payload received with no alerts.");
            return ResponseEntity.ok().build();
        }

        LOGGER.info("Alertmanager payload received: status={}, alerts={}",
            payload.getStatus(), payload.getAlerts().size());

        for (AlertmanagerWebhookPayload.Alert alert : payload.getAlerts()) {
            Map<String, String> labels = alert.getLabels();
            Map<String, String> annotations = alert.getAnnotations();

            String alertName = optionalLabel(labels, "alertname", "UnknownAlert");
            String severity = optionalLabel(labels, "severity", "info");
            String serviceKey = optionalLabel(labels, "service", null);

            Integer serviceId = resolveServiceId(serviceKey);

            String status = normalizeStatus(alert.getStatus() != null ? alert.getStatus() : payload.getStatus());

            String summary = annotations != null ? annotations.get("summary") : null;
            String description = annotations != null ? annotations.get("description") : null;
            String message = summary != null ? summary : description;
            if (message == null) {
                message = "Alert received from Alertmanager.";
            }

            Timestamp startsAt = parseTimestamp(alert.getStartsAt());
            Timestamp endsAt = parseTimestamp(alert.getEndsAt());

            String labelsJson = toJson(labels);
            String annotationsJson = toJson(annotations);

            jdbcTemplate.update(
                "INSERT INTO monitoring.alert_events " +
                    "(service_id, alert_source, alert_name, severity, status, message, labels, starts_at, ends_at) " +
                    "VALUES (?, 'PROMETHEUS', ?, ?, ?, ?, ?::jsonb, ?, ?)",
                serviceId,
                alertName,
                severity,
                status,
                message,
                labelsJson,
                startsAt,
                endsAt
            );
        }

        return ResponseEntity.ok().build();
    }

    private Integer resolveServiceId(String serviceKey) {
        if (serviceKey == null || serviceKey.trim().isEmpty()) {
            return null;
        }
        return jdbcTemplate.query(
            "SELECT id FROM monitoring.services WHERE service_key = ? LIMIT 1",
            rs -> rs.next() ? rs.getInt("id") : null,
            serviceKey
        );
    }

    private static String optionalLabel(Map<String, String> labels, String key, String fallback) {
        if (labels == null) {
            return fallback;
        }
        String value = labels.get(key);
        return value != null && !value.trim().isEmpty() ? value : fallback;
    }

    private static String normalizeStatus(String status) {
        if (status == null) {
            return "FIRING";
        }
        String normalized = status.trim().toUpperCase();
        return normalized.equals("RESOLVED") ? "RESOLVED" : "FIRING";
    }

    private Timestamp parseTimestamp(String timestamp) {
        if (timestamp == null || timestamp.trim().isEmpty()) {
            return null;
        }
        try {
            return Timestamp.from(OffsetDateTime.parse(timestamp).toInstant());
        } catch (Exception ex) {
            return null;
        }
    }

    private String toJson(Map<String, String> value) {
        if (value == null) {
            return "{}";
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException ex) {
            return "{}";
        }
    }
}
