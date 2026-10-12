from datetime import datetime
from pathlib import Path
import shutil

stamp = datetime.now().strftime("%Y%m%d-%H%M")
dest = Path("/opt/eris/.deploy-backups") / f"runtime-split-stage10-{stamp}"
dest.mkdir(parents=True, exist_ok=True)
src = Path("/opt/eris/docker-compose.yml")
text = src.read_text(encoding="utf-8")
start = text.find("\n  api-green:")
end = text.find("\n  prometheus:")
before = text if start < 0 or end < 0 else text[:start] + text[end:]
(dest / "docker-compose.yml.before.yml").write_text(before, encoding="utf-8")
shutil.copy2(src, dest / "docker-compose.yml")
nginx_src = Path("/opt/eris/ops/nginx/api-green-sidecar.conf")
if nginx_src.exists():
    target = dest / "ops/nginx/api-green-sidecar.conf"
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(nginx_src, target)
print(dest)
print("before_has_api_green", "api-green:" in before)
print("after_has_api_green", "api-green:" in text)
