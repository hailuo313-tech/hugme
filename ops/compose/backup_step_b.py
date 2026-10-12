from datetime import datetime
from pathlib import Path
import shutil

stamp = datetime.now().strftime("%Y%m%d-%H%M")
dest = Path("/opt/eris/.deploy-backups") / f"runtime-split-step-b-{stamp}"
dest.mkdir(parents=True, exist_ok=True)
files = [
    "docker-compose.yml",
    "app/main.py",
    "app/core/process_role.py",
    "app/services/runtime_shadow_consumer.py",
]
root = Path("/opt/eris")
for rel in files:
    src = root / rel
    target = dest / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, target)
print(dest)
