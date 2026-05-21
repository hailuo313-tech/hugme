"""Test script for P1-20: Account monitoring and alerting."""

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
        # Test account monitor
        from services.account_monitor import AccountMonitor, account_monitor
        print("✓ account_monitor imports successful")

        # Test alert scheduler
        from services.alert_scheduler import AlertScheduler, alert_scheduler
        print("✓ alert_scheduler imports successful")

        # Test API
        from api.monitoring import router
        print("✓ monitoring API imports successful")

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


def test_config():
    """Test configuration loading."""
    print("\nTesting configuration...")

    try:
        from core.config import settings

        print(f"✓ Configuration loaded")
        print(f"  ACCOUNT_MONITOR_ENABLED: {settings.ACCOUNT_MONITOR_ENABLED}")
        print(f"  ACCOUNT_MONITOR_METRICS_PORT: {settings.ACCOUNT_MONITOR_METRICS_PORT}")
        print(f"  ACCOUNT_MONITOR_COLLECTION_INTERVAL: {settings.ACCOUNT_MONITOR_COLLECTION_INTERVAL}")
        print(f"  ACCOUNT_MONITOR_HISTORY_RETENTION_HOURS: {settings.ACCOUNT_MONITOR_HISTORY_RETENTION_HOURS}")
        print(f"  ALERT_SCHEDULER_ENABLED: {settings.ALERT_SCHEDULER_ENABLED}")
        print(f"  ALERT_SCHEDULER_CHECK_INTERVAL: {settings.ALERT_SCHEDULER_CHECK_INTERVAL}")
        print(f"  ALERT_RULES_PATH: {settings.ALERT_RULES_PATH}")

    except Exception as e:
        print(f"✗ Configuration test failed: {e}")
        return False

    print("\n✓ Configuration tests passed")
    return True


def test_alert_rules():
    """Test alert rules loading."""
    print("\nTesting alert rules...")

    try:
        import json
        from pathlib import Path

        rules_path = Path("config/alert_rules.json")
        if not rules_path.exists():
            print(f"✗ Alert rules file not found: {rules_path}")
            return False

        with open(rules_path, 'r', encoding='utf-8') as f:
            rules_data = json.load(f)

        print(f"✓ Alert rules file loaded")
        print(f"  Total rules: {len(rules_data.get('rules', []))}")

        for rule in rules_data.get('rules', []):
            print(f"  - {rule['name']}: {rule['severity']} (enabled: {rule['enabled']})")

    except Exception as e:
        print(f"✗ Alert rules test failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n✓ Alert rules tests passed")
    return True


async def test_account_monitor():
    """Test account monitor functionality."""
    print("\nTesting account monitor...")

    try:
        from services.account_monitor import AccountMonitor
        from core.config import settings

        # Create account monitor
        monitor = AccountMonitor(
            metrics_port=9092,  # Use different port for testing
            collection_interval=5,  # Shorter for testing
            history_retention_hours=1,
        )

        print(f"✓ Account monitor created")
        print(f"  Metrics port: {monitor.metrics_port}")
        print(f"  Collection interval: {monitor.collection_interval}s")
        print(f"  History retention: {monitor.history_retention_hours}h")

        # Test start/stop
        await monitor.start()
        print(f"✓ Account monitor started")

        await asyncio.sleep(1)  # Let it initialize

        health = {
            "running": monitor._running,
            "metrics_port": monitor.metrics_port,
            "tracked_accounts_count": len(monitor.account_stats),
        }
        print(f"✓ Health check: {health}")

        # Test summary stats
        summary = await monitor.get_summary_stats()
        print(f"✓ Summary stats: {summary}")

        await monitor.stop()
        print(f"✓ Account monitor stopped")

        # Verify stopped state
        health = {
            "running": monitor._running,
            "tracked_accounts_count": len(monitor.account_stats),
        }
        print(f"✓ Health after stop: {health}")

        if not health["running"]:
            print(f"✓ Account monitor correctly stopped")
        else:
            print(f"✗ Account manager not properly stopped")
            return False

    except Exception as e:
        print(f"✗ Account monitor test failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n✓ Account monitor tests passed")
    return True


async def test_alert_scheduler():
    """Test alert scheduler functionality."""
    print("\nTesting alert scheduler...")

    try:
        from services.alert_scheduler import AlertScheduler

        # Create alert scheduler
        scheduler = AlertScheduler(
            check_interval=5,  # Shorter for testing
            alert_rules_path="config/alert_rules.json",
        )

        print(f"✓ Alert scheduler created")
        print(f"  Check interval: {scheduler.check_interval}s")
        print(f"  Alert rules path: {scheduler.alert_rules_path}")

        # Test start/stop
        await scheduler.start()
        print(f"✓ Alert scheduler started")

        await asyncio.sleep(1)  # Let it initialize

        # Check alert rules
        rules = await scheduler.get_alert_rules()
        print(f"✓ Loaded {len(rules)} alert rules")

        # Test condition evaluation
        test_context = {
            "is_connected": False,
            "is_banned": False,
            "error_rate": 0.6,
            "send_success_rate": 0.7,
            "connection_duration": 100,
        }

        for rule in rules:
            if rule.enabled:
                result = scheduler._evaluate_condition(rule.condition, test_context)
                print(f"✓ Rule '{rule.name}': {result}")

        await scheduler.stop()
        print(f"✓ Alert scheduler stopped")

        # Verify stopped state
        if not scheduler._running:
            print(f"✓ Alert scheduler correctly stopped")
        else:
            print(f"✗ Alert scheduler not properly stopped")
            return False

    except Exception as e:
        print(f"✗ Alert scheduler test failed: {e}")
        import traceback

        traceback.print_exc()
        return False

    print("\n✓ Alert scheduler tests passed")
    return True


async def main():
    """Run all tests."""
    print("=" * 60)
    print("P1-20 Account Monitoring and Alerting Tests")
    print("=" * 60)

    results = []

    # Test imports
    results.append(("Imports", test_imports()))

    # Test configuration
    results.append(("Configuration", test_config()))

    # Test alert rules
    results.append(("Alert Rules", test_alert_rules()))

    # Test account monitor
    results.append(("Account Monitor", await test_account_monitor()))

    # Test alert scheduler
    results.append(("Alert Scheduler", await test_alert_scheduler()))

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