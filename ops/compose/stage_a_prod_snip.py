from pathlib import Path

root = Path("/opt/eris")
files = {
    "session_manager": "app/services/mtproto/session_manager.py",
    "account_manager": "app/services/telegram_account_manager.py",
    "auto_reply": "app/services/mtproto/auto_reply.py",
    "health": "app/services/telegram_account_health.py",
    "ownership": "app/services/runtime_ownership.py",
    "gateway": "app/services/telegram_command_gateway.py",
}
for name, rel in files.items():
    text = (root / rel).read_text(encoding="utf-8")
    print("====", rel, "====")
    print("this_process_may_hold", "this_process_may_hold_telegram_session" in text)
    print("legacy_worker", "legacy_worker_should_handle_account" in text)
    print("submit_telegram_command", "submit_telegram_command" in text)
    if name == "session_manager":
        idx = text.find("async def _restore_sessions")
        print(text[idx:idx + 700])
        idx = text.find("async def _check_all_connections")
        print("--- health ---")
        print(text[idx:idx + 550])
    if name == "account_manager":
        idx = text.find("async def connect_account")
        print(text[idx:idx + 450])
    if name == "auto_reply":
        idx = text.find("async def handle_mtproto_new_message")
        print(text[idx:idx + 350])
    if name == "ownership":
        idx = text.find("async def legacy_worker_should_handle_account")
        print(text[idx:idx + 220])
