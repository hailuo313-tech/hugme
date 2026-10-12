"""Fix message_schedules varchar compare used by the switcher. Does not rebuild API."""

from pathlib import Path

path = Path("/opt/eris/app/services/runtime_ownership.py")
text = path.read_text(encoding="utf-8")
old = """                    SELECT 1 FROM message_schedules
                    WHERE account_id = CAST(:account_id AS uuid) AND status = 'sending'"""
new = """                    SELECT 1 FROM message_schedules
                    WHERE account_id = :account_id AND status = 'sending'"""
if new in text and old not in text:
    print("skip ownership varchar fix (already present)")
else:
    if text.count(old) != 1:
        raise SystemExit(f"expected 1 ownership probe match, found {text.count(old)}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    print("patched ownership message_schedules compare")
