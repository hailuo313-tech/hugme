from datetime import datetime
from pathlib import Path
import shutil

stamp = datetime.now().strftime("%Y%m%d-%H%M")
dest = Path("/opt/eris/.deploy-backups") / f"runtime-split-stage6-{stamp}"
dest.mkdir(parents=True, exist_ok=True)
files = [
    "app/api/admin.py",
    "app/api/telegram_accounts.py",
    "app/services/call_broadcast/incoming_review.py",
    "app/services/mtproto/session_manager.py",
    "app/services/telegram_session_login.py",
]
root = Path("/opt/eris")
for rel in files:
    src = root / rel
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
print(dest)
