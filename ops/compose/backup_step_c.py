from datetime import datetime
from pathlib import Path
import shutil

stamp = datetime.now().strftime("%Y%m%d-%H%M")
dest = Path("/opt/eris/.deploy-backups") / f"runtime-split-step-c-{stamp}"
dest.mkdir(parents=True, exist_ok=True)
root = Path("/opt/eris")
files = ["app/services/runtime_canary.py"]
for rel in files:
    src = root / rel
    if src.exists():
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
print(dest)
