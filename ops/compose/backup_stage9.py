from datetime import datetime
from pathlib import Path
import shutil

stamp = datetime.now().strftime("%Y%m%d-%H%M")
dest = Path("/opt/eris/.deploy-backups") / f"runtime-split-stage9-{stamp}"
dest.mkdir(parents=True, exist_ok=True)
files = [
    "app/core/config.py",
    "docker-compose.yml",
    ".env.example",
    ".env.template",
]
root = Path("/opt/eris")
for rel in files:
    src = root / rel
    if not src.exists():
        continue
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
print(dest)
