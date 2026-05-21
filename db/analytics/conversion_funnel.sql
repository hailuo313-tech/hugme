-- P5-07: 付费转化漏斗 SQL
-- 用于支持 Grafana 转化面板的数据查询

-- 转化漏斗各阶段用户数统计 (24小时)
WITH funnel_24h AS (
    -- 阶段1: 用户访问
    SELECT 
        'user_visit' as funnel_stage,
        COUNT(DISTINCT user_id) as user_count,
        COUNT(*) as event_count,
        NOW() - INTERVAL '24 hours' as time_window
    FROM user_activity_log
    WHERE created_at >= NOW() - INTERVAL '24 hours'
    AND activity_type = 'page_view'
    
    UNION ALL
    
    -- 阶段2: 注册完成
    SELECT 
        'signup_completed' as funnel_stage,
        COUNT(DISTINCT user_id) as user_count,
        COUNT(*) as event_count,
        NOW() - INTERVAL '24 hours' as time_window
    FROM users
    WHERE created_at >= NOW() - INTERVAL '24 hours'
    AND status = 'active'
    
    UNION ALL
    
    -- 阶段3: 付费发起
    SELECT 
        'payment_initiated' as funnel_stage,
        COUNT(DISTINCT user_id) as user_count,
        COUNT(*) as event_count,
        NOW() - INTERVAL '24 hours' as time_window
    FROM payment_events
    WHERE created_at >= NOW() - INTERVAL '24 hours'
    AND event_type = 'payment_initiated'
    
    UNION ALL
    
    -- 阶段4: 付费完成
    SELECT 
        'payment_completed' as funnel_stage,
        COUNT(DISTINCT user_id) as user_count,
        COUNT(*) as event_count,
        NOW() - INTERVAL '24 hours' as time_window
    FROM payment_events
    WHERE created_at >= NOW() - INTERVAL '24 hours'
    AND event_type = 'payment_completed'
    AND status = 'success'
)
SELECT * FROM funnel_24h ORDER BY 
    CASE funnel_stage
        WHEN 'user_visit' THEN 1
        WHEN 'signup_completed' THEN 2
        WHEN 'payment_initiated' THEN 3
        WHEN 'payment_completed' THEN 4
    END;

-- 转化漏斗各阶段用户数统计 (72小时)
WITH funnel_72h AS (
    SELECT 
        'user_visit' as funnel_stage,
        COUNT(DISTINCT user_id) as user_count,
        COUNT(*) as event_count,
        NOW() - INTERVAL '72 hours' as time_window
    FROM user_activity_log
    WHERE created_at >= NOW() - INTERVAL '72 hours'
    AND activity_type = 'page_view'
    
    UNION ALL
    
    SELECT 
        'signup_completed' as funnel_stage,
        COUNT(DISTINCT user_id) as user_count,
        COUNT(*) as event_count,
        NOW() - INTERVAL '72 hours' as time_window
    FROM users
    WHERE created_at >= NOW() - INTERVAL '72 hours'
    AND status = 'active'
    
    UNION ALL
    
    SELECT 
        'payment_initiated' as funnel_stage,
        COUNT(DISTINCT user_id) as user_count,
        COUNT(*) as event_count,
        NOW() - INTERVAL '72 hours' as time_window
    FROM payment_events
    WHERE created_at >= NOW() - INTERVAL '72 hours'
    AND event_type = 'payment_initiated'
    
    UNION ALL
    
    SELECT 
        'payment_completed' as funnel_stage,
        COUNT(DISTINCT user_id) as user_count,
        COUNT(*) as event_count,
        NOW() - INTERVAL '72 hours' as time_window
    FROM payment_events
    WHERE created_at >= NOW() - INTERVAL '72 hours'
    AND event_type = 'payment_completed'
    AND status = 'success'
)
SELECT * FROM funnel_72h ORDER BY 
    CASE funnel_stage
        WHEN 'user_visit' THEN 1
        WHEN 'signup_completed' THEN 2
        WHEN 'payment_initiated' THEN 3
        WHEN 'payment_completed' THEN 4
    END;

-- 各阶段转化率计算
WITH conversion_rates AS (
    SELECT 
        -- 访问到注册转化率
        (SELECT COUNT(DISTINCT user_id) FROM users WHERE created_at >= NOW() - INTERVAL '24 hours' AND status = 'active')::float /
        NULLIF((SELECT COUNT(DISTINCT user_id) FROM user_activity_log WHERE created_at >= NOW() - INTERVAL '24 hours' AND activity_type = 'page_view'), 0) as visit_to_signup_rate,
        
        -- 注册到付费发起转化率
        (SELECT COUNT(DISTINCT user_id) FROM payment_events WHERE created_at >= NOW() - INTERVAL '24 hours' AND event_type = 'payment_initiated')::float /
        NULLIF((SELECT COUNT(DISTINCT user_id) FROM users WHERE created_at >= NOW() - INTERVAL '24 hours' AND status = 'active'), 0) as signup_to_payment_rate,
        
        -- 付费发起到完成转化率
        (SELECT COUNT(DISTINCT user_id) FROM payment_events WHERE created_at >= NOW() - INTERVAL '24 hours' AND event_type = 'payment_completed' AND status = 'success')::float /
        NULLIF((SELECT COUNT(DISTINCT user_id) FROM payment_events WHERE created_at >= NOW() - INTERVAL '24 hours' AND event_type = 'payment_initiated'), 0) as payment_to_complete_rate,
        
        -- 整体转化率 (访问到付费完成)
        (SELECT COUNT(DISTINCT user_id) FROM payment_events WHERE created_at >= NOW() - INTERVAL '24 hours' AND event_type = 'payment_completed' AND status = 'success')::float /
        NULLIF((SELECT COUNT(DISTINCT user_id) FROM user_activity_log WHERE created_at >= NOW() - INTERVAL '24 hours' AND activity_type = 'page_view'), 0) as overall_conversion_rate
)
SELECT * FROM conversion_rates;

