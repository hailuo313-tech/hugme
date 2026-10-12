from pathlib import Path
import re

review = Path("/opt/eris/app/services/call_broadcast/incoming_review.py")
text = review.read_text(encoding="utf-8")
new_text, count = re.subn(
    r"(?<!return )await reject_inbound_call\(",
    "await _gated_reject_inbound_call(",
    text,
)
if count != 3:
    raise SystemExit(f"review reject calls: expected 3 remaining, found {count}")
review.write_text(new_text, encoding="utf-8")
print("patched review reject calls", count)

login = Path("/opt/eris/app/services/telegram_session_login.py")
old = """        connected = False
        if auto_connect:
            connected = await telegram_account_manager.connect_account(account_id)
"""
new = """        connected = False
        if auto_connect:
            from services.telegram_command_gateway import submit_telegram_command

            async def _legacy_auto_connect():
                return await telegram_account_manager.connect_account(account_id)

            gated = await submit_telegram_command(
                command_type="connect_account",
                account_id=str(account_id),
                legacy_execute=_legacy_auto_connect,
            )
            connected = bool(gated.executed and gated.value)
"""
text = login.read_text(encoding="utf-8")
if old not in text:
    raise SystemExit("session login auto_connect marker missing")
if text.count(old) != 1:
    raise SystemExit("session login auto_connect marker ambiguous")
login.write_text(text.replace(old, new, 1), encoding="utf-8")
print("patched session login auto_connect")
