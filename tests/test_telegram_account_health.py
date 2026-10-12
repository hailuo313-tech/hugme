from services.telegram_account_health import _classify


def test_classifies_real_telethon_ban_exception_names() -> None:
    assert _classify("AuthKeyUnregisteredError: auth key invalid") == "banned"
    assert _classify("UserDeactivatedBanError: user was deactivated") == "banned"
    assert _classify("PhoneNumberBannedError: phone banned") == "banned"
    assert _classify("SessionRevokedError: session revoked") == "banned"
    assert _classify("UsernameNotOccupiedError: username not occupied") == "banned"
    assert _classify("cross_account_user_deleted") == "banned"
    assert _classify("UserDeactivatedBanError: cannot send") == "banned"


def test_classifies_restrictions_and_unknown_errors() -> None:
    assert _classify("PeerFloodError: too many requests") == "restricted"
    assert _classify("TimeoutError") == "pending_recheck"
