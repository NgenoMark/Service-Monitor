global:
  smtp_smarthost: '${SMTP_HOST}'
  smtp_from: '${SMTP_FROM}'
  smtp_auth_username: '${SMTP_USER}'
  smtp_auth_password: '${SMTP_PASSWORD}'
  smtp_require_tls: true

templates:
  - '/etc/alertmanager/templates/*.tmpl'

route:
  receiver: 'email-default'
  group_by: ['alertname', 'service', 'severity']
  group_wait: 30s
  group_interval: 2m
  repeat_interval: 1h

receivers:
  - name: 'email-default'
    email_configs:
      - to: '${ALERT_EMAIL_TO}'
        send_resolved: true
        headers:
          subject: '{{ template "service_monitor.subject" . }}'
        text: '{{ template "service_monitor.text" . }}'
