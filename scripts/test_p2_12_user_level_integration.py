"""Test script for P2-12: Inbound pipeline calcUserLevel integration."""

import asyncio
import sys
from pathlib import Path

# Add app directory to path
app_dir = Path(__file__).parent.parent / "app"
sys.path.insert(0, str(app_dir))


def test_imports():
    """Test that all required modules can be imported."""
    print("Testing imports...")

    try:
        # Test level engine
        from services.level_engine import (
            UserLevelInput,
            UserLevelResult,
            calc_user_level,
            load_thresholds,
            country_tier,
        )
        print("✓ level_engine imports successful")

        # Test user level service
        from services.user_level_service import UserLevelService, user_level_service
        print("✓ user_level_service imports successful")

        # Test MTProto inbound
        from services.mtproto.newmessage_inbound import enqueue_new_message, MtprotoNewMessageAdapter
        print("✓ mtproto newmessage_inbound imports successful")

        # Test API
        from api.user_level import router
        print("✓ user_level API imports successful")

    except Exception as e:
        print(f"✗ Import test failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n✓ Import tests passed")
    return True


def test_level_engine():
    """Test level engine functionality."""
    print("\nTesting level engine...")

    try:
        from services.level_engine import (
            UserLevelInput,
            calc_user_level,
            load_thresholds,
            country_tier,
        )

        # Test threshold loading
        thresholds = load_thresholds()
        print(f"✓ Thresholds loaded: S_min={thresholds.s_min_spend}, A_min={thresholds.a_min_spend}")

        # Test country tier
        tier_us = country_tier("US")
        print(f"✓ Country tier US: {tier_us}")

        tier_cn = country_tier("CN")
        print(f"✓ Country tier CN: {tier_cn}")

        tier_unknown = country_tier(None)
        print(f"✓ Country tier None: {tier_unknown}")

        # Test level calculation - incomplete profile
        result_incomplete = calc_user_level(UserLevelInput(profile_complete=False))
        print(f"✓ Incomplete profile: level={result_incomplete.level}, reason={result_incomplete.reason}")

        # Test level calculation - operator assigned S
        result_operator_s = calc_user_level(
            UserLevelInput(profile_complete=True, operator_assigned_s=True)
        )
        print(f"✓ Operator assigned S: level={result_operator_s.level}, reason={result_operator_s.reason}")

        # Test level calculation - high spend T1
        result_high_spend = calc_user_level(
            UserLevelInput(
                profile_complete=True,
                country_code="US",
                lifetime_spend_usd=600,
            )
        )
        print(f"✓ High spend T1: level={result_high_spend.level}, reason={result_high_spend.reason}")

        # Test level calculation - VIP level
        result_vip = calc_user_level(
            UserLevelInput(
                profile_complete=True,
                vip_level=2,
            )
        )
        print(f"✓ VIP level 2: level={result_vip.level}, reason={result_vip.reason}")

        # Test level calculation - default C
        result_default = calc_user_level(
            UserLevelInput(
                profile_complete=True,
                country_code="ZZ",  # Unknown country
            )
        )
        print(f"✓ Default unknown tier: level={result_default.level}, reason={result_default.reason}")

    except Exception as e:
        print(f"✗ Level engine test failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n✓ Level engine tests passed")
    return True


async def test_user_level_service():
    """Test user level service functionality."""
    print("\nTesting user level service...")

    try:
        from services.user_level_service import UserLevelService

        # Create service instance
        service = UserLevelService()
        print("✓ User level service created")

        # Test threshold caching
        thresholds = await service.get_thresholds()
        print(f"✓ Thresholds from cache: S_min={thresholds.s_min_spend}")

        # Test cache invalidation
        await service.invalidate_thresholds_cache()
        print("✓ Thresholds cache invalidated")

        # Test default level result
        default_result = service._get_default_level_result("test_reason", "T1")
        print(f"✓ Default level result: level={default_result['level']}, reason={default_result['reason']}")

        # Test Telegram user ID extraction
        user_id_1 = service._extract_telegram_user_id("tg_123456789")
        print(f"✓ Extracted Telegram user ID: {user_id_1}")

        user_id_2 = service._extract_telegram_user_id("987654321")
        print(f"✓ Extracted Telegram user ID (no prefix): {user_id_2}")

        user_id_3 = service._extract_telegram_user_id(None)
        print(f"✓ Extracted Telegram user ID (None): {user_id_3}")

        # Test envelope enrichment (without DB)
        test_envelope = {
            "external_user_id": "tg_123456789",
            "platform": "telegram_real_user",
            "message_type": "text",
            "content": "test message",
            "trace_id": "test-trace-123",
            "account_id": "test-account",
            "metadata": {},
        }

        enriched_envelope = await service.enrich_inbound_envelope_with_level(test_envelope)
        print(f"✓ Envelope enriched: user_level={enriched_envelope['metadata'].get('user_level')}")
        print(f"✓ Envelope enriched: chat_route={enriched_envelope['metadata'].get('chat_route')}")

    except Exception as e:
        print(f"✗ User level service test failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n✓ User level service tests passed")
    return True


def test_config_files():
    """Test configuration files."""
    print("\nTesting configuration files...")

    try:
        from pathlib import Path

        # Check level thresholds config
        thresholds_path = Path("config/level_thresholds.json")
        if thresholds_path.exists():
            print(f"✓ Level thresholds config exists: {thresholds_path}")
            import json

            with open(thresholds_path, 'r', encoding='utf-8') as f:
                thresholds_data = json.load(f)
                print(f"✓ Thresholds data keys: {list(thresholds_data.keys())}")
        else:
            print(f"✗ Level thresholds config not found: {thresholds_path}")

        # Check T1 countries config
        t1_path = Path("config/t1_countries.json")
        if t1_path.exists():
            print(f"✓ T1 countries config exists: {t1_path}")
        else:
            print(f"✗ T1 countries config not found: {t1_path}")

    except Exception as e:
        print(f"✗ Config files test failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n✓ Config files tests passed")
    return True


async def main():
    """Run all tests."""
    print("=" * 60)
    print("P2-12 Inbound Pipeline calcUserLevel Integration Tests")
    print("=" * 60)

    results = []

    # Test imports
    results.append(("Imports", test_imports()))

    # Test level engine
    results.append(("Level Engine", test_level_engine()))

    # Test user level service
    results.append(("User Level Service", await test_user_level_service()))

    # Test config files
    results.append(("Config Files", test_config_files()))

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