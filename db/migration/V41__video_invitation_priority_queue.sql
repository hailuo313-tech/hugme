ALTER TABLE message_schedules
ADD COLUMN IF NOT EXISTS invitation_queue varchar(4),
ADD COLUMN IF NOT EXISTS invitation_classified_at timestamptz;

CREATE OR REPLACE FUNCTION classify_video_invitation_queue() RETURNS trigger AS $$
DECLARE r integer;
BEGIN
  IF NEW.metadata->>'delivery_mode'='app_download_nurture'
     AND NEW.metadata->>'nurture_kind'='video_chat' THEN
    r := NULLIF(NEW.metadata->>'nurture_round','')::integer;
    NEW.invitation_queue := CASE r WHEN 1 THEN 'P1' WHEN 2 THEN 'P2' WHEN 3 THEN 'P4' ELSE NULL END;
    NEW.invitation_classified_at := NOW();
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_classify_video_invitation_queue ON message_schedules;
CREATE TRIGGER trg_classify_video_invitation_queue
BEFORE INSERT OR UPDATE OF metadata ON message_schedules
FOR EACH ROW EXECUTE FUNCTION classify_video_invitation_queue();

UPDATE message_schedules SET
 invitation_queue=CASE NULLIF(metadata->>'nurture_round','')::integer
   WHEN 1 THEN 'P1' WHEN 2 THEN 'P2' WHEN 3 THEN 'P4' ELSE NULL END,
 invitation_classified_at=NOW()
WHERE metadata->>'delivery_mode'='app_download_nurture'
  AND metadata->>'nurture_kind'='video_chat';

CREATE INDEX IF NOT EXISTS idx_message_schedules_invitation_queue
ON message_schedules(invitation_queue,status,send_at) WHERE invitation_queue IS NOT NULL;
