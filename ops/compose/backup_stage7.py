from datetime import datetime
from pathlib import Path
import shutil

stamp = datetime.now().strftime("%Y%m%d-%H%M")
dest = Path("/opt/eris/.deploy-backups") / f"runtime-split-stage7-{stamp}"
dest.mkdir(parents=True, exist_ok=True)
files = [
    "app/services/message_schedule_service.py",
    "app/services/auto_delivery_worker.py",
    "app/services/fixed_auto_reply_service.py",
    "app/services/telegram_user_migration.py",
    "app/services/video_reinvite.py",
    "app/services/call_broadcast/worker.py",
    "app/services/telegram_account_health.py",
    "app/services/mtproto/account_pool.py",
]
root = Path("/opt/eris")
for rel in files:
    src = root / rel
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
print(dest)
