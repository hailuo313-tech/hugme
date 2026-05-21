# P4-10 Real Device Push Evidence

Status: evidence gate defined for staging/production.

P4-10 requires proof that a real device received a push notification. CI still
uses mocked FCM/APNs calls, so the real-device acceptance artifact is a
sanitized evidence export validated by:

```powershell
python scripts/check_p4_10_real_device_push_evidence.py evidence/p4_10_real_device_push.json
```

## Evidence Shape

Use a JSON list or `{"attempts": [...]}`:

```json
{
  "attempts": [
    {
      "provider": "fcm",
      "environment": "staging",
      "success": true,
      "message_id": "projects/.../messages/...",
      "device_token_hash": "sha256:abcd...",
      "sent_at": "2026-05-21T12:00:00Z",
      "received_at": "2026-05-21T12:00:03Z"
    }
  ]
}
```

Do not include raw device tokens, user phone numbers, real notification bodies,
or personally identifying information.
