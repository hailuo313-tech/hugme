import json
from pathlib import Path

p = Path("/opt/eris-TIKTOK/config.json")
d = json.loads(p.read_text(encoding="utf-8"))
m = d.setdefault("live_monitor", {})
m["auto_probe_enabled"] = False
m["auto_sample_enabled"] = False
m.pop("probe_interval_sec", None)
m.pop("sample_interval_sec", None)
m.setdefault("probe_delay_sec", 0.5)
m.setdefault("probe_timeout_sec", 10.0)
m.setdefault("secondary_confirmation_delay_sec", 2.0)
m.setdefault("offline_miss_threshold", 2)
a = d.setdefault("account_audit", {})
a.setdefault("delay_sec", 1.0)
a.setdefault("daily_hour", 3)
p.write_text(json.dumps(d, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("config patched")
