from services.telegram_user_migration import _error_status


def test_migration_error_status_classification():
    assert _error_status(Exception("PeerFlood restricted"), 1)[0] == "restricted"
    assert _error_status(Exception("UserPrivacyRestricted"), 1)[0] == "unreachable"
    assert _error_status(Exception("temporary network failure"), 1)[0] == "retry_wait"
    assert _error_status(Exception("temporary network failure"), 3)[0] == "failed"


if __name__ == "__main__":
    test_migration_error_status_classification()
    print("classification_tests_ok")
