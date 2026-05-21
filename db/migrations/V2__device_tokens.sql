-- P4-10: 设备令牌表
-- 用于存储移动端设备令牌，支持 FCM/APNs 推送

CREATE TABLE IF NOT EXISTS device_tokens (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL,
    device_token TEXT NOT NULL UNIQUE,
    platform VARCHAR(10) NOT NULL CHECK (platform IN ('android', 'ios')),
    device_info JSONB DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- 创建索引以提高查询性能
CREATE INDEX IF NOT EXISTS idx_device_tokens_user_id ON device_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_device_tokens_platform ON device_tokens(platform);
CREATE INDEX IF NOT EXISTS idx_device_tokens_updated_at ON device_tokens(updated_at DESC);

-- 添加注释
COMMENT ON TABLE device_tokens IS '移动端设备令牌表，用于 FCM/APNs 推送';
COMMENT ON COLUMN device_tokens.user_id IS '关联的用户 ID';
COMMENT ON COLUMN device_tokens.device_token IS '设备令牌（FCM token 或 APNs token）';
COMMENT ON COLUMN device_tokens.platform IS '平台类型：android 或 ios';
COMMENT ON COLUMN device_tokens.device_info IS '设备信息（型号、OS版本等）的 JSON 数据';