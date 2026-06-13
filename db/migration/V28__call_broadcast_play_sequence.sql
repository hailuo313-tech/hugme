-- Inbound call video sequence: 1st / 2nd / 3rd incoming call plays matching asset.

ALTER TABLE video_broadcast_assets
    ADD COLUMN IF NOT EXISTS play_sequence INTEGER
        CHECK (play_sequence IS NULL OR play_sequence BETWEEN 1 AND 3);

CREATE UNIQUE INDEX IF NOT EXISTS idx_video_broadcast_assets_active_play_sequence
    ON video_broadcast_assets(play_sequence)
    WHERE status = 'active' AND play_sequence IS NOT NULL;

COMMENT ON COLUMN video_broadcast_assets.play_sequence IS
    'Which inbound call number (1-3) should play this video; NULL = not used for inbound sequence.';
