from datetime import datetime
from pathlib import Path
import shutil

stamp = datetime.now().strftime("%Y%m%d-%H%M")
dest = Path("/opt/eris/.deploy-backups") / f"runtime-split-stage5-{stamp}"
dest.mkdir(parents=True, exist_ok=True)
src = Path("/opt/eris/docker-compose.yml")
text = src.read_text(encoding="utf-8")
start = text.find("\n  api-next:")
end = text.find("\n  prometheus:")
before = text if start < 0 or end < 0 else text[:start] + text[end:]
(dest / "docker-compose.yml.before.yml").write_text(before, encoding="utf-8")
shutil.copy2(src, dest / "docker-compose.yml")
print(dest)
print("before_has_api_next", "api-next:" in before)
print("after_has_api_next", "api-next:" in text)
print("after_has_api_green", "api-green:" in text)
