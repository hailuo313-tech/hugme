"""Beijing-time user operations report queries."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALID_RANGES = {"today", "yesterday", "week", "month", "history"}

PERIOD_CTE = """
clock AS (
  SELECT timezone('Asia/Shanghai', NOW()) AS now_bj, NOW() AS now_at
),
period AS (
  SELECT
    CASE :range_key
      WHEN 'today' THEN date_trunc('day', now_bj) AT TIME ZONE 'Asia/Shanghai'
      WHEN 'yesterday' THEN (date_trunc('day', now_bj) - interval '1 day') AT TIME ZONE 'Asia/Shanghai'
      WHEN 'week' THEN date_trunc('week', now_bj) AT TIME ZONE 'Asia/Shanghai'
      WHEN 'month' THEN date_trunc('month', now_bj) AT TIME ZONE 'Asia/Shanghai'
      ELSE '-infinity'::timestamptz
    END AS start_at,
    CASE :range_key
      WHEN 'yesterday' THEN date_trunc('day', now_bj) AT TIME ZONE 'Asia/Shanghai'
      ELSE now_at
    END AS end_at,
    now_bj
  FROM clock
)
"""


def validate_range(range_key: str) -> str:
    value = (range_key or "today").strip().lower()
    if value not in VALID_RANGES:
        raise ValueError(f"unsupported range: {value}")
    return value


async def fetch_user_report_overview(db: AsyncSession, range_key: str) -> dict[str, Any]:
    range_key = validate_range(range_key)
    row = (
        await db.execute(
            text(
                f"""
                WITH {PERIOD_CTE},
                user_activity AS (
                  SELECT c.user_id, COUNT(*) AS user_messages
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                  CROSS JOIN period p
                  WHERE m.sender_type = 'user'
                    AND m.created_at >= p.start_at AND m.created_at < p.end_at
                  GROUP BY c.user_id
                ),
                link_users AS (
                  SELECT DISTINCT COALESCE(e.user_id, l.user_id) AS user_id
                  FROM attribution_events e
                  LEFT JOIN attribution_links l ON l.tracking_id = e.tracking_id
                  CROSS JOIN period p
                  WHERE e.event_type = 'click'
                    AND e.created_at >= p.start_at AND e.created_at < p.end_at
                ),
                video_users AS (
                  SELECT DISTINCT COALESCE(
                    CASE WHEN j.user_id ~* '^[0-9a-f-]{{36}}$' THEN j.user_id::uuid END,
                    u.id
                  ) AS user_id
                  FROM call_broadcast_jobs j
                  LEFT JOIN users u ON u.external_id = 'tg_' || j.chat_id::text
                  CROSS JOIN period p
                  WHERE j.created_at >= p.start_at AND j.created_at < p.end_at
                ),
                paid_users AS (
                  SELECT DISTINCT o.user_id
                  FROM orders o CROSS JOIN period p
                  WHERE o.status = 'paid' AND o.paid_at >= p.start_at AND o.paid_at < p.end_at
                )
                SELECT
                  (SELECT COUNT(*) FROM users u CROSS JOIN period p
                    WHERE u.created_at >= p.start_at AND u.created_at < p.end_at) AS new_users,
                  (SELECT COUNT(*) FROM user_activity) AS active_users,
                  (SELECT COUNT(*) FROM user_activity WHERE user_messages >= 3) AS engaged_users,
                  (SELECT COALESCE(SUM(user_messages), 0) FROM user_activity) AS user_messages,
                  (SELECT COUNT(*) FROM link_users WHERE user_id IS NOT NULL) AS link_click_users,
                  (SELECT COUNT(*) FROM video_users WHERE user_id IS NOT NULL) AS video_users,
                  (SELECT COUNT(*) FROM paid_users WHERE user_id IS NOT NULL) AS paid_users,
                  (SELECT start_at FROM period) AS start_at,
                  (SELECT end_at FROM period) AS end_at,
                  (SELECT now_bj FROM period) AS generated_at_bj
                """
            ),
            {"range_key": range_key},
        )
    ).mappings().one()
    return dict(row)


async def fetch_user_report_trend(db: AsyncSession, range_key: str) -> list[dict[str, Any]]:
    range_key = validate_range(range_key)
    rows = (
        await db.execute(
            text(
                f"""
                WITH {PERIOD_CTE},
                bounds AS (
                  SELECT
                    CASE WHEN :range_key = 'history'
                      THEN date_trunc('month', now_bj) - interval '11 months'
                      ELSE timezone('Asia/Shanghai', start_at)
                    END AS start_local,
                    timezone('Asia/Shanghai', end_at) AS end_local,
                    CASE WHEN :range_key IN ('today', 'yesterday') THEN 'hour'
                         WHEN :range_key = 'history' THEN 'month' ELSE 'day' END AS grain
                  FROM period
                ),
                buckets AS (
                  SELECT point AS bucket_local, b.grain
                  FROM bounds b
                  CROSS JOIN LATERAL generate_series(
                    date_trunc(b.grain, b.start_local),
                    date_trunc(b.grain, b.end_local),
                    CASE b.grain WHEN 'hour' THEN interval '1 hour'
                                 WHEN 'month' THEN interval '1 month'
                                 ELSE interval '1 day' END
                  ) point
                ),
                new_users AS (
                  SELECT date_trunc(b.grain, timezone('Asia/Shanghai', u.created_at AT TIME ZONE 'UTC')) bucket_local,
                         COUNT(*) AS value
                  FROM users u CROSS JOIN bounds b
                  WHERE (u.created_at AT TIME ZONE 'UTC') >= (b.start_local AT TIME ZONE 'Asia/Shanghai')
                    AND (u.created_at AT TIME ZONE 'UTC') < (b.end_local AT TIME ZONE 'Asia/Shanghai')
                  GROUP BY 1
                ),
                activity AS (
                  SELECT date_trunc(b.grain, timezone('Asia/Shanghai', m.created_at AT TIME ZONE 'UTC')) bucket_local,
                         c.user_id, COUNT(*) AS messages
                  FROM messages m JOIN conversations c ON c.id = m.conversation_id CROSS JOIN bounds b
                  WHERE m.sender_type = 'user'
                    AND (m.created_at AT TIME ZONE 'UTC') >= (b.start_local AT TIME ZONE 'Asia/Shanghai')
                    AND (m.created_at AT TIME ZONE 'UTC') < (b.end_local AT TIME ZONE 'Asia/Shanghai')
                  GROUP BY 1, c.user_id
                )
                SELECT to_char(bs.bucket_local,
                         CASE bs.grain WHEN 'hour' THEN 'MM-DD HH24:00'
                                       WHEN 'month' THEN 'YYYY-MM' ELSE 'MM-DD' END) AS label,
                       COALESCE(n.value, 0) AS new_users,
                       COUNT(a.user_id) AS active_users,
                       COUNT(a.user_id) FILTER (WHERE a.messages >= 3) AS engaged_users
                FROM buckets bs
                LEFT JOIN new_users n ON n.bucket_local = bs.bucket_local
                LEFT JOIN activity a ON a.bucket_local = bs.bucket_local
                GROUP BY bs.bucket_local, bs.grain, n.value
                ORDER BY bs.bucket_local
                """
            ),
            {"range_key": range_key},
        )
    ).mappings().all()
    return [dict(row) for row in rows]


async def fetch_user_report_distributions(db: AsyncSession, range_key: str) -> dict[str, Any]:
    """Return profile plus incoming and AI-message distributions."""
    range_key = validate_range(range_key)
    row = (
        await db.execute(
            text(
                f"""
                WITH {PERIOD_CTE},
                activity AS (
                  SELECT c.user_id, COUNT(*)::int AS message_count
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                  CROSS JOIN period p
                  WHERE m.sender_type = 'user'
                    AND m.created_at >= p.start_at AND m.created_at < p.end_at
                  GROUP BY c.user_id
                ),
                ai_activity AS (
                  SELECT c.user_id, COUNT(*)::int AS message_count
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                  CROSS JOIN period p
                  WHERE m.sender_type = 'assistant'
                    AND m.created_at >= p.start_at AND m.created_at < p.end_at
                  GROUP BY c.user_id
                ),
                profiled AS (
                  SELECT
                    a.user_id,
                    a.message_count,
                    UPPER(COALESCE(
                      NULLIF(up.country_code, ''),
                      NULLIF(up.preferences->>'country_code', ''),
                      NULLIF(up.preferences->>'country', ''),
                      NULLIF(up.preferences->>'geo_country', ''),
                      NULLIF(up.preferences->>'ip_country', ''),
                      'UNKNOWN'
                    )) AS country,
                    CASE
                      WHEN COALESCE(
                        NULLIF(up.preferences->>'age', ''),
                        NULLIF(up.preferences->>'ai_extracted_age', '')
                      ) ~ '^[0-9]{{1,3}}$'
                      THEN COALESCE(
                        NULLIF(up.preferences->>'age', ''),
                        NULLIF(up.preferences->>'ai_extracted_age', '')
                      )::int
                    END AS age
                  FROM activity a
                  LEFT JOIN user_profiles up ON up.user_id = a.user_id
                ),
                countries AS (
                  SELECT country AS label, COUNT(*)::int AS users
                  FROM profiled
                  GROUP BY country
                ),
                ages AS (
                  SELECT
                    CASE
                      WHEN age IS NULL OR age < 1 OR age > 120 THEN '未知'
                      WHEN age < 18 THEN '18岁以下'
                      WHEN age <= 24 THEN '18–24岁'
                      WHEN age <= 34 THEN '25–34岁'
                      WHEN age <= 44 THEN '35–44岁'
                      ELSE '45岁以上'
                    END AS label,
                    CASE
                      WHEN age IS NULL OR age < 1 OR age > 120 THEN 6
                      WHEN age < 18 THEN 1
                      WHEN age <= 24 THEN 2
                      WHEN age <= 34 THEN 3
                      WHEN age <= 44 THEN 4
                      ELSE 5
                    END AS sort_order,
                    COUNT(*)::int AS users
                  FROM profiled
                  GROUP BY 1, 2
                ),
                message_buckets(label, sort_order, users) AS (
                  VALUES
                    ('3条以内', 1, (SELECT COUNT(*)::int FROM profiled WHERE message_count <= 3)),
                    ('4–6条', 2, (SELECT COUNT(*)::int FROM profiled WHERE message_count BETWEEN 4 AND 6)),
                    ('7–10条', 3, (SELECT COUNT(*)::int FROM profiled WHERE message_count BETWEEN 7 AND 10)),
                    ('11–20条', 4, (SELECT COUNT(*)::int FROM profiled WHERE message_count BETWEEN 11 AND 20)),
                    ('20条以上', 5, (SELECT COUNT(*)::int FROM profiled WHERE message_count > 20))
                ),
                ai_message_buckets(label, sort_order, users) AS (
                  VALUES
                    ('3条以内', 1, (SELECT COUNT(*)::int FROM ai_activity WHERE message_count <= 3)),
                    ('4–6条', 2, (SELECT COUNT(*)::int FROM ai_activity WHERE message_count BETWEEN 4 AND 6)),
                    ('7–10条', 3, (SELECT COUNT(*)::int FROM ai_activity WHERE message_count BETWEEN 7 AND 10)),
                    ('11–20条', 4, (SELECT COUNT(*)::int FROM ai_activity WHERE message_count BETWEEN 11 AND 20)),
                    ('20条以上', 5, (SELECT COUNT(*)::int FROM ai_activity WHERE message_count > 20))
                )
                SELECT
                  COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'users', users)
                    ORDER BY users DESC, label) FROM countries), '[]'::jsonb) AS countries,
                  COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'users', users)
                    ORDER BY sort_order) FROM ages), '[]'::jsonb) AS ages,
                  COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'users', users)
                    ORDER BY sort_order) FROM message_buckets), '[]'::jsonb) AS message_buckets,
                  COALESCE((SELECT jsonb_agg(jsonb_build_object('label', label, 'users', users)
                    ORDER BY sort_order) FROM ai_message_buckets), '[]'::jsonb) AS ai_message_buckets
                """
            ),
            {"range_key": range_key},
        )
    ).mappings().one()
    return dict(row)


async def fetch_user_collection_report(db: AsyncSession, range_key: str) -> dict[str, Any]:
    """Return collection completeness for users created in the selected period."""
    range_key = validate_range(range_key)
    # This dashboard query touches several large tables. Keep it serial so
    # PostgreSQL does not allocate dynamic shared-memory workers on the busy
    # production host; the setting is transaction-local and affects no other request.
    await db.execute(text("SET LOCAL max_parallel_workers_per_gather = 0"))
    row = (
        await db.execute(
            text(
                f"""
                WITH {PERIOD_CTE},
                cohort AS (
                  SELECT u.*
                  FROM users u CROSS JOIN period p
                  WHERE u.created_at >= p.start_at AND u.created_at < p.end_at
                ),
                collected AS (
                  SELECT
                    u.id,
                    COALESCE(NULLIF(u.channel, ''), 'UNKNOWN') AS channel,
                    COALESCE(NULLIF(up.country_code, ''), 'UNKNOWN') AS country,
                    COALESCE(NULLIF(up.preferences->>'country_source', ''), 'UNKNOWN') AS country_source,
                    COALESCE(NULLIF(up.preferences->>'profile_intake_pending', ''), 'NONE') AS pending_step,
                    COALESCE(NULLIF(up.device_os, ''), 'Unknown') AS device_os,
                    COALESCE((NULLIF(up.preferences->>'profile_country_prompt_count', ''))::int, 0) AS country_prompt_count,
                    COALESCE(LOWER(COALESCE(up.preferences->>'profile_country_prompt_exhausted', '')) IN ('true','1','yes'), FALSE) AS country_exhausted,
                    (up.preferences->>'country_source') = 'chat_answer' AS country_chat_replied,
                    NULLIF(up.preferences->>'stated_country_code', '') IS NOT NULL AS has_stated_country,
                    (up.preferences->>'age_source') = 'chat_answer' AS age_chat_replied,
                    up.user_id IS NOT NULL AS has_profile,
                    COALESCE(LOWER(up.preferences->>'telegram_phone_country_fetched') IN ('true','1','yes'), FALSE) AS phone_fetched,
                    COALESCE(NULLIF(up.preferences->>'age', ''), NULLIF(up.preferences->>'ai_extracted_age', '')) IS NOT NULL AS has_age,
                    NULLIF(up.preferences->>'current_city', '') IS NOT NULL AS has_city,
                    EXISTS (SELECT 1 FROM telegram_peer_cache pc WHERE pc.user_id=u.id AND pc.chat_id IS NOT NULL) AS has_chat_id,
                    EXISTS (SELECT 1 FROM telegram_peer_cache pc WHERE pc.user_id=u.id AND pc.access_hash IS NOT NULL) AS has_access_hash,
                    EXISTS (SELECT 1 FROM telegram_peer_cache pc WHERE pc.user_id=u.id AND pc.account_id IS NOT NULL) AS has_source_account,
                    EXISTS (SELECT 1 FROM telegram_peer_cache pc WHERE pc.user_id=u.id AND NULLIF(pc.metadata->>'phone','') IS NOT NULL) AS has_phone,
                    EXISTS (SELECT 1 FROM conversations c JOIN messages m ON m.conversation_id=c.id WHERE c.user_id=u.id AND m.sender_type='user') AS has_user_message,
                    EXISTS (SELECT 1 FROM conversations c JOIN messages m ON m.conversation_id=c.id WHERE c.user_id=u.id AND m.sender_type='assistant') AS has_ai_reply,
                    EXISTS (SELECT 1 FROM conversations c JOIN messages m ON m.conversation_id=c.id WHERE c.user_id=u.id AND m.sender_type='user' AND COALESCE(m.content_type,'text')<>'text') AS has_media,
                    COALESCE(u.is_minor_suspected, FALSE) OR COALESCE(u.risk_level, 'normal')<>'normal' AS has_risk
                  FROM cohort u LEFT JOIN user_profiles up ON up.user_id=u.id
                ),
                summary AS (
                  SELECT
                    COUNT(*)::int AS total,
                    COUNT(*) FILTER (WHERE has_profile)::int AS profiles,
                    COUNT(*) FILTER (WHERE has_chat_id)::int AS chat_ids,
                    COUNT(*) FILTER (WHERE has_access_hash)::int AS access_hashes,
                    COUNT(*) FILTER (WHERE has_source_account)::int AS source_accounts,
                    COUNT(*) FILTER (WHERE has_phone)::int AS phones,
                    COUNT(*) FILTER (WHERE country<>'UNKNOWN')::int AS countries_known,
                    COUNT(*) FILTER (WHERE country='UNKNOWN')::int AS countries_unknown,
                    COUNT(*) FILTER (WHERE phone_fetched)::int AS phone_country_fetched,
                    COUNT(*) FILTER (WHERE has_age)::int AS ages,
                    COUNT(*) FILTER (WHERE has_city)::int AS cities,
                    COUNT(*) FILTER (WHERE has_user_message)::int AS user_messages,
                    COUNT(*) FILTER (WHERE has_ai_reply)::int AS ai_replies,
                    COUNT(*) FILTER (WHERE has_media)::int AS media_users,
                    COUNT(*) FILTER (WHERE has_risk)::int AS risk_users,
                    COUNT(*) FILTER (WHERE device_os<>'Unknown')::int AS devices_known
                  FROM collected
                ),
                countries AS (
                  SELECT country AS label, COUNT(*)::int AS users FROM collected GROUP BY country
                ),
                sources AS (
                  SELECT country_source AS label, COUNT(*)::int AS users FROM collected GROUP BY country_source
                ),
                pending AS (
                  SELECT pending_step AS label, COUNT(*)::int AS users FROM collected GROUP BY pending_step
                ),
                channels AS (
                  SELECT channel AS label, COUNT(*)::int AS users FROM collected GROUP BY channel
                ),
                devices AS (
                  SELECT device_os AS label, COUNT(*)::int AS users FROM collected GROUP BY device_os
                ),
                intake AS (
                  SELECT
                    COUNT(*) FILTER (
                      WHERE pending_step = 'country'
                         OR country_prompt_count > 0
                         OR country_exhausted
                         OR country_chat_replied
                         OR has_stated_country
                    )::int AS country_asked,
                    COUNT(*) FILTER (
                      WHERE country_chat_replied
                         OR (has_stated_country AND pending_step <> 'country')
                    )::int AS country_replied,
                    COUNT(*) FILTER (WHERE pending_step = 'country')::int AS country_waiting,
                    COUNT(*) FILTER (
                      WHERE pending_step = 'age' OR age_chat_replied
                    )::int AS age_asked,
                    COUNT(*) FILTER (WHERE age_chat_replied)::int AS age_replied,
                    COUNT(*) FILTER (WHERE pending_step = 'age')::int AS age_waiting
                  FROM collected
                )
                SELECT
                  to_jsonb(summary) AS summary,
                  COALESCE((SELECT jsonb_agg(jsonb_build_object('label',label,'users',users) ORDER BY users DESC,label) FROM countries), '[]'::jsonb) AS countries,
                  COALESCE((SELECT jsonb_agg(jsonb_build_object('label',label,'users',users) ORDER BY users DESC,label) FROM sources), '[]'::jsonb) AS country_sources,
                  COALESCE((SELECT jsonb_agg(jsonb_build_object('label',label,'users',users) ORDER BY users DESC,label) FROM pending), '[]'::jsonb) AS pending_steps,
                  COALESCE((SELECT jsonb_agg(jsonb_build_object('label',label,'users',users) ORDER BY users DESC,label) FROM channels), '[]'::jsonb) AS channels,
                  COALESCE((SELECT jsonb_agg(jsonb_build_object('label',label,'users',users) ORDER BY users DESC,label) FROM devices), '[]'::jsonb) AS devices,
                  jsonb_build_object(
                    'country', jsonb_build_object(
                      'asked', intake.country_asked,
                      'replied', intake.country_replied,
                      'waiting', intake.country_waiting
                    ),
                    'age', jsonb_build_object(
                      'asked', intake.age_asked,
                      'replied', intake.age_replied,
                      'waiting', intake.age_waiting
                    )
                  ) AS intake_progress,
                  to_char(timezone('Asia/Shanghai', now()), 'YYYY-MM-DD HH24:MI:SS') AS generated_at_bj
                FROM summary, intake
                """
            ),
            {"range_key": range_key},
        )
    ).mappings().one()
    data = dict(row)
    progress = data.get("intake_progress")
    if isinstance(progress, str):
        data["intake_progress"] = json.loads(progress)
    return data


async def fetch_user_collection_users(
    db: AsyncSession,
    range_key: str,
    *,
    offset: int = 0,
    limit: int = 20,
    search: str = "",
    device_os: str = "ALL",
    after_created_at: str | None = None,
) -> dict[str, Any]:
    range_key = validate_range(range_key)
    query = search.strip()
    after = (after_created_at or "").strip() or None
    params = {
        "range_key": range_key,
        "offset": offset,
        "limit": limit,
        "search": f"%{query}%",
        "device_os": device_os if device_os in {"iOS", "Android", "Desktop", "Unknown"} else "ALL",
        "after_created_at": after,
    }
    where_search = """AND (
      :search = '%%' OR u.external_id ILIKE :search OR COALESCE(u.nickname,'') ILIKE :search
      OR COALESCE(u.peer_metadata->>'username','') ILIKE :search OR CAST(u.chat_id AS text) ILIKE :search
    )"""
    where_after = (
        "AND CAST(:after_created_at AS timestamptz) IS NOT NULL "
        "AND u.created_at > CAST(:after_created_at AS timestamptz)"
        if after
        else ""
    )
    enriched_select = """
        SELECT u.*, pc.chat_id, pc.access_hash, pc.account_id, pc.source AS credential_source,
          pc.last_seen_at AS credential_verified_at, pc.updated_at AS credential_updated_at,
          pc.metadata AS peer_metadata, ta.display_name AS account_name, ta.username AS account_username,
          up.country_code, up.preferences, up.interests, up.emotional_patterns, up.chat_style,
          up.relationship_stage, up.user_level, up.chat_route, up.vip_level,
          up.device_os, up.device_first_detected_at, up.device_last_detected_at,
          up.loneliness_score, up.emotion_score, up.retention_score, up.dependency_score,
          (SELECT MIN(c.created_at) FROM conversations c WHERE c.user_id=u.id) AS first_conversation_at,
          (SELECT MAX(c.last_message_at) FROM conversations c WHERE c.user_id=u.id) AS last_active_at,
          (SELECT COUNT(*) FROM conversations c WHERE c.user_id=u.id) AS conversation_count,
          (SELECT COUNT(*) FROM conversations c JOIN messages m ON m.conversation_id=c.id WHERE c.user_id=u.id AND m.sender_type='user') AS user_message_count,
          (SELECT COUNT(*) FROM conversations c JOIN messages m ON m.conversation_id=c.id WHERE c.user_id=u.id AND m.sender_type='assistant') AS ai_message_count,
          (SELECT COUNT(*) FROM call_broadcast_jobs j WHERE j.user_id=u.id::text OR j.external_user_id=u.external_id) AS call_count
    """
    if query:
        base = f"""
          WITH matched AS (
            SELECT DISTINCT u.id
            FROM users u
            LEFT JOIN telegram_peer_cache pc ON pc.user_id = u.id
            WHERE u.external_id ILIKE :search
               OR COALESCE(u.nickname, '') ILIKE :search
               OR COALESCE(pc.metadata->>'username', '') ILIKE :search
               OR CAST(pc.chat_id AS text) ILIKE :search
          ), enriched AS (
            {enriched_select}
            FROM users u
            JOIN matched m ON m.id = u.id
            LEFT JOIN telegram_peer_cache pc ON pc.user_id = u.id
            LEFT JOIN telegram_accounts ta ON ta.id = pc.account_id
            LEFT JOIN user_profiles up ON up.user_id = u.id
          ) SELECT * FROM enriched u
          WHERE (:device_os = 'ALL' OR COALESCE(u.device_os, 'Unknown') = :device_os)
        """
    else:
        base = f"""
          WITH {PERIOD_CTE}, cohort AS (
            SELECT u.* FROM users u CROSS JOIN period p
            WHERE u.created_at >= p.start_at AND u.created_at < p.end_at
          ), enriched AS (
            {enriched_select}
            FROM cohort u
            LEFT JOIN telegram_peer_cache pc ON pc.user_id=u.id
            LEFT JOIN telegram_accounts ta ON ta.id=pc.account_id
            LEFT JOIN user_profiles up ON up.user_id=u.id
          ) SELECT * FROM enriched u
          WHERE (:device_os = 'ALL' OR COALESCE(u.device_os, 'Unknown') = :device_os)
          {where_search} {where_after}
        """
    count_sql = f"SELECT COUNT(*) FROM ({base}) q"
    total = int((await db.execute(text(count_sql), params)).scalar() or 0)
    rows = (
        await db.execute(
            text(base + " ORDER BY u.created_at DESC OFFSET :offset LIMIT :limit"), params
        )
    ).mappings().all()
    return {"total": total, "items": [dict(row) for row in rows]}


async def fetch_user_collection_user_detail(
    db: AsyncSession,
    user_id: str,
    *,
    message_offset: int = 0,
    message_limit: int = 100,
) -> dict[str, Any] | None:
    params = {"user_id": user_id, "offset": message_offset, "limit": message_limit}
    user = (
        await db.execute(
            text(
                """
                SELECT u.*, up.preferences, up.interests, up.emotional_patterns, up.chat_style,
                  up.forbidden_topics, up.relationship_stage, up.risk_score, up.vip_level,
                  up.initiation_score, up.emotion_score, up.retention_score, up.dependency_score,
                  up.loneliness_score, up.score_stage, up.notes, up.user_level, up.chat_route,
                  up.country_code, up.level_reason, up.updated_at AS profile_updated_at,
                  up.device_os, up.device_user_agent,
                  up.device_first_detected_at, up.device_last_detected_at,
                  pc.chat_id, pc.access_hash, pc.account_id AS source_account_id,
                  pc.source AS credential_source, pc.metadata AS peer_metadata,
                  pc.last_seen_at AS credential_verified_at, pc.updated_at AS credential_updated_at,
                  ta.display_name AS receiving_account_name, ta.username AS receiving_account_username,
                  ta.user_id AS receiving_account_telegram_id
                FROM users u
                LEFT JOIN user_profiles up ON up.user_id=u.id
                LEFT JOIN telegram_peer_cache pc ON pc.user_id=u.id
                LEFT JOIN telegram_accounts ta ON ta.id=pc.account_id
                WHERE u.id=CAST(:user_id AS uuid)
                """
            ),
            params,
        )
    ).mappings().first()
    if user is None:
        return None

    async def rows(sql: str) -> list[dict[str, Any]]:
        result = (await db.execute(text(sql), params)).mappings().all()
        return [dict(item) for item in result]

    conversations = await rows(
        """SELECT id, channel, state, ai_model_used, assigned_operator_id, created_at,
        last_message_at, post_inbound_video_expert_waived_at, post_video_fixed_01_sent_at,
        post_video_fixed_02_sent_at, post_video_fixed_03_last_sent_at,
        post_video_fixed_03_stopped_at, post_video_fixed_03_stop_reason
        FROM conversations WHERE user_id=CAST(:user_id AS uuid) ORDER BY created_at DESC"""
    )
    message_total = int(
        (await db.execute(text("""SELECT COUNT(*) FROM messages m JOIN conversations c ON c.id=m.conversation_id WHERE c.user_id=CAST(:user_id AS uuid)"""), params)).scalar() or 0
    )
    messages = await rows(
        """SELECT m.id, m.conversation_id, m.sender_type, m.content, m.content_type,
        m.model_name, m.used_script_id, m.is_operator_message, m.safety_result,
        m.telegram_account_id, m.created_at
        FROM messages m JOIN conversations c ON c.id=m.conversation_id
        WHERE c.user_id=CAST(:user_id AS uuid)
        ORDER BY m.created_at DESC OFFSET :offset LIMIT :limit"""
    )
    links = await rows(
        """SELECT tracking_id, destination_url, platform, country_code, is_t1_country,
        sender_account_id, scene_step, script_category, intent, sent_at, created_at
        FROM attribution_links WHERE user_id=CAST(:user_id AS uuid) ORDER BY created_at DESC LIMIT 200"""
    )
    attribution_events = await rows(
        """SELECT event_type, tracking_id, country_code, device_os, metadata, created_at
        FROM attribution_events WHERE user_id=CAST(:user_id AS uuid) ORDER BY created_at DESC LIMIT 200"""
    )
    calls = await rows(
        """SELECT id, trigger_source, status, started_at, ended_at, failure_reason,
        rule_key, metadata, created_at FROM call_broadcast_jobs
        WHERE user_id=:user_id OR external_user_id=(SELECT external_id FROM users WHERE id=CAST(:user_id AS uuid))
        ORDER BY created_at DESC LIMIT 200"""
    )
    fixed_replies = await rows(
        """SELECT j.id, r.name AS rule_name, r.text_content, j.status, j.send_at, j.sent_at,
        j.failure_reason, j.send_attempts, j.created_at
        FROM fixed_auto_reply_jobs j LEFT JOIN fixed_auto_reply_rules r ON r.id=j.rule_id
        WHERE j.user_id=CAST(:user_id AS uuid) ORDER BY j.created_at DESC LIMIT 200"""
    )
    return {
        "user": dict(user),
        "conversations": conversations,
        "messages": messages,
        "message_total": message_total,
        "message_offset": message_offset,
        "links": links,
        "attribution_events": attribution_events,
        "calls": calls,
        "fixed_replies": fixed_replies,
        "reply_audit_gap": "AI失败与跳过原因目前仅保存在运行日志，数据库没有逐用户审计表。",
    }


def _as_int(row: dict[str, Any], key: str) -> int:
    return int(row.get(key) or 0)


def _as_user_items(row: dict[str, Any], key: str) -> list[dict[str, str]]:
    raw = row.get(key)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            return []
    if not isinstance(raw, list):
        return []
    items: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        user_id = str(item.get("user_id") or "").strip()
        if not user_id or user_id in seen:
            continue
        seen.add(user_id)
        items.append(
            {
                "user_id": user_id,
                "external_id": str(item.get("external_id") or "").strip(),
                "nickname": str(item.get("nickname") or "").strip(),
            }
        )
    return items


async def fetch_post_video_funnel_stats(db: AsyncSession, range_key: str) -> dict[str, Any]:
    """01/02/03 sends, registered/screenshot replies, and country/age asks in Beijing time."""
    range_key = validate_range(range_key)
    row = (
        await db.execute(
            text(
                f"""
                WITH {PERIOD_CTE},
                script_msgs AS (
                  SELECT m.conversation_id, c.user_id, m.model_name, m.created_at
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                  CROSS JOIN period p
                  WHERE m.created_at >= p.start_at AND m.created_at < p.end_at
                    AND m.model_name IN (
                      'post_video_script:视频后发过去的信息01',
                      'post_video_script:视频后发过去的信息02',
                      'post_video_script:视频后发过去的信息03'
                    )
                ),
                funnel_convs AS (
                  SELECT id, user_id
                  FROM conversations
                  WHERE post_video_fixed_01_sent_at IS NOT NULL
                     OR post_video_fixed_02_sent_at IS NOT NULL
                     OR post_video_fixed_03_last_sent_at IS NOT NULL
                ),
                registered_users AS (
                  SELECT c.user_id
                  FROM conversations c
                  CROSS JOIN period p
                  WHERE c.post_video_fixed_03_stop_reason = 'already_registered'
                    AND c.post_video_fixed_03_stopped_at >= p.start_at
                    AND c.post_video_fixed_03_stopped_at < p.end_at
                  UNION
                  SELECT c.user_id
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                  CROSS JOIN period p
                  WHERE m.sender_type = 'user'
                    AND m.created_at >= p.start_at AND m.created_at < p.end_at
                    AND m.model_name = 'user_intent:already_registered'
                ),
                screenshot_users AS (
                  SELECT c.user_id
                  FROM conversations c
                  CROSS JOIN period p
                  WHERE c.post_video_fixed_03_stop_reason = 'screenshot'
                    AND c.post_video_fixed_03_stopped_at >= p.start_at
                    AND c.post_video_fixed_03_stopped_at < p.end_at
                  UNION
                  SELECT fc.user_id
                  FROM funnel_convs fc
                  JOIN messages m ON m.conversation_id = fc.id
                  CROSS JOIN period p
                  WHERE m.sender_type = 'user'
                    AND m.created_at >= p.start_at AND m.created_at < p.end_at
                    AND (
                      m.content = '[photo]'
                      OR m.content_type IN ('image', 'photo')
                    )
                ),
                country_asks AS (
                  SELECT c.user_id, MIN(m.created_at) AS asked_at
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                  CROSS JOIN period p
                  WHERE m.sender_type = 'assistant'
                    AND m.created_at >= p.start_at AND m.created_at < p.end_at
                    AND (
                      (
                        m.model_name = 'post_auto_answer_profile_prompt'
                        AND m.content ~* 'city|country|国家|ciudad|cidade'
                      )
                      OR m.content ILIKE 'Before we continue, which country%'
                      OR m.content ILIKE 'Before we continue, which city%'
                      OR m.content ILIKE '继续之前，你在哪个国家%'
                      OR m.content ILIKE 'By the way, which city%'
                    )
                  GROUP BY c.user_id
                ),
                age_asks AS (
                  SELECT c.user_id, MIN(m.created_at) AS asked_at
                  FROM messages m
                  JOIN conversations c ON c.id = m.conversation_id
                  CROSS JOIN period p
                  WHERE m.sender_type = 'assistant'
                    AND m.created_at >= p.start_at AND m.created_at < p.end_at
                    AND (
                      (
                        m.model_name = 'post_auto_answer_profile_prompt'
                        AND m.content ~* 'old|age|años|anos|多大'
                      )
                      OR m.content ILIKE 'Thanks. How old are you%'
                      OR m.content ILIKE 'By the way, how old are you%'
                      OR m.content ILIKE 'By the way, which city are you from, and how old%'
                      OR m.content ILIKE '谢谢。你多大了%'
                    )
                  GROUP BY c.user_id
                ),
                country_replies AS (
                  SELECT DISTINCT ca.user_id
                  FROM country_asks ca
                  JOIN conversations c ON c.user_id = ca.user_id
                  JOIN messages m ON m.conversation_id = c.id
                  CROSS JOIN period p
                  WHERE m.sender_type = 'user'
                    AND m.created_at > ca.asked_at
                    AND m.created_at < p.end_at
                ),
                age_replies AS (
                  SELECT DISTINCT aa.user_id
                  FROM age_asks aa
                  JOIN conversations c ON c.user_id = aa.user_id
                  JOIN messages m ON m.conversation_id = c.id
                  CROSS JOIN period p
                  WHERE m.sender_type = 'user'
                    AND m.created_at > aa.asked_at
                    AND m.created_at < p.end_at
                )
                SELECT
                  (SELECT COUNT(*) FROM script_msgs WHERE model_name = 'post_video_script:视频后发过去的信息01') AS script_01_messages,
                  (SELECT COUNT(DISTINCT user_id) FROM script_msgs WHERE model_name = 'post_video_script:视频后发过去的信息01') AS script_01_users,
                  (SELECT COUNT(*) FROM script_msgs WHERE model_name = 'post_video_script:视频后发过去的信息02') AS script_02_messages,
                  (SELECT COUNT(DISTINCT user_id) FROM script_msgs WHERE model_name = 'post_video_script:视频后发过去的信息02') AS script_02_users,
                  (SELECT COUNT(*) FROM script_msgs WHERE model_name = 'post_video_script:视频后发过去的信息03') AS script_03_messages,
                  (SELECT COUNT(DISTINCT user_id) FROM script_msgs WHERE model_name = 'post_video_script:视频后发过去的信息03') AS script_03_users,
                  (SELECT COUNT(*) FROM registered_users) AS registered_users,
                  (SELECT COALESCE(json_agg(json_build_object(
                      'user_id', x.user_id,
                      'external_id', x.external_id,
                      'nickname', x.nickname
                    ) ORDER BY COALESCE(x.external_id, x.user_id)), '[]'::json)
                   FROM (
                     SELECT DISTINCT u.id::text AS user_id, u.external_id, u.nickname
                     FROM registered_users r
                     JOIN users u ON u.id = r.user_id
                   ) x) AS registered_user_items,
                  (SELECT COUNT(*) FROM screenshot_users) AS screenshot_users,
                  (SELECT COALESCE(json_agg(json_build_object(
                      'user_id', x.user_id,
                      'external_id', x.external_id,
                      'nickname', x.nickname
                    ) ORDER BY COALESCE(x.external_id, x.user_id)), '[]'::json)
                   FROM (
                     SELECT DISTINCT u.id::text AS user_id, u.external_id, u.nickname
                     FROM screenshot_users s
                     JOIN users u ON u.id = s.user_id
                   ) x) AS screenshot_user_items,
                  (SELECT COUNT(*) FROM country_asks) AS country_asked_users,
                  (SELECT COUNT(*) FROM country_replies) AS country_replied_users,
                  (SELECT COUNT(*) FROM age_asks) AS age_asked_users,
                  (SELECT COUNT(*) FROM age_replies) AS age_replied_users,
                  (SELECT start_at FROM period) AS start_at,
                  (SELECT end_at FROM period) AS end_at,
                  (SELECT now_bj FROM period) AS generated_at_bj
                """
            ),
            {"range_key": range_key},
        )
    ).mappings().one()
    data = dict(row)
    for key in (
        "script_01_messages",
        "script_01_users",
        "script_02_messages",
        "script_02_users",
        "script_03_messages",
        "script_03_users",
        "registered_users",
        "screenshot_users",
        "country_asked_users",
        "country_replied_users",
        "age_asked_users",
        "age_replied_users",
    ):
        data[key] = _as_int(data, key)
    data["registered_user_items"] = _as_user_items(data, "registered_user_items")
    data["screenshot_user_items"] = _as_user_items(data, "screenshot_user_items")
    return data
