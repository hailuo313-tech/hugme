"""Test script for P1-18: Session encryption and auto-reconnect."""

import asyncio
import sys
from pathlib import Path

# Add app directory to path
app_dir = Path(__file__).parent.parent / "app"
sys.path.insert(0, str(app_dir))

from cryptography.fernet import Fernet
from services.mtproto.session_crypto import (
    SessionCryptoError,
    decrypt_string_session,
    encrypt_string_session,
)


def test_session_crypto():
    """Test session encryption and decryption."""
    print("Testing session crypto...")

    # Generate test key
    key = Fernet.generate_key()
    print(f"Generated Fernet key: {key.decode()}")

    # Test data
    test_session = "1BQNR2oI-sK9n7s8J7n8s7J8n7s8J7n8s7J8n7s8J7n8s7J8n7s8J7n8s7J8n7s8J7n8s"

    # Test encryption
    try:
        encrypted = encrypt_string_session(test_session, key)
        print(f"✓ Encryption successful")
        print(f"  Encrypted length: {len(encrypted)}")
        print(f"  Encrypted preview: {encrypted[:50]}...")
    except Exception as e:
        print(f"✗ Encryption failed: {e}")
        return False

    # Test decryption
    try:
        decrypted = decrypt_string_session(encrypted, key)
        print(f"✓ Decryption successful")
        print(f"  Decrypted: {decrypted}")

        if decrypted == test_session:
            print(f"✓ Decryption matches original")
        else:
            print(f"✗ Decryption does not match original")
            return False
    except Exception as e:
        print(f"✗ Decryption failed: {e}")
        return False

    # Test empty session
    try:
        encrypt_string_session("", key)
        print(f"✗ Empty session should raise error")
        return False
    except SessionCryptoError:
        print(f"✓ Empty session correctly raises error")

    # Test invalid key
    try:
        invalid_key = b"invalid_key_1234567890123456"
        encrypt_string_session(test_session, invalid_key)
        print(f"✗ Invalid key should raise error")
        return False
    except SessionCryptoError:
        print(f"✓ Invalid key correctly raises error")

    # Test wrong key for decryption
    try:
        wrong_key = Fernet.generate_key()
        decrypt_string_session(encrypted, wrong_key)
        print(f"✗ Wrong key should raise error")
        return False
    except SessionCryptoError:
        print(f"✓ Wrong key correctly raises error")

    print("\n✓ Session crypto tests passed")
    return True


async def test_session_manager():
    """Test session manager functionality."""
    print("\nTesting session manager...")

    try:
        from services.mtproto.session_manager import SessionManager
        from core.config import settings

        # Create session manager
        manager = SessionManager(
            reconnect_interval=5,  # Shorter for testing
            max_reconnect_attempts=3,
            health_check_interval=10,
        )

        print(f"✓ Session manager created")
        print(f"  Reconnect interval: {manager.reconnect_interval}s")
        print(f"  Max reconnect attempts: {manager.max_reconnect_attempts}")
        print(f"  Health check interval: {manager.health_check_interval}s")

        # Test start/stop
        await manager.start()
        print(f"✓ Session manager started")

        await asyncio.sleep(1)  # Let it initialize

        health = {
            "running": manager._running,
            "reconnect_tasks_count": len(manager.reconnect_tasks),
        }
        print(f"✓ Health check: {health}")

        await manager.stop()
        print(f"✓ Session manager stopped")

        # Verify stopped state
        health = {
            "running": manager._running,
            "reconnect_tasks_count": len(manager.reconnect_tasks),
        }
        print(f"✓ Health after stop: {health}")

        if not health["running"] and health["reconnect_tasks_count"] == 0:
            print(f"✓ Session manager correctly stopped")
        else:
            print(f"✗ Session manager not properly stopped")
            return False

    except Exception as e:
        print(f"✗ Session manager test failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n✓ Session manager tests passed")
    return True


def test_config():
    """Test configuration loading."""
    print("\nTesting configuration...")

    try:
        from core.config import settings

        print(f"✓ Configuration loaded")
        print(f"  SESSION_MANAGER_ENABLED: {settings.SESSION_MANAGER_ENABLED}")
        print(f"  SESSION_RECONNECT_INTERVAL: {settings.SESSION_RECONNECT_INTERVAL}")
        print(f"  SESSION_MAX_RECONNECT_ATTEMPTS: {settings.SESSION_MAX_RECONNECT_ATTEMPTS}")
        print(f"  SESSION_HEALTH_CHECK_INTERVAL: {settings.SESSION_HEALTH_CHECK_INTERVAL}")
        print(f"  TELEGRAM_SESSION_FERNET_KEY configured: {bool(settings.TELEGRAM_SESSION_FERNET_KEY)}")

    except Exception as e:
        print(f"✗ Configuration test failed: {e}")
        return False

    print("\n✓ Configuration tests passed")
    return True


def test_imports():
    """Test that all required modules can be imported."""
    print("Testing imports...")

    try:
        # Test session crypto
        from services.mtproto.session_crypto import (
            SessionCryptoError,
            decrypt_string_session,
            encrypt_string_session,
        )
        print("✓ session_crypto imports successful")

        # Test session manager
        from services.mtproto.session_manager import SessionManager, session_manager
        print("✓ session_manager imports successful")

        # Test API
        from api.mtproto_sessions import router
        print("✓ mtproto_sessions API imports successful")

        # Test config
        from core.config import settings
        print("✓ config imports successful")

    except Exception as e:
        print(f"✗ Import test failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n✓ Import tests passed")
    return True


async def main():
    """Run all tests."""
    print("=" * 60)
    print("P1-18 Session Encryption and Auto-Reconnect Tests")
    print("=" * 60)

    results = []

    # Test imports
    results.append(("Imports", test_imports()))

    # Test configuration
    results.append(("Configuration", test_config()))

    # Test session crypto
    results.append(("Session Crypto", test_session_crypto()))

    # Test session manager
    results.append(("Session Manager", await test_session_manager()))

    # Print summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    for name, result in results:
        status = "✓ PASSED" if result else "✗ FAILED"
        print(f"{name}: {status}")

    all_passed = all(result for _, result in results)

    if all_passed:
        print("\n✓ All tests passed!")
        return 0
    else:
        print("\n✗ Some tests failed")
        return 1


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)