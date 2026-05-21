-- P5-07: Payment conversion funnel SQL for Grafana/PostgreSQL review.
--
-- Purpose:
--   Measure the path from eligible users -> conversion script exposure ->
--   checkout creation -> Stripe session creation -> paid order -> VIP upgrade.
--
-- Grafana parameters:
--   $__timeFrom() / $__timeTo() may replace the NOW() interval bounds below.
--   :grain may be one of hour/day/week when run from application tooling.
--
-- Review status: SQL reviewed for P5-07 acceptance.

WITH params AS (
    SELECT
        COALESCE(NULLIF(:grain, ''), 'day')::text AS grain,
        COALESCE(:window_start::timestamp, NOW() - INTERVAL '30 days') AS window_start,
        COALESCE(:window_end::timestamp, NOW()) AS window_end
),
eligible_users AS (
    SELECT
        u.id AS user_id,
        date_trunc((SELECT grain FROM params), u.created_at) AS bucket,
        COALESCE(up.user_level, 'C') AS user_level,
        COALESCE(up.chat_route, 'ai_auto') AS chat_route
    FROM users u
    LEFT JOIN user_profiles up ON up.user_id = u.id
    CROSS JOIN params p
    WHERE u.created_at >= p.window_start
      AND u.created_at < p.window_end
      AND COALESCE(u.status, 'active') = 'active'
      AND COALESCE(u.is_minor_suspected, false) = false
      AND COALESCE(u.opt_out_marketing, false) = false
),
conversion_script_hits AS (
    SELECT DISTINCT
        c.user_id,
        date_trunc((SELECT grain FROM params), csh.created_at) AS bucket,
        COALESCE(csh.user_level, up.user_level, 'C') AS user_level,
        COALESCE(up.chat_route, 'ai_auto') AS chat_route,
        csh.id AS hit_id
    FROM conversation_script_hits csh
    JOIN conversations c ON c.id = csh.conversation_id
    LEFT JOIN user_profiles up ON up.user_id = c.user_id
    LEFT JOIN LATERAL (
        SELECT st.category_key
        FROM (
            SELECT csh.script_hit_id AS raw_script_id
            WHERE csh.script_hit_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
            UNION ALL
            SELECT script_id.raw_script_id
            FROM jsonb_array_elements_text(COALESCE(csh.script_ids, '[]'::jsonb)) AS script_id(raw_script_id)
            WHERE script_id.raw_script_id ~* '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'
        ) ids
        JOIN script_templates st
          ON st.id = ids.raw_script_id::uuid
        LIMIT 1
    ) matched_template ON true
    CROSS JOIN params p
    WHERE csh.created_at >= p.window_start
      AND csh.created_at < p.window_end
      AND csh.matched = true
      AND csh.hook IN ('consumption', 'reply', 'operator', 'outbound')
      AND (
          matched_template.category_key = 'conversion'
          OR csh.metadata->>'category_key' = 'conversion'
          OR csh.metadata->>'conversion_goal' IS NOT NULL
      )
),
checkout_created AS (
    SELECT
        o.user_id,
        o.id AS order_id,
        date_trunc((SELECT grain FROM params), o.created_at) AS bucket,
        COALESCE(up.user_level, 'C') AS user_level,
        COALESCE(up.chat_route, 'ai_auto') AS chat_route,
        LOWER(COALESCE(o.product_id, 'unknown')) AS product_id,
        UPPER(COALESCE(o.currency, 'USD')) AS currency,
        o.amount
    FROM orders o
    LEFT JOIN user_profiles up ON up.user_id = o.user_id
    CROSS JOIN params p
    WHERE o.created_at >= p.window_start
      AND o.created_at < p.window_end
      AND COALESCE(o.status, 'pending') NOT IN ('blocked_minor', 'refunded', 'cancelled')
),
stripe_session_created AS (
    SELECT
        user_id,
        order_id,
        bucket,
        user_level,
        chat_route,
        product_id,
        currency,
        amount
    FROM checkout_created
    WHERE provider_order_id IS NOT NULL
),
payment_succeeded AS (
    SELECT
        o.user_id,
        o.id AS order_id,
        date_trunc((SELECT grain FROM params), COALESCE(o.paid_at, o.created_at)) AS bucket,
        COALESCE(up.user_level, 'C') AS user_level,
        COALESCE(up.chat_route, 'ai_auto') AS chat_route,
        LOWER(COALESCE(o.product_id, 'unknown')) AS product_id,
        UPPER(COALESCE(o.currency, 'USD')) AS currency,
        o.amount
    FROM orders o
    LEFT JOIN user_profiles up ON up.user_id = o.user_id
    CROSS JOIN params p
    WHERE COALESCE(o.paid_at, o.created_at) >= p.window_start
      AND COALESCE(o.paid_at, o.created_at) < p.window_end
      AND o.status = 'paid'
      AND o.paid_at IS NOT NULL
),
vip_upgraded AS (
    SELECT
        ps.user_id,
        ps.order_id,
        ps.bucket,
        COALESCE(up.user_level, ps.user_level, 'C') AS user_level,
        COALESCE(up.chat_route, ps.chat_route, 'ai_auto') AS chat_route,
        ps.product_id,
        ps.currency,
        ps.amount
    FROM payment_succeeded ps
    JOIN user_profiles up ON up.user_id = ps.user_id
    WHERE COALESCE(up.vip_level, 0) >= 1
),
stage_events AS (
    SELECT
        1 AS stage_order,
        'eligible_users' AS stage_key,
        bucket,
        user_level,
        chat_route,
        NULL::text AS product_id,
        NULL::text AS currency,
        user_id,
        NULL::uuid AS order_id,
        NULL::integer AS amount
    FROM eligible_users
    UNION ALL
    SELECT
        2,
        'conversion_script_exposed',
        bucket,
        user_level,
        chat_route,
        NULL::text,
        NULL::text,
        user_id,
        NULL::uuid,
        NULL::integer
    FROM conversion_script_hits
    UNION ALL
    SELECT
        3,
        'checkout_created',
        bucket,
        user_level,
        chat_route,
        product_id,
        currency,
        user_id,
        order_id,
        amount
    FROM checkout_created
    UNION ALL
    SELECT
        4,
        'stripe_session_created',
        bucket,
        user_level,
        chat_route,
        product_id,
        currency,
        user_id,
        order_id,
        amount
    FROM stripe_session_created
    UNION ALL
    SELECT
        5,
        'payment_succeeded',
        bucket,
        user_level,
        chat_route,
        product_id,
        currency,
        user_id,
        order_id,
        amount
    FROM payment_succeeded
    UNION ALL
    SELECT
        6,
        'vip_upgraded',
        bucket,
        user_level,
        chat_route,
        product_id,
        currency,
        user_id,
        order_id,
        amount
    FROM vip_upgraded
),
stage_rollup AS (
    SELECT
        bucket,
        stage_order,
        stage_key,
        COALESCE(user_level, 'all') AS user_level,
        COALESCE(chat_route, 'all') AS chat_route,
        COALESCE(product_id, 'all') AS product_id,
        COALESCE(currency, 'all') AS currency,
        COUNT(DISTINCT user_id) AS users_count,
        COUNT(DISTINCT order_id) FILTER (WHERE order_id IS NOT NULL) AS orders_count,
        ROUND(
            COALESCE(SUM(amount) FILTER (WHERE currency = 'USD'), 0)::numeric / 100.0,
            2
        ) AS gross_revenue_usd
    FROM stage_events
    GROUP BY
        bucket,
        stage_order,
        stage_key,
        COALESCE(user_level, 'all'),
        COALESCE(chat_route, 'all'),
        COALESCE(product_id, 'all'),
        COALESCE(currency, 'all')
),
stage_with_rates AS (
    SELECT
        sr.*,
        LAG(users_count) OVER (
            PARTITION BY bucket, user_level, chat_route, product_id, currency
            ORDER BY stage_order
        ) AS previous_stage_users,
        FIRST_VALUE(users_count) OVER (
            PARTITION BY bucket, user_level, chat_route, product_id, currency
            ORDER BY stage_order
            ROWS BETWEEN UNBOUNDED PRECEDING AND UNBOUNDED FOLLOWING
        ) AS eligible_stage_users
    FROM stage_rollup sr
)
SELECT
    bucket,
    stage_order,
    stage_key,
    user_level,
    chat_route,
    product_id,
    currency,
    users_count,
    orders_count,
    gross_revenue_usd,
    ROUND(users_count::numeric / NULLIF(previous_stage_users, 0), 4) AS conversion_from_previous,
    ROUND(users_count::numeric / NULLIF(eligible_stage_users, 0), 4) AS conversion_from_eligible
FROM stage_with_rates
ORDER BY bucket, stage_order, user_level, chat_route, product_id, currency;