-- 收入统计 (24小时/72小时)
SELECT 
    SUM(CASE WHEN created_at >= NOW() - INTERVAL '24 hours' THEN amount ELSE 0 END) as revenue_24h,
    SUM(CASE WHEN created_at >= NOW() - INTERVAL '72 hours' THEN amount ELSE 0 END) as revenue_72h,
    COUNT(CASE WHEN created_at >= NOW() - INTERVAL '24 hours' THEN 1 END) as transactions_24h,
    COUNT(CASE WHEN created_at >= NOW() - INTERVAL '72 hours' THEN 1 END) as transactions_72h,
    AVG(CASE WHEN created_at >= NOW() - INTERVAL '24 hours' THEN amount ELSE NULL END) as avg_transaction_24h,
    AVG(CASE WHEN created_at >= NOW() - INTERVAL '72 hours' THEN amount ELSE NULL END) as avg_transaction_72h
FROM payment_events
WHERE event_type = 'payment_completed' 
AND status = 'success'
AND created_at >= NOW() - INTERVAL '72 hours';

-- 按用户等级分层的转化分析
SELECT 
    u.level,
    COUNT(DISTINCT u.user_id) as total_users,
    COUNT(DISTINCT pe.user_id) as paying_users,
    COUNT(DISTINCT pe.user_id)::float / NULLIF(COUNT(DISTINCT u.user_id), 0) as conversion_rate_by_level,
    SUM(pe.amount) as total_revenue,
    AVG(pe.amount) as avg_revenue_per_user
FROM users u
LEFT JOIN payment_events pe ON u.user_id = pe.user_id 
    AND pe.event_type = 'payment_completed' 
    AND pe.status = 'success'
    AND pe.created_at >= NOW() - INTERVAL '24 hours'
WHERE u.created_at >= NOW() - INTERVAL '24 hours'
GROUP BY u.level
ORDER BY u.level;

-- 转化漏斗时间分析 (各阶段平均耗时)
WITH stage_timings AS (
    -- 访问到注册平均耗时
    SELECT 
        'visit_to_signup' as stage,
        AVG(EXTRACT(EPOCH FROM (u.created_at - ua.created_at))) as avg_duration_seconds
    FROM user_activity_log ua
    JOIN users u ON ua.user_id = u.user_id
    WHERE ua.activity_type = 'page_view'
    AND u.created_at >= NOW() - INTERVAL '24 hours'
    AND ua.created_at >= NOW() - INTERVAL '24 hours'
    
    UNION ALL
    
    -- 注册到付费发起平均耗时
    SELECT 
        'signup_to_payment' as stage,
        AVG(EXTRACT(EPOCH FROM (pe1.created_at - u.created_at))) as avg_duration_seconds
    FROM users u
    JOIN payment_events pe1 ON u.user_id = pe1.user_id
    WHERE pe1.event_type = 'payment_initiated'
    AND pe1.created_at >= NOW() - INTERVAL '24 hours'
    AND u.created_at >= NOW() - INTERVAL '24 hours'
    
    UNION ALL
    
    -- 付费发起到完成平均耗时
    SELECT 
        'payment_to_complete' as stage,
        AVG(EXTRACT(EPOCH FROM (pe2.created_at - pe1.created_at))) as avg_duration_seconds
    FROM payment_events pe1
    JOIN payment_events pe2 ON pe1.user_id = pe2.user_id 
        AND pe1.transaction_id = pe2.transaction_id
    WHERE pe1.event_type = 'payment_initiated'
    AND pe2.event_type = 'payment_completed'
    AND pe2.status = 'success'
    AND pe2.created_at >= NOW() - INTERVAL '24 hours'
)
SELECT * FROM stage_timings;

-- 分时段转化趋势 (小时级别)
SELECT 
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(DISTINCT CASE WHEN event_type = 'payment_completed' AND status = 'success' THEN user_id END) as completed_payments,
    SUM(CASE WHEN event_type = 'payment_completed' AND status = 'success' THEN amount ELSE 0 END) as hourly_revenue,
    COUNT(DISTINCT CASE WHEN event_type = 'payment_initiated' THEN user_id END) as initiated_payments
FROM payment_events
WHERE created_at >= NOW() - INTERVAL '72 hours'
GROUP BY DATE_TRUNC('hour', created_at)
ORDER BY hour DESC;