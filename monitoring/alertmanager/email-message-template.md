# Email Alert Template

Use this copy when an email receiver is enabled later.

Subject:

```text
[ERIS {{ .CommonLabels.severity | toUpper }}] {{ .CommonLabels.alertname }}
```

Body:

```text
Alert: {{ .CommonLabels.alertname }}
Severity: {{ .CommonLabels.severity }}
Component: {{ .CommonLabels.component }}

Summary:
{{ .CommonAnnotations.summary }}

Description:
{{ .CommonAnnotations.description }}

Runbook:
{{ .CommonAnnotations.runbook }}

Operator action:
1. Acknowledge in the ops channel.
2. Open the runbook.
3. Check the latest deployment and structured logs.
4. Escalate if beta users or payment flows are affected.
```

Safety:

- Do not include user IDs, raw trace IDs, message text, payment details, tokens, webhook secrets, or provider payloads.
- Keep email alerts short enough to be read on mobile.
- Use Discord for fast coordination and email for critical auditability.

