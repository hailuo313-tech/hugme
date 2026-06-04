-- Complete image asset trigger keywords so direct photo requests hit media delivery.
UPDATE script_templates
SET content = 'photo, photos, pic, pics, picture, pictures, selfie, selfies, image, images, snapshot, snap, face, body, face pic, body pic, full body, mirror selfie, your face, your body, 照片, 图片, 自拍',
    updated_at = NOW()
WHERE title = '用户聊天中想要看本人图片的关键词'
  AND hook = 'reply'
  AND (platform = 'telegram_real_user' OR platform IS NULL);
