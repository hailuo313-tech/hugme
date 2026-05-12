# Discord Alert Template

Use this copy when a Discord webhook receiver is enabled later.

## Critical

`[CRITICAL] {{ .CommonLabels.alertname }}`

Component: `{{ .CommonLabels.component }}`

Summary: `{{ .CommonAnnotations.summary }}`

Action: open the runbook, check recent deploys, and acknowledge in the ops channel.

Runbook: `{{ .CommonAnnotations.runbook }}`

## Warning

`[WARNING] {{ .CommonLabels.alertname }}`

Component: `{{ .CommonLabels.component }}`

Summary: `{{ .CommonAnnotations.summary }}`

Action: inspect during the current operating window; escalate if it persists or affects beta users.

Runbook: `{{ .CommonAnnotations.runbook }}`

## Safety

Never include user IDs, message text, payment details, API keys, bot tokens, or raw trace IDs in Discord alerts.

