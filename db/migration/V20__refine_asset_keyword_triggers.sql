-- Refine asset keyword triggers so ordinary sexual praise does not resend media.
UPDATE script_templates
SET content = 'video, videos, vid, vids, clip, clips, movie, gif, tape, recording, custom video, dirty video, short clip, private video, bedroom video, cam, webcam, video call, facetime, live, live show, private call',
    updated_at = NOW()
WHERE title = '用户聊天中想要看本人视频的关键词'
  AND hook = 'reply'
  AND (platform = 'telegram_real_user' OR platform IS NULL);

UPDATE script_templates
SET content = 'photo, photos, pic, pics, picture, pictures, selfie, selfies, image, images, snapshot, snap, face, body, face pic, body pic, full body, mirror selfie, your face, your body',
    updated_at = NOW()
WHERE title = '用户聊天中想要看本人图片的关键词'
  AND hook = 'reply'
  AND (platform = 'telegram_real_user' OR platform IS NULL);
