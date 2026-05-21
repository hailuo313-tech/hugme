# P5-07 Payment Conversion Funnel SQL

Task: P5-07

Acceptance: SQL reviewed and ready for the P5-08 Grafana conversion panel.

## Artifact

- `monitoring/sql/p5_07_payment_conversion_funnel.sql`

## Funnel Stages

1. `eligible_users`
2. `conversion_script_exposed`
3. `checkout_created`
4. `stripe_session_created`
5. `payment_succeeded`
6. `vip_upgraded`

## Review Notes

- The SQL uses only operational identifiers needed for aggregation and does not
  select phone numbers, external IDs, message text, or raw Stripe payloads.
- The conversion exposure stage is based on `conversation_script_hits` and
  `script_templates.category_key = 'conversion'`, with metadata fallback for
  hits that store `category_key` or `conversion_goal`.
- Paid conversion is based on `orders.status = 'paid'` and `paid_at IS NOT NULL`.
- VIP upgrade is counted after paid order confirmation when `user_profiles.vip_level >= 1`.
- Output fields are stable for Grafana: `bucket`, `stage_order`, `stage_key`,
  `user_level`, `chat_route`, `product_id`, `currency`, counts, revenue, and
  conversion rates.

## Suggested Grafana Usage

Use PostgreSQL datasource and replace the parameter defaults in the `params` CTE:

```sql
COALESCE($__timeFrom()::timestamp, NOW() - INTERVAL '30 days') AS window_start,
COALESCE($__timeTo()::timestamp, NOW()) AS window_end
```

For daily panels, set `:grain` to `day`. For 24-hour drilldown, use `hour`.

## Review Result

Approved for P5-07 SQL review baseline.
